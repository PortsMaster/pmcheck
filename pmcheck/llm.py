"""Optional Gemini review of the port's text files. Advisory only; never decides pass/fail."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_CHARS = 400_000          # well inside Flash's context; keeps the free-tier token budget sane
MAX_FILE_CHARS = 60_000
TEXT_NAMES = re.compile(r"(\.sh|\.bash|\.ini|\.gptk|\.json|\.xml|\.md|\.txt|\.cfg|\.conf|\.py)$", re.I)
PROMPT_FILE = Path(__file__).resolve().parent / "prompt" / "rules.md"

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
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
    parts = ["## File tree"]
    files = port.logical_files()
    tree = [f"{port.rel(p)}  ({p.stat().st_size} bytes)" for p in files]
    if len(tree) > 400:
        tree = tree[:400] + [f"... {len(files) - 400} more files"]
    parts.append("\n".join(tree))
    parts.append("## Findings already reported by the rule checker (do not repeat these)")
    parts.append("\n".join(f"- [{f.severity}] {f.rule} {f.file}:{f.line} {f.message}" for f in findings) or "(none)")
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


def review(port, findings, api_key=None, model=None, timeout=180):
    """Returns a list of dicts, or a string explaining why there is no AI review."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "AI review skipped: no GEMINI_API_KEY."
    model = model or os.environ.get("PMCHECK_GEMINI_MODEL", DEFAULT_MODEL)
    system = PROMPT_FILE.read_text() if PROMPT_FILE.exists() else ""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": build_input(port, findings)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    req = urllib.request.Request(
        API.format(model=model), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        return f"AI review unavailable (HTTP {e.code}{', rate limited' if e.code == 429 else ''})."
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return f"AI review unavailable ({e.__class__.__name__})."
    try:
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
        items = json.loads(text)
    except (KeyError, IndexError, ValueError):
        return "AI review returned no usable answer."
    out = []
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict) and it.get("issue"):
            out.append({k: it[k] for k in ("severity", "file", "line", "issue", "fix") if k in it})
    return out[:40]
