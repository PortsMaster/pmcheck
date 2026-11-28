"""Static lists the rules check against. Edit here, not in the rules."""
import json
import os
import re
import tempfile
import time
import urllib.request
from pathlib import Path

# harbourmaster config.py HM_GENRES
GENRES = {
    "action", "adventure", "arcade", "casino/card", "fps", "platformer", "puzzle",
    "racing", "rhythm", "rpg", "simulation", "sports", "strategy", "visual novel", "other",
}

GAMEINFO_TAGS = {"path", "name", "desc", "releasedate", "developer", "publisher", "genre", "image"}

PORT_JSON_ATTRS = {
    "title", "porter", "desc", "desc_md", "inst", "inst_md", "genres", "image", "rtr", "exp",
    "runtime", "store", "availability", "reqs", "arch", "min_glibc",
}

ARCHES = {"aarch64", "armhf", "x86_64", "x86"}

# ELF e_machine names from readelf -h -> port.json arch key
ELF_MACHINE_ARCH = {
    "AArch64": "aarch64",
    "ARM": "armhf",
    "Advanced Micro Devices X86-64": "x86_64",
    "Intel 80386": "x86",
}

# Libraries a port must never bundle: the CFW ships a device-specific build.
BANNED_LIBS = [
    (re.compile(r"^libSDL2(-2\.0)?\.so"), "SDL2 comes from the CFW (device-patched KMS/DRM, input, audio)"),
    (re.compile(r"^libGLESv1_CM\.so|^libGLESv2\.so|^libmali"), "GPU driver library, always from the CFW"),
    (re.compile(r"^libdrm\.so|^libgbm\.so"), "display stack library, always from the CFW"),
    (re.compile(r"^libwayland-(client|egl|cursor|server)\.so"), "compositor-adjacent library, always from the CFW"),
    (re.compile(r"^libc\.so|^ld-linux|^libm\.so|^libpthread\.so|^libdl\.so|^librt\.so"), "glibc itself must never be bundled"),
    (re.compile(r"^libasound\.so"), "ALSA comes from the CFW"),
    (re.compile(r"^libudev\.so"), "udev comes from the CFW"),
]
# libGL/libEGL are only allowed inside a gl4es.<arch>/ folder.
GL_LIBS = re.compile(r"^lib(GL|EGL)\.so")

# Near-universal on CFW base images: bundling only bloats the port.
COMMON_LIBS = [
    re.compile(p) for p in (
        # the packaging rules' list; libstdc++/libgcc_s can legitimately be newer than the CFW's (GLIBCXX)
        r"^libSDL2_image-2\.0\.so", r"^libSDL2_mixer-2\.0\.so",
        r"^libpng16\.so", r"^libz\.so", r"^libfreetype\.so", r"^libexpat\.so", r"^libbz2\.so",
    )
]

# NEEDED entries a port can expect the CFW to provide.
CFW_PROVIDED = [
    re.compile(p) for p in (
        r"^libc\.so", r"^libm\.so", r"^libdl\.so", r"^libpthread\.so", r"^librt\.so", r"^ld-linux",
        r"^libgcc_s\.so", r"^libstdc\+\+\.so", r"^libSDL2-2\.0\.so", r"^libSDL2_(image|mixer|ttf)-2\.0\.so",
        r"^libGL\.so", r"^libEGL\.so", r"^libGLES", r"^libdrm\.so", r"^libgbm\.so", r"^libasound\.so",
        r"^libudev\.so", r"^libz\.so", r"^libpng16\.so", r"^libfreetype\.so", r"^libexpat\.so",
        r"^libbz2\.so", r"^libogg\.so", r"^libvorbis", r"^libopenal\.so", r"^libpulse", r"^libcrypt\.so",
        r"^liblzma\.so", r"^libutil\.so", r"^libresolv\.so", r"^libatomic\.so", r"^libSDL-1\.2\.so",
        r"^libX11\.so", r"^libwayland-",
    )
]

# Runtime squashfs keys. Display labels ("Westonpack 0.2") are wrong in port.json.
RUNTIME_KEY = re.compile(
    r"\b((?:weston_pkg|mesa_pkg|frt|mono|python|renpy|zulu|jdk|jre|java|pyxel|solarus|godot|dotnet|rlvm)"
    r"[\w.\-]*?)(?:\.squashfs)?\b"
)
# Runtime catalog snapshot from PortMaster-New's ports.json; refresh with tools/update_runtimes.py
RUNTIMES = json.loads((Path(__file__).parent / "runtimes.json").read_text())

# Prebuilt PortMaster tools/loaders: shipping one doesn't mean the porter compiled anything.
PREBUILT_RE = re.compile(r"^(gmloader(next|-next)?|box64|box86|love|frt_[\w.]+|westonwrap|gptokeyb2?|7zzs|xdelta3|innoextract|portmsg|mkxp-z|gamepad-picker)(\.(aarch64|armhf|x86_64))?$", re.I)
META_FILES = {"port.json", "readme.md", "gameinfo.xml", "screenshot.png", "screenshot.jpg", "cover.png", "testing_thread.txt"}
IMAGE_MAX_BYTES = 100 * 1024
PACKAGING_GUIDE = "https://portmaster.games/contribute/porting/packaging/"
SCRIPT_TEMPLATES = "https://portmaster.games/contribute/porting/script-templates/"
FIRST_PORT_GUIDE = "https://portmaster.games/contribute/porting/your-first-port/"
DISCORD_FIRST_PORT = "https://discord.com/channels/1122861252088172575/1232622554984878120"
PNG_COMPRESSOR = "https://portmaster.games/tools/png-compressor/"
COVER_GENERATOR = "https://portmaster.games/tools/cover-generator/"
LOOSE_FILE_LIMIT = 100
PART_RE_SPLIT = re.compile(r"\.part\.\d+$")
GIT_FILE_LIMIT = 100 * 1024 * 1024

TAR_SNIPPET = '''\
# create (on the build machine)
tar czf gamedata.tar.gz --owner=0 --group=0 --numeric-owner {folders}

# launch script
ARCHIVE_FILE="gamedata.tar.gz"
if [[ -f "$ARCHIVE_FILE" ]]; then
    pm_message "Extracting game data, this can take a few minutes..." --title "Please wait"
    if ! gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -; then
        pm_show_error "Could not extract $ARCHIVE_FILE. Check that there is enough free space, then launch again." --title "Extraction failed"
        exit 1
    fi
    $ESUDO rm -f "$ARCHIVE_FILE"
elif [ ! -f '{guard}' ]; then
    pm_show_error "No game data found and $ARCHIVE_FILE is missing. Reinstall the port." --title "Game data missing"
    exit 1
fi'''

# min_glibc only matters from this version up (the old baseline was Ubuntu 20.04, glibc 2.31)
GLIBC_BASELINE = "2.30"

# Variables PortMaster's control.txt / device_info.txt / funcs.txt / libgl_*.txt set (PortMaster-GUI), plus the
# usual system ones. A ${NAME:-...} read of anything else that the script never sets is an outside override knob.
PM_ENV = set("""ANALOGSTICKS ANALOG_STICKS ANALOG_TRIGGERS ASPECT_X ASPECT_Y CFW_GLIBC CFW_NAME CFW_VERSION CONTROL_DIR
CUR_TTY DEVICE DEVICE_ARCH DEVICE_CAPABILITIES DEVICE_CPU DEVICE_HAS_AARCH64 DEVICE_HAS_ARMHF DEVICE_HAS_RUMBLE
DEVICE_HAS_SWAP DEVICE_HAS_X86 DEVICE_HAS_X86_64 DEVICE_HAS_ZRAM DEVICE_INFO_VERSION DEVICE_KERNEL_VERSION DEVICE_NAME
DEVICE_RAM DEVICE_RAM_MB DEVICE_REFRESH_RATE DEVICE_TOUCH DISPLAY_HEIGHT DISPLAY_ORIENTATION DISPLAY_WIDTH ESUDO
ESUDOKILL ESUDOKILL2 GPTOKEYB GPTOKEYB2 GPU_DRIVER GPU_DRIVER_VERSION HAS_DESKTOP_GL HAS_DRI_DRIVERS HOTKEY LOWRES
PM_CAN_MOUNT PM_FUNCS_VERSION PM_PORTNAME PM_RESOURCE_DIR PM_SCRIPTNAME PM_VERSION PORT_32BIT TASKSET
HOME PATH LD_LIBRARY_PATH LD_PRELOAD USER PWD OLDPWD TERM SHELL LANG DISPLAY WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS
BASH_SOURCE BASH_VERSION EUID UID HOSTNAME TMPDIR SWAYSOCK I3SOCK""".split())
PM_ENV_PREFIX = ("SDL_", "LIBGL_", "XDG_", "MESA_", "MONO_", "DOTNET_", "PULSE_", "PIPEWIRE_", "ALSA_", "LC_", "QT_", "GALLIUM_", "BOX64_", "BOX86_", "GMLOADER_", "PATCHER_", "WESTON", "WRAPPED_")

# Normalized launch-script lines found in >= min_scripts merged PortMaster-New scripts (tools/build_script_lines.py)
SCRIPT_LINES = json.loads((Path(__file__).parent / "script_lines.json").read_text())

# What merged ports ship besides the launch script: shared helper hashes, own-code size, patchscript size (tools/build_port_files.py)
PORT_FILES = json.loads((Path(__file__).parent / "port_files.json").read_text())

# Builds of the shared runtime loaders (gmloadernext.aarch64 ...) merged ports ship, by git blob id (tools/build_known_binaries.py)
KNOWN_BINARIES = json.loads((Path(__file__).parent / "known_binaries.json").read_text())["binaries"]

# a game's own content formats; a port shipping them is usually redistributing edited game data
GAME_CONTENT_EXT = {".xnb", ".xwb", ".xsb", ".xgs"}

MARKDOWN_GENERATOR = "https://portmaster.games/tools/markdown-generator/"

# library name stem -> the project name its licence file is usually named after
LIB_LICENCE_ALIASES = {"bz2": "bzip2", "crypto": "openssl", "ssl": "openssl", "lzma": "xz", "z": "zlib"}

# ---------------------------------------------------------------- sh.reinvented
# Launch scripts that redo what PortMaster's own files already do (usually an AI assistant without PortMaster's
# conventions). Calibrated on the 1536 merged scripts (2026-11-21): code lines median 38, p99 118; functions p99 1.
SCRIPT_MEDIAN = 38
SCRIPT_P95 = 77
TEMPLATE_DIFF_MIN = 6   # sh.template-diff: merged ports have a median of 0 such lines, p90 5, p95 8
SCRIPT_P99 = 118
REINVENT_WARN = 7       # merged ports: only Moonlight (a streaming client) reaches 7
REINVENT_ERROR = 10     # no merged port reaches 10
FIRST_PORT_CHANNEL = "https://discord.com/channels/1122861252088172575/1232622554984878120"
# (key, regex over code lines, hits needed, what the block does, what PortMaster already provides)
REINVENT_SIGNALS = [
    ("cfw-detect", r"/etc/os-release|\.config/\.OS\b|plymouth|/proc/device-tree/model|/boot/[\w./-]*\.dtb", 2,
     "works out the CFW from os-release, plymouth or device files", "$CFW_NAME is already set by device_info.txt"),
    ("arch-detect", r"\buname\s+-m\b|ld-linux-aarch64\.so|ld-linux-armhf\.so\.3", 1,
     "works out the CPU architecture itself", "$DEVICE_ARCH and $DEVICE_HAS_ARMHF are already set by device_info.txt"),
    ("ldd-check", r"(^|[\s;|(])ldd(32|_32)?\s|\s--list\s", 1,
     "checks the game's libraries with ldd", "nothing is needed: a missing library already shows up in log.txt"),
    ("cpu-probe", r"/proc/cpuinfo", 1,
     "reads /proc/cpuinfo to pick settings", "$DEVICE_CPU and $DEVICE_RAM are already set by device_info.txt"),
    ("fb0-write", r"of=/dev/fb\d|>\s*/dev/fb\d", 1,
     "writes to the framebuffer directly", "SDL2 draws the screen and pm_finish hands it back to the frontend"),
    ("shell-reexec", r"BASH_VERSION|exec\s+bash\b", 1,
     "restarts itself under bash", "PortMaster always starts launch scripts with bash (#!/bin/bash)"),
    ("signal-traps", r"^\s*trap\b.*\b(INT|TERM|HUP)\b", 1,
     "sets its own signal traps", "pm_finish cleans up, and funcs.txt already sets the exit trap"),
    ("resource-pm", r"(source|\.)\s+\"?\$\{?controlfolder\}?/funcs\.txt|unset\s+PM_FUNCS_VERSION", 1,
     "loads funcs.txt again", "control.txt already loads funcs.txt once"),
    ("controlfolder-extra", r"controlfolder=\"?/(PortMaster|mnt/|storage/|var/|roms2?/tools)|PortMaster\"\s+\"/", 1,
     "searches more places for PortMaster", "the template's four-path controlfolder block finds it on every CFW"),
    ("sysctl-write", r"(tee|>)\s*/proc/sys/|sysctl\s+-w", 1,
     "changes kernel settings", "ports leave kernel settings to the CFW"),
    ("esudo-env", r"\$\{?ESUDO\}?\s+env\s", 1,
     "runs the game as root through $ESUDO env", "the game runs as the normal user; $ESUDO is only for mount and chmod"),
    ("pm-guards", r'\[\s*-f\s+"?\$\{?controlfolder\}?/control\.txt"?\s*\]|command\s+-v\s+pm_\w+|\[\s*-n\s+"?\$\{?GPTOKEYB2?\}?"?\s*\]', 1,
     "treats PortMaster as optional (checks for control.txt, $GPTOKEYB or the pm_* helpers)",
     "launch scripts only run under PortMaster, which always provides control.txt, $GPTOKEYB2 and the pm_* helpers"),
    ("gamedir-search", r"(?:^|\bthen\b|\belse\b|;)\s*(export\s+)?GAMEDIR=", 3,
     "searches several places for its own game folder", "GAMEDIR=/$directory/ports/<folder>: control.txt sets $directory on every CFW"),
    ("system-libpath", r'LD_LIBRARY_PATH=(?:[^\n]*?/(?:usr/|opt/[\w-]+/(?:extra/)?)?lib(?:32|64)?(?:/[\w-]+)?(?=[:"\s]|$)){4}', 1,
     "puts the system's library folders on LD_LIBRARY_PATH", "the system folders are searched anyway; list only the port's own libs folder"),
    ("script-dir", r'readlink\s+-f\s+"?\$0|dirname\s+"?\$0|BASH_SOURCE', 1,
     "works out where the script itself lives", "$GAMEDIR (from $directory) already points at the port folder"),
]
# existing findings that are themselves PortMaster work done again
REINVENT_RULES = {
    "sh.boilerplate", "sh.env-knobs", "sh.libgl-manual", "sh.gpu-probe", "sh.has-armhf", "sh.device-info", "sh.uinput",
    "sh.controlfolder", "sh.mod", "sh.get_controls", "sh.pm_finish", "sh.swap", "sh.home", "sh.sdl-driver", "sh.trap-exit",
    "sh.setup-helper", "files.duplicate-script", "sh.no-gptokeyb", "sh.kill-gptokeyb", "sh.tty-message",
}

# bin.debug: strip only pays off for real savings
STRIP_MIN = 5 * 1048576     # below this, no finding
STRIP_WARN = 20 * 1048576   # from here a warning, between the two a note


RUNTIME_CATALOG_URL = "https://github.com/PortsMaster/PortMaster-New/releases/latest/download/ports.json"


def runtime_in_live_catalog(squashfs):
    """Is this runtime in the catalog harbourmaster reads right now? The bundled runtimes.json is a snapshot and a runtime
    published after it was taken is not in it. True/False, or None when the catalog cannot be fetched (offline, PMCHECK_OFFLINE=1).
    The runtime names are cached for six hours in the temp folder."""
    if os.environ.get("PMCHECK_OFFLINE"):
        return None
    cache = Path(tempfile.gettempdir()) / "pmcheck-runtime-catalog.json"
    try:
        if not cache.exists() or time.time() - cache.stat().st_mtime > 6 * 3600:
            raw = urllib.request.urlopen(RUNTIME_CATALOG_URL, timeout=15).read()
            names = sorted(k for k, a in json.loads(raw)["utils"].items() if k.endswith(".squashfs") and (a.get("runtime_name") or k) == k)
            cache.write_text(json.dumps(names))
        return squashfs in json.loads(cache.read_text())
    except (OSError, ValueError, KeyError):
        return None
