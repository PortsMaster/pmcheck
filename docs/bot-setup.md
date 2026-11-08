# /checkport bot: setup guide

These steps deploy the admin-only Discord port checker on the build server: rules plus the Gemini advisory review.
Plan for about 30 minutes. Everything used is free.

## 0. What you need
- Admin rights on the PortMaster Discord server.
- A Google account, for the Gemini key.
- The build server (`pmuser`) with `sudo` once, to install podman.
- The `pmcheck` code in a **public** GitHub repo, `PortsMaster/pmcheck`. The PR check installs it on fork PRs, which get no secrets, so a private repo won't work. The repo holds no secrets: the token and the Gemini key stay in the server's env file.

## 1. Put the code on GitHub
Create `PortsMaster/pmcheck` as a **public** repo with no README, licence or .gitignore (the code brings its own). Then, on the machine that has `/root/compile/pmcheck`:
```bash
cd /root/compile/pmcheck
git init && git add . && git commit -m "pmcheck 0.1.0"
git remote add origin git@github.com:PortsMaster/pmcheck.git
git push -u origin main
git tag v0.1.0 && git push --tags
```
The tag is also what the PR workflow pins later.

## 2. Create the Discord application
1. Open https://discord.com/developers/applications and choose **New Application**. Name it `PortMaster Checker`.
2. **Bot** tab:
   - Choose **Reset Token**, then copy the token. Discord shows it once; it becomes `DISCORD_TOKEN`.
   - Turn **Public Bot** off, so only you can invite it.
   - Leave all three **Privileged Gateway Intents** off. The bot doesn't need them.
3. **Installation** tab: set **Install Link** to *None*.
4. **OAuth2 → URL Generator**:
   - Scopes: `bot` and `applications.commands`.
   - Bot permissions: `View Channels`, `Send Messages`, `Attach Files`.
   - Open the generated URL, pick the PortMaster server, and choose **Authorize**.

## 3. Collect the server and role IDs
1. In Discord, go to **User Settings → Advanced** and turn on **Developer Mode**.
2. Right-click the server icon → **Copy Server ID**. This is `GUILD_ID`.
3. Go to **Server Settings → Roles**, right-click each role allowed to use the command (admins, reviewers) → **Copy Role ID**. Comma-separated, these become `ADMIN_ROLE_IDS`.

## 4. Create the Gemini API key
1. Open https://aistudio.google.com/apikey.
2. Choose **Create API key**, in a new project. Don't enable billing: the free tier needs none.
3. Copy the key. This is `GEMINI_API_KEY`.

On the free tier, Google may use the prompts to improve its models. That's fine here because port files are public anyway. You can check the free rate limits in AI Studio under the key's project. One `/checkport` is one request.

## 5. Install podman on the build server
```bash
sudo apt update && sudo apt install -y podman git
sudo loginctl enable-linger pmuser     # lets pmuser's services run without a login session
```
Everything after this runs as `pmuser`, with no sudo.

## 6. Get the code and build the image
```bash
cd ~/git-scripts
git clone https://github.com/PortsMaster/pmcheck.git
cd pmcheck
podman build -t pmcheck-bot -f bot/Containerfile .
```
The image is `python:3.12-slim` plus `binutils` and `shellcheck`, with pmcheck and discord.py installed. It runs as an unprivileged user.

## 7. Configure
```bash
mkdir -p ~/.config/systemd/user
cp bot/config.example.env ~/.config/pmcheck-bot.env
chmod 600 ~/.config/pmcheck-bot.env
nano ~/.config/pmcheck-bot.env
```
Fill in:
```
DISCORD_TOKEN=<token from step 2>
GUILD_ID=<server ID from step 3>
ADMIN_ROLE_IDS=<role ID>,<role ID>
GEMINI_API_KEY=<key from step 4>
PMCHECK_GEMINI_MODEL=gemini-2.5-flash
MAX_DOWNLOAD_MB=1024
CHECK_TIMEOUT=900
```
- If Google renames or retires the free model, change only `PMCHECK_GEMINI_MODEL`.
- The bot refuses to start when `ADMIN_ROLE_IDS` is empty.

## 8. First run in the foreground
```bash
podman run --rm --env-file ~/.config/pmcheck-bot.env \
  --read-only --tmpfs /tmp:rw,size=8g,mode=1777 \
  --cap-drop=ALL --security-opt no-new-privileges \
  localhost/pmcheck-bot:latest
```
Wait for `pmcheck bot ready as PortMaster Checker#1234`, then go to step 10 to test it. Stop it with Ctrl+C.

## 9. Run it as a service
```bash
cp bot/pmcheck-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now pmcheck-bot
systemctl --user status pmcheck-bot
journalctl --user -u pmcheck-bot -f      # live log
```
The service restarts on failure and starts again on reboot, because of the linger from step 5.

## 10. Test in Discord
1. **Admin:** run `/checkport url:<link to a port zip>`.
   - To get a link, right-click a zip attachment in Discord and choose **Copy Link**. A GitHub release asset link also works.
   - After 10 to 60 seconds you should see a summary, an `AI notes` part, and an attached `pmcheck-<port>.md`.
2. **Non-admin account:** the command is hidden, or answers *"This command is for PortMaster admins."*
3. **A link from another site:** the bot answers *"Only https links from Discord or GitHub are accepted."*
4. **mcrust as a check:** expect 2 errors (`arch`, `min_glibc`) plus the warnings from the manual review.

If the summary shows `AI review unavailable (HTTP 429, rate limited)`, the free-tier limit was hit. The rules report is still complete.

## 11. Optional: lock the command down further in Discord
Go to **Server Settings → Integrations → PortMaster Checker → /checkport**. There you can limit the command to the admin roles and to a single channel such as `#port-check`. This works on top of the role check in the bot's code.

## 12. Updating
**Rules, prompt or bot code:**
```bash
cd ~/git-scripts/pmcheck && git pull
podman build -t pmcheck-bot -f bot/Containerfile .
systemctl --user restart pmcheck-bot
```
- The AI rules live in `pmcheck/prompt/rules.md`; editing it needs the same rebuild.
- Before changing rules, test locally: `pip install . && pmcheck some-port.zip` (add `--ai` with `GEMINI_API_KEY` set).

## Troubleshooting
| Symptom | Cause / fix |
|--|--|
| `/checkport` not in the command list | The commands sync to the guild at startup. Check `GUILD_ID`, restart, then reload Discord with Ctrl+R. |
| `KeyError: 'DISCORD_TOKEN'` | The env file wasn't passed; check the path in the service file. |
| `Improper token has been passed` | The token was reset or mistyped; reset it again in step 2. |
| `download failed: HTTP 404/403` | The Discord attachment link expired (they're signed for about 24 h); copy a fresh link. |
| `check timed out` | The port is very large or the server is busy; raise `CHECK_TIMEOUT`. |
| `AI review skipped: no GEMINI_API_KEY` | The key is missing from the env file. |

## Security summary
- Port code is never executed: zips are only parsed, plus `readelf`/`objdump`/`shellcheck`.
- Zips that contain `..` paths, absolute paths or symlinks, or that expand into a zip bomb, are rejected.
- Only Discord and GitHub https links are accepted, with a size cap and one check at a time.
- The container runs read-only and unprivileged, with no capabilities, and with memory, CPU and process limits.
- The Gemini review only sees text files and can't act. Its output is advisory.
