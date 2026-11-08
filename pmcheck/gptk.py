"""Classic gptokeyb .gptk checks (names from gptokeyb src/config.cpp, util.cpp char_to_keycode, analog.cpp @ 5b1284e).

The parser reads `fscanf("%s = %s")` token pairs: one token per value, `\\"` matches no key (the
"unbound" idiom), and an empty value makes the parser take the next line's button name as the value.
"""
import re

from .findings import Finding, ERROR, WARN

KEYS = set(
    "up down left right mouse_left mouse_right space esc end home shift leftshift rightshift ctrl leftctrl rightctrl "
    "alt leftalt rightalt backspace enter pageup pagedown insert delete capslock tab pause menu".split()
)
KEYS |= set("abcdefghijklmnopqrstuvwxyz0123456789")
KEYS |= {f"numpad{i}" for i in range(10)} | {"numpad*", "numpad/", "numpad+", "numpad-", "numpad,", "numpad.", "numpadenter"}
KEYS |= {f"f{i}" for i in range(1, 13)}
KEYS |= set("@#€%&*-+()!\"':;/?.,~`|{}$^_=[]\\<>")
EXTRA = {"add_alt", "add_ctrl", "add_shift", "repeat"}
EMPTY = '\\"'

HK = "a b x y l1 l2 r1 r2".split()
BUTTONS = set("back guide start l3 r3 up down left right".split()) | set(HK) | {f"{b}_hk" for b in HK}
STICKS = {f"{s}_analog_{d}" for s in ("left", "right") for d in ("up", "down", "left", "right")}
BUTTONS |= STICKS
MOUSE_MOVE = {f"mouse_movement_{d}" for d in ("up", "down", "left", "right")}
NUMERIC = set("deadzone deadzone_scale deadzone_delay deadzone_y deadzone_x deadzone_triggers dpad_mouse_step "
              "mouse_slow_scale mouse_scale mouse_delay repeat_delay repeat_interval".split())
DEADZONE_MODES = {"axial", "radial", "scaled_radial", "sloped_axial", "sloped_scaled_axial", "hybrid", "default"}


def check_gptk(text, f):
    seen = {}
    lines = text.splitlines()
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            yield Finding("gptk.syntax", WARN, f"Line is not 'button = key': {s[:40]!r}.", file=f, line=n)
            continue
        k, v = (x.strip() for x in s.split("=", 1))
        if not re.fullmatch(r"\S+", k):
            yield Finding("gptk.syntax", WARN, f"Button name {k!r} contains spaces.", file=f, line=n)
            continue
        if not v:
            yield Finding("gptk.empty", WARN, f"{k} has no value; the parser then reads the next line's button name as its key.", file=f, line=n,
                          fix=f"{k} = \\\"")
            continue
        if len(v.split()) > 1:
            yield Finding("gptk.syntax", WARN, f"{k} = {v!r}: only the first word is read.", file=f, line=n)
        v = v.split()[0]
        # `up = up` + `up = repeat` / `add_shift` is the normal way to add a flag, not a duplicate.
        if v not in EXTRA and v != EMPTY:
            if k in seen and k not in NUMERIC:
                yield Finding("gptk.duplicate", WARN, f"{k} is set twice (lines {seen[k]} and {n}); only the last one counts.", file=f, line=n)
            seen[k] = n
        if k == "deadzone_mode":
            if v not in DEADZONE_MODES:
                yield Finding("gptk.value", WARN, f"Unknown deadzone_mode {v!r}.", file=f, line=n)
            continue
        if k in NUMERIC:
            if not re.fullmatch(r"-?\d+", v):
                yield Finding("gptk.value", WARN, f"{k} needs a number, got {v!r}.", file=f, line=n)
            continue
        if k not in BUTTONS:
            if v == EMPTY:
                continue
            alias = {"select": "back", "hotkey": "guide", "mode": "guide"}.get(k)
            yield Finding("gptk.button", WARN, f"Unknown button/option {k!r} (classic gptokeyb ignores it, so {v} is never sent).", file=f, line=n,
                          fix=f"{alias} = {v}" if alias else "")
            continue
        if v == EMPTY or v in EXTRA:
            continue
        if v == "mouse_slow" and k in HK:
            continue
        if v in MOUSE_MOVE and (k in STICKS or k in ("up", "down", "left", "right")):
            continue
        if v.lower() not in KEYS:
            yield Finding("gptk.key", ERROR, f'Unknown key "{v}" for {k} (classic gptokeyb maps it to nothing, the button is dead).', file=f, line=n,
                          fix='Use a name from gptokeyb\'s key table (e.g. enter, esc, leftshift), or \\" for no key.')
