#!/usr/bin/env python3
"""Refresh pmcheck/runtimes.json from PortMaster-New's released ports.json (the catalog harbourmaster reads)."""
import datetime
import json
import sys
import urllib.request
from pathlib import Path

URL = "https://github.com/PortsMaster/PortMaster-New/releases/latest/download/ports.json"


def build(d):
    keys, files = {}, {}
    for fname, a in d["utils"].items():
        if not fname.endswith(".squashfs"):
            continue
        # harbourmaster keys a runtime by runtime_name, or by the file name when that is missing (source.py)
        key = a.get("runtime_name") or fname
        keys.setdefault(key, set()).add(a.get("runtime_arch") or "aarch64")
        files[fname] = key
    return {"updated": datetime.date.today().isoformat(),
            "keys": {k: sorted(v) for k, v in sorted(keys.items())},
            "files": dict(sorted(files.items()))}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    raw = Path(src).read_bytes() if src else urllib.request.urlopen(URL, timeout=30).read()
    out = Path(__file__).resolve().parent.parent / "pmcheck" / "runtimes.json"
    out.write_text(json.dumps(build(json.loads(raw)), indent=1) + "\n")
    print(f"{out}: {len(json.loads(out.read_text())['keys'])} runtimes")


if __name__ == "__main__":
    main()
