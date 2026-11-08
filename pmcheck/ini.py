"""gptokeyb2 .ini checks (key names from gptokeyb2 src/keys.c, see g2keys.json)."""
import json
import re
from pathlib import Path

from .findings import Finding, ERROR, WARN, INFO

_K = json.loads((Path(__file__).parent / "g2keys.json").read_text())
KEYS = set(_K["keys"])
KEYS_CI = {k.lower() for k in KEYS}
BUTTONS = set(_K["buttons"])
SPECIAL = set(
    "add_alt add_ctrl add_shift add_letter alt ctrl shift arrow_keys cancel_text clear finish_text hold_state "
    "lower_case upper_case toggle_case mouse_absolute mouse_movement mouse_slow mouse_left mouse_right mouse_middle "
    "mouse_wheel_up mouse_wheel_down next_letter next_word prev_letter prev_word parent pop_state push_state "
    "remove_letter repeat set_state".split()
)
STICK_KEYS = re.compile(r"^(left|right)_analog(_(up|down|left|right))?$")
STATE_DIRECTIVES = {"overlay", "charset", "wordset", "mouse_wheel_amount"}
MOUSE_CONFIG = {"deadzone_mode", "deadzone_scale", "deadzone_x", "deadzone_y"}


def check_ini(text, f, scripts=""):
    sect = None
    config = {}
    stick_keys = mouse = False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s[0] in "#;":
            continue
        if s.startswith("["):
            sect = s.lower()
            continue
        if "=" not in s or sect is None:
            continue
        s = re.sub(r"\s+#.*$", "", s)
        k, v = (x.strip() for x in s.split("=", 1))
        k = k.lower()
        if sect.startswith("[config"):
            config[k] = v
            continue
        if k in STATE_DIRECTIVES:
            continue
        if not v:
            continue
        if k not in BUTTONS:
            yield Finding("ini.button", WARN, f"Unknown button {k!r}.", file=f, line=n)
            continue
        toks = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', v)
        prev = None
        for q, w in toks:
            t = q or w
            if not t:
                continue
            if prev in ("push_state", "set_state", "hold_state"):
                prev = t
                continue
            ok = t in KEYS or t.lower() in KEYS_CI or (not q and t in SPECIAL)
            if not ok:
                yield Finding("ini.key", ERROR, f'Unknown key "{t}" for {k} (gptokeyb2 ignores it, the button is dead).', file=f, line=n,
                              fix="Use a name from the gptokeyb2 key table (e.g. leftshift, enter, esc).")
            prev = t
        if STICK_KEYS.match(k):
            if "mouse_movement" in v:
                mouse = True
            else:
                stick_keys = True
    if mouse:
        missing = sorted(MOUSE_CONFIG - set(config))
        if missing:
            yield Finding("ini.mouse-config", WARN, "Stick mouse without the standard [config] block (missing " + ", ".join(missing) + "); the cursor drifts.",
                          file=f, snippet="[config]\nmouse_delay = 16\ndeadzone_mode = scaled_radial\ndeadzone_scale = 6\ndeadzone_x = 2000\ndeadzone_y = 2000")
        if "DISPLAY_WIDTH" not in scripts or "deadzone_scale" not in scripts:
            yield Finding("ini.mouse-hires", INFO, "No high-res mouse-speed bump in the launch script (sed deadzone_scale when DISPLAY_WIDTH > 1280).", file=f)
    if stick_keys and not ({"deadzone_x", "deadzone_y"} <= set(config)):
        yield Finding("ini.deadzone", WARN, "A stick sends keys but [config] has no deadzone_x/deadzone_y; a resting stick holds arrow keys.", file=f,
                      snippet="[config]\ndeadzone_x = 10000\ndeadzone_y = 10000")
