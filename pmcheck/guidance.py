"""A short plain-language note above the findings: where a porter should read first.

A list of findings does not say where it comes from. Two patterns have a common cause the porter can fix at the root:
the package or script does not follow the port layout, or the script carries blocks of the kind an AI assistant adds
(checks, logging and fallbacks the platform already provides). The note points to the documentation for each.
"""
from . import data

# the package or the launch script departs from the standard layout
STRUCTURE = {"structure.no-script", "structure.no-gamedir", "structure.wrapper", "structure.top-level", "structure.gamedir-name", "files.missing",
             "port.json.items", "sh.shebang", "sh.boilerplate", "sh.controlfolder", "sh.header-modified", "sh.control", "sh.mod", "sh.get_controls"}
# script logic of the kind merged ports do not have: wrappers, own plumbing, features the platform or the game already covers
AI_SHAPED = {"sh.reinvented", "sh.launch-indirection", "files.extra-code", "sh.env-knobs", "sh.long-function", "sh.length", "sh.comments", "sh.log-per-launch",
             "sh.log-pipeline", "sh.controls-status", "sh.gamedir-search", "sh.pm-guard", "sh.signal-handling", "sh.umask", "sh.sysfs-write", "sh.self-update",
             "sh.system-python", "sh.hotkey-override", "files.placeholder", "sh.header-modified"}


def _ids(findings, group):
    return sorted({f.rule for f in findings if f.rule in group})


def guidance(findings, links=True):
    """Markdown paragraphs, or "" when neither pattern is present. links=False wraps URLs in <> for Discord (no embeds)."""
    u = (lambda x: x) if links else (lambda x: f"<{x}>")
    structure = _ids(findings, STRUCTURE)
    shaped = _ids(findings, AI_SHAPED)
    out = []
    if len(structure) >= 2 or any(r.startswith("structure.no-") for r in structure):
        out.append("**The package or the launch script does not follow the PortMaster layout.** Most of the list below comes from that, so fixing the layout first "
                   "clears much of it. How a port is put together: the packaging guide "
                   f"{u(data.PACKAGING_GUIDE)}, the script templates {u(data.SCRIPT_TEMPLATES)}, and the #your-first-port channel on Discord {u(data.DISCORD_FIRST_PORT)}.")
    if len(shaped) >= 3:
        out.append("**Several findings are typical of a script written with an AI assistant:** blocks that add checks, logging, fallbacks or helper programs that PortMaster "
                   "and the template already provide. Using an AI is fine, and it helps to say so in the PR. Please read every line, delete what you cannot explain, "
                   "and build the script from a merged port that is close to yours instead of from a generic template. The AI porting reference is pinned in the "
                   f"#your-first-port channel {u(data.DISCORD_FIRST_PORT)}; the short version is on {u(data.FIRST_PORT_GUIDE)}.")
    return "\n\n".join(out)
