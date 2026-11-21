#!/usr/bin/env python3
"""Copy the launch-script templates from the PortMaster website (docs/contribute/porting/script-templates.md in
PortsMaster/PortMaster-Wiki-New) into pmcheck/templates/site/, one file per tab, plus index.json.

  python3 tools/build_site_templates.py <path to script-templates.md>
"""
import json
import re
import sys
from pathlib import Path


def main(md):
    text = Path(md).read_text().replace("\r\n", "\n")
    out = Path(__file__).resolve().parent.parent / "pmcheck" / "templates" / "site"
    out.mkdir(parents=True, exist_ok=True)
    index, group = {}, ""
    for block in re.split(r"^(?=# |=== )", text, flags=re.M):
        if block.startswith("# "):
            group = block.splitlines()[0][2:].replace("Portscript Templates", "").strip()
            continue
        m = re.match(r'=== "(.+?)"\n(.*)', block, re.S)
        if not m:
            continue
        name = m.group(1).rstrip(")") if m.group(1).count(")") > m.group(1).count("(") else m.group(1)
        # a tab can hold variants: "**OpenGL 2:**" then a code block, "**OpenGL ES:**" then another
        for i, code in enumerate(re.finditer(r"(?:\*\*([^*\n]+?):?\*\*\s*\n)?\s*```[ \t]*(?:bash|sh)?[ \t]*\n(.*?)```", m.group(2), re.S)):
            variant = (code.group(1) or "").strip(": ")
            body = "\n".join(l[4:] if l.startswith("    ") else l for l in code.group(2).splitlines()) + "\n"
            label = f"{name} ({variant})" if variant else name
            slug = re.sub(r"[^a-z0-9]+", "-", f"{group} {label}".lower()).strip("-")
            (out / f"{slug}.sh").write_text(body)
            index[slug] = {"name": label, "group": group, "tab": name}
    (out / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(f"{len(index)} templates -> {out}: {', '.join(index)}")


if __name__ == "__main__":
    main(sys.argv[1])
