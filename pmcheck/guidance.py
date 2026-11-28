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
    """Markdown paragraphs, or "" when neither pattern is present. links=False wraps URLs in <> for Discord (no embeds).
    The counts change with every re-run, so a porter fixing things sees the note shrink and then go."""
    u = (lambda x: x) if links else (lambda x: f"<{x}>")
    structure = _ids(findings, STRUCTURE)
    shaped = _ids(findings, AI_SHAPED)
    total = len(findings)
    n_structure = sum(1 for f in findings if f.rule in STRUCTURE)
    n_shaped = sum(1 for f in findings if f.rule in AI_SHAPED)
    out = []
    if len(structure) >= 2 or any(r.startswith("structure.no-") for r in structure):
        out.append("**As it is, this port does not meet the PortMaster standard yet and cannot be accepted into PortMaster.** "
                   f"{n_structure} of the {total} findings below are about how the package and the launch script are laid out. Fixing those first usually clears more of the list. "
                   "To learn how a port is put together and how the launch scripts need to look here:\n"
                   f"- Packaging guide: {u(data.PACKAGING_GUIDE)}\n"
                   f"- Script templates: {u(data.SCRIPT_TEMPLATES)}\n"
                   f"- The #your-first-port channel on Discord: {u(data.DISCORD_FIRST_PORT)}")
    if len(shaped) >= 3:
        out.append(f"**{n_shaped} findings are typical of a script written or extended with an AI assistant:** blocks that add checks, logging or fallbacks "
                   "that PortMaster and the template already provide. AI tools are welcome here, and saying so in the PR helps the reviewers. Before you submit:\n"
                   "- Read every line, and take out what you cannot explain. Most merged ports are short.\n"
                   "- Base the script on a merged port that is close to yours, not on a generic template.\n\n"
                   f"The #your-first-port channel has a complete porting reference written for AI-assisted porting, kept up to date there: {u(data.DISCORD_FIRST_PORT)}. "
                   f"The short version is on {u(data.FIRST_PORT_GUIDE)}.")
    return "\n\n".join(out)
