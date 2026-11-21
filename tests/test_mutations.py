"""Planted errors and valid variants on a known-clean port.

Every MUTATION plants one mistake into the clean test port and must produce its rule at its severity.
Every VALID variant is a legitimate way of writing a port that has been flagged by mistake before
(or easily could be); it must not add any ERROR or WARN to the clean port.

python3 -m unittest discover -s tests -t .
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from pmcheck.model import load
from pmcheck.rules import run_all

from tests.test_rules import FIX, GAMEINFO, GOOD_SH, README, make_port, png

HOOK = 'cd "$GAMEDIR"\n'          # insertion point in GOOD_SH, right after cd
LAUNCH = '$GPTOKEYB2 "testgame.aarch64" &\n'


def gd(root):
    return Path(root) / "testgame"


def sh(root, edit):
    p = Path(root) / "Test Game.sh"
    p.write_text(edit(p.read_text()))


def insert(text):
    return lambda root: sh(root, lambda s: s.replace(HOOK, HOOK + text, 1))


def pj(root, **attr):
    p = gd(root) / "port.json"
    d = json.loads(p.read_text())
    for k, v in attr.items():
        if k.startswith("_"):
            d[k[1:]] = v
        else:
            d["attr"][k] = v
    p.write_text(json.dumps(d))


def gameinfo(root, old, new):
    p = gd(root) / "gameinfo.xml"
    p.write_text(p.read_text().replace(old, new))


def lib(root, name, folder="libs.aarch64", fixture=None, licence=True):
    d = gd(root) / folder
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / (fixture or name), d / name)
    if licence:
        stem = name.split(".so")[0].replace("lib", "", 1)
        (gd(root) / "licenses" / f"LICENSE.{stem}").write_text("MIT")


def ini(root, text, name="testgame.ini", pass_c=True):
    (gd(root) / name).write_text(text)
    if pass_c:
        sh(root, lambda s: s.replace(LAUNCH, f'$GPTOKEYB2 "testgame.aarch64" -c "./{name}" &\n'))


def gptk(root, text):
    (gd(root) / "testgame.gptk").write_text(text)
    sh(root, lambda s: s.replace(LAUNCH, '$GPTOKEYB "testgame.aarch64" -c "./testgame.gptk" &\n'))


def write(rel, data):
    def f(root):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data)
    return f


def remove(rel):
    return lambda root: (Path(root) / rel).unlink()


def both(*fns):
    def f(root):
        for fn in fns:
            fn(root)
    return f


# (name, mutate, rule, severity)
MUTATIONS = [
    # launch script
    ("crlf", lambda r: sh(r, lambda s: s.replace("\n", "\r\n")), "sh.crlf", "ERROR"),
    ("no shebang", lambda r: sh(r, lambda s: s.replace("#!/bin/bash\n", "", 1)), "sh.shebang", "ERROR"),
    ("code above header", lambda r: sh(r, lambda s: s.replace("#!/bin/bash\n", "#!/bin/bash\nexport FOO=1\n", 1)), "sh.boilerplate", "ERROR"),
    ("comment above header", lambda r: sh(r, lambda s: s.replace("#!/bin/bash\n", "#!/bin/bash\n# my port\n", 1)), "sh.boilerplate", "WARN"),
    ("no control.txt", lambda r: sh(r, lambda s: s.replace("source $controlfolder/control.txt\n", "")), "sh.control", "WARN"),
    ("no mod_ file", lambda r: sh(r, lambda s: s.replace('[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"\n', "")), "sh.mod", "WARN"),
    ("no get_controls", lambda r: sh(r, lambda s: s.replace("get_controls\n", "")), "sh.get_controls", "WARN"),
    ("no pm_finish", lambda r: sh(r, lambda s: s.replace("pm_finish\n", "")), "sh.pm_finish", "WARN"),
    ("SDL_VIDEODRIVER", insert("export SDL_VIDEODRIVER=kmsdrm\n"), "sh.sdl-driver", "ERROR"),
    ("SDL_AUDIODRIVER", insert("export SDL_AUDIODRIVER=alsa\n"), "sh.sdl-driver", "ERROR"),
    ("SDL driver default", insert("export SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-alsa}\n"), "sh.sdl-driver", "WARN"),
    ("export LD_PRELOAD", insert('export LD_PRELOAD="$GAMEDIR/libhook.so"\n'), "sh.ld_preload", "ERROR"),
    ("bare libgl_default", insert('source "${controlfolder}/libgl_default.txt"\n'), "sh.libgl", "ERROR"),
    ("tar -xzf", insert('tar -xzf "$GAMEDIR/data.tar.gz"\n'), "sh.tar-z", "ERROR"),
    ("export HOME", insert('export HOME="$GAMEDIR/conf"\n'), "sh.home", "ERROR"),
    ("XDG_CONFIG_HOME", insert('export XDG_CONFIG_HOME="$GAMEDIR/conf"\n'), "sh.home", "ERROR"),
    ("bind source not created", insert('bind_directories ~/.other "$GAMEDIR/conf/other"\n'), "sh.bind-source", "WARN"),
    ("bind_files source not touched", insert('bind_files ~/.otherrc "$GAMEDIR/conf/.otherrc"\n'), "sh.bind-source", "WARN"),
    ("pm_message options first", insert('pm_message --title "Hi" "Hello"\n'), "sh.pm_message-order", "ERROR"),
    ("portmsg direct", insert('./portmsg.${DEVICE_ARCH} "Hello"\n'), "sh.portmsg", "ERROR"),
    ("plain sudo", insert("sudo chmod 666 /dev/uinput\n"), "sh.sudo", "WARN"),
    ("no gptokeyb", lambda r: sh(r, lambda s: s.replace(LAUNCH, "")), "sh.no-gptokeyb", "ERROR"),
    ("-c file missing", lambda r: sh(r, lambda s: s.replace(LAUNCH, '$GPTOKEYB2 "testgame.aarch64" -c "./nothere.ini" &\n')), "sh.gptk-missing", "ERROR"),
    ("-c $GAMEDIR file missing", lambda r: sh(r, lambda s: s.replace(LAUNCH, '$GPTOKEYB2 "testgame.aarch64" -c "$GAMEDIR/nothere.ini" &\n')), "sh.gptk-missing", "ERROR"),
    ("old log line", insert('exec > "$GAMEDIR/log.txt" 2>&1\n'), "sh.log-old", "WARN"),
    ("kill gptokeyb after patcher", insert('source "$controlfolder/utils/patcher.txt"\n$ESUDO kill -9 $(pidof gptokeyb)\n'), "sh.kill-gptokeyb", "WARN"),
    ("echo before exit", insert('if [ ! -f data.pak ]; then\n  echo "data.pak missing"\n  exit 1\nfi\n'), "sh.echo-message", "WARN"),
    ("tty message", insert('if [ ! -f data.pak ]; then\n  echo "data.pak missing" > /dev/tty0\n  exit 1\nfi\n'), "sh.tty-message", "WARN"),
    ("paste pipe", insert("ls | paste\n"), "sh.paste", "WARN"),
    ("comment block", insert("# one\n# two\n# three\n"), "sh.comments", "INFO"),
    ("shell syntax error", insert("if [ -f x ]; then\n  echo hi\n"), "sh.shellcheck" if shutil.which("shellcheck") else "sh.syntax", "ERROR"),
    ("tar without no-same-owner", insert('gunzip -c data.tar.gz | tar -xf -\n'), "sh.tar-owner", "WARN"),
    ("device_info sourced", lambda r: sh(r, lambda s: s.replace("source $controlfolder/control.txt\n", "source $controlfolder/control.txt\nsource $controlfolder/device_info.txt\n")), "sh.device-info", "WARN"),
    ("chmod uinput", insert("$ESUDO chmod 666 /dev/uinput\n"), "sh.uinput", "WARN"),
    ("no GAMEDIR", lambda r: sh(r, lambda s: s.replace("GAMEDIR=/$directory/ports/testgame\n", "DIR=/$directory/ports/testgame\n").replace('cd "$GAMEDIR"\n', 'cd "$DIR"\n')), "sh.gamedir", "WARN"),
    ("no pm_platform_helper", lambda r: sh(r, lambda s: s.replace('pm_platform_helper "$GAMEDIR/testgame.aarch64"\n', "")), "sh.platform-helper", "WARN"),
    ("tee log to other path", insert('LOG_FILE="$GAMEDIR/log.txt"\nexec > >(tee "$LOG_FILE") 2>&1\n'), "sh.log-old", "WARN"),
    ("classic gptokeyb, blank .gptk", lambda r: gptk(r, "a =\nb =\n"), "sh.gptokeyb-classic", "WARN"),
    ("classic gptokeyb, empty .gptk", lambda r: gptk(r, ""), "sh.gptokeyb-classic", "WARN"),
    ("oga_events restart", insert("$ESUDO systemctl restart oga_events &\n"), "sh.old-cleanup", "WARN"),
    ("old cleanup tail", lambda r: sh(r, lambda s: s.replace("pm_finish\n", 'unset SDL_GAMECONTROLLERCONFIG\nprintf "\\033c" > /dev/tty0\n')), "sh.old-cleanup", "WARN"),
    ("unset at the end with pm_finish", lambda r: sh(r, lambda s: s.replace("pm_finish\n", "unset SDL_GAMECONTROLLERCONFIG\npm_finish\n")), "sh.old-cleanup", "WARN"),
    # port.json
    ("port.json broken", write("testgame/port.json", "{ not json"), "port.json.parse", "ERROR"),
    ("port.json name", lambda r: pj(r, _name="other.zip"), "port.json.name", "WARN"),
    ("port.json items", lambda r: pj(r, _items=["Other.sh", "testgame"]), "port.json.items", "ERROR"),
    ("porter with comma", lambda r: pj(r, porter=["Alice, Bob"]), "port.json.porter", "WARN"),
    ("title empty", lambda r: pj(r, title=""), "port.json.title", "ERROR"),
    ("min_glibc empty", lambda r: pj(r, min_glibc=""), "port.json.min_glibc", "ERROR"),
    ("arch empty", lambda r: pj(r, arch=[]), "port.json.arch", "ERROR"),
    ("arch invalid", lambda r: pj(r, arch=["arm64"]), "port.json.arch", "ERROR"),
    ("runtime label", lambda r: pj(r, runtime=["Westonpack 0.2"]), "port.json.runtime", "ERROR"),
    ("runtime arch suffix", lambda r: pj(r, runtime=["weston_pkg_0.2.aarch64"]), "port.json.runtime", "ERROR"),
    ("runtime arch file name", lambda r: pj(r, runtime=["weston_pkg_0.2.x86_64.squashfs"]), "port.json.runtime", "ERROR"),
    ("runtime not in catalog", lambda r: pj(r, runtime=["dotnet-9.0.22.aarch64.squashfs"]), "port.json.runtime", "ERROR"),
    ("unknown attr", lambda r: pj(r, colour="red"), "port.json.unknown-attr", "WARN"),
    ("bad genre", lambda r: pj(r, genres=["Puzzle Platformer"]), "port.json.genres", "ERROR"),
    ("store as strings", lambda r: pj(r, store=["https://example.com"]), "port.json.store", "ERROR"),
    ("rtr without game licence", lambda r: (gd(r) / "licenses" / "LICENSE.testgame").rename(gd(r) / "licenses" / "LICENSE.zlib"), "licenses.game", "ERROR"),
    # gameinfo.xml
    ("gameinfo broken", write("testgame/gameinfo.xml", "<gameList><game>"), "gameinfo.parse", "ERROR"),
    ("gameinfo path", lambda r: gameinfo(r, "./Test Game.sh", "./Other.sh"), "gameinfo.path", "ERROR"),
    ("gameinfo image wrong file", lambda r: gameinfo(r, "./testgame/screenshot.png", "./testgame/shot.png"), "gameinfo.image", "ERROR"),
    ("gameinfo image wrong case", lambda r: gameinfo(r, "./testgame/screenshot.png", "./TestGame/screenshot.png"), "gameinfo.image", "ERROR"),
    ("README names a missing patch", write("testgame/README.md", README + "\nApply `game-fixes.patch` first.\n"), "readme.missing-file", "WARN"),
    ("rtr with paid game", lambda r: pj(r, rtr=True, availability="paid"), "port.json.rtr", "ERROR"),
    ("log from a test run", write("testgame/log.txt", "game started\n"), "structure.leftover", "WARN"),
    ("saves in conf", lambda r: [write(f"testgame/conf/save{i}.dat", "x")(r) for i in range(6)], "structure.leftover", "WARN"),
    ("gameinfo image no folder", lambda r: gameinfo(r, "./testgame/screenshot.png", "./screenshot.png"), "gameinfo.image", "ERROR"),
    ("gameinfo releasedate", lambda r: gameinfo(r, "20260101T000000", "2026-01-01"), "gameinfo.releasedate", "WARN"),
    ("gameinfo no developer", lambda r: gameinfo(r, "<developer>Someone</developer>", ""), "gameinfo.field", "WARN"),
    ("gameinfo extra tag", lambda r: gameinfo(r, "<genre>", "<players>2</players><genre>"), "gameinfo.tag", "WARN"),
    # files and images
    ("no README", remove("testgame/README.md"), "files.missing", "ERROR"),
    ("no port.json", remove("testgame/port.json"), "files.missing", "ERROR"),
    ("no gameinfo", remove("testgame/gameinfo.xml"), "files.missing", "ERROR"),
    ("no screenshot", remove("testgame/screenshot.png"), "files.missing", "WARN"),
    ("screenshot size", write("testgame/screenshot.png", png(800, 600)), "images.screenshot-size", "ERROR"),
    ("screenshot too big", write("testgame/screenshot.png", png(640, 480)[:-12] + os.urandom(150_000) + png(640, 480)[-12:]), "images.size", "WARN"),
    ("cover in wrong place", write("testgame/data/cover.png", png(64, 64)), "files.cover-location", "WARN"),
    ("README without a thank-you", write("testgame/README.md", README.replace("## Notes\n\nThanks.", "## About\n\nA game.")), "readme.thanks", "WARN"),
    ("README no Controls", write("testgame/README.md", README.replace("## Controls", "## Keys")), "readme.section", "WARN"),
    ("README no Compile", write("testgame/README.md", README.split("## Compile")[0]), "readme.section", "INFO"),
    # licences
    ("no licenses folder", lambda r: shutil.rmtree(gd(r) / "licenses"), "licenses.missing", "ERROR"),
    ("empty licenses folder", lambda r: (gd(r) / "licenses" / "LICENSE.testgame").unlink(), "licenses.empty", "ERROR"),
    ("lib without licence", lambda r: lib(r, "libfoo.so.1", licence=False), "licenses.component", "WARN"),
    ("loose licence files", both(lambda r: shutil.rmtree(gd(r) / "licenses"), write("testgame/LICENSE.txt", "MIT")), "licenses.folder", "WARN"),
    # libraries
    ("bundled SDL2", lambda r: lib(r, "libSDL2-2.0.so.0"), "libs.banned", "ERROR"),
    ("libGL outside gl4es", lambda r: lib(r, "libGL.so.1"), "libs.banned", "ERROR"),
    ("near-universal lib", lambda r: lib(r, "libpng16.so.16"), "libs.common", "WARN"),
    ("named not after SONAME", lambda r: lib(r, "libfoo.so", fixture="libfoo.so.1"), "libs.soname", "WARN"),
    ("duplicate of SONAME", both(lambda r: lib(r, "libfoo.so.1"), lambda r: lib(r, "libfoo.so", fixture="libfoo.so.1")), "libs.duplicate", "WARN"),
    ("upstream SDL3", lambda r: lib(r, "libSDL3.so.0"), "libs.sdl3", "ERROR"),
    ("X11 without Westonpack", lambda r: lib(r, "libX11.so.6"), "libs.x11", "WARN"),
    # control files
    ("ini bad key", lambda r: ini(r, "[controls]\na = return\n"), "ini.key", "ERROR"),
    ("ini duplicate", lambda r: ini(r, "[controls]\na = space\na = enter\n"), "ini.duplicate", "WARN"),
    ("ini bad button", lambda r: ini(r, "[controls]\nsellect = esc\n"), "ini.button", "WARN"),
    ("gl driver export unguarded", insert('if [ -f "$controlfolder/libgl_${CFW_NAME}.txt" ]; then\n  source "$controlfolder/libgl_${CFW_NAME}.txt"\nelse\n  source "$controlfolder/libgl_default.txt"\nfi\nexport SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1"\n'), "sh.gl-driver", "WARN"),
    ("mouse ini without hi-res bump", lambda r: ini(r, "[config]\nmouse_delay = 16\ndeadzone_mode = scaled_radial\ndeadzone_scale = 6\ndeadzone_x = 2000\ndeadzone_y = 2000\n[controls]\nleft_analog = mouse_movement\n"), "ini.mouse-hires", "INFO"),
    ("ini stick without deadzone", lambda r: ini(r, "[controls]\nleft_analog_up = up\n"), "ini.deadzone", "INFO"),
    ("ini not passed", lambda r: ini(r, "[controls]\na = space\n", pass_c=False), "ini.unused", "WARN"),
    ("note names a missing doc", write("testgame/data/PUT_FILES_HERE.txt", "See ../testgame.md for installation.\n"), "files.missing-doc", "WARN"),
    ("patcher questions change the UI", both(write("testgame/setup/questions.lua", "local questions = {\n  { id = \"Q\", question = \"Pick one\", options = { { \"a\", \"A\" } } },\n}\nlocal ok, t = pcall(require, \"talkies\")\nreturn questions\n"),
                                              insert('export PATCHER_QUESTIONS="$GAMEDIR/setup/questions.lua"\n')), "patcher.questions-code", "WARN"),
    ("identical lib copies", both(lambda r: lib(r, "libfoo.so.1"), lambda r: lib(r, "libfoo.so.1.6", fixture="libfoo.so.1"), lambda r: lib(r, "libfoo.so.1.7", fixture="libfoo.so.1")), "libs.identical", "WARN"),
    ("libgl sourced from the data folder", both(write("testgame/gl4es/libGL.so.1", b""), write("testgame/licenses/LICENSE.gl4es", "MIT"),
        lambda r: sh(r, lambda s: s.replace('cd "$GAMEDIR"\n', 'GAME="$GAMEDIR/gamedata"\ncd "$GAME"\nif [ -f "$controlfolder/libgl_${CFW_NAME}.txt" ]; then\n  source "$controlfolder/libgl_${CFW_NAME}.txt"\nelse\n  source "$controlfolder/libgl_default.txt"\nfi\n'))), "sh.libgl-cwd", "WARN"),
    ("patchscript without the failure marker", both(write("testgame/patch/patchscript", '#!/bin/bash\nfail() { echo "Patching process failed."; exit 1; }\nxdelta3 -d -s a b c || fail\n'),
        insert('export PATCHER_FILE="$GAMEDIR/patch/patchscript"\n')), "patcher.fail-marker", "WARN"),
    ("LIBGL set by hand", insert("export LIBGL_ES=2 LIBGL_GL=21\nexport LIBGL_FB=4\n"), "sh.libgl-manual", "WARN"),
    ("LIBGL unset by hand", insert("unset LIBGL_EGL LIBGL_GLES\n"), "sh.libgl-manual", "WARN"),
    ("GPU driver probe", insert('if [ -d /sys/module/panfrost ]; then\n  echo panfrost\nfi\n'), "sh.gpu-probe", "WARN"),
    ("libmali scan", insert('for lib in /usr/lib/libmali.so.1; do\n  [ -e "$lib" ] && echo "$lib"\ndone\n'), "sh.gpu-probe", "WARN"),
    ("env override knob", insert('case "${TESTGAME_GL:-auto}" in\n  gl4es) echo x ;;\nesac\n'), "sh.env-knobs", "WARN"),
    ("self-defaulting knob", insert('export TESTGAME_FPS="${TESTGAME_FPS:-30}"\n'), "sh.env-knobs", "WARN"),
    ("long non-standard logic", insert("if grep -qi thing6 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c6\"\nfi\nif grep -qi thing7 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c7\"\nfi\nif grep -qi thing8 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c8\"\nfi\nif grep -qi thing9 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c9\"\nfi\ncase \"${MODE}\" in\n  a) X=$(grep -c foo /proc/cpuinfo) ;;\nesac\nif grep -qi thing0 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c0\"\nfi\nif grep -qi thing1 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c1\"\nfi\nif grep -qi thing2 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c2\"\nfi\nif grep -qi thing3 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c3\"\nfi\nif grep -qi thing4 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c4\"\nfi\nif grep -qi thing5 /etc/os-release; then\n  awk \"{print $1}\" /proc/asound/cards > \"$GAMEDIR/c5\"\nfi\n"), "sh.nonstandard", "WARN"),
    ("ini with nothing in it", lambda r: ini(r, "# kill switch only\n[controls]\n"), "ini.empty", "INFO"),
    ("echo, pm_finish, exit", insert('if [ ! -f data.pak ]; then\n  echo "data.pak missing"\n  sleep 5\n  pm_finish\n  exit 1\nfi\n'), "sh.echo-message", "WARN"),
    ("gptk bad key", lambda r: gptk(r, "a = return\n"), "gptk.key", "ERROR"),
    ("gptk empty value", lambda r: gptk(r, "a = \nb = esc\n"), "gptk.empty", "WARN"),
    ("gptk select", lambda r: gptk(r, "select = esc\n"), "gptk.button", "WARN"),
    ("gptk duplicate", lambda r: gptk(r, "a = space\na = enter\n"), "gptk.duplicate", "WARN"),
    # structure
    ("__MACOSX", write("__MACOSX/._x", "x"), "structure.junk", "WARN"),
    ("stray top-level file", write("notes.txt", "x"), "structure.top-level", "WARN"),
    ("too many files", lambda r: [write(f"testgame/data/f{i}.dat", "x")(r) for i in range(120)], "structure.too-many-files", "WARN"),
    ("symlink", lambda r: os.symlink("testgame.aarch64", gd(r) / "link.aarch64"), "structure.symlink", "ERROR"),
    # found in testing-thread ports
    ("gameinfo root is <game>", write("testgame/gameinfo.xml", GAMEINFO.replace("<gameList>", "").replace("</gameList>", "")), "gameinfo.structure", "ERROR"),
    ("env bash shebang", lambda r: sh(r, lambda s: s.replace("#!/bin/bash", "#!/usr/bin/env bash", 1)), "sh.shebang", "WARN"),
    ("custom header, no control.txt", lambda r: sh(r, lambda s: s.replace("source $controlfolder/control.txt\n", 'echo "control.txt"\n')), "sh.control", "WARN"),
    ("lib missing its SONAME copy", lambda r: lib(r, "libfoo.so.1.6", fixture="libfoo.so.1"), "libs.soname", "WARN"),
    ("gl4es lib without gl4es licence", lambda r: lib(r, "libGL.so.1", folder="gl4es.aarch64"), "licenses.component", "WARN"),
    ("ini stick, no deadzone at all", lambda r: ini(r, "[config]\nmouse_delay = 16\n\n[controls]\nleft_analog_up = up\n"), "ini.deadzone", "INFO"),
    # found in thedishwashervampiresmile
    ("port asoundrc over the CFW's", both(write("testgame/asoundrc", 'pcm.!default {\n  type plug\n  slave.pcm "hw:rockchiprk817co,0"\n}\n'),
                                          insert('[ -f "$HOME/.asoundrc" ] && cp "$HOME/.asoundrc" "$HOME/.asoundrc.bak"\ncp "$GAMEDIR/asoundrc" "$HOME/.asoundrc"\n')), "sh.asoundrc", "WARN"),
    ("system GLES lib as GL driver", insert("export SDL_VIDEO_GL_DRIVER=libGLESv2.so\n"), "sh.gl-driver-gles", "INFO"),
    # found in kye (PR 2870)
    ("game output to its own file", insert('"$GAMEDIR/testgame.aarch64" > "$PWD/run.txt" 2>&1\n'), "sh.log-split", "WARN"),
    ("big true-colour bmp", write("testgame/splash.bmp", b"BM" + b"\x00" * 26 + b"\x18\x00" + b"\x00" * (300 * 1024)), "files.bmp", "INFO"),
    ("README with a title heading and <br/>", write("testgame/README.md", "## Testgame\nThanks to someone!\n<br/>\n\n## Controls\n\n| Button | Action |\n"), "readme.layout", "INFO"),
    ("shipped XNA content", write("testgame/patches/sprites.xnb", b"XNBw\x05\x01"), "files.game-content", "INFO"),
    # found in hollowknight (PR 2880), teeworlds (PR 2881), ghostship, mazeburrow (PR 2877)
    ("install signature on line 2", lambda r: sh(r, lambda s: s.replace("#!/bin/bash\n", "#!/bin/bash\n# PORTMASTER: testgame.zip, Test Game.sh\n", 1)), "sh.signature", "INFO"),
    ("cd GAMEDIR || exit", lambda r: sh(r, lambda s: s.replace(HOOK, 'cd "$GAMEDIR" || exit 1\n', 1)), "sh.cd-exit", "INFO"),
    ("32-bit program without PORT_32BIT", insert("LD_LIBRARY_PATH=/lib32:/usr/lib32 ./testgame.aarch64 --setup\n"), "sh.port-32bit", "WARN"),
    ("PORT_32BIT after mod_", insert('export PORT_32BIT="Y"\nLD_LIBRARY_PATH=/lib32:/usr/lib32 ./testgame.aarch64 --setup\n'), "sh.port-32bit", "WARN"),
    ("own 32-bit userland test", insert('[ -e /lib/ld-linux-armhf.so.3 ] && echo "32-bit libraries"\n'), "sh.has-armhf", "INFO"),
    ("pm_finish before the game", insert('pm_finish\necho "now the game"\n'), "sh.pm-finish-mid", "WARN"),
    ("EXIT trap, then a message cut off by exit", insert('trap "rm -f $GAMEDIR/lock" EXIT\nif [ ! -f x ]; then\n  pm_message "x is missing"\n  sleep 5\n  exit 1\nfi\n'),
     "sh.trap-exit", "INFO"),
    ("swap set up by the script", insert("$ESUDO swapon /dev/zram0\n"), "sh.swap", "INFO"),
    ("swap in a sourced helper", both(write("testgame/swap.txt", "swap_on() {\n  $ESUDO mkswap /dev/zram1\n}\n"), insert('source "$GAMEDIR/swap.txt"\n')), "sh.swap", "INFO"),
    ("long first-run helper", both(write("testgame/setup.py", "\n".join(f"print({i})" for i in range(320)) + "\n"), insert('python3 "$GAMEDIR/setup.py" --pending\n')), "sh.setup-helper", "INFO"),
    ("two copies of one setup script", both(*(write(f"testgame/tools/{n}", "#!/bin/bash\n" + "".join(f'echo "step {i}: converting the game files, please wait"\n' for i in range(90)) + extra)
                                              for n, extra in (("patchscript", "echo 32\n"), ("patchscript64", "echo 64\n")))), "files.duplicate-script", "INFO"),
    ("ini with only [config] settings", lambda r: ini(r, "[config]\ndeadzone_mode = axial\ndeadzone = 2000\n\n[controls]\n"), "ini.empty", "INFO"),
    # found in retrocityrampagedx
    ("stub copied into the game files", both(write("testgame/libsteam_api.so", b"\x00"),
                                             insert('box64_note=1 # box64\ncp -f "$GAMEDIR/libsteam_api.so" "$GAMEDIR/gamedata/x86_64/libsteam_api.so"\n')), "sh.player-files", "INFO"),
    ("steam_appid.txt next to a stub", both(write("testgame/libsteam_api.so", b"\x00"), insert("printf '204630' > \"$GAMEDIR/gamedata/steam_appid.txt\"\n")),
     "sh.steam-appid", "INFO"),
    ("saves mirrored into conf and back", insert('CONFDIR="$GAMEDIR/conf"\nfor f in "$CONFDIR"/save*; do cp "$f" "$GAMEDIR/gamedata/"; done\n'
                                                 'for f in "$GAMEDIR/gamedata"/save*; do cp -f "$f" "$CONFDIR/"; done\n'), "sh.save-mirror", "INFO"),
    ("long custom function", insert("remap() {\n" + "".join(f"  echo {i}\n" for i in range(25)) + "}\nremap\n"), "sh.long-function", "INFO"),
    ("README with a download section", write("testgame/README.md", "## Notes\nThanks!\n\n## Download\nGet the zip from the releases page.\n\n## Controls\n\n| Button | Action |\n"),
     "readme.download", "INFO"),
    # found in fearandhunger / felvidek (quixjs) and pokemonfulldex
    ("HOTKEY set by the script", insert('export HOTKEY="${HOTKEY:-guide}"\n'), "sh.hotkey-override", "WARN"),
    ("port downloads its own updates", insert('update="$(python3 update.py "$controlfolder/autoinstall")"\n'), "sh.self-update", "WARN"),
    ("many lines no example or merged port has", insert("".join(f'if [ -f "$GAMEDIR/flag{i}" ]; then touch "$GAMEDIR/done{i}"; fi\n' for i in range(8))),
     "sh.template-diff", "INFO"),
]

# (name, change): valid ways of writing a port; must add no ERROR or WARN
VALID = [
    ("EXIT trap after the extraction message (berusky2)", insert('pm_message "Extracting"\ntrap "swaymsg seat x hide_cursor 1000" EXIT\n')),
    ("EXIT trap, message then pm_finish then exit (ghostship)", insert('trap "swap_off" EXIT\nif [ ! -f x ]; then\n  pm_message "x"\n  sleep 5\n  pm_finish\n  exit 0\nfi\n')),
    ("library copied within the port's libs folder", insert('cp -f "$GAMEDIR/libs/librk.so" "$GAMEDIR/libs/libmoonlight-rk.so"\n')),
    ("MonoMod output renamed", insert('mv "$GAMEDIR/gamedata/MONOMODDED_Game.dll.so" "$GAMEDIR/gamedata/Game.dll.so"\n')),
    ("PORT_32BIT before mod_ for a 32-bit route", both(lambda r: sh(r, lambda s: s.replace('[ -f "${controlfolder}/mod_', '[ "$ROUTE" = 32 ] && export PORT_32BIT="Y"\n[ -f "${controlfolder}/mod_', 1)),
                                                   insert("LD_LIBRARY_PATH=/lib32:/usr/lib32 ./testgame.aarch64 --setup\n"))),
    ("lib32 appended by a 64-bit runtime", insert('export LD_LIBRARY_PATH="$GAMEDIR/libs:/usr/lib32:$LD_LIBRARY_PATH"\n')),
    ("cd || exit before libgl", both(write("testgame/libs.aarch64/.keep", ""), insert('cd "$GAMEDIR/data"\ncd "$GAMEDIR" || exit 1\nif [ -f "${controlfolder}/libgl_${CFW_NAME}.txt" ]; then\n  source "${controlfolder}/libgl_${CFW_NAME}.txt"\n'
                                                                                  'else\n  source "${controlfolder}/libgl_default.txt"\nfi\n'))),
    ("pm_finish then exit", insert('if [ ! -f x ]; then\n  pm_message "x is missing"\n  sleep 5\n  pm_finish\n  exit 1\nfi\n[ -f y ] || { pm_message "y"; pm_finish; exit 1; }\n')),
    ("pm_finish ends one branch", insert('if [ -f mac ]; then\n  $GPTOKEYB2 "machismo" &\n  ./machismo\n  pm_finish\nelse\n  echo "linux build"\nfi\n')),
    ("EXIT trap keeps pm_message_end", insert('pm_message "Starting"\ntrap "rm -f $GAMEDIR/lock; pm_message_end" EXIT\n')),

    ("quoted bind target with spaces", insert('mkdir -p "$GAMEDIR/savedata"\nbind_directories "$HOME/.local/share/Some Studio/Game" "$GAMEDIR/savedata"\n')),
    ("bind source via variable", insert('CONF="$GAMEDIR/conf/"\nmkdir -p "$GAMEDIR/conf"\nbind_directories ~/.thing "$CONF"\n')),
    ("bind source created by mkdir -p of a subfolder", insert('CONF="$GAMEDIR/conf/.game"\nmkdir -p "$CONF/save/slots"\nbind_directories ~/.game "$CONF"\n')),
    ("bind_files source touched", insert('mkdir -p "$GAMEDIR/conf"\ntouch "$GAMEDIR/conf/.rc"\nbind_files ~/.rc "$GAMEDIR/conf/.rc"\n')),
    ("XDG prefix on one command", insert('XDG_DATA_HOME="$GAMEDIR/conf" ./testgame.aarch64 --version\n')),
    ("XDG set to the default", insert('export XDG_DATA_HOME="$HOME/.local/share"\n')),
    ("progress echo", insert('echo "Starting the game"\n')),
    ("echo writing state", insert('if [ ! -f x ]; then\n  echo "1" > "$GAMEDIR/state"\n  exit 1\nfi\n')),
    ("echo then pm_show_error", insert('if [ ! -f x ]; then\n  echo "x missing"\n  pm_show_error "x is missing" --title "Missing"\n  exit 1\nfi\n')),
    ("console clear", insert('printf "\\033c" > /dev/tty0\n')),
    ("console clear before pm_finish", lambda r: sh(r, lambda s: s.replace("pm_finish\n", 'printf "\\033c" > /dev/tty0\npm_finish\n'))),
    ("unset mid-script", insert("unset SDL_GAMECONTROLLERCONFIG\n")),
    ("current tee log via exec", insert('exec > >(tee "$GAMEDIR/log.txt") 2>&1\n')),
    ("GAMEDIR exported", lambda r: sh(r, lambda s: s.replace("GAMEDIR=/$directory", "export GAMEDIR=/$directory"))),
    ("current log line", insert('> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1\n')),
    ("old pm_message without options", insert('pm_message "Loading"\n')),
    ("pm_message with options", insert('pm_message "Loading" --title "Please wait" --timeout 5\n')),
    ("gunzip | tar", insert('gunzip -c data.tar.gz | tar --no-same-owner -xf -\n')),
    ("libgl via CFW file", insert('if [ -f "${controlfolder}/libgl_${CFW_NAME}.txt" ]; then\n  source "${controlfolder}/libgl_${CFW_NAME}.txt"\nelse\n  source "${controlfolder}/libgl_default.txt"\nfi\n')),
    ("LD_PRELOAD prefix on the game", lambda r: sh(r, lambda s: s.replace("./testgame.aarch64\n", 'LD_PRELOAD="$GAMEDIR/libhook.so" ./testgame.aarch64\n'))),
    ("GameMaker template exports", insert('export LD_LIBRARY_PATH="/usr/lib:$LD_LIBRARY_PATH"\nexport SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"\n')),
    ("classic gptokeyb", lambda r: sh(r, lambda s: s.replace("$GPTOKEYB2", "$GPTOKEYB"))),
    ("classic .gptk", lambda r: gptk(r, "back = esc\nstart = enter\na = space\nb = \\\"\nup = up\nup = repeat\n")),
    ("gptokeyb2 -x mode", lambda r: sh(r, lambda s: s.replace(LAUNCH, '$GPTOKEYB2 "testgame.aarch64" -x &\n'))),
    ("-c file made by the script", lambda r: sh(r, lambda s: s.replace(LAUNCH, 'cp "$GAMEDIR/conf/default.ini" "$GAMEDIR/made.ini"\n$GPTOKEYB2 "testgame.aarch64" -c "$GAMEDIR/made.ini" &\n'))),
    ("-c controlfolder template", lambda r: sh(r, lambda s: s.replace(LAUNCH, '$GPTOKEYB "testgame.aarch64" -c "$controlfolder/gamecontrollerdb.txt" &\n'))),
    ("helper ini not for gptokeyb", both(write("testgame/helper.ini", "[controls]\na = context_click\n"),
                                         insert('HELPER="$GAMEDIR/helper.ini"\n'))),
    ("gptokeyb2 select alias", lambda r: ini(r, "[controls]\nselect = esc\n")),
    ("ini via variable", lambda r: (ini(r, "[controls]\na = space\nb = \\\"\n", pass_c=False),
                                    sh(r, lambda s: s.replace(LAUNCH, 'CTRL="$GAMEDIR/testgame.ini"\n$GPTOKEYB2 "testgame.aarch64" -c "$CTRL" &\n')))),
    ("ini with hotkey section", lambda r: ini(r, "[controls]\na = space\nhotkey = hold_state hk_state\n\n[controls:hk_state]\nr1 = enter\n")),
    ("runtime with .squashfs", lambda r: pj(r, runtime=["weston_pkg_0.2.squashfs"])),
    ("runtime without suffix", lambda r: pj(r, runtime=["weston_pkg_0.2"])),
    ("catalog key with arch in it", lambda r: pj(r, runtime=["mono-6.12.0.122-aarch64.squashfs"])),
    ("pm_message before a branch that exits", insert('pm_message "Preparing data"\nif ! true; then\n  pm_show_error "Failed" --title "Error"\n  exit 1\nfi\n')),
    ("template harbourmaster check", insert('if [ ! -f "$controlfolder/harbourmaster" ]; then\n  pm_message "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info."\n  sleep 5\n  exit 1\nfi\n')),
    ("thanks under Credits instead of Notes", write("testgame/README.md", README.replace("## Notes\n\nThanks.", "## Credits\n\nThanks to the author.").replace("## Controls", "# Game\n\n## Controls"))),
    ("export XDG_DATA_HOME (packaging guide)", insert('export XDG_DATA_HOME="$GAMEDIR/conf"\n')),
    ("pm_message then exit (EXIT trap keeps it up 3 s)", insert('if [ ! -f "$GAMEDIR/data.pak" ]; then\n  pm_message "Put data.pak in ports/testgame."\n  exit 1\nfi\n')),
    ("gl driver export guarded on LIBGL_ES", insert('if [ -f "$controlfolder/libgl_${CFW_NAME}.txt" ]; then\n  source "$controlfolder/libgl_${CFW_NAME}.txt"\nelse\n  source "$controlfolder/libgl_default.txt"\nfi\nif [[ "$LIBGL_ES" != "" ]]; then\n  export SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1"\nfi\n')),
    ("README names a shipped patch", both(write("testgame/patches/game-fixes.patch", "x"), write("testgame/README.md", README + "\nApply `game-fixes.patch` first.\n"))),
    ("note names README.md", write("testgame/data/PUT_FILES_HERE.txt", "See ../README.md for installation.\n")),
    ("patcher questions built from the screen size", both(write("testgame/setup/questions.lua", "local questions = {\n  { id = \"Q\", question = \"Pick one\", options = { { \"a\", \"A\" } } },\n}\nlocal w = tonumber(os.getenv(\"DISPLAY_WIDTH\"))\nif w and w > 640 then table.insert(questions, { id = \"R\", question = \"Res?\", options = {} }) end\nreturn questions\n"),
                                                         insert('export PATCHER_QUESTIONS="$GAMEDIR/setup/questions.lua"\n'))),
    ("empty min_glibc, binaries below 2.30", both(lambda r: shutil.copy(FIX / "libglibc217.so.1", gd(r) / "testgame.aarch64"), lambda r: pj(r, min_glibc=""))),
    ("libgl sourced from GAMEDIR", both(write("testgame/gl4es/libGL.so.1", b""), write("testgame/licenses/LICENSE.gl4es", "MIT"),
        insert('if [ -f "$controlfolder/libgl_${CFW_NAME}.txt" ]; then\n  source "$controlfolder/libgl_${CFW_NAME}.txt"\nelse\n  source "$controlfolder/libgl_default.txt"\nfi\ncd "$GAMEDIR/data"\n'))),
    ("patchscript with the failure marker", both(write("testgame/patch/patchscript", '#!/bin/bash\nfail() { echo "PATCH_FAIL_MSG:Wrong version"; echo "Patching process failed!"; exit 1; }\nxdelta3 -d -s a b c || fail\n'),
        insert('export PATCHER_FILE="$GAMEDIR/patch/patchscript"\n'))),
    ("LIBGL_FB only read", insert('if [[ "$LIBGL_FB" != "" ]]; then\n  echo gl4es\nfi\n')),
    ("own variable with a default", insert('RES="$(cat "$GAMEDIR/res.txt" 2>/dev/null)"\necho "${RES:-640}"\n')),
    ("CFW variables with defaults", insert('echo "${DISPLAY_WIDTH:-640} ${SDL_VIDEODRIVER:-} ${XDG_CONFIG_HOME:-$HOME/.config} ${LD_LIBRARY_PATH:-}"\n')),
    ("own launcher config and launch arguments (lix)", insert("if ! grep -qx \"PLAY=1\" \"$GAMEDIR/launch.cfg\" 2>/dev/null; then\n  pm_finish\n  exit 0\nfi\nsource \"$GAMEDIR/game.cfg\"\nexport GAME_CURSOR_SCALE\nsed -i \"s/^mouse_scale = .*/mouse_scale = $MOUSE_SCALE/\" \"$GAMEDIR/game.gptk\"\nif [ \"$SCREEN_MODE\" = \"1\" ]; then\n  FULL=\"--fullscreen\"\nelse\n  FULL=\"--hardfull=${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}\"\nfi\n: > \"$GAMEDIR/log.txt\" && exec > >(tee \"$GAMEDIR/log.txt\") 2>&1\n")),
    ("sdl3 shim forwarding, OmniOSK prefix, bind to $HOME", insert('mkdir -p \"$GAMEDIR/conf/app\"\nbind_directories \"$HOME/.config/app\" \"$GAMEDIR/conf/app\"\nif [ -n \"$SDL_VIDEODRIVER\" ]; then\n  export SDL3SHIM_SDL2_VIDEODRIVER=\"$SDL_VIDEODRIVER\"\n  GAME_SDL_VIDEODRIVER=sdl2\nfi\nSDL_VIDEODRIVER=\"$GAME_SDL_VIDEODRIVER\" LD_PRELOAD=\"$GAMEDIR/libs.aarch64/libomni_osk.so\" ./testgame.aarch64 --version\n')),
    ("README Building instead of Compile", write("testgame/README.md", README.replace("## Compile", "## Building"))),
    ("HOME only as bind_directories fallback", insert('mkdir -p "$GAMEDIR/conf/.game"\nif type bind_directories >/dev/null 2>&1; then\n  bind_directories ~/.game "$GAMEDIR/conf/.game"\nelse\n  export HOME="$GAMEDIR/conf"\nfi\n')),
    ("SDL driver only logged", insert('echo "SDL_VIDEODRIVER=$SDL_VIDEODRIVER"\n')),
    ("empty log and conf placeholder", both(write("testgame/log.txt", ""), write("testgame/conf/.gitkeep", ""))),
    ("gptokeyb2 exclusive directive", lambda r: ini(r, "[controls]\noverlay = clear\nexclusive = false\n")),
    ("near-universal lib as a fallback", lambda r: lib(r, "libpng16.so.16", folder="libs.aarch64/fallback")),
    ("empty runtime and nulls", lambda r: pj(r, runtime=[], image=None, desc_md=None, inst_md=None)),
    ("cover as gameinfo image", both(lambda r: gameinfo(r, "screenshot.png</image>", "cover.png</image>"))),
    ("licence as an image", both(lambda r: (gd(r) / "licenses" / "LICENSE.testgame").unlink(),
                                 write("testgame/licenses/permission.png", png(10, 10)))),
    ("license folder singular", lambda r: (gd(r) / "licenses").rename(gd(r) / "license")),
    ("no cover", remove("testgame/cover.png")),
    ("no testing_thread", remove("testgame/testing_thread.txt")),
    ("not rtr, no game licence", both(lambda r: pj(r, rtr=False),
                                      lambda r: (gd(r) / "licenses" / "LICENSE.testgame").rename(gd(r) / "licenses" / "LICENSE.zlib"))),
    ("PR layout", lambda r: [(gd(r) / n).rename(Path(r) / n) for n in ("port.json", "README.md", "gameinfo.xml", "screenshot.png", "cover.png")]),
    ("lib with licence", lambda r: lib(r, "libfoo.so.1")),
    ("libGL inside gl4es", both(lambda r: lib(r, "libGL.so.1", folder="gl4es.aarch64"), write("testgame/licenses/LICENSE.gl4es", "MIT"))),
    ("X11 with Westonpack", both(lambda r: lib(r, "libX11.so.6"), insert('weston_runtime="weston_pkg_0.2"\n'), lambda r: pj(r, runtime=["weston_pkg_0.2"]))),
    # found in testing-thread ports
    ("gptk inline comments", lambda r: gptk(r, "back = esc     # quit modifier\na = enter        # confirm\n")),
    ("ini plain deadzone", lambda r: ini(r, "[config]\ndeadzone = 12000\n\n[controls]\nleft_analog_up = up\nleft_analog_down = down\n")),
    ("ini mouse with plain deadzone", lambda r: ini(r, "[config]\nmouse_delay = 16\ndeadzone_mode = scaled_radial\ndeadzone_scale = 6\ndeadzone = 2000\n\n[controls]\nleft_analog = mouse_movement\na = mouse_left\n")),
    ("control.txt found by a loop", lambda r: sh(r, lambda s: s.replace("source $controlfolder/control.txt\n",
        'for c in /opt/system/Tools/PortMaster/control.txt /roms/ports/PortMaster/control.txt; do [ -f "$c" ] && CTL="$c" && break; done\nsource "$CTL"\n'))),
    ("lower-case gamelist root", lambda r: gameinfo(r, "gameList>", "gamelist>")),
    ("cover.jpg as image", both(write("testgame/cover.jpg", b"\xff\xd8\xff\xe0jpg"), lambda r: gameinfo(r, "screenshot.png</image>", "cover.jpg</image>"))),
    ("runtime port with empty arch", lambda r: (pj(r, arch=[], runtime=["weston_pkg_0.2"]), insert('weston_runtime="weston_pkg_0.2"\n')(r))),
    ("licences spelling", lambda r: (gd(r) / "licenses").rename(gd(r) / "licences")),
    ("debian copyright licence", lambda r: (lib(r, "libfoo.so.1", licence=False),
                                            write("testgame/licenses/debian/libfoo1.copyright", "MIT")(r))),
    ("SDL3 shim driver forwarding", insert('GAME_SDL_VIDEODRIVER=""\nif [ -n "$SDL_VIDEODRIVER" ]; then\n  export SDL3SHIM_SDL2_VIDEODRIVER="$SDL_VIDEODRIVER"\n  GAME_SDL_VIDEODRIVER=sdl2\nfi\n'
                                           'SDL_VIDEODRIVER="$GAME_SDL_VIDEODRIVER" ./testgame.aarch64 --version\n')),
    ("lib loaded by its unversioned name", lambda r: (lib(r, "libfoo.so", fixture="libfoo.so.1"), write("testgame/game.config", '<dllmap dll="foo" target="libfoo.so"/>')(r))),
    ("wrapper script", both(write("Test Game MP.sh", '#!/bin/bash\nSCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\nexec "$SCRIPT_DIR/Test Game.sh" MP\n'),
                            lambda r: pj(r, _items=["Test Game.sh", "Test Game MP.sh", "testgame"]))),
    ("kill between launcher and game", both(write("testgame/launcher.gptk", "back = esc\nstart = enter\n"),
                                            insert('$GPTOKEYB "love" -c "$GAMEDIR/launcher.gptk" &\n$LOVE_RUN launcher\n$ESUDO pkill -9 -f "gptokeyb"\n'))),
    ("ArkOS asoundrc restored from the CFW backup", insert('if [ ! -f ~/.asoundrc ] && [ -f ~/.asoundrcbak ]; then\n  $ESUDO cp ~/.asoundrcbak ~/.asoundrc\nfi\n')),
    ("asoundrc created only when the CFW has none", insert('if [ ! -f "${HOME}/.asoundrc" ]; then\n  printf "pcm.!default { type plug }\\n" > "${HOME}/.asoundrc"\nfi\n')),
    ("own XNA content in the game's data folder", write("testgame/gamedata/Content/font.xnb", b"XNBw")),
    ("pm_message, sleep, exit", insert('if [ ! -f data.pak ]; then\n  pm_message "data.pak missing"\n  sleep 10\n  pm_finish\n  exit 1\nfi\n')),
    ("stderr captured for the error message", insert('./testgame.aarch64 --install 2> install.err\nERROR=$(sed "s/^x//" install.err)\n')),
    ("game output teed to a second file", insert('./testgame.aarch64 > >(tee "$GAMEDIR/server.log") 2>&1 &\n')),
    ("tar data with guard", insert('ARCHIVE_FILE="gamedata.tar.gz"\nif [[ -f "$ARCHIVE_FILE" ]]; then\n'
                                   '    pm_message "Extracting" --title "Please wait"\n'
                                   '    if ! gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -; then\n'
                                   '        pm_show_error "Could not extract" --title "Extraction failed"\n        exit 1\n    fi\n'
                                   '    $ESUDO rm -f "$ARCHIVE_FILE"\nfi\n')),
]


def findings(root, pr=False):
    port = load(root, pr=pr)
    try:
        return run_all(port)
    finally:
        port.cleanup()


PR_LAYOUT = ("port.json", "README.md", "gameinfo.xml", "screenshot.png", "cover.png")

# (name, mutate, rule, severity) checked with the strict PR layout (--pr)
PR_MUTATIONS = [
    ("PR: metadata in the game folder", lambda r: None, "structure.pr-layout", "ERROR"),
    ("PR: port.json name", lambda r: (to_pr(r), pj_at(r, _name="other.zip")), "port.json.name", "ERROR"),
    ("PR: no screenshot", lambda r: (to_pr(r), (Path(r) / "screenshot.png").unlink()), "files.missing", "ERROR"),
]


def to_pr(root):
    for n in PR_LAYOUT:
        (gd(root) / n).rename(Path(root) / n)


def pj_at(root, **attr):
    p = Path(root) / "port.json"
    d = json.loads(p.read_text())
    for k, v in attr.items():
        d[k[1:]] = v if k.startswith("_") else d["attr"].__setitem__(k, v)
    p.write_text(json.dumps(d))


class Mutations(unittest.TestCase):
    def test_pr_planted_errors_are_caught(self):
        for name, mutate, rule, sev in PR_MUTATIONS:
            with self.subTest(name), tempfile.TemporaryDirectory() as t:
                t = Path(t) / "testgame"
                make_port(t)
                mutate(t)
                got = {(f.rule, f.severity) for f in findings(t, pr=True)}
                self.assertIn((rule, sev), got, f"{name}: expected {rule} {sev}, got {sorted(got)}")

    def test_planted_errors_are_caught(self):
        for name, mutate, rule, sev in MUTATIONS:
            with self.subTest(name), tempfile.TemporaryDirectory() as t:
                make_port(t)
                mutate(t)
                got = {(f.rule, f.severity) for f in findings(t)}
                self.assertIn((rule, sev), got, f"{name}: expected {rule} {sev}, got {sorted(got)}")


class ShellcheckFindings(unittest.TestCase):
    def test_shellcheck_findings_do_not_crash_the_script_check(self):
        """the shellcheck loop once reused the name of the script's line list, and every later check crashed"""
        from unittest import mock
        import pmcheck.rules as rules
        real_which, real_run = shutil.which, rules._run
        sc = json.dumps([{"code": 2242, "message": "Can only exit with status 0-255.", "line": 3}])
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(rules.shutil, "which", lambda n, *a, **k: "/usr/bin/shellcheck" if n == "shellcheck" else real_which(n, *a, **k)), \
                mock.patch.object(rules, "_run", lambda cmd: sc if cmd[0] == "shellcheck" else real_run(cmd)):
            make_port(t)
            got = {f.rule for f in findings(t)}
        self.assertIn("sh.shellcheck", got)
        self.assertFalse([r for r in got if r.startswith("internal.")], sorted(got))


class ImageSize(unittest.TestCase):
    def test_jpeg_size_without_pil(self):
        from unittest import mock
        import builtins
        from pmcheck.rules import image_size
        real_import = builtins.__import__
        jpg = b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xc0\x00\x11\x08\x03\xc0\x05\x00\x03" + b"\x00" * 9 + b"\xff\xd9"
        with tempfile.TemporaryDirectory() as t, mock.patch.object(builtins, "__import__",
                lambda name, *a, **k: (_ for _ in ()).throw(ImportError()) if name == "PIL" else real_import(name, *a, **k)):
            p = Path(t) / "screenshot.jpg"
            p.write_bytes(jpg)
            self.assertEqual(tuple(image_size(p)), (1280, 960))


class PerArchLibs(unittest.TestCase):
    def test_same_library_name_in_two_arch_folders_is_checked_in_both(self):
        """libs.aarch64/x.so and libs.armhf/x.so once shared one entry, so only the last folder was checked"""
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            lib(t, "libGL.so.1", fixture="libfoo.so.1")
            lib(t, "libGL.so.1", folder="libs.armhf", fixture="libfoo.so.1")
            got = sorted(f.file for f in findings(t) if f.rule == "libs.banned")
        self.assertEqual(got, ["testgame/libs.aarch64/libGL.so.1", "testgame/libs.armhf/libGL.so.1"])


class ArmhfNote(unittest.TestCase):
    def rules(self, extra):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            extra(t)
            return {(f.rule, f.severity) for f in findings(t)}

    def test_armhf_only_without_armhf_arch(self):
        got = self.rules(lambda r: (gd(r) / "testgame.aarch64").write_bytes((FIX / "hello.armhf").read_bytes()))
        self.assertIn(("port.json.arch", "WARN"), got)

    def test_armhf_only_with_armhf_arch(self):
        got = self.rules(lambda r: ((gd(r) / "testgame.aarch64").write_bytes((FIX / "hello.armhf").read_bytes()), pj(r, arch=["armhf"])))
        self.assertNotIn(("port.json.arch", "WARN"), got)
        self.assertNotIn(("port.json.arch", "INFO"), got)

    def test_armhf_port_with_aarch64_helper(self):
        got = self.rules(lambda r: ((gd(r) / "testgame.aarch64").rename(gd(r) / "gamepad-picker.aarch64"),
                                    shutil.copy(FIX / "hello.armhf", gd(r) / "testgame.armhf"), pj(r, arch=["armhf"])))
        self.assertNotIn(("port.json.arch", "WARN"), got)
        self.assertNotIn(("port.json.arch", "INFO"), got)

    def test_armhf_next_to_aarch64_picked_by_the_script(self):
        """a script that chooses the build by the 32-bit userland (and checks its glibc) needs no arch or min_glibc note"""
        got = self.rules(lambda r: (shutil.copy(FIX / "hello.armhf", gd(r) / "testgame.armhf"),
                                    sh(r, lambda s: s.replace(HOOK, HOOK + '[ "$DEVICE_HAS_ARMHF" = Y ] && /lib/ld-linux-armhf.so.3 --version\n', 1))))
        self.assertNotIn(("port.json.arch", "INFO"), got)
        self.assertNotIn(("port.json.min_glibc", "INFO"), got)

    def test_armhf_next_to_aarch64(self):
        got = self.rules(lambda r: shutil.copy(FIX / "hello.armhf", gd(r) / "testgame.armhf"))
        self.assertIn(("port.json.arch", "INFO"), got)
        self.assertNotIn(("port.json.arch", "WARN"), got)


class PRScope(unittest.TestCase):
    def test_runtime_in_the_port_pr(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t) / "testgame"
            make_port(t)
            to_pr(t)
            port = load(t, pr=True)
            port.pr_outside = ["ports/testgame/Test Game.sh", "runtimes/dotnet-6.0.36.aarch64.squashfs"]
            try:
                got = [f for f in run_all(port) if f.rule == "pr.outside-ports"]
            finally:
                port.cleanup()
        self.assertEqual(len(got), 1)
        self.assertIn("runtimes/dotnet-6.0.36.aarch64.squashfs", got[0].message)


class LicenceAlias(unittest.TestCase):
    def test_library_licence_under_the_project_name(self):
        """libbz2 with LICENSE.bzip2.txt (ghostship), libcrypto with an OpenSSL licence"""
        for name, licence in (("libbz2.so.1", "LICENSE.bzip2.txt"), ("libcrypto.so.1.1", "LICENSE.openssl.txt")):
            with self.subTest(name), tempfile.TemporaryDirectory() as t:
                make_port(t)
                lib(t, name, fixture="libfoo.so.1", licence=False)
                (gd(t) / "licenses" / licence).write_text("licence text")
                got = [f.message for f in findings(t) if f.rule == "licenses.component"]
            self.assertEqual(got, [], name)


class GptkNoKey(unittest.TestCase):
    def test_quote_variants_mean_no_key(self):
        """akeyspath: x = "\\" maps to no key in classic gptokeyb, like \\"; l2 = l2 is a real dead button"""
        from pmcheck.gptk import check_gptk
        got = [(f.rule, f.line) for f in check_gptk('x = "\\"\na = \\"\nl2 = l2\nb = \\\\\ny = /"\nr1 = "\n', "t.gptk")]
        got = [x for x in got if x[0] != "gptk.placeholder"]
        self.assertEqual(got, [("gptk.key", 3)])   # bugdom's \\\\ and /" are no key too; a lone " is a real key


class IniQuotedAction(unittest.TestCase):
    def test_quoted_special_action(self):
        """openmohaa: l1 = "mouse_slow" (gptokeyb2 strips quotes before matching); "return" is still no key"""
        from pmcheck.ini import check_ini
        got = [f.line for f in check_ini('[controls]\nl1 = "mouse_slow"\nback = return\n', "t.ini") if f.rule == "ini.key"]
        self.assertEqual(got, [3])

    def test_inline_comments(self):
        """wargus: r2 = "shift"   ; Shift for queued commands (inih strips ; and # comments after whitespace)"""
        from pmcheck.ini import check_ini
        text = '[controls]\nr2 = "shift"   ; Shift for queued commands\nb = "h" ; harvest ; town hall;\ny = "p"   # Patrol\na = ";"\n'
        self.assertEqual([f.message for f in check_ini(text, "t.ini") if f.rule == "ini.key"], [])


class GptkByGptokeyb2(unittest.TestCase):
    PP = 'a = "mouse_left"\nl1 = "mouse_slow"\nstart = "enter"\nr3 = \\"\nup = mouse_movement_up\ndown = \\" \nr2 = "shift"   ; queued commands\ndeadzone_mode = scaled_radial\n'

    def test_papersplease_style_gptk_with_gptokeyb2(self):
        """papersplease: quoted keys and \\" placeholders in a .gptk started with $GPTOKEYB2 are all valid"""
        from pmcheck.rules import _gptk_by_g2
        from pmcheck.gptk import check_gptk
        self.assertTrue(_gptk_by_g2("PapersPlease.gptk", '$GPTOKEYB2 "$BINARY" -c "$GAMEDIR/$BINARY.gptk" &'))
        self.assertEqual([f.message for f in check_gptk(self.PP, "t.gptk", g2=True) if f.severity == "ERROR"], [])

    def test_quoted_keys_with_classic_gptokeyb(self):
        from pmcheck.gptk import check_gptk
        got = [f.line for f in check_gptk(self.PP, "t.gptk") if f.rule == "gptk.key"]
        self.assertEqual(got, [1, 2, 3, 7])   # classic gptokeyb keeps the quotes, so every quoted value is dead


class GptkPlaceholder(unittest.TestCase):
    def test_non_template_placeholders(self):
        """bugdom: back = \\\\ unbinds like \\", but the template spells it \\" """
        from pmcheck.gptk import check_gptk
        text = 'back = \\\\\nstart = \\"\na = "\\"\nb = /"\n'
        got = [(f.rule, f.severity, f.line) for f in check_gptk(text, "t.gptk")]
        self.assertEqual(got, [("gptk.placeholder", "INFO", 1), ("gptk.placeholder", "INFO", 3), ("gptk.placeholder", "INFO", 4)])
        g2 = [(f.severity, f.line) for f in check_gptk(text, "t.gptk", g2=True) if f.rule == "gptk.placeholder"]
        self.assertEqual(g2, [("INFO", 1), ("WARN", 3), ("INFO", 4)])   # gptokeyb2 strips the quotes of "\\": a real backslash


class GptkUnused(unittest.TestCase):
    def test_alt_gptk_never_loaded(self):
        """Farmner: altFarmner.gptk is never passed with -c; report it once instead of its keys"""
        from pmcheck.rules import _gptk_unused
        sh_ = '$GPTOKEYB "frt_3.5.2" -c "./Farmner.gptk" &\n'
        self.assertTrue(_gptk_unused("altFarmner.gptk", sh_))
        self.assertFalse(_gptk_unused("Farmner.gptk", sh_))
        self.assertFalse(_gptk_unused("x.gptk", '$GPTOKEYB2 "$BINARY" -c "$GAMEDIR/$BINARY.gptk" &\n'))   # computed name: can't tell
        self.assertFalse(_gptk_unused("alt.gptk", 'cp alt.gptk game.gptk\n$GPTOKEYB "g" -c "./game.gptk" &\n'))


class GameLicenceByName(unittest.TestCase):
    def test_licence_named_after_the_game_outside_licenses(self):
        """turbotabletennis/turbotabletennis.license.txt next to the binary"""
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            for f in (gd(t) / "licenses").iterdir():
                if "testgame" in f.name.lower():
                    f.unlink()
            (gd(t) / "testgame.license.txt").write_text("Free to redistribute.")
            got = {f.rule for f in findings(t)}
        self.assertNotIn("licenses.game", got)


class GameLicenceLoose(unittest.TestCase):
    def rules(self, files):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (gd(t) / "licenses" / "LICENSE.testgame").unlink()
            for n in files:
                (gd(t) / n).write_text("licence")
            return {f.rule for f in findings(t)}

    def test_developer_named_licence(self):
        """gunsandguns: LICENSE.yousfiwalid.txt; operius: GAME.LICENSE.txt"""
        self.assertNotIn("licenses.game", self.rules(["LICENSE.yousfiwalid.txt"]))
        self.assertNotIn("licenses.game", self.rules(["GAME.LICENSE.txt"]))
        self.assertNotIn("licenses.game", self.rules(["gpl.txt"]))   # meritous

    def test_component_licence_is_not_the_games(self):
        self.assertIn("licenses.game", self.rules(["LICENSE.FRT.txt"]))
        self.assertIn("licenses.game", self.rules(["gl4es.LICENSE"]))


DW3_STYLE = ("""if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
case "$(uname -m)" in aarch64) arch=aarch64 ;; *) arch=armhf ;; esac
unset PM_FUNCS_VERSION
source "$controlfolder/funcs.txt"
check_libs() {
  ldd "$GAMEDIR/testgame.aarch64" | grep "not found"
}
pick_renderer() {
  awk '/CPU part/ {print $4}' /proc/cpuinfo
}
blank_fb() {
  dd if=/dev/zero of=/dev/fb0 bs=4096 count=10
}
run_with_env() {
  $ESUDO env SDL_GAMECONTROLLERCONFIG="$SDL_GAMECONTROLLERCONFIG" "$@"
}
""" + "".join(f'echo "step {i}"\n' for i in range(240)))
GENERATED = ("""# generated by portgen 1.2
trap 'cleanup' INT TERM HUP
os=$(grep '^NAME=' /etc/os-release)
[ -f "$HOME/.config/.OS" ] && os=$(cat "$HOME/.config/.OS")
echo 0 | $ESUDO tee /proc/sys/vm/page-cluster
a() { :; }
b() { :; }
cleanup() { :; }
""" + "".join(f'echo "line {i}"\n' for i in range(130)))


class Reinvented(unittest.TestCase):
    def rules(self, text):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            insert(text)(t)
            fs = findings(t)
            return {(f.rule, f.severity) for f in fs}, fs

    def test_dw3_style_script(self):
        got, fs = self.rules(DW3_STYLE)
        self.assertIn(("sh.reinvented", "ERROR"), got)
        f = next(f for f in fs if f.rule == "sh.reinvented")
        for what in ("CPU architecture", "ldd", "/proc/cpuinfo", "framebuffer", "bash", "funcs.txt", "$ESUDO env"):
            self.assertIn(what, f.snippet)

    def test_generated_script(self):
        got, fs = self.rules(GENERATED)
        self.assertTrue({("sh.reinvented", "WARN"), ("sh.reinvented", "ERROR")} & got, sorted(got))
        self.assertIn("script generator", next(f for f in fs if f.rule == "sh.reinvented").snippet)

    def test_wording_stays_kind(self):
        """the porter reads this: no judgement words (porter-facing tone)"""
        _, fs = self.rules(DW3_STYLE)
        f = next(f for f in fs if f.rule == "sh.reinvented")
        text = (f.message + f.fix + (f.snippet or "")).lower()
        for word in ("slop", "low effort", "lazy", "no offense", "won't be merged", "garbage"):
            self.assertNotIn(word, text)

    def test_long_plain_and_function_heavy_scripts(self):
        plain = "".join(f'export GAME_OPTION_{i}="{i}"\n' for i in range(200))
        funcs = "".join(f"f{i}() {{\n  echo {i}\n}}\n" for i in range(9)) + "".join(f'echo "{i}"\n' for i in range(200))
        for text in (plain, funcs):
            got, _ = self.rules(text)
            self.assertNotIn(("sh.reinvented", "ERROR"), got)
            self.assertNotIn(("sh.reinvented", "WARN"), got)

    def test_callout_first_in_markdown(self):
        from pmcheck.report import markdown
        _, fs = self.rules(DW3_STYLE)
        md = markdown("testgame", fs)
        self.assertLess(md.index("Before the details: the launch script"), md.index("## "  + "\u274c") if "\u274c" in md else len(md))


class LeanScriptNotes(unittest.TestCase):
    def test_moves_inside_libs_are_not_player_files(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            insert('cp -f "$GAMEDIR/libs/librk.so" "$GAMEDIR/libs/libx.so"\nmv "$GAMEDIR/gamedata/MONOMODDED_G.dll.so" "$GAMEDIR/gamedata/G.dll.so"\n')(t)
            self.assertNotIn("sh.player-files", {f.rule for f in findings(t)})

    def test_closest_merged_port_for_box64_westonpack(self):
        """retrocityrampagedx: a box64 + crusty script is compared with the box64/Westonpack example and a merged box64 port"""
        from pmcheck import peers, templates
        text = open(Path(__file__).parent / "fixtures" / "rcr_like.sh").read() if (Path(__file__).parent / "fixtures" / "rcr_like.sh").exists() else (
            '#!/bin/bash\nweston_dir=/tmp/weston\nweston_runtime="weston_pkg_0.2"\n$ESUDO mount "$controlfolder/libs/${weston_runtime}.squashfs" "$weston_dir"\n'
            '$ESUDO env $weston_dir/westonwrap.sh headless noop kiosk crusty_glx_gl4es "$GAMEDIR/box64" ./game\n')
        self.assertEqual(templates.pick(text)[0], "site/westonpack-box64")
        peer, _ = peers.closest(text)
        self.assertIsNotNone(peer)
        self.assertIn("box64", peer["tags"])


class Templates(unittest.TestCase):
    def test_every_template_parses(self):
        from pmcheck import templates
        for p in sorted((templates.HERE / "site").glob("*.sh")) + sorted((templates.HERE / "new").glob("*.sh")):
            key = f"{p.parent.name}/{p.stem}"
            self.assertTrue(templates.keys_of(key), key)
            self.assertTrue(p.read_text().startswith("#!/bin/bash"), key)
        self.assertGreaterEqual(len(templates.site_index()), 30)

    def test_pick_by_kind(self):
        from pmcheck import templates
        cases = {
            "./ua_host64 \"$GAMEDIR/arm64\"": "site/standard-unity",
            "./quixjs.${DEVICE_ARCH} --launcher -c port.toml": "site/standard-rpg-maker-mv",
            "$weston_dir/westonwrap.sh headless noop kiosk crusty_glx_gl4es \"$GAMEDIR/box64\" ./game": "site/westonpack-box64",
            "$weston_dir/westonwrap.sh headless noop kiosk crusty_x11egl $godot_dir/godot45": "site/westonpack-godot-4",
            "./gmloadernext.aarch64 -c gmloader.json": "site/standard-gmloader-next",
            "\"$GAMEDIR/box64/box64\" ./game.x86_64": "site/standard-box64",
            "\"$GAMEDIR/box86/box86\" ./game.x86": "site/standard-box86",
            "export MONO_PATH=\"$GAMEDIR/dlls\"": "site/standard-mono",
            "./testgame.aarch64": "site/standard-basic",
        }
        for line, want in cases.items():
            self.assertEqual(templates.pick("#!/bin/bash\n" + line + "\n")[0], want, line)

    def test_new_templates_are_clean(self):
        """the templates themselves must pass pmcheck's script rules (they are what porters copy)"""
        from pmcheck import templates
        ours = ["standard-gl4es", "standard-patcher", "standard-gmloader-next", "standard-mkxp-z", "standard-ren-py", "standard-mono",
                "standard-net-8", "standard-box64", "standard-box86", "standard-rpg-maker-mv", "standard-unity", "westonpack-box64"]
        for key in ["new/basic"] + [f"site/{k}" for k in ours]:
            with self.subTest(key), tempfile.TemporaryDirectory() as t:
                make_port(t)
                body = templates.text_of(key).replace("portfolder", "testgame").replace("portexecutable", "testgame")
                (Path(t) / "Test Game.sh").write_text(body)
                bad = [f"{f.rule} {f.line} {f.message[:80]}" for f in findings(t) if f.severity in ("ERROR", "WARN") and f.rule.startswith("sh.") and f.rule != "sh.gptk-missing"]   # the example .ini is the port's own
                self.assertEqual(bad, [], key)


class RagingThunderLike(unittest.TestCase):
    def test_no_game_folder_named_by_the_script(self):
        """ragingthunder2: the binary and .gptk next to the script, only src/ as a folder; src/ is not the game folder"""
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            for p in list(gd(t).iterdir()):
                if p.is_file() and p.suffix != ".json":
                    p.rename(Path(t) / p.name)
            shutil.rmtree(gd(t))
            (Path(t) / "src").mkdir()
            (Path(t) / "src" / "main.c").write_text("int main(){}")
            got = findings(t)
            f = next(f for f in got if f.rule == "structure.no-gamedir")
        self.assertIn("ports/testgame/", f.message)
        self.assertNotIn("src", {x.file.split("/")[0] for x in got if x.file})

    def test_optional_portmaster_and_folder_search(self):
        text = ('[ -f "$controlfolder/control.txt" ] && source "$controlfolder/control.txt"\n'
                'if command -v pm_platform_helper >/dev/null; then pm_platform_helper x; fi\n'
                'SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"\n'
                'if [ -d a ]; then GAMEDIR=a\nelif [ -d b ]; then GAMEDIR=b\nelse GAMEDIR=c\nfi\n'
                'export LD_LIBRARY_PATH="$GAMEDIR/libs:/usr/lib/arm-linux-gnueabihf:/usr/lib32:/lib32:/usr/lib:$LD_LIBRARY_PATH"\n')
        import re
        from pmcheck import data
        hits = {k for k, rx, need, _, _ in data.REINVENT_SIGNALS if len(re.findall(rx, text, re.M)) >= need}
        self.assertTrue({"pm-guards", "gamedir-search", "system-libpath", "script-dir"} <= hits, hits)


class StripThreshold(unittest.TestCase):
    def rules(self, strip_min, strip_warn):
        from unittest import mock
        import pmcheck.data as data
        with tempfile.TemporaryDirectory() as t, mock.patch.object(data, "STRIP_MIN", strip_min), mock.patch.object(data, "STRIP_WARN", strip_warn):
            make_port(t)
            shutil.copy(FIX / "hellodebug.aarch64", gd(t) / "testgame.aarch64")
            return {(f.rule, f.severity) for f in findings(t)}

    def test_small_savings_are_not_reported(self):
        """berusky2: 4 MB of debug info in gl4es is not worth a rebuild"""
        got = self.rules(5 * 1048576, 20 * 1048576)
        self.assertFalse({r for r in got if r[0] == "bin.debug"}, got)

    def test_note_and_warning_by_size(self):
        self.assertIn(("bin.debug", "INFO"), self.rules(1, 1 << 40))
        self.assertIn(("bin.debug", "WARN"), self.rules(1, 2))


class SoTokens(unittest.TestCase):
    def test_same_names_as_the_regex(self):
        import re
        from pmcheck.rules import so_tokens
        rx = re.compile(rb"[\w.+\-]*\.so(?:\.[\w.]*)?(?![\w.\-])")
        blob = (b"\x00libfoo.so.1\x00xx libbar-2.0.so\x00.so\x00libc++.so.6\x00also.something\x00libz.so.1.2.13 "
                b"libx.so.2.so\x00notaso.sox\x00" + bytes(range(256)) * 50 + b"libend.so")
        self.assertEqual(so_tokens(blob), set(rx.findall(blob)))


class ValidVariants(unittest.TestCase):
    def test_valid_variants_add_nothing(self):
        for name, change in VALID:
            with self.subTest(name), tempfile.TemporaryDirectory() as t:
                t = Path(t) / "testgame"      # ports/<name>/, as in PortMaster-New
                make_port(t)
                change(t)
                pr = name == "PR layout"
                bad = [f"{f.rule} {f.severity} {f.file}:{f.line} {f.message}" for f in findings(t, pr=pr)
                       if f.severity in ("ERROR", "WARN")]
                self.assertEqual(bad, [], name)


if __name__ == "__main__":
    unittest.main()
