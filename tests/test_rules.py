"""python3 -m unittest discover -s tests   (from the repo root)"""
import io
import json
import os
import shutil
import stat
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

from pmcheck.model import load, LoadError
from pmcheck.rules import run_all
from pmcheck.ini import check_ini
from pmcheck.gptk import check_gptk

FIX = Path(__file__).parent / "fixtures"

GOOD_SH = """#!/bin/bash

XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}

if [ -d "/opt/system/Tools/PortMaster/" ]; then
  controlfolder="/opt/system/Tools/PortMaster"
elif [ -d "/opt/tools/PortMaster/" ]; then
  controlfolder="/opt/tools/PortMaster"
elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then
  controlfolder="$XDG_DATA_HOME/PortMaster"
else
  controlfolder="/roms/ports/PortMaster"
fi

source $controlfolder/control.txt
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"
get_controls

GAMEDIR=/$directory/ports/testgame
cd "$GAMEDIR"
mkdir -p "$GAMEDIR/conf/testgame"
bind_directories ~/.testgame "$GAMEDIR/conf/testgame"

$GPTOKEYB2 "testgame.aarch64" &
pm_platform_helper "$GAMEDIR/testgame.aarch64"
./testgame.aarch64

pm_finish
"""

PORT_JSON = {
    "version": 4, "name": "testgame.zip", "items": ["Test Game.sh", "testgame"], "items_opt": [],
    "attr": {"title": "Test Game", "porter": ["Cebion"], "desc": "A test game.", "desc_md": None,
             "inst": "Ready to run.", "inst_md": None, "genres": ["puzzle"], "image": None, "rtr": True,
             "exp": False, "runtime": [], "store": [], "availability": "full", "reqs": [], "arch": ["aarch64"],
             "min_glibc": "2.34"},
}

GAMEINFO = """<?xml version="1.0" encoding="utf-8"?>
<gameList><game>
<path>./Test Game.sh</path><name>Test Game</name><desc>A test game.</desc>
<releasedate>20260101T000000</releasedate><developer>Someone</developer><publisher>Open Source</publisher>
<genre>Puzzle</genre><image>./testgame/screenshot.png</image>
</game></gameList>
"""

README = "## Notes\n\nThanks.\n\n## Controls\n\n| A | Jump |\n\n## Compile\n\nmake\n"


def png(w, h):
    raw = b"".join(b"\x00" + b"\x00" * (w * 3) for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_port(root, **over):
    root = Path(root)
    gd = root / "testgame"
    (gd / "licenses").mkdir(parents=True)
    (root / "Test Game.sh").write_text(over.get("sh", GOOD_SH))
    shutil.copy(FIX / "hello.aarch64", gd / "testgame.aarch64")
    pj = json.loads(json.dumps(PORT_JSON))
    for k, v in over.get("attr", {}).items():
        pj["attr"][k] = v
    (gd / "port.json").write_text(json.dumps(pj))
    (gd / "gameinfo.xml").write_text(over.get("gameinfo", GAMEINFO))
    (gd / "README.md").write_text(README)
    (gd / "testing_thread.txt").write_text("x")
    (gd / "screenshot.png").write_bytes(png(*over.get("shot", (640, 480))))
    (gd / "cover.png").write_bytes(png(64, 64))
    (gd / "licenses" / "LICENSE.testgame").write_text("MIT")
    for i in range(over.get("extra_files", 0)):
        (gd / "data").mkdir(exist_ok=True)
        (gd / "data" / f"f{i}.dat").write_text("x")
    return root


def rules_of(path, sev=None, pr=False):
    port = load(path, pr=pr)
    try:
        return {f.rule for f in run_all(port) if sev is None or f.severity == sev}
    finally:
        port.cleanup()


class GoodPort(unittest.TestCase):
    def test_clean(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            self.assertEqual(rules_of(t, "ERROR"), set())
            self.assertEqual(rules_of(t, "WARN"), set())


def to_pr_layout(root, names=("port.json", "README.md", "gameinfo.xml", "screenshot.png", "cover.png")):
    for n in names:
        (Path(root) / "testgame" / n).rename(Path(root) / n)


class Layouts(unittest.TestCase):
    def test_zip_accepts_pr_layout(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            to_pr_layout(t)
            self.assertEqual(rules_of(t, "ERROR") | rules_of(t, "WARN"), set())

    def test_zip_accepts_mixed(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            to_pr_layout(t, ("screenshot.png", "README.md"))
            self.assertEqual(rules_of(t, "ERROR") | rules_of(t, "WARN"), set())

    def test_pr_mode_rejects_zip_layout(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            self.assertIn("structure.pr-layout", rules_of(t, pr=True))

    def test_pr_mode_accepts_pr_layout(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "testgame"          # ports/<name>/ in PortMaster-New
            make_port(root)
            to_pr_layout(root)
            self.assertEqual(rules_of(root, "ERROR", pr=True), set())

    def test_pr_name_must_match_folder(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "othername"
            make_port(root)
            to_pr_layout(root)
            self.assertIn("port.json.name", rules_of(root, "ERROR", pr=True))

    def test_zip_stray_top_file(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "notes.txt").write_text("x")
            self.assertIn("structure.top-level", rules_of(t))


class Planted(unittest.TestCase):
    """Errors Ganimoth planted in a darkspasm copy, rebuilt on the test port."""
    def test_script_in_gamedir(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "Test Game.sh").rename(Path(t) / "testgame" / "Test Game.sh")
            got = rules_of(t)
            self.assertIn("structure.script-in-gamedir", got)
            self.assertNotIn("structure.no-gamedir", got)

    def test_image_without_extension(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, gameinfo=GAMEINFO.replace("screenshot.png", "screenshot"))
            self.assertIn("gameinfo.image", rules_of(t, "ERROR"))

    def test_empty_arch_entry(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, attr={"arch": [""]})
            port = load(t)
            try:
                fs = [f for f in run_all(port) if f.rule == "port.json.arch"]
            finally:
                port.cleanup()
            self.assertEqual(len(fs), 1)
            self.assertIn('["aarch64"]', fs[0].fix)

    def test_echo_before_exit(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace("cd \"$GAMEDIR\"\n", 'cd "$GAMEDIR"\nif [ ! -f x ]; then\n  echo "Missing game files."\n  exit 1\nfi\n'))
            self.assertIn("sh.echo-message", rules_of(t))

    def test_empty_licenses(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "licenses" / "LICENSE.testgame").unlink()
            self.assertIn("licenses.empty", rules_of(t))


class Relaxed(unittest.TestCase):
    def test_no_testing_thread_ok(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "testing_thread.txt").unlink()
            self.assertNotIn("files.testing-thread", rules_of(t))

    def test_prebuilt_loader_needs_no_compile(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            gd = Path(t) / "testgame"
            (gd / "testgame.aarch64").rename(gd / "gmloadernext.aarch64")
            (gd / "README.md").write_text(README.split("## Compile")[0])
            self.assertNotIn("readme.section", rules_of(t))

    def test_compiled_binary_needs_compile(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "README.md").write_text(README.split("## Compile")[0])
            self.assertIn("readme.section", rules_of(t))


    def test_readme_rename_hint(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            gd = Path(t) / "testgame"
            (gd / "README.md").rename(gd / "testgame.md")
            port = load(t)
            try:
                f = [f for f in run_all(port) if f.rule == "files.missing"]
            finally:
                port.cleanup()
            self.assertEqual(len(f), 1)
            self.assertIn("Rename testgame/testgame.md to testgame/README.md", f[0].fix)


class HotkeyLicenceLog(unittest.TestCase):
    def test_no_gptokeyb(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace('$GPTOKEYB2 "testgame.aarch64" &\n', ""))
            self.assertIn("sh.no-gptokeyb", rules_of(t, "ERROR"))

    def test_classic_gptokeyb_ok(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace("$GPTOKEYB2", "$GPTOKEYB"))
            self.assertNotIn("sh.no-gptokeyb", rules_of(t))

    def test_rtr_needs_game_licence(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            lic = Path(t) / "testgame" / "licenses"
            (lic / "LICENSE.testgame").rename(lic / "LICENSE.zlib")
            self.assertIn("licenses.game", rules_of(t, "ERROR"))
            (lic / "permission.png").write_bytes(png(10, 10))
            self.assertNotIn("licenses.game", rules_of(t))

    def test_not_rtr_no_game_licence_ok(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, attr={"rtr": False})
            lic = Path(t) / "testgame" / "licenses"
            (lic / "LICENSE.testgame").rename(lic / "LICENSE.zlib")
            self.assertNotIn("licenses.game", rules_of(t))

    def test_old_log_line(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace('cd "$GAMEDIR"\n', 'cd "$GAMEDIR"\nexec > "$GAMEDIR/log.txt" 2>&1\n'))
            self.assertIn("sh.log-old", rules_of(t, "WARN"))
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace('cd "$GAMEDIR"\n', 'cd "$GAMEDIR"\n> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1\n'))
            self.assertNotIn("sh.log-old", rules_of(t))


class OtherIni(unittest.TestCase):
    def test_helper_ini_not_gptokeyb(self):
        with tempfile.TemporaryDirectory() as t:
            sh = GOOD_SH.replace("./testgame.aarch64\n", 'layout="$GAMEDIR/helper.ini"\nHELPER_LAYOUT="$layout" ./testgame.aarch64\n')
            make_port(t, sh=sh)
            (Path(t) / "testgame" / "helper.ini").write_text("[controls]\na = context_click\nkind = wheel\n")
            rules = rules_of(t)
            self.assertFalse({r for r in rules if r.startswith("ini.")}, rules)

    def test_ini_via_variable_checked(self):
        with tempfile.TemporaryDirectory() as t:
            sh = GOOD_SH.replace('$GPTOKEYB2 "testgame.aarch64" &', 'CTRL="$GAMEDIR/testgame.ini"\n$GPTOKEYB2 "testgame.aarch64" -c "$CTRL" &')
            make_port(t, sh=sh)
            (Path(t) / "testgame" / "testgame.ini").write_text("[controls]\na = return\n")
            self.assertIn("ini.key", rules_of(t))


class ScriptNoise(unittest.TestCase):
    def sh_rules(self, extra):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace('cd "$GAMEDIR"\n', 'cd "$GAMEDIR"\n' + extra))
            return rules_of(t)

    def test_echo_progress_and_state_ok(self):
        r = self.sh_rules('echo "Creating swap..."\n$ESUDO zramctl --find || {\n  echo "1" > "$GAMEDIR/state"\n  exit 1\n}\n')
        self.assertNotIn("sh.echo-message", r)

    def test_echo_before_exit_flagged(self):
        r = self.sh_rules('if [ ! -f x ]; then\n  echo "Game files missing"\n  exit 1\nfi\n')
        self.assertIn("sh.echo-message", r)

    def test_bind_quoted_target_with_spaces(self):
        r = self.sh_rules('mkdir -p "$GAMEDIR/savedata"\nbind_directories "$HOME/.local/share/Some Studio/Game" "$GAMEDIR/savedata"\n')
        self.assertNotIn("sh.bind-source", r)

    def test_kill_gptokeyb_obsolete(self):
        self.assertIn("sh.kill-gptokeyb", self.sh_rules('source "$controlfolder/utils/patcher.txt"\n$ESUDO kill -9 $(pidof gptokeyb) 2>/dev/null\n'))

    def test_bind_source_via_variable(self):
        r = self.sh_rules('CONF="$GAMEDIR/conf/"\nmkdir -p "$GAMEDIR/conf"\nbind_directories "$HOME/.thing" "$CONF"\n')
        self.assertNotIn("sh.bind-source", r)

    def test_tty_message(self):
        r = self.sh_rules('if [ ! -f x ]; then\n  printf "\\033c" > $CUR_TTY\n  echo "Missing x" > $CUR_TTY\n  exit 1\nfi\n')
        self.assertIn("sh.tty-message", r)

    def test_sdl_driver_default_is_warn(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace('cd "$GAMEDIR"\n', 'cd "$GAMEDIR"\nexport SDL_AUDIODRIVER=${SDL_AUDIODRIVER:-alsa}\n'))
            self.assertIn("sh.sdl-driver", rules_of(t, "WARN"))
            self.assertNotIn("sh.sdl-driver", rules_of(t, "ERROR"))

    def test_xdg_prefix_on_command_ok(self):
        self.assertNotIn("sh.xdg", self.sh_rules('XDG_DATA_HOME="$GAMEDIR/conf" ./testgame.aarch64 --version\n'))

    def test_gameinfo_image_case(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, gameinfo=GAMEINFO.replace("./testgame/screenshot.png", "./TestGame/screenshot.png"))
            port = load(t)
            try:
                f = [x for x in run_all(port) if x.rule == "gameinfo.image"]
            finally:
                port.cleanup()
            self.assertTrue(f and "wrong case" in f[0].message and "./testgame/screenshot.png" in f[0].fix, f)

    def test_xdg_default_ok(self):
        self.assertNotIn("sh.xdg", self.sh_rules('export XDG_DATA_HOME="$HOME/.local/share"\n'))


class SDL3(unittest.TestCase):
    def test_upstream_sdl3_is_error(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            libs = Path(t) / "testgame" / "libs.aarch64"
            libs.mkdir()
            shutil.copy(FIX / "hello.aarch64", libs / "libSDL3.so.0")
            port = load(t)
            try:
                fs = {(f.rule, f.severity) for f in run_all(port) if f.rule.startswith("libs.")}
            finally:
                port.cleanup()
            self.assertEqual(fs, {("libs.sdl3", "ERROR")})


class PRLink(unittest.TestCase):
    def test_pr_number(self):
        from pmcheck.ghpr import pr_number
        self.assertEqual(pr_number("https://github.com/PortsMaster/PortMaster-New/pull/2853"), 2853)
        self.assertEqual(pr_number("https://github.com/PortsMaster/PortMaster-New/pull/2853/files"), 2853)
        self.assertIsNone(pr_number("https://github.com/someone/PortMaster-New/pull/1"))
        self.assertIsNone(pr_number("http://github.com/PortsMaster/PortMaster-New/pull/1"))
        self.assertIsNone(pr_number("https://github.com.evil.example/PortsMaster/PortMaster-New/pull/1"))


class BadPorts(unittest.TestCase):
    def check(self, rule, **over):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, **over)
            self.assertIn(rule, rules_of(t))

    def test_min_glibc(self):
        self.check("port.json.min_glibc", attr={"min_glibc": ""})

    def test_porter(self):
        self.check("port.json.porter", attr={"porter": ["A, B"]})

    def test_genre(self):
        self.check("port.json.genres", attr={"genres": ["platform"]})

    def test_runtime_label(self):
        self.check("port.json.runtime", attr={"runtime": ["Westonpack 0.2"]})

    def test_screenshot_size(self):
        self.check("images.screenshot-size", shot=(320, 240))

    def test_gameinfo_image(self):
        self.check("gameinfo.image", gameinfo=GAMEINFO.replace("./testgame/screenshot.png", "./screenshot.png"))

    def test_gameinfo_cover_ok(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, gameinfo=GAMEINFO.replace("screenshot.png", "cover.png"))
            self.assertNotIn("gameinfo.image", rules_of(t))

    def test_gameinfo_cover_missing(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, gameinfo=GAMEINFO.replace("screenshot.png", "cover.png"))
            (Path(t) / "testgame" / "cover.png").unlink()
            self.assertIn("gameinfo.image", rules_of(t, "ERROR"))

    def test_no_cover_ok(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "cover.png").unlink()
            self.assertEqual(rules_of(t, "WARN"), set())

    def test_cover_location(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "cover.png").rename(Path(t) / "testgame" / "licenses" / "cover.png")
            self.assertIn("files.cover-location", rules_of(t))

    def test_too_many_files(self):
        self.check("structure.too-many-files", extra_files=120)

    def test_sdl_driver(self):
        self.check("sh.sdl-driver", sh=GOOD_SH.replace("get_controls\n", "get_controls\nexport SDL_VIDEODRIVER=kmsdrm\n"))

    def test_above_header(self):
        self.check("sh.boilerplate", sh=GOOD_SH.replace("\nXDG_DATA_HOME", "\nFOO=1\nXDG_DATA_HOME", 1))

    def test_crlf(self):
        self.check("sh.crlf", sh=GOOD_SH.replace("\n", "\r\n"))

    def test_tar_z(self):
        self.check("sh.tar-z", sh=GOOD_SH.replace("pm_finish", 'tar -xzf "data.tar.gz"\npm_finish'))

    def test_bind_source(self):
        self.check("sh.bind-source", sh=GOOD_SH.replace('mkdir -p "$GAMEDIR/conf/testgame"\n', ""))

    def test_pm_message_order(self):
        self.check("sh.pm_message-order", sh=GOOD_SH.replace("pm_finish", 'pm_message --title "x" "Hello"\npm_finish'))

    def test_home(self):
        self.check("sh.home", sh=GOOD_SH.replace("cd \"$GAMEDIR\"", 'cd "$GAMEDIR"\nexport HOME="$GAMEDIR"'))

    def test_banned_sdl(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            libs = Path(t) / "testgame" / "libs.aarch64"
            libs.mkdir()
            # any aarch64 ELF named like SDL2 is enough for the name rule; give it a .so name and DYN type via the PIE fixture
            shutil.copy(FIX / "hello.aarch64", libs / "libSDL2-2.0.so.0")
            self.assertIn("libs.banned", rules_of(t))

    def test_image_too_big(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "cover.png").write_bytes(png(64, 64) + os.urandom(120 * 1024))
            self.assertIn("images.size", rules_of(t))


class Ini(unittest.TestCase):
    def test_bad_key(self):
        rules = {f.rule for f in check_ini('[controls]\ny = "lshift"\n', "x.ini")}
        self.assertIn("ini.key", rules)

    def test_stick_deadzone(self):
        rules = {f.rule for f in check_ini('[controls]\nleft_analog_up = "up"\n', "x.ini")}
        self.assertIn("ini.deadzone", rules)

    def test_empty_key(self):
        self.assertEqual([f.rule for f in check_ini('[controls]\nup = \\"\n', "x.ini")], [])

    def test_duplicate_button(self):
        rules = {f.rule for f in check_ini('[controls:hotkey]\nr1 = a\nr1 = pop_state\n', "x.ini")}
        self.assertIn("ini.duplicate", rules)

    def test_same_button_other_section_ok(self):
        rules = {f.rule for f in check_ini('[controls]\nr1 = a\n[controls:hotkey]\nr1 = b\n', "x.ini")}
        self.assertNotIn("ini.duplicate", rules)

    def test_good(self):
        txt = '[config]\ndeadzone_x = 10000\ndeadzone_y = 10000\n[controls]\na = "space"\nleft_analog_up = "up"\n'
        self.assertEqual([f.rule for f in check_ini(txt, "x.ini")], [])


class Gptk(unittest.TestCase):
    def rules(self, txt):
        return [f.rule for f in check_gptk(txt, "x.gptk")]

    def test_good(self):
        txt = 'back = esc\nstart = enter\na = \\"\nb = space\nup = up\nup = repeat\nleft_analog_up = mouse_movement_up\nx = mouse_slow\ndeadzone_mode = scaled_radial\ndeadzone = 2000\n'
        self.assertEqual(self.rules(txt), [])

    def test_empty_value(self):
        self.assertIn("gptk.empty", self.rules("a = \nb = space\n"))

    def test_bad_key(self):
        self.assertIn("gptk.key", self.rules("a = return\n"))

    def test_select_is_back(self):
        fs = list(check_gptk("select = esc\n", "x.gptk"))
        self.assertEqual(fs[0].rule, "gptk.button")
        self.assertEqual(fs[0].fix, "back = esc")

    def test_classic_script_ok(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t, sh=GOOD_SH.replace('$GPTOKEYB2 "testgame.aarch64" &', '$GPTOKEYB "testgame.aarch64" -c "./testgame.gptk" &'))
            (Path(t) / "testgame" / "testgame.gptk").write_text("back = esc\nstart = enter\n")
            self.assertEqual(rules_of(t, "ERROR") | rules_of(t, "WARN"), set())

    def test_sections_mean_gptokeyb2(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            (Path(t) / "testgame" / "testgame.gptk").write_text('[controls]\ny = "lshift"\n')
            got = rules_of(t)
            self.assertIn("ini.key", got)
            self.assertFalse(any(r.startswith("gptk.") for r in got))


class ZipSafety(unittest.TestCase):
    def zip_with(self, name, data=b"x", symlink=False):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            zi = zipfile.ZipInfo(name)
            if symlink:
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, data)
        f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        f.write(buf.getvalue())
        f.close()
        return f.name

    def test_traversal(self):
        p = self.zip_with("../evil.sh")
        with self.assertRaises(LoadError):
            load(p)
        os.unlink(p)

    def test_absolute(self):
        p = self.zip_with("/etc/evil")
        with self.assertRaises(LoadError):
            load(p)
        os.unlink(p)

    def test_symlink_not_extracted(self):
        p = self.zip_with("game/link", b"/etc/passwd", symlink=True)
        port = load(p)
        try:
            self.assertFalse((port.root / "game" / "link").exists())
            self.assertTrue(port.symlinks)
        finally:
            port.cleanup()
            os.unlink(p)

    def test_zip_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            make_port(t)
            zp = Path(t).parent / (Path(t).name + ".zip")
            with zipfile.ZipFile(zp, "w") as z:
                for f in Path(t).rglob("*"):
                    z.write(f, f.relative_to(t))
            try:
                self.assertEqual(rules_of(zp, "ERROR"), set())
            finally:
                zp.unlink()


@unittest.skipUnless(os.environ.get("PMCHECK_MCRUST"), "set PMCHECK_MCRUST=/path/to/mcrust.zip")
class Mcrust(unittest.TestCase):
    def test_review_findings(self):
        got = rules_of(os.environ["PMCHECK_MCRUST"])
        for r in ("port.json.min_glibc", "port.json.porter", "images.size",
                  "structure.too-many-files", "runtime.bundled", "licenses.component", "sh.xdg"):
            self.assertIn(r, got)


if __name__ == "__main__":
    unittest.main()
