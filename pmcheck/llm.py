"""Optional Gemini review of the port's text files. Advisory only; never decides pass/fail."""
import datetime
import json
import os
import re
import urllib.error
import socket
import time
import urllib.request
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-latest"
FALLBACK_MODEL = "gemini-flash-lite-latest"
MAX_CHARS = 400_000          # well inside Flash's context; keeps the free-tier token budget sane
MAX_FILE_CHARS = 60_000
TEXT_NAMES = re.compile(r"(\.sh|\.bash|\.ini|\.gptk|\.json|\.xml|\.md|\.txt|\.cfg|\.conf|\.py)$", re.I)
PROMPT_FILE = Path(__file__).resolve().parent / "prompt" / "rules.md"
REFERENCE_FILE = Path(__file__).resolve().parent / "prompt" / "reference.md"
MAX_REFERENCE_CHARS = 60_000

# Engine detection -> sections of reference.md (by heading prefix) sent as background.
# The whole reference (~325 KB) is a porting guide; only the part matching the port helps a review.
ENGINES = (
    ("GameMaker (gmloader)", lambda files, sh: any(re.match(r"gmloader", n) for n in files), ["### 1.7.8"]),
    ("Westonpack", lambda files, sh: "weston_pkg" in sh or "westonwrap" in sh, ["### 1.7.4", "### 1.7.5"]),
    ("Godot (FRT)", lambda files, sh: any(n.startswith("frt_") or n.endswith(".pck") for n in files), ["### 1.7.6"]),
    ("LÖVE", lambda files, sh: "love" in files or ".love" in sh or "love_" in sh, ["### 1.7.7"]),
    ("Pyxel", lambda files, sh: "pyxel" in sh, ["### 1.7.9"]),
    ("mkxp-z", lambda files, sh: "mkxp" in sh, ["### 1.7.10"]),
    (".NET / Mono", lambda files, sh: "dotnet" in sh or "mono" in sh, ["### 1.7.11"]),
    ("box64 / box86", lambda files, sh: "box64" in sh or "box86" in sh, ["### 1.7.14"]),
    ("Java", lambda files, sh: "javaruntime" in sh or "zulu" in sh or "JAVA_HOME" in sh, ["### 1.7.15"]),
)
ALWAYS = ["### 1.7.13"]                      # pm_message / pm_show_error
INI_SECTIONS = ["### 1.8.1"]                 # gptokeyb2 .ini


def _sections(text, prefixes):
    """Return the reference sections whose heading starts with one of prefixes, each up to the next heading of the same or higher level."""
    lines, out = text.splitlines(), []
    for pre in prefixes:
        level = pre.count("#")
        for i, l in enumerate(lines):
            if l.startswith(pre):
                j = i + 1
                in_code = False
                while j < len(lines):
                    if lines[j].startswith("```"):
                        in_code = not in_code
                    m = re.match(r"^(#+) ", lines[j])
                    if not in_code and m and len(m.group(1)) <= level:
                        break
                    j += 1
                out.append("\n".join(lines[i:j]))
                break
    return out


def engine_reference(port):
    """Background text for the detected engine(s), or '' when nothing matches or the reference is missing."""
    if not REFERENCE_FILE.exists():
        return ""
    files = {p.name.lower() for p in port.logical_files()}
    sh = "\n".join(port.read_text(s) for s in port.scripts)
    names, prefixes = [], list(ALWAYS)
    for name, detect, secs in ENGINES:
        if detect(files, sh):
            names.append(name)
            prefixes += secs
    if any(n.endswith(".ini") for n in files) and "GPTOKEYB2" in sh:
        prefixes += INI_SECTIONS
    text = "\n\n".join(_sections(REFERENCE_FILE.read_text(), prefixes))[:MAX_REFERENCE_CHARS]
    if not text:
        return ""
    head = ("## Engine reference" + (f" (detected: {', '.join(names)})" if names else "") + "\n"
            "Background on how such ports are usually built. The rules above win on any conflict. "
            "It describes one project's conventions; a third-party port may legitimately differ, so only report a difference that breaks on a device.\n\n")
    return head + text

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "kind": {"type": "STRING", "enum": ["issue", "dispute"]},
            "finding": {"type": "STRING"},
            "severity": {"type": "STRING", "enum": ["error", "warning", "note"]},
            "file": {"type": "STRING"},
            "line": {"type": "INTEGER"},
            "issue": {"type": "STRING"},
            "fix": {"type": "STRING"},
        },
        "required": ["severity", "issue"],
    },
}


def _numbered(text):
    return "\n".join(f"{i:4}| {l}" for i, l in enumerate(text.splitlines(), 1))


def build_input(port, findings):
    parts = [f"Today's date: {datetime.date.today().isoformat()}. Dates up to today are not in the future.", "## File tree"]
    files = port.logical_files()
    tree = [f"{port.rel(p)}  ({p.stat().st_size} bytes)" for p in files]
    if len(tree) > 400:
        tree = tree[:400] + [f"... {len(files) - 400} more files"]
    parts.append("\n".join(tree))
    parts.append("## Findings already reported by the rule checker (do not repeat these; dispute one by its F number if the files prove it wrong)")
    parts.append("\n".join(f"- F{i} [{f.severity}] {f.rule} {f.file}:{f.line} {f.message}" for i, f in enumerate(findings, 1)) or "(none)")
    lic_dirs = [p for p in files if re.search(r"(^|/)licen[cs]es?/", port.rel(p))]
    budget = MAX_CHARS
    priority = sorted(
        (p for p in files if TEXT_NAMES.search(p.name) and p not in lic_dirs and p.stat().st_size < 2_000_000),
        key=lambda p: (0 if p.suffix == ".sh" else 1 if p.name in ("port.json", "gameinfo.xml", "README.md") else 2, len(p.parts)),
    )
    for p in priority:
        body = port.read_text(p, MAX_FILE_CHARS * 4)[:MAX_FILE_CHARS]
        chunk = f"## File: {port.rel(p)}\n```\n{_numbered(body)}\n```"
        if len(chunk) > budget:
            break
        budget -= len(chunk)
        parts.append(chunk)
    if lic_dirs:
        parts.append("## Licence files (name + first lines)")
        for p in lic_dirs[:60]:
            head = "\n".join(port.read_text(p, 4000).splitlines()[:5])
            parts.append(f"### {port.rel(p)}\n{head}")
    return "\n\n".join(parts)


# AI findings the model keeps making although rules.md lists them as valid; dropped in code.
def _has(t, *pats):
    return all(re.search(p, t) for p in pats)


KNOWN_FALSE = (
    # harbourmaster appends .squashfs when missing (harbour.py:1172); both spellings are merged
    lambda t: "squashfs" in t and _has(t, r"extension|suffix|remove|without|must not|should not|catalog key"),
    # gptokeyb2 -x (virtual xbox360 pad, config mode off, main.c:245) and -c are both optional: any flag advice is dropped
    lambda t: "gptokeyb" in t and _has(t, r"(?<![\w-])-[xc]\b|xbox|\bini\b|config file|configuration file"),
    # gptokeyb kills with pkill (regex on the 15-char process name); a prefix of the binary matches
    lambda t: _has(t, r"gptokeyb|kill", r"device_arch|\.aarch64|arch suffix"),
)


def known_false(it):
    t = f"{it.get('issue', '')} {it.get('fix', '')}".lower()
    # an "issue" about a rule finding is a dispute in the wrong shape (and its F number was wrong when seen)
    if re.search(r"\bf\d+\b|rule checker|rule finding", t):
        return True
    return any(f(t) for f in KNOWN_FALSE)


RETRY_CODES = {429, 500, 502, 503, 504, "timeout"}
RETRY_DELAYS = (0, 5, 20)


def _call(model, body, api_key, timeout):
    """Returns (response, error text, HTTP code)."""
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), None, 200
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"][:200].rstrip(". ")
        except Exception:
            msg = ""
        hint = {429: ", rate limited", 503: ", Gemini overloaded, try again later",
                404: f", model {model!r} not found, set PMCHECK_GEMINI_MODEL"}.get(e.code, "")
        return None, f"AI review unavailable (HTTP {e.code}{hint}){': ' + msg if msg else ''}.", e.code
    except (TimeoutError, socket.timeout):
        return None, f"AI review unavailable (no answer from {model} within {timeout}s).", "timeout"
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            return None, f"AI review unavailable (no answer from {model} within {timeout}s).", "timeout"
        return None, f"AI review unavailable ({e.__class__.__name__}).", None
    except ValueError as e:
        return None, f"AI review unavailable ({e.__class__.__name__}).", None


def review(port, findings, api_key=None, model=None, timeout=150):
    """Returns a list of dicts, or a string explaining why there is no AI review."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "AI review skipped: no GEMINI_API_KEY."
    model = model or os.environ.get("PMCHECK_GEMINI_MODEL", DEFAULT_MODEL)
    system = PROMPT_FILE.read_text() if PROMPT_FILE.exists() else ""
    ref = engine_reference(port)
    if ref:
        system += "\n\n" + ref
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": build_input(port, findings)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    models = [model]
    fallback = os.environ.get("PMCHECK_GEMINI_FALLBACK", FALLBACK_MODEL)
    if fallback and fallback != model:
        models.append(fallback)
    resp = err = None
    for m in models:
        for delay in RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            resp, err, code = _call(m, body, api_key, timeout)
            if resp is not None or code not in RETRY_CODES or code == "timeout":
                break
        if resp is not None or code not in RETRY_CODES:
            break
    if resp is None:
        return err
    try:
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
        items = json.loads(text)
    except (KeyError, IndexError, ValueError):
        return "AI review returned no usable answer."
    lengths = {port.rel(p): len(port.read_text(p).splitlines()) for p in port.logical_files() if TEXT_NAMES.search(p.name)}
    out, disputes = [], []
    for it in items if isinstance(items, list) else []:
        if not (isinstance(it, dict) and isinstance(it.get("issue"), str) and it["issue"].strip()):
            continue
        if it.get("kind") == "dispute":
            m = re.fullmatch(r"F?(\d+)", str(it.get("finding", "")).strip())
            if m and 1 <= int(m.group(1)) <= len(findings):
                f = findings[int(m.group(1)) - 1]
                disputes.append({"kind": "dispute", "rule": f.rule, "file": f.file, "line": f.line,
                                 "finding": f.message[:200], "issue": str(it["issue"])[:500]})
            continue
        if known_false(it):
            continue
        it = {k: it[k] for k in ("severity", "file", "line", "issue", "fix") if k in it}
        for k in ("issue", "fix", "file"):
            if k in it:
                it[k] = str(it[k])[:500]
        # Drop line numbers that can't exist (models sometimes emit runaway digits).
        line = it.get("line")
        n = lengths.get(it.get("file", ""))
        if not isinstance(line, int) or line < 1 or (n is not None and line > n) or line > 100000:
            it.pop("line", None)
        out.append(it)
    return out[:10] + disputes[:10]
