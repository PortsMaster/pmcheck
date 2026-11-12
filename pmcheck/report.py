import json

from . import __version__
from .findings import ERROR, WARN, INFO, ORDER


def counts(findings):
    c = {ERROR: 0, WARN: 0, INFO: 0}
    for f in findings:
        c[f.severity] += 1
    return c


def summary_line(findings):
    c = counts(findings)
    return f"{c[ERROR]} errors, {c[WARN]} warnings, {c[INFO]} notes"


def md(text):
    """Escape markdown in finding text (Discord and GitHub would turn libgl_*.txt or LIX_CURSOR_MIN_SCALE into italics);
    `code spans` stay as they are."""
    parts = str(text).split("`")
    for i in range(0, len(parts), 2):          # even parts are outside backticks
        parts[i] = "".join("\\" + c if c in "\\*_~|" else c for c in parts[i])
    return "`".join(parts) if len(parts) % 2 else "`".join(parts[:-1]) + "\\`" + parts[-1]


def markdown(name, findings, ai=None):
    fs = sorted(findings, key=lambda f: (ORDER[f.severity], f.file, f.line))
    out = [f"# pmcheck {__version__}: {name}", "", f"**{summary_line(findings)}**", ""]
    icon = {ERROR: "❌", WARN: "⚠️", INFO: "ℹ️"}
    for sev in (ERROR, WARN, INFO):
        group = [f for f in fs if f.severity == sev]
        if not group:
            continue
        out += [f"## {icon[sev]} {sev} ({len(group)})", ""]
        for f in group:
            loc = f" `{f.file}{':' + str(f.line) if f.line else ''}`" if f.file else ""
            out.append(f"- **{f.rule}**{loc}: {md(f.message)}")
            if f.fix:
                out.append(f"  - Fix: {md(f.fix)}")
            if f.snippet:
                out += ["", "  ```bash", *["  " + l for l in f.snippet.splitlines()], "  ```", ""]
        out.append("")
    if ai is not None:
        out += ["## 🤖 AI review (advisory)", ""]
        if isinstance(ai, str):
            out.append(f"_{md(ai)}_")
        elif not ai:
            out.append("_No additional issues found._")
        items = ai if isinstance(ai, list) else []
        for a in items:
            loc = f" `{a.get('file', '')}{':' + str(a['line']) if a.get('line') else ''}`" if a.get("file") else ""
            out.append(f"- **{a.get('severity', 'note')}**{loc}: {md(a.get('issue', ''))}")
            if a.get("fix"):
                out.append(f"  - Fix: {md(a['fix'])}")
        out.append("")
    return "\n".join(out)


def as_json(name, findings, ai=None):
    return json.dumps({"port": name, "counts": counts(findings), "findings": [f.dict() for f in findings], "ai": ai}, indent=2)


def github(findings, prefix=""):
    """GitHub workflow commands -> annotations on the PR diff."""
    level = {ERROR: "error", WARN: "warning", INFO: "notice"}
    out = []
    for f in sorted(findings, key=lambda f: ORDER[f.severity]):
        msg = f"{f.message}" + (f" Fix: {f.fix}" if f.fix else "")
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        props = [f"title=pmcheck {f.rule}"]
        if f.file:
            props.append(f"file={prefix}{f.file}")
            if f.line:
                props.append(f"line={f.line}")
        out.append(f"::{level[f.severity]} {','.join(props)}::{msg}")
    return "\n".join(out)
