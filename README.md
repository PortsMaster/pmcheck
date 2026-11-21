# pmcheck

A static packaging checker for PortMaster ports. It only parses files and runs `readelf`/`objdump`/`shellcheck`, and never executes port code.

- **Library + CLI**: `pmcheck <zip|folder|PR link> [--pr] [--format md|json|github] [--ai] [--warn-only]`. Testing zips accept either layout; `--pr` enforces the PortMaster-New layout. A `https://github.com/PortsMaster/PortMaster-New/pull/<n>` link downloads and checks the ports that PR touches.
- **Discord bot**: `/checkport <url or PR link>`, admin roles only (rules + Gemini advisory review). Setup: `docs/bot-setup.md`.
- **PR check**: `workflows/port_check.yaml` → copy it to `PortMaster-New/.github/workflows/`. Rules only.

## Run
```bash
pip install .            # Pillow; binutils + shellcheck from the OS
pmcheck port.zip
pmcheck --sweep PortMaster-New/ports      # rule hit counts across all ports
GEMINI_API_KEY=... pmcheck port.zip --ai  # adds the AI review section
python3 -m unittest discover -s tests -t .
```

Exit codes: 0 ok, 1 errors found (0 with `--warn-only`), 2 could not load.

## Tests
- `tests/test_mutations.py`: about 100 planted errors, each injected into a clean port, must be caught at the right severity; about 50 valid variants (template lines, quoted paths, wrapper scripts, shim builds ...) must add no ERROR or WARN. Every false positive found in a real port gets a valid variant here.
- `tests/test_rules.py`: rule details, layouts, zip safety.
- Real-port corpus (local, not in this repo): `/root/compile/pmcheck-corpus/run.py` checks about 120 ports (testing-thread zips, PRs, a PortMaster-New sample, Cebion's ports) against a reviewed baseline and prints every new or vanished finding.

## Rules
`pmcheck/rules.py` (one `@check` function per area), `pmcheck/ini.py` (gptokeyb2), lists in `pmcheck/data.py`.
The AI prompt is `pmcheck/prompt/rules.md`, so admins can edit it without touching code.
gptokeyb2 key names: `pmcheck/g2keys.json`, generated from `gptokeyb2/src/keys.c`.
Standard launch-script lines (`sh.nonstandard`): `pmcheck/script_lines.json`, normalized lines found in at least 10 merged PortMaster-New scripts plus the percentiles of non-standard lines per merged port. Refresh it with `tools/build_script_lines.py` (instructions at the top of the file) when the template changes.
Templates and peers (`sh.template-diff`, `sh.length`, the AI review's comparison): `pmcheck/templates/site/` (the website's script templates, refresh with `tools/build_site_templates.py <script-templates.md>`), `pmcheck/templates/new/` (templates for engines the site doesn't have yet, plus `_patterns.sh` with documented building blocks), and `pmcheck/script_peers.json` (every merged script with kind tags and hashed lines, refresh with `tools/build_peers.py <PortMaster-New checkout>`).
Scripts that redo PortMaster's own work (`sh.reinvented`, shown first in the report): a score from script length, shell functions, a generator banner, the blocks in `data.REINVENT_SIGNALS` (each with what PortMaster provides instead) and the related findings in `data.REINVENT_RULES`. WARN at `REINVENT_WARN`, ERROR at `REINVENT_ERROR`, calibrated so no merged port reaches ERROR. The text is read by the porter: it describes the script, never the person.

## Bot deployment (build server)
```bash
podman build -t pmcheck-bot -f bot/Containerfile .
cp bot/config.example.env ~/.config/pmcheck-bot.env   # fill in token, guild, admin role IDs, Gemini key
cp bot/pmcheck-bot.service ~/.config/systemd/user/ && systemctl --user enable --now pmcheck-bot
```
Discord app: bot scope + `applications.commands`, no privileged intents. The bot refuses to start without `ADMIN_ROLE_IDS`.
