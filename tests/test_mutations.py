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
    ("ini stick without deadzone", lambda r: ini(r, "[controls]\nleft_analog_up = up\n"), "ini.deadzone", "INFO"),
    ("ini not passed", lambda r: ini(r, "[controls]\na = space\n", pass_c=False), "ini.unused", "WARN"),
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
]

# (name, change): valid ways of writing a port; must add no ERROR or WARN
VALID = [
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
