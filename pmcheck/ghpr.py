"""Fetch the port folders of a PortMaster-New pull request (no git, no code execution).

Uses the GitHub REST API (a few calls per PR; GITHUB_TOKEN raises the 60/hour anonymous limit)
and downloads each file of ports/<name>/ at the PR head commit from raw.githubusercontent.com.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = "PortsMaster/PortMaster-New"
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


def _get(url, raw=False, timeout=60):
    headers = {"User-Agent": "pmcheck", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.read() if raw else json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 403 and url.startswith(API):
            raise PRError("GitHub API rate limit reached (60 requests/hour without GITHUB_TOKEN); try again later.")
        raise PRError(f"GitHub returned HTTP {e.code} for {url.split('?')[0]}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise PRError(f"GitHub not reachable ({e.__class__.__name__}).")


def _subtree(repo, sha, name):
    """Tree sha of ports/<name> at commit sha, or None."""
    root = _get(f"{API}/repos/{repo}/git/trees/{sha}")
    ports = next((t["sha"] for t in root["tree"] if t["path"] == "ports" and t["type"] == "tree"), None)
    if not ports:
        return None
    listing = _get(f"{API}/repos/{repo}/git/trees/{ports}")
    return next((t["sha"] for t in listing["tree"] if t["path"] == name and t["type"] == "tree"), None)


def fetch(url, dest, max_bytes, log=print):
    """Download the ports a PR touches into dest/<name>/. Returns (info dict, [port folder paths])."""
    n = pr_number(url)
    if n is None:
        raise PRError("Not a PortMaster-New pull request link.")
    pr = _get(f"{API}/repos/{REPO}/pulls/{n}")
    head = pr.get("head") or {}
    repo = (head.get("repo") or {}).get("full_name") or ""
    sha = head.get("sha") or ""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PRError("The PR's source branch is gone (fork deleted?).")
    names = []
    for page in range(1, 31):
        files = _get(f"{API}/repos/{REPO}/pulls/{n}/files?per_page=100&page={page}")
        for f in files:
            parts = f["filename"].split("/")
            if len(parts) >= 3 and parts[0] == "ports" and f.get("status") != "removed" and parts[1] not in names:
                names.append(parts[1])
        if len(files) < 100:
            break
    if not names:
        raise PRError(f"PR #{n} adds or changes no files under ports/.")
    if len(names) > MAX_PORTS:
        raise PRError(f"PR #{n} touches {len(names)} ports; the bot checks at most {MAX_PORTS}.")
    info = {"number": n, "title": pr.get("title", ""), "state": pr.get("state", ""), "repo": repo, "sha": sha, "ports": names}
    jobs, total = [], 0
    for name in names:
        if not SAFE_PART.match(name) or name in (".", ".."):
            raise PRError(f"Bad port folder name {name!r}.")
        tsha = _subtree(repo, sha, name)
        if not tsha:
            continue   # port folder deleted in this PR
        tree = _get(f"{API}/repos/{repo}/git/trees/{tsha}?recursive=1")
        if tree.get("truncated"):
            raise PRError(f"ports/{name} has too many files for the GitHub tree API.")
        for t in tree["tree"]:
            if t["type"] == "tree":
                continue
            if t["type"] != "blob" or t.get("mode") == "120000":
                raise PRError(f"ports/{name}/{t['path']} is a symlink or submodule; not allowed in a port.")
            parts = t["path"].split("/")
            if any(p in ("", ".", "..") or not SAFE_PART.match(p) for p in parts):
                raise PRError(f"Unsafe path in ports/{name}: {t['path']!r}")
            total += t.get("size", 0)
            jobs.append((name, t["path"]))
    if not jobs:
        raise PRError(f"PR #{n} only deletes ports; nothing to check.")
    if len(jobs) > MAX_FILES:
        raise PRError(f"PR #{n} has {len(jobs)} files; the bot checks at most {MAX_FILES}.")
    if total > max_bytes:
        raise PRError(f"PR #{n} is {total >> 20} MB; the limit is {max_bytes >> 20} MB.")
    log(f"  PR #{n} ({repo}@{sha[:8]}): {', '.join(names)}, {len(jobs)} files, {total / 1048576:.1f} MB")
    dest = Path(dest)

    def one(job):
        name, path = job
        q = urllib.parse.quote(f"ports/{name}/{path}")
        data = _get(f"{RAW}/{repo}/{sha}/{q}", raw=True, timeout=300)
        out = dest / name / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, jobs))
    return info, [dest / name for name in names if (dest / name).is_dir()]
