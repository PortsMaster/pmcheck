"""Fetch the port folders of a PortMaster-New pull request (no code execution).

Normal path: anonymous git over HTTPS (refs/pull/N/head of the upstream repo), which doesn't count
against the REST API quota: commits only to find the merge base, then the two trees without blobs,
then only the blobs of the changed ports. Files are written from `git cat-file`, never from the
worktree, so symlinks, .gitattributes filters and eol rules don't apply.
The REST API is used for one optional metadata call (title, state), and as the fallback when git
isn't installed or can't reach GitHub (GITHUB_TOKEN raises its 60/hour anonymous limit).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = "PortsMaster/PortMaster-New"
GIT_REMOTE = f"https://github.com/{REPO}.git"
PR_RE = re.compile(r"^https://github\.com/PortsMaster/PortMaster-New/pull/(\d+)(?:[/?#].*)?$", re.I)
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
MAX_PORTS = 3
MAX_FILES = 5000
SAFE_PART = re.compile(r"^[^/\\\x00]+$")


class PRError(ValueError):
    pass


def pr_number(url):
    m = PR_RE.match(url.strip())
    return int(m.group(1)) if m else None


def _get(url, raw=False, timeout=60, tries=5, accept="application/vnd.github+json"):
    headers = {"User-Agent": "pmcheck", "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith((API, RAW)):
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read() if raw else json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read(4096) or b"{}").get("message", "") if url.startswith(API) else ""
            except (ValueError, OSError, AttributeError):
                msg = ""
            wait = e.headers.get("Retry-After", "")
            exhausted = e.headers.get("X-RateLimit-Remaining") == "0"
            # 429, 5xx and GitHub's secondary rate limit (403 + Retry-After or "secondary" in the message,
            # hit by bursts of large blob downloads even with a token) are temporary: wait, then retry
            secondary = e.code == 403 and not exhausted and (wait or "secondary" in msg.lower())
            if (e.code == 429 or e.code >= 500 or secondary) and attempt < tries - 1:
                time.sleep(min(int(wait), 60) if wait.isdigit() else 2 ** attempt * 5)
                continue
            if url.startswith(API) and (exhausted or (e.code == 403 and not token)):
                if not token:
                    raise PRError("GitHub API rate limit reached (60 requests/hour, no GITHUB_TOKEN set in the bot's env file); try again later.")
                raise PRError("GitHub API rate limit reached (5000 requests/hour for this GITHUB_TOKEN); try again later.")
            if secondary:
                raise PRError("GitHub's secondary rate limit stopped the downloads (too many large requests at once); try again in a few minutes.")
            if e.code == 429:
                raise PRError("GitHub is rate limiting file downloads (HTTP 429); try again in a few minutes"
                              + ("." if token else ", or set GITHUB_TOKEN in the bot's env file."))
            raise PRError(f"GitHub returned HTTP {e.code} for {url.split('?')[0]}" + (f": {msg}" if msg else ""))
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < tries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise PRError(f"GitHub not reachable ({e.__class__.__name__}).")


def _subtree(repo, sha, name):
    """Tree sha of ports/<name> at commit sha, or None."""
    root = _get(f"{API}/repos/{repo}/git/trees/{sha}")
    ports = next((t["sha"] for t in root["tree"] if t["path"] == "ports" and t["type"] == "tree"), None)
    if not ports:
        return None
    listing = _get(f"{API}/repos/{repo}/git/trees/{ports}")
    return next((t["sha"] for t in listing["tree"] if t["path"] == name and t["type"] == "tree"), None)


class _GitUnavailable(Exception):
    pass


def _meta(n, strict):
    """PR metadata from the REST API. strict=False: fall back to defaults when the API refuses."""
    try:
        pr = _get(f"{API}/repos/{REPO}/pulls/{n}")
    except PRError:
        if strict:
            raise
        return {"title": f"PR #{n}", "state": "open", "repo": REPO}
    head = pr.get("head") or {}
    return {"title": pr.get("title", ""), "state": pr.get("state", ""),
            "repo": (head.get("repo") or {}).get("full_name") or "", "sha": head.get("sha") or ""}


def _port_names(n, paths):
    names = []
    for f in paths:
        parts = f.split("/")
        if len(parts) >= 3 and parts[0] == "ports" and parts[1] not in names:
            names.append(parts[1])
    if not names:
        raise PRError(f"PR #{n} adds or changes no files under ports/.")
    if len(names) > MAX_PORTS:
        raise PRError(f"PR #{n} touches {len(names)} ports; the bot checks at most {MAX_PORTS}.")
    for name in names:
        if not SAFE_PART.match(name) or name in (".", ".."):
            raise PRError(f"Bad port folder name {name!r}.")
    return names


def _check_entry(name, path, kind, mode):
    if kind == "tree":
        return False
    if kind != "blob" or mode == "120000":
        raise PRError(f"ports/{name}/{path} is a symlink or submodule; not allowed in a port.")
    if any(p in ("", ".", "..") or not SAFE_PART.match(p) for p in path.split("/")):
        raise PRError(f"Unsafe path in ports/{name}: {path!r}")
    return True


def _check_totals(n, jobs, total, max_bytes):
    if not jobs:
        raise PRError(f"PR #{n} only deletes ports; nothing to check.")
    if len(jobs) > MAX_FILES:
        raise PRError(f"PR #{n} has {len(jobs)} files; the bot checks at most {MAX_FILES}.")
    if total > max_bytes:
        raise PRError(f"PR #{n} is {total >> 20} MB; the limit is {max_bytes >> 20} MB.")


def _write(dest, name, path, data):
    out = Path(dest) / name / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)


def fetch(url, dest, max_bytes, log=print, remote=GIT_REMOTE):
    """Download the ports a PR touches into dest/<name>/. Returns (info dict, [port folder paths])."""
    n = pr_number(url)
    if n is None:
        raise PRError("Not a PortMaster-New pull request link.")
    try:
        return _fetch_git(n, dest, max_bytes, log, remote)
    except _GitUnavailable as e:
        log(f"  git fetch unavailable ({e}); using the GitHub API")
        return _fetch_api(n, dest, max_bytes, log)


def _git(cwd, *args, timeout=300, data=None):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/true", "LC_ALL": "C"}
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false", "-c", "core.autocrlf=false",
           "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "protocol.file.allow=always",
           "-c", "advice.detachedHead=false", *args]
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, input=data, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise _GitUnavailable("git not installed")
    except subprocess.TimeoutExpired:
        raise _GitUnavailable(f"git {args[0]} timed out")
    if r.returncode:
        err = (r.stderr.decode(errors="replace").strip().splitlines() or ["?"])[-1]
        raise _GitError(err)
    return r.stdout


class _GitError(Exception):
    pass


NET_ERR = re.compile(r"unable to access|could not resolve|timed out|connection|ssl|early eof|remote end hung up|"
                     r"fatal: protocol|filtering not recognized|unsupported", re.I)


def _git_fetch(cwd, n, *args):
    try:
        _git(cwd, "fetch", "-q", "--no-tags", "--no-write-fetch-head", *args)
    except _GitError as e:
        if "couldn't find remote ref" in str(e).lower():
            raise PRError(f"PR #{n} not found.")
        if NET_ERR.search(str(e)):
            raise _GitUnavailable(str(e))
        raise PRError(f"git fetch failed: {e}")


def _fetch_git(n, dest, max_bytes, log, remote):
    dest = Path(dest)
    work = Path(tempfile.mkdtemp(prefix="pmcheck-git-", dir=dest.parent if dest.parent.is_dir() else None))
    try:
        # 1. commits only (both refs), for the merge base
        a = work / "hist"
        a.mkdir()
        _git(a, "init", "-q")
        _git_fetch(a, n, "--filter=tree:0", remote, f"+refs/pull/{n}/head:refs/pr", "+refs/heads/main:refs/main")
        sha = _git(a, "rev-parse", "refs/pr").decode().strip()
        try:
            base = _git(a, "merge-base", "refs/main", "refs/pr").decode().strip()
        except _GitError:
            raise PRError(f"PR #{n} shares no history with main.")
        shutil.rmtree(a, ignore_errors=True)
        # 2. the two trees, no blobs
        b = work / "tree"
        b.mkdir()
        _git(b, "init", "-q")
        _git_fetch(b, n, "--depth=1", "--filter=blob:none", remote, f"+{sha}:refs/pr", f"+{base}:refs/base")
        out = _git(b, "diff", "--name-only", "--no-renames", "-z", "refs/base", "refs/pr", "--", "ports/")
        alln = _git(b, "diff", "--name-only", "--no-renames", "-z", "--diff-filter=d", "refs/base", "refs/pr")
        changed = [p for p in alln.decode(errors="surrogateescape").split("\0") if p]
        touched = [p for p in out.decode(errors="surrogateescape").split("\0") if p]
        names = _port_names(n, [p for p in changed if p.startswith("ports/")] or touched)
        meta = _meta(n, strict=False)
        info = {"number": n, "title": meta["title"], "state": meta["state"], "repo": meta.get("repo") or REPO,
                "sha": sha, "ports": names, "files": changed}
        # 3. validate every entry before any blob comes down
        jobs, total = [], 0
        for name in names:
            raw = _git(b, "ls-tree", "-r", "-t", "-l", "-z", "--full-tree", "refs/pr", "--", f"ports/{name}/")
            for rec in raw.split(b"\0"):
                if not rec:
                    continue
                head, _, path = rec.partition(b"\t")
                mode, kind, oid, size = head.decode().split()
                rel = path.decode(errors="surrogateescape")[len(f"ports/{name}/"):]
                if _check_entry(name, rel, kind, mode):
                    total += int(size)
                    jobs.append((name, rel, oid))
        _check_totals(n, jobs, total, max_bytes)
        log(f"  PR #{n} ({info['repo']}@{sha[:8]}): {', '.join(names)}, {len(jobs)} files, {total / 1048576:.1f} MB (git)")
        # 4. one batched blob download for just these folders
        _git(b, "config", "core.sparseCheckout", "true")
        (b / ".git" / "info").mkdir(exist_ok=True)
        (b / ".git" / "info" / "sparse-checkout").write_text("".join(f"/ports/{x}/\n" for x in names))
        try:
            _git(b, "checkout", "-q", "refs/pr", timeout=600)
        except _GitError as e:
            if NET_ERR.search(str(e)):
                raise _GitUnavailable(str(e))
            raise PRError(f"git checkout failed: {e}")
        # 5. byte-exact export from the object store, streamed (PRs can be up to max_bytes)
        _export(b, dest, jobs)
        return info, [dest / x for x in names if (dest / x).is_dir()]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _export(repo, dest, jobs):
    import threading
    p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                         "HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"})

    def feed():
        try:
            p.stdin.write("".join(f"{j[2]}\n" for j in jobs).encode())
        except OSError:
            pass
        finally:
            p.stdin.close()
    t = threading.Thread(target=feed, daemon=True)
    t.start()
    try:
        for name, rel, oid in jobs:
            hdr = p.stdout.readline().split()
            if len(hdr) != 3 or hdr[0].decode() != oid or hdr[1] != b"blob":
                raise PRError(f"git could not read ports/{name}/{rel}.")
            left = int(hdr[2])
            out = Path(dest) / name / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                while left:
                    chunk = p.stdout.read(min(left, 1 << 20))
                    if not chunk:
                        raise PRError(f"git stopped while reading ports/{name}/{rel}.")
                    f.write(chunk)
                    left -= len(chunk)
            p.stdout.read(1)   # newline after each object
    finally:
        p.kill()
        p.wait()
        t.join(5)
        p.stdout.close()


def _fetch_api(n, dest, max_bytes, log):
    meta = _meta(n, strict=True)
    repo, sha = meta["repo"], meta["sha"]
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PRError("The PR's source branch is gone (fork deleted?).")
    names, changed = [], []
    for page in range(1, 31):
        files = _get(f"{API}/repos/{REPO}/pulls/{n}/files?per_page=100&page={page}")
        for f in files:
            if f.get("status") != "removed":
                changed.append(f["filename"])
        names_src = [f["filename"] for f in files if f.get("status") != "removed"]
        names += [x for x in names_src if x not in names]
        if len(files) < 100:
            break
    names = _port_names(n, names)
    info = {"number": n, "title": meta["title"], "state": meta["state"], "repo": repo, "sha": sha, "ports": names, "files": changed}
    jobs, total = [], 0
    for name in names:
        tsha = _subtree(repo, sha, name)
        if not tsha:
            continue   # port folder deleted in this PR
        tree = _get(f"{API}/repos/{repo}/git/trees/{tsha}?recursive=1")
        if tree.get("truncated"):
            raise PRError(f"ports/{name} has too many files for the GitHub tree API.")
        for t in tree["tree"]:
            if _check_entry(name, t["path"], t["type"], t.get("mode")):
                total += t.get("size", 0)
                jobs.append((name, t["path"], t["sha"]))
    _check_totals(n, jobs, total, max_bytes)
    log(f"  PR #{n} ({repo}@{sha[:8]}): {', '.join(names)}, {len(jobs)} files, {total / 1048576:.1f} MB (API)")

    def one(job):
        name, path, blob = job
        if os.environ.get("GITHUB_TOKEN"):
            # blob API: 5000/hour with a token; raw.githubusercontent.com rate-limits per IP (HTTP 429)
            data = _get(f"{API}/repos/{repo}/git/blobs/{blob}", raw=True, timeout=300, accept="application/vnd.github.raw")
        else:
            q = urllib.parse.quote(f"ports/{name}/{path}")
            data = _get(f"{RAW}/{repo}/{sha}/{q}", raw=True, timeout=300)
        _write(dest, name, path, data)

    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, jobs))
    dest = Path(dest)
    return info, [dest / name for name in names if (dest / name).is_dir()]
