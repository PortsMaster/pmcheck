"""Discord bot: admin-only /checkport <url> -> pmcheck report (rules + Gemini advisory).

Env (see config.example.env):
  DISCORD_TOKEN, GUILD_ID, ADMIN_ROLE_IDS (comma separated), GEMINI_API_KEY,
  PMCHECK_GEMINI_MODEL (optional), MAX_DOWNLOAD_MB (default 1024), CHECK_TIMEOUT (default 900)
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


async def run_pmcheck(zip_path, fmt):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-m", "pmcheck", str(zip_path), "--format", fmt, "--ai", "--warn-only",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise ValueError(f"check timed out after {TIMEOUT}s")
    if proc.returncode not in (0, 1):
        raise ValueError(err.decode(errors="replace").strip()[-500:] or "pmcheck failed")
    return out.decode(errors="replace")


@tree.command(name="checkport", description="Check a PortMaster port zip against the packaging guidelines", guild=GUILD)
@app_commands.describe(url="Link to the port .zip (Discord attachment or GitHub)")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def checkport(inter: discord.Interaction, url: str):
    name = Path(urlparse(url).path).name or "?"
    log(f"/checkport {name} by {inter.user}")
    if not is_admin(inter.user):
        log("  rejected: not an admin")
        await inter.response.send_message("This command is for PortMaster admins.", ephemeral=True)
        return
    if not url_ok(url):
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
            zip_path = tmp / "port.zip"
            t0 = time.monotonic()
            size = await download(url, zip_path)
            log(f"  downloaded {size / 1048576:.1f} MB in {time.monotonic() - t0:.0f}s; running rules + AI review")
            t1 = time.monotonic()
            result = json.loads(await run_pmcheck(zip_path, "json"))
            md = await run_pmcheck_md_from(result)
            c = result["counts"]
            ai = result.get("ai")
            ai_state = f"{len(ai)} AI notes" if isinstance(ai, list) else (ai or "no AI")
            log(f"  done in {time.monotonic() - t1:.0f}s: {c['ERROR']} errors, {c['WARN']} warnings, {c['INFO']} notes; {ai_state}")
        except (ValueError, aiohttp.ClientError, json.JSONDecodeError) as e:
            log(f"  failed: {e}")
            await inter.followup.send(f"❌ Check failed: {e}")
            return
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    c = result["counts"]
    lines = [f"**{result['port']}**: {c['ERROR']} errors, {c['WARN']} warnings, {c['INFO']} notes"]
    for f in [x for x in result["findings"] if x["severity"] == "ERROR"][:8]:
        lines.append(f"❌ `{f['rule']}` {f['message'][:160]}")
    ai = result.get("ai")
    if isinstance(ai, list) and ai:
        lines.append("🤖 AI notes:")
        for a in ai[:4]:
            lines.append(f"• {a.get('issue', '')[:160]}")
    elif isinstance(ai, str):
        lines.append(f"🤖 {ai}")
    msg = "\n".join(lines)[:1900]
    file = discord.File(io.BytesIO(md.encode()), filename=f"pmcheck-{result['port']}.md")
    await inter.followup.send(msg, file=file)


async def run_pmcheck_md_from(result):
    """Render markdown from the JSON result (avoids a second check and a second Gemini call)."""
    from pmcheck.findings import Finding
    from pmcheck.report import markdown
    fs = [Finding(**{k: f.get(k, "" if k not in ("line",) else 0) for k in ("rule", "severity", "message", "file", "line", "fix", "snippet")})
          for f in result["findings"]]
    return markdown(result["port"], fs, result.get("ai"))


@client.event
async def on_ready():
    await tree.sync(guild=GUILD)
    print(f"pmcheck bot ready as {client.user}", flush=True)


if __name__ == "__main__":
    if not ADMIN_ROLES:
        sys.exit("ADMIN_ROLE_IDS is empty; refusing to start an unrestricted bot.")
    client.run(TOKEN)
