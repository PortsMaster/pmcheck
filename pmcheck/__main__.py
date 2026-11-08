"""pmcheck CLI.

  python -m pmcheck <zip|folder> [--format md|json|github] [--ai] [--warn-only]
  python -m pmcheck --sweep <PortMaster-New/ports>     rule hit counts across many ports
"""
import argparse
import collections
import sys
from pathlib import Path

from . import report
from .findings import ERROR
from .model import load, LoadError
from .rules import run_all


def check_one(path, ai=False):
    port = load(path)
    try:
        findings = run_all(port)
        ai_result = None
        if ai:
            from .llm import review
            ai_result = review(port, findings)
        name = port.gamedir.name if port.gamedir else Path(path).name
        return name, findings, ai_result
    finally:
        port.cleanup()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pmcheck")
    ap.add_argument("path")
    ap.add_argument("--format", choices=("md", "json", "github"), default="md")
    ap.add_argument("--ai", action="store_true", help="add the Gemini advisory review (needs GEMINI_API_KEY)")
    ap.add_argument("--warn-only", action="store_true", help="exit 0 even with errors")
    ap.add_argument("--prefix", default="", help="path prefix for GitHub annotations (e.g. ports/foo/)")
    ap.add_argument("--summary", help="also append the markdown report to this file (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--sweep", action="store_true", help="path is a folder of ports; print rule hit counts")
    a = ap.parse_args(argv)

    if a.sweep:
        hits, ports_with = collections.Counter(), collections.Counter()
        dirs = sorted(p for p in Path(a.path).iterdir() if p.is_dir())
        for d in dirs:
            try:
                _, fs, _ = check_one(d)
            except LoadError as e:
                print(f"{d.name}: load error: {e}", file=sys.stderr)
                continue
            for r in {(f.severity, f.rule) for f in fs}:
                ports_with[r] += 1
            for f in fs:
                hits[(f.severity, f.rule)] += 1
        print(f"{len(dirs)} ports")
        for (sev, rule), n in sorted(ports_with.items(), key=lambda kv: -kv[1]):
            print(f"{n:5} ports  {hits[(sev, rule)]:6} hits  {sev:5} {rule}")
        return 0

    try:
        name, findings, ai = check_one(a.path, a.ai)
    except LoadError as e:
        print(f"pmcheck: {e}", file=sys.stderr)
        return 2
    if a.format == "md":
        print(report.markdown(name, findings, ai))
    elif a.format == "json":
        print(report.as_json(name, findings, ai))
    else:
        print(report.github(findings, a.prefix))
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write(report.markdown(name, findings, ai) + "\n")
    failed = any(f.severity == ERROR for f in findings)
    return 1 if failed and not a.warn_only else 0


if __name__ == "__main__":
    sys.exit(main())
