"""Discord bot: admin-only /checkport <url> -> pmcheck report (rules + Gemini advisory).

Env (see config.example.env):
  DISCORD_TOKEN, GUILD_ID, ADMIN_ROLE_IDS (comma separated), GEMINI_API_KEY,
  PMCHECK_GEMINI_MODEL (optional), MAX_DOWNLOAD_MB (default 1024), CHECK_TIMEOUT (default 900),
  GITHUB_TOKEN (optional, read-only; raises the GitHub API limit for PR links)
"""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord
from discord import app_commands

from pmcheck import ghpr

ALLOWED_HOSTS = {
    "cdn.discordapp.com", "media.discordapp.net",
    "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com", "raw.githubusercontent.com", "codeload.github.com",
}
TOKEN = os.environ["DISCORD_TOKEN"]
GUILD = discord.Object(id=int(os.environ["GUILD_ID"]))
ADMIN_ROLES = {int(x) for x in os.environ.get("ADMIN_ROLE_IDS", "").split(",") if x.strip()}
MAX_BYTES = int(os.environ.get("MAX_DOWNLOAD_MB", "1024")) * 1024 * 1024
TIMEOUT = int(os.environ.get("CHECK_TIMEOUT", "900"))

intents = discord.Intents.none()
intents.guilds = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
lock = asyncio.Lock()


def log(msg):
    print(msg, flush=True)   # journald adds the timestamp


def is_admin(member):
    return isinstance(member, discord.Member) and any(r.id in ADMIN_ROLES for r in member.roles)


def url_ok(url):
    u = urlparse(url)
    return u.scheme == "https" and u.hostname in ALLOWED_HOSTS


async def download(url, dest):
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, allow_redirects=True, max_redirects=5) as r:
            if r.status != 200:
                raise ValueError(f"download failed: HTTP {r.status}")
            if r.url.host not in ALLOWED_HOSTS:
                raise ValueError(f"redirected to a host that is not allowed: {r.url.host}")
            size = 0
            total = int(r.headers.get("Content-Length") or 0)
            if total:
                log(f"  downloading {total / 1048576:.1f} MB")
            with open(dest, "wb") as fh:
                async for chunk in r.content.iter_chunked(1 << 20):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError(f"file is larger than {MAX_BYTES >> 20} MB")
                    fh.write(chunk)
            return size


async def run_pmcheck(zip_path, fmt, workdir, pr=False):
    # TMPDIR inside the per-check folder: even a killed check leaves nothing outside it.
    env = dict(os.environ, TMPDIR=str(workdir))
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-m", "pmcheck", str(zip_path), "--format", fmt, "--ai", "--warn-only", *(["--pr"] if pr else []),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ValueError(f"check timed out after {TIMEOUT}s")
    if proc.returncode not in (0, 1):
        raise ValueError(err.decode(errors="replace").strip()[-500:] or "pmcheck failed")
    return out.decode(errors="replace")


@tree.command(name="checkport", description="Check a PortMaster port zip against the packaging guidelines", guild=GUILD)
@app_commands.describe(url="Port .zip link (Discord attachment or GitHub) or a PortMaster-New pull request link")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def checkport(inter: discord.Interaction, url: str):
    prn = ghpr.pr_number(url)
    name = f"PR #{prn}" if prn else (Path(urlparse(url).path).name or "?")
    log(f"/checkport {name} by {inter.user}")
    if not is_admin(inter.user):
        log("  rejected: not an admin")
        await inter.response.send_message("This command is for PortMaster admins.", ephemeral=True)
        return
    if not prn and not url_ok(url):
        log(f"  rejected: host {urlparse(url).hostname}")
        await inter.response.send_message("Only https links from Discord or GitHub are accepted.", ephemeral=True)
        return
    if lock.locked():
        log("  rejected: another check is running")
        await inter.response.send_message("A check is already running, try again in a minute.", ephemeral=True)
        return
    await inter.response.defer(thinking=True)
    async with lock:
        tmp = Path(tempfile.mkdtemp(prefix="pmbot-"))
        try:
            t0 = time.monotonic()
            if prn:
                info, targets = await asyncio.to_thread(ghpr.fetch, url, tmp / "ports", MAX_BYTES, log)
                title = f"PR #{prn}: {info['title']}" + ("" if info["state"] == "open" else f" ({info['state']})")
            else:
                targets, title = [tmp / "port.zip"], None
                size = await download(url, targets[0])
            log(f"  downloaded in {time.monotonic() - t0:.0f}s; running rules + AI review")
            results, mds = [], []
            for target in targets:
                t1 = time.monotonic()
                result = json.loads(await run_pmcheck(target, "json", tmp, pr=bool(prn)))
                results.append(result)
                mds.append(await run_pmcheck_md_from(result))
                c = result["counts"]
                ai = result.get("ai")
                ai_state = f"{len(ai)} AI notes" if isinstance(ai, list) else (ai or "no AI")
                log(f"  {result['port']} done in {time.monotonic() - t1:.0f}s: {c['ERROR']} errors, {c['WARN']} warnings, {c['INFO']} notes; {ai_state}")
        except (ValueError, aiohttp.ClientError, json.JSONDecodeError) as e:
            log(f"  failed: {e}")
            await inter.followup.send(f"❌ Check failed: {e}")
            return
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    # One output only: the full report inline when it fits, otherwise a headline plus the report as a file.
    md = "\n\n---\n\n".join(mds)
    if title:
        md = f"**{title}**\n<{url}>\n\n{md}"
    if len(md) <= 1900:
        await inter.followup.send(md)
        return
    counts = "; ".join(f"**{r['port']}**: {r['counts']['ERROR']} errors, {r['counts']['WARN']} warnings, {r['counts']['INFO']} notes" for r in results)
    head = (f"**{title}**\n" if title else "") + counts + ". Full report attached."
    fname = f"pmcheck-pr{prn}.md" if prn else f"pmcheck-{results[0]['port']}.md"
    await inter.followup.send(head, file=discord.File(io.BytesIO(md.encode()), filename=fname))


async def run_pmcheck_md_from(result):
    """Render markdown from the JSON result (avoids a second check and a second Gemini call)."""
    from pmcheck.findings import Finding
    from pmcheck.report import markdown
    fs = [Finding(**{k: f.get(k, "" if k not in ("line",) else 0) for k in ("rule", "severity", "message", "file", "line", "fix", "snippet")})
          for f in result["findings"]]
    return markdown(result["port"], fs, result.get("ai"))


def clean_stale():
    """Remove check folders left by a crash or kill (the container's /tmp is a RAM tmpfs, also wiped on restart)."""
    root = Path(tempfile.gettempdir())
    for d in list(root.glob("pmbot-*")) + list(root.glob("pmcheck-*")):
        shutil.rmtree(d, ignore_errors=True)


@client.event
async def on_ready():
    await tree.sync(guild=GUILD)
    print(f"pmcheck bot ready as {client.user}", flush=True)


if __name__ == "__main__":
    if not ADMIN_ROLES:
        sys.exit("ADMIN_ROLE_IDS is empty; refusing to start an unrestricted bot.")
    clean_stale()
    client.run(TOKEN)
