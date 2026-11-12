#!/usr/bin/env python3
"""Build pmcheck/script_lines.json from a PortMaster-New checkout (only ports/*/*.sh is read).

  git clone --filter=blob:none --no-checkout --depth 1 https://github.com/PortsMaster/PortMaster-New.git pmnew
  cd pmnew && git sparse-checkout set --no-cone '/ports/*/*.sh' && git checkout && cd ..
  python3 tools/build_script_lines.py pmnew
"""
import collections
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pmcheck import scriptnorm  # noqa: E402

MIN_SCRIPTS = 10   # a normalized line in at least this many merged scripts is standard


def main(root):
    scripts = sorted(Path(root, "ports").glob("*/*.sh"))
    freq, per = collections.Counter(), []
    for p in scripts:
        ls = scriptnorm.lines(p.read_text(errors="replace"))
        per.append(ls)
        freq.update({k for _, k, _ in ls})
    common = {k: c for k, c in freq.items() if c >= MIN_SCRIPTS}
    counts = sorted(sum(1 for _, k, raw in ls if scriptnorm.counted(k, raw, common)) for ls in per)
    q = lambda f: counts[int(f * (len(counts) - 1))]
    out = {
        "generated": datetime.date.today().isoformat(),
        "scripts": len(scripts),
        "min_scripts": MIN_SCRIPTS,
        "percentiles": {"50": q(.5), "75": q(.75), "90": q(.9), "95": q(.95), "99": q(.99)},
        "lines": dict(sorted(common.items())),
    }
    dest = Path(__file__).resolve().parent.parent / "pmcheck" / "script_lines.json"
    dest.write_text(json.dumps(out, indent=0, ensure_ascii=False) + "\n")
    print(f"{len(scripts)} scripts, {len(common)} standard lines, percentiles {out['percentiles']} -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pmnew")
