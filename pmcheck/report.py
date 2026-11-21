import json
import re

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


CODE = re.compile(r"""(?x)
    "\w+":\s*(?:"[^"\n]*"|\[[^\]\n]*\]|\w+)                                                 # JSON: "min_glibc": "2.34"
  | [\w.-]*\$\{?\w+\}?(?:[^\s,;()'"`<>]*[^\s,;()'"`<>.:])?                               # $VAR, mod_${CFW_NAME}.txt, $GAMEDIR/log.txt
  | (?<![\w.<])/(?:usr|lib|lib32|lib64|dev|proc|sys|etc|tmp|opt|roms|storage|mnt|run|var|bin|sbin)\b[\w./*-]*[\w*]  # /usr/lib32
  | (?<![\w.])[A-Za-z_][A-Za-z0-9_]*=(?:"[^"\n]*"|'[^'\n]*'|[^\s,;()'"`<>]*[^\s,;()'"`<>.:])  # NAME=value, NAME="value"
  | (?<![\w./<-])(?=[\w.+*-]*/)(?=[^\s]*(?:[._]|/(?:\s|$|[,;)])))[\w.+*-]*\w(?:/[\w.+*-]*)+(?<![.:])   # paths with a dot, _ or trailing /
  | (?<![\w.])[\w+*-][\w.+*-]*\.(?:txt|sh|ini|gptk|json|xml|py|lua|toml|squashfs|so(?:\.\d+)*)(?!\w)   # file names
  | (?<![\w.])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9.]*[A-Za-z0-9])+(?![\w])                     # snake_case / UPPER_CASE names
""")


def _code_spans(text):
    """Outside backticks and links: code-looking words become `code spans` (variables, assignments, file names),
    everything else gets markdown escaping."""
    out, last = [], 0
    for m in CODE.finditer(text):
        out.append("".join("\\" + c if c in "\\*_~|" else c for c in text[last:m.start()]))
        out.append(f"`{m.group(0)}`")
        last = m.end()
    out.append("".join("\\" + c if c in "\\*_~|" else c for c in text[last:]))
    return "".join(out)


def md(text):
    """Escape markdown in finding text (Discord and GitHub would turn libgl_*.txt or LIX_CURSOR_MIN_SCALE into italics);
    `code spans` stay as they are."""
    parts = str(text).split("`")
    for i in range(0, len(parts), 2):          # even parts are outside backticks
        # links stay as they are, in <...>: no escaping inside them, and Discord shows no preview embed
        bits = re.split(r"(https?://[^\s<>]*[^\s<>.,;:)'])", parts[i])
        for j in range(len(bits)):
            bits[j] = f"<{bits[j]}>" if j % 2 else _code_spans(bits[j])
        parts[i] = "".join(bits)
    return "`".join(parts) if len(parts) % 2 else "`".join(parts[:-1]) + "\\`" + parts[-1]


def fix_text(fix):
    """A fix that is one shell command is shown as one code span, a sentence as text."""
    if "`" not in fix and "\n" not in fix and re.search(r"[$|>&=]", fix) and not re.match(r"[A-Z][a-z]+\s", fix) and not re.search(r"\w\.\s+[A-Z]", fix):
        return f"`{fix}`"
    return md(fix)


def markdown(name, findings, ai=None):
    lead = [f for f in findings if f.rule == "sh.reinvented"]
    fs = sorted((f for f in findings if f.rule != "sh.reinvented"), key=lambda f: (ORDER[f.severity], f.file, f.line))
    out = [f"# pmcheck {__version__}: {name}", "", f"**{summary_line(findings)}**", ""]
    icon = {ERROR: "❌", WARN: "⚠️", INFO: "ℹ️"}
    for f in lead:   # the launch script as a whole comes before the single findings
        out += [f"## 📋 Before the details: the launch script ({f.severity})", "", md(f.message), ""]
        if f.snippet:
            out += ["What PortMaster already provides for each block:", "", "```", *f.snippet.splitlines(), "```", ""]
        steps = [x.strip() for x in re.split(r"\s*\d\)\s+", f.fix) if x.strip()]
        out += [f"{i}. {md(x)}" for i, x in enumerate(steps, 1)] + [""]
    for sev in (ERROR, WARN, INFO):
        group = [f for f in fs if f.severity == sev]
        if not group:
            continue
        out += [f"## {icon[sev]} {sev} ({len(group)})", ""]
        for f in group:   # one block per finding: header, explanation, fix, listing
            loc = f" · `{f.file}{':' + str(f.line) if f.line else ''}`" if f.file else ""
            out += [f"**{f.rule}**{loc}", md(f.message)]
            if f.snippet:
                out += ["```", *f.snippet.splitlines(), "```"]
            if f.fix:
                out.append(f"**Fix:** {fix_text(f.fix)}")
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
        msg = f"{f.message}" + (f" Fix: {f.fix}" if f.fix else "") + (f"\n{f.snippet}" if f.snippet else "")
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        props = [f"title=pmcheck {f.rule}"]
        if f.file:
            props.append(f"file={prefix}{f.file}")
            if f.line:
                props.append(f"line={f.line}")
        out.append(f"::{level[f.severity]} {','.join(props)}::{msg}")
    return "\n".join(out)
