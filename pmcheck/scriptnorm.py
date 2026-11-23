"""Normalize launch-script lines so the same template line matches across ports (used by sh.nonstandard).

A line is "standard" when its normalized form appears in enough merged PortMaster-New scripts
(script_lines.json, built by tools/build_script_lines.py) or in the documented templates below.
Only lines that reach outside the port count: system paths (/proc, /sys, /etc, /usr/lib ...), $HOME,
driver/audio environment variables, system tools, CFW-name branching. A port reading its own config,
setting its own variables and building its launch arguments is game-specific, not unusual logic.
"""
import re

from . import data

KNOWN = data.PM_ENV | {"GAMEDIR", "controlfolder", "directory", "sdl_controllerconfig", "CONFDIR", "BINARY"}

# Documented template lines that are newer than most merged ports (CLAUDE.md / docs), normalized form.
TEMPLATE = {
    "if [[ :$LD_LIBRARY_PATH: == *:P:* ]]; then",
    "export SDL_VIDEO_GL_DRIVER=P",
    "export SDL_VIDEO_EGL_DRIVER=P",
    "if ! gunzip -c $V | tar --no-same-owner -xf -; then",
    "> P && exec > >(tee P) N>&N",
    ": > P && exec > >(tee P) N>&N",
}


def _var(m):
    v = m.group(1) or m.group(2)
    if v in KNOWN or v.startswith(data.PM_ENV_PREFIX) or v.isdigit():
        return m.group(0)
    return "$V"


def norm(line, port):
    """Normalized form of one line, or None for blank lines and comments."""
    l = line.strip()
    if not l or l.startswith("#"):
        return None
    l = re.sub(r"\s+#.*$", "", l)
    l = l.replace('"', "").replace("'", "")
    l = re.sub(r"^export\s+GAMEDIR=", "GAMEDIR=", l)
    l = re.sub(r"^(pm_message|pm_show_error|echo|printf)\b.*", r"\1 S", l)
    l = re.sub(r"^(export\s+)?(PATCHER_GAME|PATCHER_TIME)=.*", r"\1\2=S", l)
    if port:
        l = re.sub(re.escape(port), "PORT", l, flags=re.I)
    l = re.sub(r"\$\{(\w+)[^}]*\}|\$(\w+)", _var, l)
    l = re.sub(r"^(export\s+|local\s+)?([A-Za-z_]\w*)=",
               lambda m: (m.group(1) or "") + (m.group(2) if m.group(2) in KNOWN or m.group(2).startswith(data.PM_ENV_PREFIX) else "V") + "=", l)
    l = re.sub(r"[^\s=:;|&<>()\[\]]*/[^\s=:;|&<>()\[\]]*", "P", l)
    l = re.sub(r"\b\d+(\.\d+)*\b", "N", l)
    l = re.sub(r"\s+", " ", l)
    if re.match(r"(\$ESUDO )?(chmod|mkdir|rm|touch)\b", l):   # the same command over two files or folders is the template's line
        l = re.sub(r"( \S+)\1\b", r"\1", l)
    return l


def exempt(k, raw=""):
    """Game-specific lines every port has in its own form: plain assignments, launches, block ends, control flow, tests of the port's own files.
    raw lets a line that reaches into the system (a CFW check, /etc, /sys ...) stay visible."""
    if re.fullmatch(r"(export\s+)?V=[^$`|;&]*", k) or re.fullmatch(r"(export\s+)?V=(P|\$V|\$GAMEDIR\S*)", k):
        return True
    if re.fullmatch(r"(export\s+)?(GAMEDIR|CONFDIR|BINARY)=[^$`|;&]*", k):   # BINARY=dhewmN: the game's own name
        return True
    if re.fullmatch(r"V=\$\(P( [^()]*)?\)", k):   # GAME=$(./launcher "$GAMEDIR"): the port's own helper program
        return True
    if re.match(r"(\$TASKSET\s+)?(\./|\$GAMEDIR/|P\b|\$V\b|\$BINARY|mono\b|java\b|box64\b|box86\b|\$GPTOKEYB2?\b|pm_platform_helper\b)", k):
        return True
    if re.fullmatch(r"fi|else|done|esac|;;|\}|then|do|continue|break|while (true|:); do|exit( \S+)?|return( \S+)?", k):
        return True
    if re.fullmatch(r"cd \S+ \|\| (exit|return)( \S+)?", k):   # sh.cd-exit reports this one
        return True
    if re.search(r"\bumount\s+\"?\$\{?\w*_dir\b", raw):   # unmounting the runtime the script mounted itself
        return True
    if re.match(r"(\$ESUDO )?(env )?P (headless|cleanup)\b", k):   # the Westonpack call; templates.pick() already chose the mode's template
        return True
    if re.fullmatch(r"for \w+ in [^;]*; do", k) and "$(" not in k and not SYSTEM.search(raw or k):
        return True   # a loop over the port's own files or variables
    if re.fullmatch(r"(elif|if) (\[\[?|!) .*; then", k) and "$(" not in k and not SYSTEM.search(raw or k):
        return True   # a test of the port's own files and variables; the commands inside are checked on their own lines
    return False


SYSTEM = re.compile(r"""(?x)
   (?<![\w$}/])/(proc|sys|dev(?!/null\b)|etc|usr|lib|lib32|lib64|tmp|var|run|bin|sbin|mnt|media)(/|\b)
 | \$HOME\b | \$\{HOME\} | (^|\s)~/
 | \b(export|unset)\b[^#]*\b(LIBGL_|SDL_(VIDEO|AUDIO|RENDER|HINT)|LD_PRELOAD|ALSA_|PULSE_|MESA_|GALLIUM_|PIPEWIRE_)\w*
 | ^\s*(LIBGL_|SDL_(VIDEO|AUDIO|RENDER)|ALSA_|PULSE_|MESA_|GALLIUM_)\w*=
 | \b(systemctl|modprobe|insmod|sysctl|swapon|swapoff|amixer|alsactl|nmcli|killall|pkill|setenforce)\b
 | \bmount\b(?!.*squashfs) | \bumount\b(?!\s+\"?\$\{?\w*_dir\b)
 | \b(CFW_NAME|DEVICE_NAME|DEVICE_CPU)\b | os-release
""")


# Documented patterns that reach outside the port on purpose: PortMaster's bind helpers (target under $HOME),
# the sdl3-sdl2-backend driver forwarding, and an LD_PRELOAD prefix on the launch line (OmniOSK).
DOCUMENTED = re.compile(r"^\s*(bind_(directories|files)\b|pm_(gptokeyb_finish|finish|platform_helper|message_close)\b|(export\s+)?SDL3SHIM_\w+=|SDL_(VIDEO|AUDIO)DRIVER=\S*GAME_SDL_\w*DRIVER|LD_PRELOAD=\S+\s+\S)")


def counted(k, raw, common):
    """Does this line count as non-standard logic: rare, not template, not game-specific, and reaching outside the port?"""
    return (k not in common and k not in TEMPLATE and not exempt(k, raw) and not DOCUMENTED.match(raw)
            and bool(SYSTEM.search(raw)))


def lines(text):
    """[(line number, normalized, raw)] for the code lines of a script; argument continuations and heredoc bodies are skipped."""
    m = re.search(r"GAMEDIR=.*?/ports/([\w.\-]+)", text)
    port = m.group(1) if m else None
    out, cont, heredoc = [], False, None
    for n, raw in enumerate(text.splitlines(), 1):
        if heredoc:                                    # heredoc body is data, not logic
            if raw.strip() == heredoc:
                heredoc = None
            continue
        k = None if cont else norm(raw, port)
        cont = raw.rstrip().endswith("\\")
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", raw)
        if m and not raw.lstrip().startswith("#"):
            heredoc = m.group(1)
        if k:
            out.append((n, k, raw))
    return out
