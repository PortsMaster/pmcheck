"""Static lists the rules check against. Edit here, not in the rules."""
import re

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
    (re.compile(r"^libSDL3\.so"), "real SDL3 is not shipped; use the sdl3-sdl2-backend shim build if SDL3 is needed"),
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
        r"^libSDL2_image-2\.0\.so", r"^libSDL2_mixer-2\.0\.so", r"^libSDL2_ttf-2\.0\.so",
        r"^libpng16\.so", r"^libz\.so", r"^libfreetype\.so", r"^libexpat\.so", r"^libbz2\.so",
        r"^libstdc\+\+\.so", r"^libgcc_s\.so", r"^libogg\.so", r"^libvorbis(file)?\.so",
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
RUNTIME_ARCH_SUFFIX = re.compile(r"\.(aarch64|armhf|x86_64)(\.squashfs)?$")

# Prebuilt PortMaster tools/loaders: shipping one doesn't mean the porter compiled anything.
PREBUILT_RE = re.compile(r"^(gmloader(next|-next)?|box64|box86|love|frt_[\w.]+|westonwrap|gptokeyb2?|7zzs|xdelta3|innoextract|portmsg|mkxp-z|gamepad-picker)(\.(aarch64|armhf|x86_64))?$", re.I)
META_FILES = {"port.json", "readme.md", "gameinfo.xml", "screenshot.png", "screenshot.jpg", "cover.png", "testing_thread.txt"}
IMAGE_MAX_BYTES = 100 * 1024
PNG_COMPRESSOR = "https://jantrueno.github.io/PortMaster-Wiki/tools/png-compressor/"
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
