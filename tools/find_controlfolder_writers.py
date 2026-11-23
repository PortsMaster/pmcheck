#!/usr/bin/env python3
"""List launch scripts that create, write or delete anything inside PortMaster's own folder.

A folder made at $XDG_DATA_HOME/PortMaster (~/.local/share/PortMaster) makes every other port's header pick that empty
folder instead of the real PortMaster, so every port then fails with "control.txt: No such file".

    python3 -I tools/find_controlfolder_writers.py <folder|script.sh> ...      (folders are searched recursively for *.sh)

Exit status 1 when a script is listed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pmcheck.rules import controlfolder_writes  # noqa: E402


def scripts(args):
    for a in args:
        p = Path(a)
        yield from ([p] if p.is_file() else sorted(p.rglob("*.sh")))


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    found = 0
    for s in scripts(argv):
        text = s.read_bytes().decode("utf-8", "replace")
        code = [(n, l) for n, l in enumerate(text.splitlines(), 1) if not l.strip().startswith("#")]
        hits = controlfolder_writes(code)
        if hits:
            found += 1
            print(s)
            for n, l in hits:
                print(f"  {n:>4}  {l[:150]}")
    print(f"{found} script(s) write into PortMaster's folder")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
