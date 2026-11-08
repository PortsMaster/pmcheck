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

## Rules
`pmcheck/rules.py` (one `@check` function per area), `pmcheck/ini.py` (gptokeyb2), lists in `pmcheck/data.py`.
The AI prompt is `pmcheck/prompt/rules.md`, so admins can edit it without touching code.
gptokeyb2 key names: `pmcheck/g2keys.json`, generated from `gptokeyb2/src/keys.c`.

## Bot deployment (build server)
```bash
podman build -t pmcheck-bot -f bot/Containerfile .
cp bot/config.example.env ~/.config/pmcheck-bot.env   # fill in token, guild, admin role IDs, Gemini key
cp bot/pmcheck-bot.service ~/.config/systemd/user/ && systemctl --user enable --now pmcheck-bot
```
Discord app: bot scope + `applications.commands`, no privileged intents. The bot refuses to start without `ADMIN_ROLE_IDS`.
