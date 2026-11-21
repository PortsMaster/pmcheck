#!/usr/bin/env python3
"""Build pmcheck/script_peers.json from a PortMaster-New checkout (only ports/*/*.sh is read; see build_script_lines.py
for the sparse clone). Per merged script: folder, script name, kind tags, code-line count and hashed normalized lines;
per kind: script count and median length.

  python3 tools/build_peers.py pmnew
"""
import collections
import datetime
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pmcheck import peers  # noqa: E402


def main(root):
    scripts = sorted(Path(root, "ports").glob("*/*.sh"))
    ports, df, by_kind = [], collections.Counter(), collections.defaultdict(list)
    for p in scripts:
        text = p.read_text(errors="replace")
        t = peers.tags(text)
        keys = peers.line_keys(text)
        n = len(peers.code_lines(text))
        df.update(keys)
        k = peers.kind(t)
        by_kind[k].append(n)
        ports.append({"name": p.parent.name, "script": p.name, "tags": t, "kind": k, "lines": n, "keys": keys})
    out = {
        "generated": datetime.date.today().isoformat(),
        "scripts": len(scripts),
        "df": {k: c for k, c in df.items() if c > 1},
        "kinds": {k: {"count": len(v), "median": int(statistics.median(v))} for k, v in sorted(by_kind.items())},
        "ports": ports,
    }
    dest = Path(__file__).resolve().parent.parent / "pmcheck" / "script_peers.json"
    dest.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{len(scripts)} scripts, {len(by_kind)} kinds -> {dest} ({dest.stat().st_size >> 10} KB)")
    for k, v in sorted(out["kinds"].items(), key=lambda kv: -kv[1]["count"])[:15]:
        print(f"  {k}: {v['count']} scripts, median {v['median']} lines")


if __name__ == "__main__":
    main(sys.argv[1])
