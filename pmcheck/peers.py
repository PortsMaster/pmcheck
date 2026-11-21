"""Closest merged PortMaster port to a launch script (pmcheck/script_peers.json, built by tools/build_peers.py).

A launch script is compared with the merged scripts of the same kind (engine/runtime tags) by the normalized lines
they share, rare lines counting more than template lines. Reviewers do the same by hand: "look at how port X does it".
"""
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from . import scriptnorm

REPO = "https://github.com/PortsMaster/PortMaster-New/blob/main/ports"
RAW = "https://raw.githubusercontent.com/PortsMaster/PortMaster-New/main/ports"

# (tag, pattern over the script's code): what kind of port this is
TAGS = [
    ("unity", r"\bua_host"),
    ("quixjs", r"\bquixjs"),
    ("lus", r"\.o2r\b|baseroms/"),
    ("westonpack", r"westonwrap|weston_pkg"),
    ("box64", r"\bbox64\b"),
    ("box86", r"\bbox86\b"),
    ("mono", r"\bmono-[\d.]+|MONO_PATH|MMLoader"),
    ("dotnet", r"dotnet-[\d.]+|DOTNET_ROOT"),
    ("godot", r"\bfrt_|godot"),
    ("gamemaker", r"gmloader"),
    ("love", r"LOVE_RUN|love_[\d.]+|\blove\.txt"),
    ("java", r"\bzulu|\bjava\b|JAVA_HOME"),
    ("renpy", r"renpy"),
    ("python", r"python_3[\d.]*\.squashfs|pyxel|PYTHONHOME"),
    ("gl4es", r"libgl_\$\{?CFW_NAME|libgl_default"),
]


def code_lines(text):
    return [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def _love_runs_game(code):
    """LÖVE as the game's engine, not as a settings/extract helper before another binary (LUS ports, the patcher)."""
    lines = [l for l in code.splitlines() if l.strip()]
    tail = [l for l in lines if not re.match(r"\s*(pm_finish|exit|fi|done|rm\s|\$ESUDO\s+umount|umount|if\s|\})", l)][-3:]
    return any(re.search(r"LOVE_RUN|\blove\b|\.love\b", l) for l in tail)


def tags(text):
    code = "\n".join(code_lines(text))
    found = [t for t, rx in TAGS if re.search(rx, code, re.I) and (t != "love" or _love_runs_game(code))]
    if "unity" in found or "quixjs" in found:
        found = [t for t in found if t in ("unity", "quixjs", "westonpack", "box64")]
    return found or ["native"]


def kind(tag_list):
    """The tags that set the script's shape (gl4es is a detail when an engine tag is present)."""
    main = [t for t in tag_list if t != "gl4es"]
    return "+".join(main) if main else "+".join(tag_list)


def line_keys(text):
    """Short hashes of the normalized lines (the same normalization as sh.nonstandard)."""
    return sorted({hashlib.sha1(k.encode()).hexdigest()[:8] for _, k, _ in scriptnorm.lines(text) if k})


@lru_cache(maxsize=1)
def index():
    p = Path(__file__).with_name("script_peers.json")
    return json.loads(p.read_text()) if p.exists() else None


def closest(text, exclude=None):
    """(peer dict, similarity) of the most similar merged script of the same kind, or (None, 0)."""
    idx = index()
    if not idx:
        return None, 0.0
    mine_tags = tags(text)
    mine_kind = kind(mine_tags)
    keys = set(line_keys(text))
    n = idx["scripts"]
    df = idx["df"]
    idf = lambda k: math.log(n / df.get(k, 1))
    best, best_s = None, 0.0
    for p in idx["ports"]:
        if exclude and p["name"] == exclude:
            continue
        same = p["kind"] == mine_kind
        if not same and not set(mine_tags) & set(p["tags"]) - {"gl4es"}:
            continue
        theirs = set(p["keys"])
        inter = sum(idf(k) for k in keys & theirs)
        union = sum(idf(k) for k in keys | theirs) or 1.0
        s = inter / union + (0.2 if same else 0.0)
        if s > best_s:
            best, best_s = p, s
    return best, best_s


def kind_median(k):
    idx = index()
    return (idx or {}).get("kinds", {}).get(k, {}).get("median")


def url(peer):
    return f"{REPO}/{peer['name']}/{peer['script'].replace(' ', '%20')}"


def raw_url(peer):
    from urllib.parse import quote
    return f"{RAW}/{quote(peer['name'])}/{quote(peer['script'])}"
