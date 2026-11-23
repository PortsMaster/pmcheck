"""Example launch scripts per kind of port and the lines of a port's script that none of them has (sh.template-diff).

The examples are the PortMaster website's script templates (templates/site/, copied by tools/build_site_templates.py
from https://portmaster.games/contribute/porting/script-templates/) and new ones for engines the site doesn't cover
yet (templates/new/: the annotated Basic). templates/new/_patterns.sh holds documented building blocks any port
may use (data extraction, the ROCKNIX touch block, OmniOSK ...).
"""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from . import scriptnorm

HERE = Path(__file__).parent / "templates"
SITE_URL = "https://portmaster.games/contribute/porting/script-templates/"

NEW_NAMES = {"basic": "Basic (annotated)"}


@lru_cache(maxsize=1)
def site_index():
    p = HERE / "site" / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


def name(key):
    """Porter-facing name and where to find it."""
    kind, slug = key.split("/", 1)
    if kind == "site":
        meta = site_index().get(slug, {})
        group = f"{meta.get('group')} " if meta.get("group") and meta.get("group") != "Standard" else ""
        return f"the '{group}{meta.get('name', slug)}' template ({SITE_URL})"
    return f"the '{NEW_NAMES.get(slug, slug)}' template (being added to {SITE_URL})"


@lru_cache(maxsize=None)
def keys_of(key):
    p = HERE / (key + ".sh")
    return frozenset(k for _, k, _ in scriptnorm.lines(p.read_text())) if p.exists() else frozenset()


def text_of(key):
    p = HERE / (key + ".sh")
    return p.read_text() if p.exists() else ""


def pick(text, files=()):
    """The templates a launch script should look like (most specific first)."""
    code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    has = lambda rx: re.search(rx, code, re.I)
    out = []
    if has(r"\bua_host"):
        out.append("site/standard-unity")
    elif has(r"\bquixjs"):
        out.append("site/standard-rpg-maker-mv")
    elif has(r"westonwrap|weston_pkg"):
        if has(r"\bbox(64|86)\b"):
            out.append("site/westonpack-box64")
        elif has(r"godot"):
            out.append("site/westonpack-godot-4")
        elif has(r"\bzulu|javaruntime|JAVA_HOME|\bjava\b"):
            out.append("site/westonpack-java-opengl-2-1-through-mesapack-virgl" if has(r"virgl") else "site/westonpack-java-no-gl-pure-xlib")
        elif has(r"crusty_glx_gl4es"):
            out.append("site/westonpack-sdl2-opengl-2" if has(r"SDL_VIDEO_X11|libSDL2") else "site/westonpack-opengl-2-glx-gl4es")
        elif has(r"virgl"):
            out.append("site/westonpack-opengl-2-glx-virgl")
        elif has(r"crusty_x11egl"):
            out.append("site/westonpack-sdl2-opengl-es" if has(r"SDL_VIDEO_X11") else "site/westonpack-opengl-es-egl-x11")
        else:
            out.append("site/westonpack-xlib")
    elif has(r"\bbox86\b"):
        out.append("site/standard-box86")
    elif has(r"\bbox64\b"):
        out.append("site/standard-box64")
    elif has(r"\bfrt_|godot"):
        out.append("site/standard-godot-3")
    elif has(r"gmloadernext|gmloader-next"):
        out.append("site/standard-gmloader-next")
    elif has(r"gmloader"):
        out.append("site/standard-gamemaker")
    elif has(r"pyxel"):
        out.append("site/standard-pyxel")
    elif has(r"\bmono-[\d.]|MONO_PATH|MMLoader"):
        out.append("site/standard-mono")
    elif has(r"dotnet-[\d.]|DOTNET_ROOT"):
        out.append("site/standard-net-8")
    elif has(r"mkxp"):
        out.append("site/standard-mkxp-z")
    elif has(r"renpy"):
        out.append("site/standard-ren-py")
    elif has(r"LOVE_RUN|love_[\d.]") and not has(r"\$GAMEDIR/(launcher|extract)\b"):
        out.append("site/standard-love2d")
    elif has(r"libgl_(\$\{?CFW_NAME|default)"):
        out.append("site/standard-gl4es")
    if has(r"PATCHER_FILE"):
        out.append("site/standard-patcher")
    if not out:
        out.append("site/standard-basic")   # new/basic (annotated) only adds known-good lines, see allowed()
    return out


def allowed(keys):
    out = set(keys_of("new/_patterns")) | keys_of("site/standard-basic") | keys_of("new/basic")
    for k in keys:
        out |= keys_of(k)
    return out


def extra_lines(text, keys, peer_keys=(), common=frozenset()):
    """[(line, raw)] of logic lines that neither the templates, the documented patterns, the standard lines of merged
    ports nor the closest merged port has. Game-specific lines (assignments, the launch line, block ends) and
    system-reaching lines (sh.nonstandard lists those) are left out."""
    ok = allowed(keys)
    peer = set(peer_keys)
    out = []
    for n, k, raw in scriptnorm.lines(text):
        if k in ok or k in common or k in scriptnorm.TEMPLATE or scriptnorm.exempt(k, raw) or scriptnorm.DOCUMENTED.match(raw):
            continue
        if scriptnorm.SYSTEM.search(raw) or hashlib.sha1(k.encode()).hexdigest()[:8] in peer:
            continue
        out.append((n, raw.strip()))
    return out


def describe(keys):
    """'the 'A' and 'B' templates (<where>)', one link for all of them."""
    site = [site_index().get(k.split("/", 1)[1], {}).get("name", k) for k in keys if k.startswith("site/")]
    new = [NEW_NAMES.get(k.split("/", 1)[1], k) for k in keys if k.startswith("new/")]
    parts = []
    if site:
        parts.append(" and ".join(f"'{n}'" for n in site) + f" template{'s' if len(site) > 1 else ''} ({SITE_URL})")
    if new:
        where = "the same page" if site else SITE_URL
        parts.append(" and ".join(f"'{n}'" for n in new) + f" template{'s' if len(new) > 1 else ''} (being added to {where})")
    return "the " + " and the ".join(parts)
