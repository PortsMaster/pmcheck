#!/usr/bin/env python3
"""Build pmcheck/known_binaries.json: which builds of the shared runtime loaders merged ports ship.

Needs only the file list with git blob ids, no file content (a blobless clone is enough):

  git clone --filter=blob:none --no-checkout --depth 1 https://github.com/PortsMaster/PortMaster-New.git pmnew
  git -C pmnew ls-tree -r HEAD > tree.txt
  python3 tools/build_known_binaries.py tree.txt

Never `git ls-tree -l` on a blobless clone: the sizes make git download every blob one by one.

Records, for every executable (*.aarch64) or library (*.so*) name that at least MIN_COPIES merged ports ship: how many copies, how many different
builds, how many ports have a build of their own, and the git blob ids (12 hex digits) of the builds.
"""
import collections
import datetime
import json
import re
import sys
from pathlib import Path

MIN_COPIES = 20


def main(tree):
    by = collections.defaultdict(list)
    for line in Path(tree).read_text().splitlines():
        meta, path = line.split("\t", 1)
        sha = meta.split()[2]
        parts = path.split("/")
        if parts[0] == "ports" and len(parts) > 2 and re.search(r"\.(?:aarch64|so(?:\.\d+)*)$", parts[-1]):
            by[parts[-1]].append((sha, parts[1]))
    out = {}
    for name, v in sorted(by.items()):
        if len(v) < MIN_COPIES:
            continue
        count = collections.Counter(h for h, _ in v)
        out[name] = {"copies": len(v), "builds": len(count), "own_build": len({p for h, p in v if count[h] == 1}),
                     "hashes": sorted(h[:12] for h in count)}
    dest = Path(__file__).resolve().parent.parent / "pmcheck" / "known_binaries.json"
    dest.write_text(json.dumps({"generated": datetime.date.today().isoformat(), "binaries": out}, indent=0) + "\n")
    print(", ".join(f"{n}: {d['copies']} copies, {d['builds']} builds, {d['own_build']} own" for n, d in out.items()), "->", dest)


if __name__ == "__main__":
    main(sys.argv[1])
