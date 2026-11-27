#!/usr/bin/env python3
"""Build pmcheck/port_files.json from a PortMaster-New checkout: what merged ports ship besides the launch script.

Reads only ports/*/*.sh, ports/*/**/*.py and ports/*/**/patchscript* (sparse checkout, see build_script_lines.py):

  git clone --filter=blob:none --no-checkout --depth 1 https://github.com/PortsMaster/PortMaster-New.git pmnew
  cd pmnew && git sparse-checkout set --no-cone '/ports/*/*.sh' '/ports/**/*.py' '/ports/**/patchscript*' && git checkout && cd ..
  python3 tools/build_port_files.py pmnew

Never `git ls-tree -l` on a blobless clone: the sizes make git download every blob one by one.

Records: helper files that are byte-identical in several ports (the shared patcher tools), how much code of its own the
ports of an ordinary kind ship, how long merged patchscripts are, and how many scripts start the game through another script.
"""
import collections
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pmcheck import peers  # noqa: E402

CODE_EXT = (".py",)   # .js/.rb/.pl in merged ports are game scripting data (OpenFodder, PuzzleScript), not helpers
SHARED_MIN = 3   # a code file that is byte-identical in this many ports is a shared helper


def code_lines(text):
    return len([l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")])


def digest(text):
    return hashlib.sha1(text.encode()).hexdigest()


def pct(vals, f):
    vals = sorted(vals)
    return vals[int(f * (len(vals) - 1))] if vals else 0


def main(root):
    ports = Path(root, "ports")
    scripts = sorted(ports.glob("*/*.sh"))
    kind_of, flagged = {}, []
    for s in scripts:
        text = s.read_text(errors="replace")
        kind_of.setdefault(s.parent.name, peers.kind(peers.tags(text)))
        if peers.indirect_launch(text):
            flagged.append(s.parent.name)
    files = collections.defaultdict(dict)   # port -> {relative path: (digest, lines)}
    for p in ports.glob("*/**/*"):
        if p.is_file() and p.suffix in CODE_EXT:
            text = p.read_text(errors="replace")
            files[p.relative_to(ports).parts[0]][str(p.relative_to(ports / p.relative_to(ports).parts[0]))] = (digest(text), code_lines(text))
    users = collections.defaultdict(set)
    names = {}
    for port, fs in files.items():
        for rel, (h, _) in fs.items():
            users[h].add(port)
            names.setdefault(h, Path(rel).name)
    shared = {h: names[h] for h, u in users.items() if len(u) >= SHARED_MIN}
    own = {}
    for port, fs in files.items():
        if kind_of.get(port) in peers.ENGINE_SCRIPT_KINDS:
            continue
        n = sum(lines for h, lines in fs.values() if h not in shared)
        if n:
            own[port] = n
    patch = [code_lines(p.read_text(errors="replace")) for p in ports.glob("*/**/patchscript*") if p.is_file()]
    out = {
        "generated": datetime.date.today().isoformat(),
        "scripts": len(scripts),
        "shared_min": SHARED_MIN,
        "shared": dict(sorted(shared.items(), key=lambda kv: kv[1])),
        "own_code": {"ports": len(own), "p50": pct(own.values(), .5), "p90": pct(own.values(), .9), "max": max(own.values(), default=0),
                     "largest": [k for k, _ in sorted(own.items(), key=lambda kv: -kv[1])[:3]]},
        "patchscript": {"count": len(patch), "p50": pct(patch, .5), "p90": pct(patch, .9), "max": max(patch, default=0)},
        "indirect_launch": {"scripts": len(scripts), "flagged": len(flagged), "ports": sorted(set(flagged))},
    }
    dest = Path(__file__).resolve().parent.parent / "pmcheck" / "port_files.json"
    dest.write_text(json.dumps(out, indent=0, ensure_ascii=False) + "\n")
    print(f"{len(scripts)} scripts, {len(shared)} shared helpers, own code in {len(own)} ports (max {out['own_code']['max']}), "
          f"patchscripts {len(patch)} (max {out['patchscript']['max']}), indirect launch {len(flagged)} -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1])
