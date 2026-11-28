"""All checks. Each check takes a Port and yields Findings. Nothing here executes port code."""
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from . import data, peers, templates
from .findings import Finding, ERROR, WARN, INFO
from .ini import check_ini
from .gptk import check_gptk
from . import scriptnorm

CHECKS = []


def check(fn):
    CHECKS.append(fn)
    return fn


def name_cleaner(text):
    # PortMaster-New tools/libs/util.py
    temp = re.sub(r"[^a-zA-Z0-9 _\-\.]+", "", text.strip().lower())
    return re.sub(r"[ \.]+", ".", temp)


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


# ---------------------------------------------------------------- ELF helpers
def is_elf(p):
    try:
        with open(p, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


@lru_cache(maxsize=None)
def elf_info(path):
    out = _run(["readelf", "-h", "-d", "-l", "-W", str(path)])
    m = re.search(r"Machine:\s+(.+)", out)
    machine = m.group(1).strip() if m else ""
    typ = re.search(r"Type:\s+(\w+)", out)
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out)
    soname = re.search(r"\(SONAME\)\s+Library soname: \[([^\]]+)\]", out)
    static = "INTERP" not in out and not needed
    syms = _run(["objdump", "-T", str(path)])
    glibc = sorted(set(re.findall(r"GLIBC_(2\.\d+(?:\.\d+)?)", syms)), key=version_tuple)
    return {
        "machine": machine,
        "arch": data.ELF_MACHINE_ARCH.get(machine, machine),
        "type": typ.group(1) if typ else "",
        "needed": needed,
        "soname": soname.group(1) if soname else "",
        "static": static,
        "glibc": glibc[-1] if glibc else "",
    }


ANDROID_DIR = re.compile(r"(^|/)(arm64-v8a|armeabi(-v7a)?|x86|x86_64)/")
HOST_ARCHES = {"aarch64", "armhf"}


def elves(port, host_only=True):
    """ELF files. host_only drops Android guest libs (gmloader) and x86 guest binaries (box86/box64),
    which run under a loader and never touch the device's glibc directly."""
    if not hasattr(port, "_elves"):
        port._elves = [(p, elf_info(p)) for p in port.logical_files()
                       if not data.PART_RE_SPLIT.search(p.name) and is_elf(p)]
    if not host_only:
        return port._elves
    return [(p, i) for p, i in port._elves
            if i["arch"] in HOST_ARCHES and not ANDROID_DIR.search(port.rel(p)) and "libc.so" not in i["needed"]]


def script_text(port, s):
    return port.read_text(s)


def json_load(port):
    if not hasattr(port, "_pj"):
        port._pj = None
        p = port.meta_file("port.json") if port.meta else None
        if p:
            try:
                port._pj = json.loads(port.read_text(p))
            except ValueError as e:
                port._pj = e
    return port._pj


def fix_glibc():
    return "objdump -T <file> | grep -o 'GLIBC_2\\.[0-9]*' | sort -uV | tail -1"


# ---------------------------------------------------------------- structure
@check
def structure(port):
    for s in port.inner_scripts:
        yield Finding("structure.script-in-gamedir", ERROR, f"{port.rel(s)} is inside the game folder; the launch script must sit next to it, at the top level.",
                      file=port.rel(s), fix=f"Move {s.name} up one level, out of {s.parent.name}/.")
    if port.wrapper:
        # harbourmaster extracts zip paths as they are into ports/ and only takes top-level *.sh as launch scripts
        yield Finding("structure.wrapper", ERROR, f"Everything in the zip is inside an extra {port.wrapper}/ folder. PortMaster installs the zip as it is, "
                      f"so the launch script lands in ports/{port.wrapper}/ instead of ports/ and the game folder one level too deep; the port won't start.",
                      fix=f"Zip the contents of {port.wrapper}/, not the folder: the zip's top level holds the .sh and the game folder.")
    if not port.scripts:
        yield Finding("structure.no-script", ERROR, "No launch script (.sh) at the top level.")
    if port.gamedir is None:
        exp = getattr(port, "expected_gamedir", None)
        if exp:
            loose = [p.name for p in port.top_files if p.name.lower() not in data.META_FILES]
            others = [d.name + "/" for d in port.top_dirs]
            yield Finding("structure.no-gamedir", ERROR, f"The script runs the game from ports/{exp}/, but the zip has no {exp}/ folder"
                          + (f": {', '.join(loose[:6])} sit next to the script" if loose else "")
                          + (f" (other folders: {', '.join(others[:4])})" if others else "") + ". PortMaster installs the zip as it is, so the game files "
                          "would land in ports/ instead of the game folder.", fix=f"Put everything except the .sh into a folder named {exp}/ and zip the .sh and that folder.")
        else:
            yield Finding("structure.no-gamedir", ERROR, "Game folder not found (no single top-level folder and no GAMEDIR match).")
        return
    gd = port.gamedir.name
    if gd != name_cleaner(gd):
        yield Finding("structure.gamedir-name", ERROR, f"Game folder {gd!r} is not a clean name; use {name_cleaner(gd)!r}.")
    elif re.search(r"[_\-.]", gd):
        yield Finding("structure.gamedir-squash", INFO, f"Game folder {gd!r}: new ports use lowercase, squashed names (no _ - .).")
    if port.pr and port.layout != "pr":
        yield Finding("structure.pr-layout", ERROR, "PR layout: port.json, README.md, gameinfo.xml and the images go next to the .sh, not in the game folder.",
                      fix=f"Move them from {gd}/ up one level.")
    if not port.pr:
        extra = [p.name for p in port.top_files if p.name.lower() not in data.META_FILES]
        if extra:
            yield Finding("structure.top-level", WARN, "Zip top level should hold only the .sh, the game folder and the port metadata; found: " + ", ".join(extra),
                          fix="Move these into the game folder.")
    if port.layout == "zip" and len(port.top_dirs) > 1:
            yield Finding("structure.top-level", WARN, "More than one top-level folder: " + ", ".join(d.name for d in port.top_dirs))
    for j in sorted(set(port.junk)):
        yield Finding("structure.junk", WARN, f"Junk file/folder {j!r} in the package.", fix="Remove it (macOS/Windows leftovers).")
    if port.symlinks:
        links = sorted(port.symlinks)
        shown = ", ".join(repr(x) for x in links[:5]) + (f" and {len(links) - 5} more" if len(links) > 5 else "")
        yield Finding("structure.symlink", ERROR, f"{len(links)} symlink{'s' if len(links) > 1 else ''} ({shown}): symlinks break on FAT/exFAT and across zip/copy.",
                      fix="Replace each with the real file (for libraries: one file named after the exact SONAME).")
    for p in port.files():
        size = p.stat().st_size
        if size > data.GIT_FILE_LIMIT:
            yield Finding("structure.file-too-big", ERROR, f"{port.rel(p)} is {size >> 20} MB; GitHub rejects files over 100 MB.",
                          file=port.rel(p), fix="Split into several .tar.gz archives along content boundaries.")
    # metadata shipped twice: next to the .sh and again in the game folder (only one copy is used)
    if port.root != port.gamedir:
        dups = sorted(f.name for f in port.top_files if f.name.lower() in data.META_FILES and (port.gamedir / f.name).is_file()
                      and (port.gamedir / f.name).read_bytes() == f.read_bytes())   # same file, not e.g. the engine's own README
        if dups:
            yield Finding("structure.duplicate-meta", WARN, f"{', '.join(dups)} {'is' if len(dups) == 1 else 'are'} both next to the .sh and in {port.gamedir.name}/; keep one copy.",
                          fix=f"Delete the copies in {port.gamedir.name}/ (PR layout keeps them next to the .sh).")
    # leftovers from a test run on a device
    log = port.gamedir / "log.txt"
    if log.is_file() and log.stat().st_size > 0:
        yield Finding("structure.leftover", WARN, f"{port.rel(log)} is a log from a test run; the script writes it on every launch.", file=port.rel(log), fix="Delete it.")
    conf = port.gamedir / "conf"
    if conf.is_dir():
        saved = [p for p in conf.rglob("*") if p.is_file() and p.name != ".gitkeep"]
        if len(saved) > 5:
            yield Finding("structure.leftover", WARN, f"{port.rel(conf)}/ holds {len(saved)} files, likely saves and settings from a test run; players would start with them.",
                          file=port.rel(conf), fix="Ship conf/ empty (a .gitkeep is fine) and let the game or script create its defaults.")
    count = len(port.logical_files())
    if count > data.LOOSE_FILE_LIMIT:
        biggest = _biggest_subdirs(port)
        folders = " ".join(f"{d}/" for d in biggest) or "gamedata/"
        yield Finding(
            "structure.too-many-files", WARN,
            f"{count} files in the package (limit {data.LOOSE_FILE_LIMIT}). Pack the bulk data into a .tar.gz extracted on first launch."
            + (f" Largest folders by file count: {', '.join(biggest)}." if biggest else ""),
            fix="Leave the binary, the library folder (libs.aarch64/, libs/), licenses/ and the control .ini outside the archive.",
            snippet=data.TAR_SNIPPET.format(folders=folders, guard=f"{biggest[0] if biggest else 'gamedata'}/<some-known-file>"),
        )


def _biggest_subdirs(port, n=3):
    if port.gamedir is None:
        return []
    counts = {}
    for p in port.logical_files():
        try:
            rel = p.relative_to(port.gamedir)
        except ValueError:
            continue
        if len(rel.parts) > 1 and not rel.parts[0].startswith(("libs.", "gl4es", "licen")) and rel.parts[0] not in ("libs", "lib", "conf"):
            counts[rel.parts[0]] = counts.get(rel.parts[0], 0) + 1
    return [k for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v > 10][:n]


@check
def required_files(port):
    if port.meta is None:
        return
    where = port.where()
    for name, sev in (("port.json", ERROR), ("README.md", ERROR), ("gameinfo.xml", ERROR),
                      ("screenshot.png", ERROR)):
        if port.meta_file(name) is None and not (name == "screenshot.png" and port.meta_file("screenshot.jpg")):
            fix = ""
            if name == "README.md":
                md = [f for d in port.meta_dirs() for f in sorted(d.glob("*")) if f.is_file() and f.suffix.lower() == ".md"]
                if md:
                    fix = f"Rename {port.rel(md[0])} to {port.rel(md[0].parent / 'README.md')}."
            if name == "screenshot.png" and not port.pr:
                sev = WARN   # testing zips often get the screenshot last; the PR needs it
            yield Finding("files.missing", sev, f"Missing {name} ({where}).", fix=fix)
    for c in port.files():
        if c.name.lower() == "cover.png" and c.parent not in port.meta_dirs():
            twin = port.root / c.name
            if port.gamedir is not None and c.parent == port.gamedir and twin.is_file() and twin.read_bytes() == c.read_bytes():
                continue   # structure.duplicate-meta reports the extra copy
            yield Finding("files.cover-location", WARN, f"{port.rel(c)} is in the wrong place; cover.png goes {where}.", file=port.rel(c))
    if port.gamedir is not None:
        lic = [d for d in port.gamedir.iterdir() if d.is_dir() and d.name.lower() in ("licenses", "license", "licences", "licence")]
        loose = [f for f in port.gamedir.iterdir() if f.is_file() and (re.search(r"licen[cs]e|copying|eula", f.name, re.I) or GENERIC_LICENCE.match(f.name))]
        if not lic and loose:
            yield Finding("licenses.folder", WARN, "Licence files sit loose in the game folder (" + ", ".join(f.name for f in loose) + "); move them into licenses/.")
        elif not lic:
            yield Finding("licenses.missing", ERROR, "No licenses/ folder inside the game folder.")
        elif not any(f.is_file() for f in lic[0].rglob("*")):
            yield Finding("licenses.empty", ERROR, f"{port.rel(lic[0])}/ is empty.")


# ---------------------------------------------------------------- port.json
@check
def port_json(port):
    pj = json_load(port)
    p = port.meta_file("port.json") if port.meta else None
    if p is None:
        return
    f = port.rel(p)
    if isinstance(pj, Exception):
        yield Finding("port.json.parse", ERROR, f"port.json is not valid JSON: {pj}", file=f)
        return
    if not isinstance(pj, dict):
        yield Finding("port.json.parse", ERROR, "port.json is not a JSON object.", file=f)
        return
    if pj.get("version") != 4:
        yield Finding("port.json.version", WARN, f"port.json version is {pj.get('version')!r}; current schema is 4.", file=f)
    attr = pj.get("attr") or {}
    gd = port.gamedir.name if port.gamedir else None
    name = str(pj.get("name") or "")
    if port.pr:
        # build_release.py: new ports need name == name_cleaner(<PR folder>) + ".zip" and a game folder of that name;
        # ports added before 2024-01-26 are exempt, so a different game folder is only reported when the name is off too.
        want = name_cleaner(port.root.name) + ".zip"
        if name_cleaner(name) != want:
            yield Finding("port.json.name", ERROR, f"name is {name!r}, must be {want!r} (the PR folder's name).", file=f)
    elif not name.endswith(".zip"):
        yield Finding("port.json.name", ERROR, f"name is {name!r}; it must end in .zip ({(gd or name) + '.zip'!r}).", file=f)
    elif gd and name != f"{gd}.zip":
        yield Finding("port.json.name", WARN, f"name is {name!r}; a new port's name is <game folder>.zip, {gd + '.zip'!r} (older ports keep theirs).", file=f)
    items = [str(i).rstrip("/") for i in (pj.get("items") or [])]
    actual = [s.name for s in port.scripts] + ([gd] if gd else [])
    for i in items if port.scripts and gd else []:   # without a script or game folder structure.* already says so
        if i not in actual and not (port.root / i).exists():
            yield Finding("port.json.items", ERROR, f"items lists `{i}`, which is not in the package.", file=f)
    for a in actual if port.scripts and gd else []:
        if a not in items:
            yield Finding("port.json.items", ERROR, f"`{a}` is in the package but not in items.", file=f)
    for k in attr:
        if k not in data.PORT_JSON_ATTRS:
            yield Finding("port.json.unknown-attr", WARN, f"Unknown attr {k!r}.", file=f)
    if not str(attr.get("title", "")).strip():
        yield Finding("port.json.title", ERROR, "attr.title is empty.", file=f)
    porters = attr.get("porter")
    if isinstance(porters, str):
        porters = [porters]
        yield Finding("port.json.porter", WARN, "porter should be a list.", file=f)
    if not porters:
        yield Finding("port.json.porter", ERROR, "porter is empty.", file=f)
    for who in porters or []:
        if re.search(r",|&|\band\b|/", str(who)):
            yield Finding("port.json.porter", WARN, f"porter entry {who!r} looks like several names; use one list entry per porter.", file=f,
                          fix='"porter": [' + ", ".join(json.dumps(x.strip()) for x in re.split(r",|&|\band\b|/", who) if x.strip()) + "]")
    for k in ("desc", "inst"):
        v = attr.get(k)
        if not str(v or "").strip():
            yield Finding(f"port.json.{k}", ERROR, f"attr.{k} is empty.", file=f)
        elif "\\n" in str(v) or re.search(r"\*\*|^#|\]\(", str(v), re.M):
            yield Finding(f"port.json.{k}", WARN, f"attr.{k} is shown as plain text in the app; remove markdown / \\n escapes (use {k}_md).", file=f)
    genres = attr.get("genres") or []
    if not genres:
        yield Finding("port.json.genres", ERROR, "genres is empty.", file=f)
    for g in genres:
        if g not in data.GENRES:
            yield Finding("port.json.genres", ERROR, f"Unknown genre {g!r}. Valid: {', '.join(sorted(data.GENRES))}.", file=f)
    for s in attr.get("store") or []:
        if not isinstance(s, dict) or not {"name", "gameurl"} <= set(s):
            yield Finding("port.json.store", ERROR, f"store entries must be objects with name/gameurl/developerurl, got {s!r}.", file=f)
    if attr.get("exp"):
        yield Finding("port.json.exp", INFO, "exp is true: the port is hidden by default. Only for released ports that should stay hidden.", file=f)
    runtimes = attr.get("runtime") or []
    if isinstance(runtimes, str):
        runtimes = [runtimes]
    for r in runtimes:
        if " " in r:
            yield Finding("port.json.runtime", ERROR, f"runtime {r!r} is a display label; use the catalog key (e.g. weston_pkg_0.2).", file=f)
        else:
            # harbourmaster appends .squashfs and looks the name up in the catalog (harbour.py runtime_check)
            sq = r if r.endswith(".squashfs") else r + ".squashfs"
            cat = data.RUNTIMES
            if sq in cat["keys"]:
                pass
            elif sq in cat["files"]:
                yield Finding("port.json.runtime", ERROR, f"runtime {r!r} is the file name of one arch build; use the catalog key.", file=f,
                              fix=f'"runtime": ["{cat["files"][sq]}"]')
            elif data.runtime_in_live_catalog(sq):
                pass   # published after the bundled snapshot was taken
            else:
                yield Finding("port.json.runtime", ERROR, f"runtime {r!r} is not in PortMaster's runtime catalog (checked {cat['updated']}); "
                              "harbourmaster refuses it as an unknown runtime, so the port can't download it.", file=f,
                              fix="Use a published runtime, or get the new runtime added to PortMaster first.")
    covers = ((attr.get("image") or {}).get("covers") if isinstance(attr.get("image"), dict) else None) or []
    if any(not str(c).strip() for c in covers):
        yield Finding("port.json.covers", INFO, 'image.covers holds an empty entry (`[""]`). No merged port has one.', file=f,
                      fix='Leave `"covers"` out, or list the real file names.')
    arch = attr.get("arch") or []
    found = sorted({i["arch"] for _, i in elves(port)})
    bad = [a for a in arch if a not in data.ARCHES]
    if bad:
        good = [a for a in arch if a in data.ARCHES] or found
        yield Finding("port.json.arch", ERROR, f"Invalid arch entr{'y' if len(bad) == 1 else 'ies'} {', '.join(map(repr, bad))}.", file=f,
                      fix=f'"arch": {json.dumps(sorted(set(good) | set(found)))}')
        arch = [a for a in arch if a in data.ARCHES]
    if runtimes and arch and not found:
        yield Finding("port.json.arch", INFO, "No native binaries; with a runtime set, arch can stay [].", file=f)
    if found and not arch and not bad and not runtimes:   # harbourmaster ignores arch when a runtime is set
        yield Finding("port.json.arch", ERROR, f"Native binaries for {', '.join(found)} but arch is empty.", file=f,
                      fix=f'"arch": {json.dumps(found)}')
    # arch is an OR list; device_info.txt adds "armhf" to an aarch64 device's capabilities only when it
    # has a 32-bit userland. There are no armhf-only devices. Prebuilt helpers (gamepad-picker, gptokeyb...) don't count.
    found = sorted({i["arch"] for p, i in elves(port) if not data.PREBUILT_RE.match(p.name)}) or found
    scripts_all = "\n".join(script_text(port, sc) for sc in port.scripts)
    armhf_test = re.search(r"DEVICE_HAS_ARMHF|-[edfx]\s+\"?/(usr/)?lib(32\b|/ld-linux-armhf)", scripts_all)
    armhf_glibc = re.search(r"ld-linux-armhf\.so\.3\"?\s+--version|\bldd\s+--version", scripts_all)
    if "armhf" in found and "aarch64" in found:
        if not armhf_test:   # a script that picks the build by the userland has a reason
            yield Finding("port.json.arch", INFO, "Ships an armhf build next to the aarch64 one. Every device runs the aarch64 build and some have no 32-bit userland: ask the porter why the armhf version is included.",
                          file=f)
    elif "armhf" in found and arch and "armhf" not in arch:
        yield Finding("port.json.arch", WARN, "Only armhf binaries, but arch does not list armhf: the port is offered on devices without a 32-bit userland, where it can't start.",
                      file=f, fix='"arch": ["armhf"]')
    for a in found:
        if arch and a not in arch and a != "armhf":   # armhf is handled above
            yield Finding("port.json.arch", WARN, f"Ships {a} binaries but arch does not list {a}.", file=f)
    # min_glibc
    # harbourmaster compares min_glibc with the native glibc (device_info.txt CFW_GLIBC, getconf), so binaries
    # of an arch the port doesn't list (armhf next to aarch64) only need the 32-bit userland's own glibc
    allg = [(i["glibc"], p, i["arch"]) for p, i in elves(port) if i["glibc"]]
    need = [(g, p) for g, p, a in allg if not arch or a in arch]
    other = [(g, p) for g, p, a in allg if arch and a not in arch]
    if other and not armhf_glibc:   # the script reads the 32-bit glibc version before choosing that build
        otop, ofile = max(other, key=lambda x: version_tuple(x[0]))
        if not need or version_tuple(otop) > version_tuple(max(need, key=lambda x: version_tuple(x[0]))[0]):
            yield Finding("port.json.min_glibc", INFO, f"{port.rel(ofile)} needs GLIBC_{otop} from the 32-bit userland; min_glibc only covers the native one, "
                          "so the script has to check it before choosing that route.", file=f)
    if need:
        top, top_file = max(need, key=lambda x: version_tuple(x[0]))
        mg = str(attr.get("min_glibc") or "")
        if version_tuple(top) < version_tuple(data.GLIBC_BASELINE):
            pass   # every supported CFW has it (old baseline Ubuntu 20.04, glibc 2.31): min_glibc can stay empty
        elif not mg:
            yield Finding("port.json.min_glibc", ERROR, f"min_glibc is empty but {port.rel(top_file)} needs GLIBC_{top}.", file=f,
                          fix=f'"min_glibc": "{top}"')
        elif version_tuple(mg) < version_tuple(top):
            yield Finding("port.json.min_glibc", ERROR, f"min_glibc is {mg} but {port.rel(top_file)} needs GLIBC_{top}.", file=f,
                          fix=f'"min_glibc": "{top}"')
    # runtimes the script mounts vs. listed
    used = set()
    for s in port.scripts:
        for m in re.finditer(r"([\w.\-]+)\.squashfs|runtime=\"?([\w.\-]+)", script_text(port, s)):
            key = m.group(1) or m.group(2)
            if key and data.RUNTIME_KEY.fullmatch(key) and "$" not in key:
                used.add(key)
    listed = {r[:-9] if r.endswith(".squashfs") else r for r in runtimes}
    missing = sorted(used - listed)
    if missing:
        # keep the entries as written, add the missing ones in the same spelling (with or without .squashfs)
        suffix = ".squashfs" if not runtimes or any(r.endswith(".squashfs") for r in runtimes) else ""
        full = list(runtimes) + [m + suffix for m in missing]
        names = " and ".join(repr(m) for m in missing)
        yield Finding("port.json.runtime", WARN,
                      f"The script mounts the runtime{'s' if len(missing) > 1 else ''} {names}, but the \"runtime\" list in port.json does not include {'them' if len(missing) > 1 else 'it'}. "
                      "PortMaster downloads only the listed runtimes when it installs the port; anything else the script has to fetch on first launch, which fails without internet.",
                      file=f, fix=f'Set it in port.json: "runtime": {json.dumps(full)}')


# ---------------------------------------------------------------- gameinfo.xml
@check
def gameinfo(port):
    p = port.meta_file("gameinfo.xml") if port.meta else None
    if p is None:
        return
    f = port.rel(p)
    try:
        root = ET.fromstring(port.read_text(p).encode())
    except ET.ParseError as e:
        yield Finding("gameinfo.parse", ERROR, f"gameinfo.xml is not well-formed: {e}", file=f)
        return
    # harbourmaster merges root.findall("game"): any root name works, a bare <game> root is never merged
    game = root.find("game")
    if game is None:
        yield Finding("gameinfo.structure", ERROR, "No <game> inside the root element, so PortMaster adds nothing to the game list. Expected <gameList><game>...</game></gameList>.", file=f)
        return
    for child in game:
        if child.tag not in data.GAMEINFO_TAGS:
            yield Finding("gameinfo.tag", WARN, f"Undocumented tag <{child.tag}>.", file=f)
    get = lambda t: (game.findtext(t) or "").strip()
    empty = [t for t in ("name", "desc", "developer", "releasedate", "genre") if not get(t)]
    if empty:
        yield Finding("gameinfo.field", WARN, "Missing or empty: " + ", ".join(f"<{t}>" for t in empty) + ".", file=f)
    scripts = {f"./{s.name}" for s in port.scripts}
    if get("path") and scripts and get("path") not in scripts:
        yield Finding("gameinfo.path", ERROR, f"<path> {get('path')!r} does not match the script ({', '.join(sorted(scripts))}).", file=f)
    if get("releasedate") and not re.fullmatch(r"\d{8}T\d{6}", get("releasedate")):
        yield Finding("gameinfo.releasedate", WARN, f"<releasedate> {get('releasedate')!r}: use YYYYMMDDT000000.", file=f)
    if port.gamedir is not None:
        gd = port.gamedir.name
        want = f"./{gd}/screenshot.png"
        img = get("image")
        ok = {f"./{gd}/{n}": n for n in ("screenshot.png", "screenshot.jpg", "cover.png", "cover.jpg")}
        target = img[len(f"./{gd}/"):] if img.startswith(f"./{gd}/") else None
        if not img:
            yield Finding("gameinfo.image", ERROR, "<image> is missing.", file=f, fix=f"<image>{want}</image>")
        elif img not in ok and not (target and "/" not in target and port.meta_file(target)):
            have = next((f"./{gd}/{n}" for n in ("screenshot.png", "screenshot.jpg", "cover.png") if port.meta_file(n)), want)
            if img.lower() in {k.lower() for k in ok} or img.lower() == have.lower():
                yield Finding("gameinfo.image", ERROR, f"<image> {img!r} has the wrong case; the folder is {gd!r} and device filesystems are case-sensitive.", file=f,
                              fix=f"<image>{have if have.lower() == img.lower() else img.replace(img.split('/')[1], gd, 1)}</image>")
            elif re.fullmatch(r"\./[^/]+", img) and port.meta_file(img[2:]):
                yield Finding("gameinfo.image", ERROR, f"<image> {img!r} lacks the game folder; PortMaster installs the image into {gd}/, so the frontend finds no image.", file=f,
                              fix=f"<image>./{gd}/{img[2:]}</image>")
            else:
                yield Finding("gameinfo.image", ERROR, f"<image> {img!r} points to a file that is not in the package.", file=f, fix=f"<image>{have}</image>")
        elif img not in ok:
            yield Finding("gameinfo.image", WARN, f"<image> is {img!r}; use {want!r} (or ./{gd}/cover.png).", file=f, fix=f"<image>{want}</image>")
        elif port.meta_file(ok[img]) is None and ok[img] != "screenshot.png":   # a missing screenshot.png is files.missing already
            yield Finding("gameinfo.image", ERROR, f"<image> points to {ok[img]}, but the package has no {ok[img]} {port.where()}.", file=f,
                          fix=f"Add {ok[img]}, or use <image>{want}</image>.")


# ---------------------------------------------------------------- images
def image_size(p):
    try:
        from PIL import Image
        with Image.open(p) as im:
            return im.size
    except Exception:
        pass
    with open(p, "rb") as fh:
        data_ = fh.read(1 << 20)
    if data_[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data_[16:24])
    if data_[:2] == b"\xff\xd8":   # JPEG: walk the segments to the frame header (SOF0..SOF15 except DHT/JPG/DAC)
        i = 2
        while i + 9 < len(data_) and data_[i] == 0xFF:
            marker, seglen = data_[i + 1], struct.unpack(">H", data_[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data_[i + 5:i + 9])
                return (w, h)
            i += 2 + seglen
    return None


@check
def images(port):
    if port.meta is None:
        return
    shot = port.meta_file("screenshot.png") or port.meta_file("screenshot.jpg")
    if shot:
        size = image_size(shot)
        if size and tuple(size) != (640, 480):
            yield Finding("images.screenshot-size", ERROR, f"screenshot is {size[0]}x{size[1]}, must be 640x480.", file=port.rel(shot))
    cov = port.meta_file("cover.png") or port.meta_file("cover.jpg")
    if cov:
        csize = image_size(cov)
        if csize and tuple(csize) != (640, 480):
            yield Finding("images.cover-size", ERROR, f"cover is {csize[0]}x{csize[1]}, must be 640x480.", file=port.rel(cov),
                          fix=f"Make a 640x480 cover with {data.COVER_GENERATOR}")
    if not cov:
        yield Finding("images.no-cover", INFO, "No cover.png; the screenshot is used in its place.",
                      fix=f"Make one with {data.COVER_GENERATOR}")
    for p in (p for d in port.meta_dirs() for p in d.iterdir()):
        if p.is_file() and re.match(r"^(screenshot|cover)(\..+)?\.(png|jpe?g)$", p.name, re.I):
            kb = p.stat().st_size
            if kb > data.IMAGE_MAX_BYTES:
                yield Finding("images.size", WARN, f"{p.name} is {kb / 1024:.1f} KB (limit {data.IMAGE_MAX_BYTES // 1024} KB).", file=port.rel(p),
                              fix=f"Compress it with {data.PNG_COMPRESSOR}")


# ---------------------------------------------------------------- README
@check
def readme(port):
    p = port.meta_file("README.md") if port.meta else None
    if p is None:
        return
    text = port.read_text(p)
    heads = {h.strip().lower() for h in re.findall(r"^#{1,3}\s*(.+?)\s*#*$", text, re.M)}
    # the guide asks for a thank-you to the creator; "## Notes" is only its usual place
    if not any(x.startswith("notes") for x in heads) and not re.search(r"\bthank|\bcredits?\b", text, re.I):
        yield Finding("readme.thanks", WARN, "README has no thank-you to the game's creator (usually a '## Notes' section at the top).", file=port.rel(p),
                      fix="## Notes\n\nThanks to <creator> for creating <game>!")
    need = ["controls"]
    # an executable the porter built, in the game folder or in a tools/ folder; libraries and the runtimes' own loaders don't count
    if any(not data.PREBUILT_RE.match(p.name) and ".so" not in p.name and not re.search(r"(^|/)(jre|jdk)[^/]*/", port.rel(p))
           and (p.parent == port.gamedir or info["type"] == "EXEC" or (info["type"] == "DYN" and not info["soname"]))
           for p, info in elves(port)):
        need.append("compile")
    shipped = {f.name for f in port.files()}
    # patches only: other archive names in a README are usually game files the player brings, or the port zip
    names = re.findall(r"`([\w.+-]+\.(?:patch|diff|tar\.gz|tgz|tar\.xz|zip))`", text)
    missing = sorted({m for m in names if m not in shipped and (re.search(r"\.(patch|diff)$", m) or re.search(r"patch", m, re.I))})
    if missing:
        yield Finding("readme.missing-file", WARN, f"The README refers to {', '.join(missing)}, which the package does not contain; nobody can repeat the build without it.",
                      file=port.rel(p), fix=f"Ship it (patches go in {port.gamedir.name if port.gamedir else '<gamedir>'}/patches/) or link where to get it.")
    issues = []
    first = re.search(r"^#{1,3}\s*(.+?)\s*#*$", text, re.M)
    if first and not re.match(r"(notes|controls|compile|build)", first.group(1).strip(), re.I):
        issues.append(f"it starts with '{first.group(0).strip()}' instead of '## Notes'")
    tags = sorted({t.lower() for t in re.findall(r"<(br|div|p|center|font|span|img)\b", text, re.I)})
    if tags:
        issues.append("it uses HTML (" + ", ".join(f"<{t}>" for t in tags) + ")")
    if issues:
        yield Finding("readme.layout", INFO, f"README doesn't follow the template: {'; '.join(issues)}.", file=port.rel(p),
                      fix=f"## Notes / ## Controls / ## Compile in plain markdown; {data.MARKDOWN_GENERATOR} builds one.")
    dl = re.search(r"^#{1,3}\s*(downloads?|releases?|get it|installing the zip)\b.*$", text, re.M | re.I) or \
        re.search(r"harbourmaster\s+install|autoinstall\b|/-/releases|/releases/(latest|permalink)", text, re.I)
    if dl:
        yield Finding("readme.download", INFO, f"The README tells players where else to download or how to install the port (`{dl.group(0).strip()[:60]}`). "
                      "On PortMaster the port is installed by PortMaster itself, so this part only fits your own repository's README.",
                      file=port.rel(p), fix="Keep Notes, Controls and Compile here; move download and install instructions to your repository.")
    for h in need:
        alt = ("compile", "build", "building") if h == "compile" else (h,)
        if not any(x.startswith(alt) for x in heads):
            yield Finding("readme.section", WARN if h != "compile" else INFO, f"README has no '## {h.title()}' section.", file=port.rel(p))


@check
def patcher_file(port):
    """PortMaster's patcher (utils/patcher) watches the patch script's output for "Patching process failed!";
    its thread reports success whenever the script ends without it."""
    if port.gamedir is None:
        return
    for s in port.scripts:
        for m in re.finditer(r"PATCHER_FILE=[\"']?([^\"'\s]+)", script_text(port, s)):
            target = _resolve(port, m.group(1))
            if target is None or not target.is_file():
                continue
            text = port.read_text(target)
            if re.search(r"\bexit\s+[1-9]|\bexit\s+\$", text) and "Patching process failed!" not in text:
                near = re.search(r"Patch\w*\s+(process\s+)?failed[^!\n\"']*", text, re.I)
                yield Finding("patcher.fail-marker", WARN, f"{port.rel(target)} can fail but never prints \"Patching process failed!\""
                              + (f" (it prints {near.group(0).strip()!r})" if near else "") + "; the patcher then shows its success screen.",
                              file=port.rel(target), fix='echo "Patching process failed!" before exit 1 (PATCH_FAIL_MSG:<text> first to set the message).')


@check
def patcher_questions(port):
    """PortMaster's patcher runs the PATCHER_QUESTIONS file as Lua in its own global environment (utils/patcher/main.lua,
    load(..., _G)); it should only build and return the questions table."""
    scripts = "\n".join(script_text(port, s) for s in port.scripts)
    if "PATCHER_QUESTIONS" not in scripts or port.gamedir is None:
        return
    for q in port.gamedir.rglob("*.lua"):
        text = port.read_text(q)
        code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
        if q.name not in scripts or not re.search(r"\bquestion\s*=", code):
            continue
        bad = sorted({m.group(0).strip("( ") for m in re.finditer(r"\b(require|os\.execute|os\.remove|os\.rename|io\.popen|io\.open|loadstring|dofile|setmetatable|love\.|_G\b|package\.)\s*\(?|\bTalkies\b|\btalkies\b", code)})
        if bad:
            yield Finding("patcher.questions-code", WARN, f"{port.rel(q)} runs inside PortMaster's patcher with its full Lua environment and does more than return the questions: {', '.join(bad)}.",
                          file=port.rel(q), fix="Only build and return the questions table; don't change the patcher's UI or touch files from it.")


def _is_xna_effect(f):
    """A compiled XNA/MonoGame effect (shader) .xnb: a program someone wrote, not the game's sprites, fonts or audio."""
    if f.suffix.lower() != ".xnb":
        return False
    try:
        head = f.read_bytes()[:600]
    except OSError:
        return False
    return head[:3] == b"XNB" and b"Microsoft.Xna.Framework.Content.EffectReader" in head


@check
def game_content(port):
    """Files in a game's own content format (XNA: .xnb sprites/fonts, .xwb/.xsb audio banks) shipped with the port are
    usually edited copies of the game's data, which a port can't redistribute."""
    if port.gamedir is None:
        return
    hits = [f for f in port.files() if f.suffix.lower() in data.GAME_CONTENT_EXT
            and "gamedata" not in (x.lower() for x in port.rel(f).split("/")[1:-1]) and not _is_xna_effect(f)]
    if hits:
        names = ", ".join(port.rel(f) for f in hits[:4]) + (", ..." if len(hits) > 4 else "")
        yield Finding("files.game-content", INFO, f"Ships files in the game's own content format ({names}). If they are made from the game's files "
                      "(recoloured sprites, edited fonts or sounds), they can't be redistributed.",
                      file=port.rel(hits[0]), fix="Ask where they come from; build them on device from the player's copy at first launch, or ship a binary diff (xdelta) instead.")


@check
def bitmaps(port):
    """Uncompressed 24/32-bit .bmp files: a 640x480 one is 900 KB where a PNG is a fraction of it."""
    big = []
    for f in port.files():
        if f.suffix.lower() != ".bmp" or (port.gamedir and "gamedata" in port.rel(f).split("/")[1:-1]):
            continue
        try:
            head = f.read_bytes()[:32]
        except OSError:
            continue
        if head[:2] == b"BM" and len(head) >= 30 and struct.unpack("<H", head[28:30])[0] >= 24 and f.stat().st_size > 256 * 1024:
            big.append(f)
    if big:
        names = ", ".join(f"{port.rel(f)} ({f.stat().st_size // 1024} KB)" for f in big[:4])
        yield Finding("files.bmp", INFO, f"Uncompressed true-colour bitmap{'s' if len(big) > 1 else ''}: {names}.", file=port.rel(big[0]),
                      fix="Use PNG if whatever loads it reads PNG, otherwise an 8-bit indexed BMP.")


@check
def doc_refs(port):
    """A player-facing text (script, setup message, placeholder note) pointing at a .md file the package lacks."""
    shipped = {f.name.lower() for f in port.files()}
    seen = {}
    for f in port.files():
        if f.stat().st_size > 256_000 or f.suffix.lower() in (".md", ".json", ".xml", ".png", ".jpg", ".apk", ".dll", ".so"):
            continue
        if re.search(r"(^|/)(licen[cs]es?|legal)(/|$)", port.rel(f), re.I) or re.search(r"licen[cs]e|copying|notice|copyright", f.name, re.I):
            continue   # third-party licence texts name their own project's files
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        text = "\n".join(l for l in raw.decode("utf-8", "replace").splitlines() if not l.lstrip().startswith(("#", "--", "//")))
        for m in re.finditer(r"(?<![\w/.-])(?:\.\./)?([\w-]+\.md)\b", text):
            name = m.group(1)
            if name.lower() not in shipped and not name.lower().startswith(("license", "changelog")):
                seen.setdefault(name, []).append(port.rel(f))
    for name, where in sorted(seen.items()):
        where = sorted(set(where))
        yield Finding("files.missing-doc", WARN, f"{', '.join(where[:3])} send{'s' if len(where) == 1 else ''} the player to {name}, which the package does not contain.",
                      file=where[0], fix="Point it at README.md, or ship the file.")


# ---------------------------------------------------------------- binaries / libs
def _in_gl4es(p):
    return any(part.startswith("gl4es") for part in p.parts)


SO_TAIL = re.compile(rb"\.so(?:\.[\w.]*)?(?![\w.\-])")
SO_CHARS = frozenset(b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-")


def so_tokens(blob):
    """Every library-name token (libfoo.so, libfoo.so.1.2) in a byte string. Scans from each '.so' instead of
    running a regex over every byte: about 200x faster on large binaries and APKs."""
    out, i = set(), blob.find(b".so")
    while i != -1:
        m = SO_TAIL.match(blob, i)
        if m:
            j = i
            while j > 0 and blob[j - 1] in SO_CHARS:
                j -= 1
            out.add(blob[j:m.end()])
        i = blob.find(b".so", i + 3)
    return out


def _named_elsewhere(port, p):
    """Another file in the package names this library (dlopen() by name, a .NET dllmap, a Lisp/CFFI core ...).
    Every file is read once per port; the exact library names found are kept per file."""
    if not hasattr(port, "_so_names"):
        port._so_names = {}
        for q in port.logical_files():
            try:
                if q.stat().st_size <= 200_000_000:
                    port._so_names[q] = so_tokens(q.read_bytes())
            except OSError:
                pass
    want = p.name.encode()
    return any(want in names for q, names in port._so_names.items() if q != p)


def _sdl3_gpu_use(port):
    """'compute' / 'gpu' when a native binary imports SDL3's GPU API (with / without compute pipelines), else ''."""
    use = ""
    for p, info in elves(port):
        if info["type"] == "DYN" and ".so" in p.name:
            continue
        syms = _run(["nm", "-D", "--undefined-only", str(p)])
        if "SDL_CreateGPUComputePipeline" in syms:
            return "compute"
        if re.search(r"\bSDL_CreateGPUDevice", syms):
            use = "gpu"
    return use


@check
def binaries(port):
    scripts_all = "\n".join(script_text(port, s) for s in port.scripts)
    bundled = {}
    libfiles = []   # every shared library file; bundled maps names, so libs.aarch64/x.so and libs.armhf/x.so share a key
    for p, info in elves(port):
        if info["type"] == "DYN" and (".so" in p.name):
            bundled[p.name] = p
            libfiles.append(p)
            if info["soname"]:
                bundled.setdefault(info["soname"], p)
    # byte-identical copies of one library (libfoo.so + libfoo.so.1.2): libs.duplicate covers the SONAME pair
    by_hash = {}
    for p in sorted(set(bundled.values()), key=lambda x: port.rel(x)):
        try:
            by_hash.setdefault((p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()), []).append(p)
        except OSError:
            pass
    in_identical = set()
    identical_groups = []
    for group in by_hash.values():
        stems = {}
        for g in group:
            stems.setdefault(g.name.split(".so")[0], []).append(g)
        group = max(stems.values(), key=len)   # copies under other names are aliases the game loads on purpose
        if len(group) < 2:
            continue
        so = elf_info(group[0])["soname"]
        if so and any(g.name == so for g in group) and len(group) == 2:
            continue   # one file is named after the SONAME: libs.duplicate decides
        in_identical.update(group)
        names = ", ".join(port.rel(g) for g in group)
        keep = f"keep {so}, plus any other name the game opens itself" if so else "keep one"
        identical_groups.append((names, keep, port.rel(group[0])))
    if len(identical_groups) == 1:
        names, keep, first = identical_groups[0]
        yield Finding("libs.identical", WARN, f"Identical copies of one library: {names}; {keep}.", file=first, fix="Delete the extra copies.")
    elif identical_groups:
        names, keep, first = identical_groups[0]
        yield Finding("libs.identical", WARN, f"{len(identical_groups)} libraries are shipped as several identical copies, e.g. {names}; {keep}. "
                      f"Also: {', '.join(g[0].split(',')[0].rsplit('/', 1)[-1] for g in identical_groups[1:7])}{', ...' if len(identical_groups) > 7 else ''}.",
                      file=first, fix="Delete the extra copies of each: keep the file named after the SONAME plus any other name the game opens itself.")
    x11_done = False
    common = {}
    for p in sorted(libfiles, key=lambda x: port.rel(x)):
        name = p.name
        rel = port.rel(p)
        if data.GL_LIBS.match(name) and not _in_gl4es(p):
            yield Finding("libs.banned", ERROR, f"{rel}: libGL/libEGL outside a gl4es.<arch>/ folder.", file=rel)
        for rx, why in data.BANNED_LIBS:
            if rx.match(name):
                yield Finding("libs.banned", ERROR, f"{rel} must not be bundled: {why}.", file=rel, fix="Delete it.")
        if name.startswith("libSDL3.so") and b"SDL3SHIM_" not in p.read_bytes():
            msg = f"{rel} is upstream SDL3. SDL3 games ship the sdl3-sdl2-backend shim, which hands video, audio and input to the CFW's SDL2 (fbdev, rotation, KMSDRM quirks)."
            fix = "Build against https://github.com/bmdhacks/SDL/tree/sdl2-backend and ship its libSDL3.so.0 instead."
            gpu = _sdl3_gpu_use(port)
            if gpu == "compute":
                # the shim's GLES GPU backend (SPIRV-Cross) has no compute pipelines yet: "will assert if called"
                msg += (" The game renders through SDL3's GPU API and uses compute pipelines. The shim runs the GPU API on GLES 3.x, but has no compute"
                        " pipelines yet, so it can't run this game as it is. Upstream SDL3 runs it only on Vulkan, which needs a Vulkan driver and SDL3's own"
                        " KMSDRM, so it works on few devices and CFWs.")
                fix = ("Disable the compute passes in the game (often optional effects such as FSR or motion blur) and use the shim's GLES GPU backend,"
                       " or add compute pipelines to the shim's GLES backend (GLES 3.1 has compute shaders).")
            elif gpu == "gpu":
                msg += " The game renders through SDL3's GPU API; the shim provides it on GLES 3.x (SPIR-V shaders through SPIRV-Cross), so no Vulkan is needed."
            yield Finding("libs.sdl3", ERROR, msg, file=rel, fix=fix)
        if re.match(r"^lib(X11|xcb)\.so", name) and not re.search(r"westonwrap|weston_pkg", scripts_all) and not x11_done:
            x11_done = True
            yield Finding("libs.x11", WARN, f"Bundles X11 libraries ({rel.rsplit('/', 1)[0]}/libX*, libxcb*) without Westonpack. On KMS/DRM devices nothing draws through X11, the binary only links it.", file=rel,
                          fix="Rebuild without X11 and drop the libX*/libxcb* files (OHRRPGCE: scons gfx=sdl2 no_x11=1).")
        # a fallback/ folder is only linked when the CFW lacks the library (runtime.src find_library pattern)
        for rx in data.COMMON_LIBS if "fallback" not in p.parent.name.lower() else ():
            if rx.match(name):
                common.setdefault(name, []).append(p)
        so = elf_info(p)["soname"]
        if so and p.name != so and p.name not in scripts_all and not _named_elsewhere(port, p):
            if p in in_identical:
                continue   # libs.identical already names the whole group
            if (p.parent / so).exists():
                if re.search(r"\bmono\b|dotnet", scripts_all, re.I):
                    continue   # .NET P/Invoke opens the unversioned name, native libs NEED the SONAME: both copies are used
                yield Finding("libs.duplicate", WARN, f"{rel} duplicates {so} in the same folder; ship only {so}.", file=rel, fix="Delete it.")
            else:
                yield Finding("libs.soname", WARN, f"{rel} should be named after its SONAME {so!r}.", file=rel)
    if common:
        first = min((p for ps in common.values() for p in ps), key=lambda x: port.rel(x))
        folders = sorted({port.rel(p.parent) for ps in common.values() for p in ps})
        yield Finding("libs.common", WARN, f"{', '.join(sorted(common))} (in {', '.join(folders)}) are near-universal on CFW images; bundling them only bloats the port.",
                      file=port.rel(first), fix="Remove them and test on device; add back only what a device reports missing.")
    pj = json_load(port)
    rts = " ".join(map(str, ((pj.get("attr") or {}).get("runtime") or []) if isinstance(pj, dict) else [])) + " " + scripts_all
    provided = list(data.CFW_PROVIDED)
    if re.search(r"weston", rts):
        provided.append(re.compile(r"^lib(X\w*|xcb\S*|GLU|xkbcommon\S*|wayland-\S+)\.so"))
    if re.search(r"qt6", rts, re.I):
        provided.append(re.compile(r"^libQt6\w+\.so"))
    # bundled libraries nothing in the port links. Only when the port ships its own native executable:
    # without one the game runs in a runtime or loader (Mono, Godot, gmloader ...) that dlopens libraries by name.
    linked = {n for _, info in elves(port) for n in info["needed"]}
    unlinked = set()
    has_exe = any(not data.PREBUILT_RE.match(p.name) and ".so" not in p.name and (info["type"] == "EXEC" or (info["type"] == "DYN" and not info["static"] and not info["soname"]))
                  for p, info in elves(port))
    if has_exe and not re.search(r"mono|dotnet|box64|box86|gmloader", scripts_all, re.I):
        for p in set(bundled.values()):
            so = elf_info(p)["soname"]
            if (p.name not in linked and so not in linked and p.name not in scripts_all and (not so or so not in scripts_all)
                    and not _in_gl4es(p) and not re.search(r"(^|/)(jre|jdk)[^/]*/", port.rel(p))):
                unlinked.add(p)
    needers = {}
    for p, info in elves(port):
        rel = port.rel(p)
        if re.search(r"(^|/)(jre|jdk)[^/]*/", rel):
            continue   # a bundled JRE's optional AWT/sound libs load lazily
        for n in info["needed"]:
            if n not in bundled and not any(rx.match(n) for rx in provided):
                # name a linked needer when there is one
                if n not in needers or (needers[n] in {port.rel(u) for u in unlinked} and p not in unlinked):
                    needers[n] = rel
    if needers:
        libs = sorted(needers)
        rel_unlinked = {port.rel(p) for p in unlinked}
        def who(n):
            r = needers[n]
            # the needer itself is linked by nothing: it only loads if the game dlopens it
            return f"{r}, which nothing in the port links, so it only matters if the game loads it at runtime" if r in rel_unlinked else r
        shown = ", ".join(f"{n} ({who(n)})" for n in libs[:8]) + (f" and {len(libs) - 8} more" if len(libs) > 8 else "")
        yield Finding("bin.needed", INFO, f"{len(libs)} needed librar{'y' if len(libs) == 1 else 'ies'} not bundled and not on the known CFW list: {shown}.",
                      fix="Check on device; bundle a library only if a device reports it missing.")
    # Bundled language runtimes where PortMaster ships a squashfs
    for p in port.logical_files():
        rel = port.rel(p)
        if p.name == "java" and p.parent.name == "bin" and is_elf(p):
            yield Finding("runtime.bundled", WARN, f"{rel}: bundled Java. PortMaster provides JDK/JRE runtimes (squashfs).", file=rel)
        elif re.match(r"^libmonosgen-2\.0\.so|^libcoreclr\.so", p.name):
            rts = (json_load(port).get("attr") or {}).get("runtime") if isinstance(json_load(port), dict) else None
            godot = [r for r in (rts if isinstance(rts, list) else [rts or ""]) if str(r).startswith("godot_") and "mono" not in str(r)]
            hint = (f" This looks like a Godot .NET export, but port.json asks for `{godot[0]}`; the .NET build needs the matching `{godot[0].replace('.squashfs', '')}.mono.squashfs`." if godot else "")
            yield Finding("runtime.bundled", WARN, f"{rel}: bundled Mono/.NET. PortMaster provides runtime squashfs files.{hint}", file=rel)


@lru_cache(maxsize=None)
def strip_savings(path):
    """Bytes strip would remove (debug sections + symbol table), and whether there is debug info."""
    out = _run(["readelf", "-S", "-W", str(path)])
    total, debug = 0, False
    for m in re.finditer(r"\]\s+(\S+)\s+\S+\s+[0-9a-f]+\s+[0-9a-f]+\s+([0-9a-f]+)", out):
        name, size = m.group(1), int(m.group(2), 16)
        if name.startswith((".debug_", ".zdebug_")):
            total += size
            debug = True
        elif name in (".symtab", ".strtab"):
            total += size
    return total, debug


@check
def debug_symbols(port):
    debug, syms = [], []
    for p, info in elves(port):
        if data.PREBUILT_RE.match(p.name) or re.search(r"(^|/)(jre|jdk)[^/]*/", port.rel(p)):
            continue
        saved, has_debug = strip_savings(p)
        if saved >= 512 * 1024:
            (debug if has_debug else syms).append((p, saved))
    mb = lambda b: f"{b / 1048576:.1f} MB"
    for hits, what in ((debug, "debug info"), (syms, "symbol tables (not stripped)")):
        if not hits:
            continue
        hits.sort(key=lambda h: -h[1])
        total = sum(s for _, s in hits)
        if total < data.STRIP_MIN:
            continue   # a few MB are not worth a rebuild
        sev = WARN if total >= data.STRIP_WARN else INFO
        before = sum(p.stat().st_size for p, _ in hits)
        shown = ", ".join(f"{port.rel(p)} ({mb(s)})" for p, s in hits[:6]) + (f" and {len(hits) - 6} more" if len(hits) > 6 else "")
        yield Finding("bin.debug", sev, f"Binaries ship with {what}; strip would save {mb(total)} of {mb(before)}: {shown}.",
                      file=port.rel(hits[0][0]), fix="strip <file> (or link with -s) before packaging.")


# ---------------------------------------------------------------- archives
@check
def archives(port):
    for p in port.logical_files():
        if not re.search(r"\.(tar\.gz|tgz|tar\.xz|tar)$", p.name) or data.PART_RE_SPLIT.search(p.name):
            continue
        rel = port.rel(p)
        bad_owner = jdk = False
        try:
            with tarfile.open(p, "r|*") as tf:
                for n, m in enumerate(tf):
                    if (m.uid or m.gid) and not bad_owner:
                        bad_owner = (m.name, m.uid, m.gid)
                    if re.search(r"(^|/)bin/java$", m.name):
                        jdk = True
                    if n > 200_000:
                        break
        except (tarfile.TarError, OSError, EOFError) as e:
            yield Finding("archive.read", WARN, f"{rel}: could not read archive ({e}).", file=rel)
            continue
        if bad_owner:
            yield Finding("archive.owner", ERROR, f"{rel}: entries keep real ownership ({bad_owner[0]} uid {bad_owner[1]}, gid {bad_owner[2]}); "
                          "extraction fails on CFWs that run unprivileged.", file=rel,
                          fix="Rebuild with: tar czf <archive> --owner=0 --group=0 --numeric-owner <folders>")
        if jdk:
            yield Finding("runtime.bundled", WARN, f"{rel} contains a JDK. PortMaster provides JDK/JRE runtimes (squashfs) to mount instead.", file=rel)


# ---------------------------------------------------------------- licences
@check
def licences(port):
    if port.gamedir is None:
        return
    lic = next((d for d in port.gamedir.iterdir() if d.is_dir() and d.name.lower() in ("licenses", "license", "licences", "licence")), None)
    pj = json_load(port)
    attr = (pj.get("attr") or {}) if isinstance(pj, dict) else {}
    if attr.get("rtr") is True and attr.get("availability") == "paid":
        # rtr = everything ships with the port; paid = the player buys and copies in the game files
        yield Finding("port.json.rtr", ERROR, 'rtr is true but availability is "paid": the player supplies the game files, so the port is not ready to run.',
                      file=port.rel(json_load_path(port)) if json_load_path(port) else "", fix='"rtr": false')
    elif attr.get("rtr") is True and not _game_licence(port, lic, attr):
        where = port.rel(lic) if lic else f"{port.gamedir.name}/licenses"
        yield Finding("licenses.game", ERROR, "Ready-to-run port with no licence for the game itself (only library licences found).",
                      file=port.rel(json_load_path(port)) if json_load_path(port) else "",
                      fix=f"Add {where}/LICENSE.{port.gamedir.name}.txt with the game's licence, or the developer's permission to distribute (an image of it is fine).")
    if lic is None:
        return
    corpus = " ".join(f.name.lower() for f in lic.rglob("*"))
    for f in lic.rglob("*"):
        if f.is_file() and f.stat().st_size < 2_000_000:
            corpus += " " + port.read_text(f).lower()
    squashed = re.sub(r"[^a-z0-9]", "", corpus)
    tokens = set()
    for f in lic.rglob("*"):
        for t in re.split(r"[^a-z0-9+]+", f.name.lower()):
            if len(t) >= 3 and t not in ("license", "licence", "licenses", "copying", "copyright", "txt", "notice", "readme"):
                tokens.add(t)
                core = re.sub(r"\d+$", "", re.sub(r"^lib", "", t))   # libbrotli1.copyright -> brotli
                if len(core) >= 3:
                    tokens.add(core)
    main_bins = {f"{port.gamedir.name}.aarch64", port.gamedir.name}
    # the engine's own modules: unversioned libX.so files that link each other in one folder and that a program of the port links
    # (libgame.so, libsheet.so ...). Third-party libraries carry a SONAME version or stand alone.
    unversioned = {p: i for p, i in elves(port) if re.fullmatch(r"lib[\w+-]+\.so", p.name) and i["soname"] in ("", None, p.name)}
    exe_needs = {n for p, i in elves(port) if ".so" not in p.name for n in i["needed"]}
    own_modules = set()
    for p, i in unversioned.items():
        sibs = {q.name for q in unversioned if q.parent == p.parent and q != p}
        linked_together = bool(sibs & set(i["needed"])) or any(p.name in j["needed"] for q, j in unversioned.items() if q.parent == p.parent and q != p)
        if linked_together and any(q.name in exe_needs for q in unversioned if q.parent == p.parent):
            own_modules.add(p)
    LIB_DIR = re.compile(r"(^|/)(libs?(\.[\w]+)?|gl4es[^/]*|lib/arm64-v8a)/")
    TOOLS = re.compile(r"^(astcenc|oggenc|oggdec|ffmpeg|ffprobe|7z\w*|xdelta3?|innoextract|box64|box86|unrar|bsdtar|lz4|zstd)(\.\w+)?$")
    for p, info in elves(port):
        if p.name in main_bins or p in own_modules:
            continue
        rel = port.rel(p)
        # a component that brings its own licence tree (a JRE's legal/, a runtime's LICENSE)
        if any((d / "legal").is_dir() or any(d.glob("LICENSE*")) for d in p.parents if port.gamedir in d.parents):
            continue
        if not (LIB_DIR.search(rel) or TOOLS.match(p.name)):
            continue   # the port's own programs and engine modules
        stem = re.sub(r"^lib", "", p.name.split(".so")[0]).lower()
        stem = re.sub(r"[-.]\d+(\.\d+)*$", "", stem)
        camel = re.split(r"(?<=[a-z])(?=[A-Z])", re.sub(r"^lib", "", p.name.split(".so")[0]))[0].lower()
        cands = {re.sub(r"[^a-z0-9]", "", stem), re.split(r"[_\-.]", stem)[0], re.sub(r"file$", "", stem), camel}
        cands = {c for c in cands if len(c) > 2}
        gl = next((d.name.split(".")[0].lower() for d in p.parents if d.name.lower().startswith("gl4es")), None)
        if gl:
            cands.add(gl)
        flat = re.sub(r"[^a-z0-9]", "", stem)
        alias = data.LIB_LICENCE_ALIASES.get(flat)   # libbz2 -> bzip2: the project's name, not the library's
        if alias:
            cands.add(alias)
        if any(f.startswith(t) or t.startswith(f) for f in filter(None, (flat, alias)) for t in tokens if len(t) >= 3):
            continue
        if cands and not any(c in squashed for c in cands):
            name = gl or stem
            yield Finding("licenses.component", WARN, f"No licence found mentioning {name!r} ({port.rel(p)}).", file=port.rel(p),
                          fix=f"Add {port.rel(lic)}/LICENSE.{name}.")


GENERIC_LICENCE = re.compile(r"^(licen[cs]e|copying|eula|permission|copyright|[al]?gpl(-?v?[23](\.0)?)?|mit|bsd|zlib|unlicense)s?(\.(txt|md))?$", re.I)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def json_load_path(port):
    return port.meta_file("port.json") if port.meta else None


def _game_licence(port, lic, attr):
    """True if something in the package looks like the game's own licence or distribution permission."""
    keys = {port.gamedir.name.lower(), re.sub(r"[^a-z0-9]", "", str(attr.get("title", "")).lower())}
    keys |= {w for w in re.findall(r"[a-z0-9]{4,}", str(attr.get("title", "")).lower())}
    keys |= {"game", "permission", "eula"}
    # what the port bundles: a loose licence named after one of these is that component's, not the game's
    components = {re.sub(r"^lib", "", p.name.lower()).split(".")[0] for p, _ in elves(port, host_only=False)}
    components |= {"frt", "gl4es", "sdl", "sdl2", "godot", "love", "mono", "dotnet", "box64", "box86", "gmloader", "gmloadernext", "westonpack",
                   "openal", "zlib", "png", "ogg", "vorbis", "freetype", "portmaster", "gptokeyb", "monogame", "fna", "renpy", "python"}
    # the developer's name, from the store links (gunsandguns: LICENSE.yousfiwalid.txt)
    for st in attr.get("store") or []:
        for u in (st.get("developerurl"), st.get("gameurl")) if isinstance(st, dict) else ():
            for w in re.findall(r"[a-z0-9]{4,}", re.sub(r"^https?://(www\.)?", "", str(u or "").lower())):
                if w not in ("itch", "steampowered", "store", "https", "http", "html", "games", "gamejolt", "github", "com", "net", "org", "app", "apps"):
                    keys.add(w)
    keys.discard("")
    for f in port.gamedir.rglob("*"):
        if not f.is_file() or any(p.startswith("libs.") for p in f.relative_to(port.gamedir).parts):
            continue
        in_lic = lic is not None and lic in f.parents
        name = f.name.lower()
        if GENERIC_LICENCE.match(name):
            return True
        squashed = re.sub(r"[^a-z0-9]", "", name)
        if re.search(r"licen[cs]e|copying|eula|permission", name) and any(k in squashed for k in keys):
            return True   # turbotabletennis/turbotabletennis.license.txt: named after the game, wherever it sits
        if f.parent == port.gamedir and re.search(r"licen[cs]e|copying|eula", name):
            # loose in the game folder and named after nothing the port bundles (gunsandguns: LICENSE.yousfiwalid.txt)
            words = {w for w in re.split(r"[^a-z0-9]+", name) if len(w) >= 3} - {"license", "licence", "licenses", "licences", "copying", "eula", "txt", "md"}
            if words and not any(w in components or any(c.startswith(w) or w.startswith(c) for c in components if len(c) >= 3) for w in words):
                return True
        if in_lic and (name.endswith(IMAGE_EXT) or any(k in re.sub(r"[^a-z0-9]", "", name) for k in keys)):
            return True
    return False


@check
def duplicate_scripts(port):
    """Two near-identical helper scripts (a 32-bit and a 64-bit copy of one setup): one script with a switch is half the review."""
    if port.gamedir is None:
        return
    cands = []
    for p in port.logical_files():
        if p in port.scripts or re.search(r"(^|/)licen[cs]es?/", port.rel(p), re.I):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if not 4096 <= size <= 1_000_000:
            continue
        if p.suffix.lower() in (".sh", ".py", ".bash"):
            cands.append(p)
        elif not p.suffix:
            with p.open("rb") as fh:
                if fh.read(2) == b"#!":
                    cands.append(p)
    cands = sorted(cands, key=lambda x: port.rel(x))[:40]
    texts = {p: [l.strip() for l in port.read_text(p).splitlines() if l.strip() and not l.strip().startswith("#")] for p in cands}   # code lines: comments differ first
    done = set()
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a in done or b in done:
                continue
            if min(len(texts[a]), len(texts[b])) < 60:
                continue
            sm = difflib.SequenceMatcher(None, texts[a], texts[b], autojunk=False)
            if sm.quick_ratio() >= 0.9 and sm.ratio() >= 0.9:
                done |= {a, b}
                yield Finding("files.duplicate-script", INFO, f"{port.rel(a)} and {port.rel(b)} are {sm.ratio():.0%} the same script; every fix has to be made twice.",
                              file=port.rel(b), fix="Keep one script and pass the difference as an argument or variable.")


@check
def pr_scope(port):
    """Files the pull request changes outside ports/ (PR mode, --pr-files)."""
    outside = [x for x in getattr(port, "pr_outside", None) or [] if not x.startswith("ports/")]
    if not outside:
        return
    rt = [x for x in outside if x.startswith("runtimes/")]
    rest = [x for x in outside if x not in rt]
    if rt:
        yield Finding("pr.outside-ports", WARN, f"The pull request also adds {', '.join(rt[:3])}{' and more' if len(rt) > 3 else ''}. A runtime goes in its own pull request, "
                      "reviewed and merged before the port that needs it.", fix="Remove it from this PR and open a separate one for the runtime.")
    if rest:
        yield Finding("pr.outside-ports", WARN, f"The pull request changes files outside ports/: {', '.join(rest[:5])}{' and more' if len(rest) > 5 else ''}.",
                      fix="A port PR only touches ports/<name>/; move other changes to their own PR.")


# ---------------------------------------------------------------- launch script
BOILER = re.compile(r"^XDG_DATA_HOME=")


@check
def launch_script(port):
    for s in port.scripts:
        yield from _script(port, s)


def _assigns(code):
    return dict(re.findall(r"^\s*(?:export\s+|local\s+)?(\w+)=\"?([^\"\s;]+)\"?\s*$", "\n".join(l for _, l in code), re.M))


def _port_path(port, arg, assigns):
    """A script path (quoted, with $VARS from simple assignments) as a file in the package, or None."""
    arg = arg.strip("\"'")
    for _ in range(3):
        arg = re.sub(r"\$\{?(\w+)\}?", lambda v: assigns.get(v.group(1), v.group(0)) if v.group(1) not in ("GAMEDIR", "directory", "HOME") else v.group(0), arg)
    if port.gamedir is None or "controlfolder" in arg:
        return None
    if "$" in arg:
        t = _resolve(port, arg)
    elif not arg.startswith(("/", "~")):
        t = port.gamedir / arg.removeprefix("./")
    else:
        t = None
    return t if t is not None and t.is_file() else None


def _functions(code):
    """name -> (first line, last line) of shell functions defined at the top level."""
    out, cur = {}, None
    for n, l in code:
        m = re.match(r"\s*(?:function\s+)?(\w+)\s*\(\)\s*\{?\s*$", l)
        if cur is None and m:
            cur = (m.group(1), n)
        elif cur is not None and re.match(r"\}\s*$", l):
            out[cur[0]] = (cur[1], n)
            cur = None
    return out


def _script_parts(port, s, code=None):
    """[(file, [(line, code line)])]: the launch script plus the helpers it sources from the port folder."""
    if code is None:
        code = [(n, l) for n, l in enumerate(port.read_text(s).splitlines(), 1) if not l.strip().startswith("#")]
    assigns = _assigns(code)
    helpers = []
    for n, l in code:
        # also "[ -f x ] && . x" and "then source x"
        for m in re.finditer(r"(?:^|&&|\|\||;|\bthen\b|\bdo\b)\s*(?:source|\.)\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)", l):
            t = _port_path(port, m.group(1), assigns)
            if t is not None and t not in helpers and t not in port.scripts:
                helpers.append(t)
    return [(port.rel(s), code)] + [(port.rel(h), [(n, l) for n, l in enumerate(port.read_text(h).splitlines(), 1) if not l.strip().startswith("#")])
                                    for h in helpers]


def reinvent_score(port, findings):
    """sh.reinvented: a launch script that redoes much of what PortMaster's own files do. One finding with every block
    and its PortMaster replacement; the wording describes the script, never the porter."""
    scripts = [sc for sc in port.scripts if len([l for l in port.read_text(sc).splitlines() if l.strip() and not l.strip().startswith("#")]) > 8]
    if not scripts:
        return None
    s = max(scripts, key=lambda sc: len(port.read_text(sc)))
    text = port.read_text(s)
    parts = _script_parts(port, s)
    raw_all = text + "\n" + "\n".join(port.read_text(port.root / p) for p, _ in parts[1:])
    n_code = len([l for _, l in parts[0][1] if l.strip()])
    funcs = len(re.findall(r"^\s*(?:function\s+)?[\w-]+\s*\(\)\s*(?:\{|$)", raw_all, re.M))
    points, blocks = 0, []
    p99 = data.SCRIPT_P99
    if n_code > 4 * p99:
        points += 3
    elif n_code > 2 * p99:
        points += 2
    elif n_code > p99:
        points += 1
    if funcs >= 8:
        points += 2
    elif funcs >= 3:
        points += 1
    if re.search(r"generated by|auto-?generated", raw_all, re.I):
        points += 2
        blocks.append((parts[0][0], 0, "was produced by a script generator", "a launch script written from a merged port of the same engine"))
    for key, rx, need, what, instead in data.REINVENT_SIGNALS:
        hits = [(where, n) for where, c in parts for n, l in c if re.search(rx, l)]
        if len(hits) >= need:
            points += 1
            blocks.append((hits[0][0], hits[0][1], what, instead))
    rules_hit = {f.rule for f in findings if f.rule in data.REINVENT_RULES or (f.rule == "sh.nonstandard" and f.severity == WARN)}
    points += len(rules_hit)
    com = next((f for f in findings if f.rule == "sh.comments"), None)
    if com and com.message.count(",") >= 3:
        points += 1
    if points < data.REINVENT_WARN:
        return None
    sev = ERROR if points >= data.REINVENT_ERROR else WARN
    others = len(rules_hit)
    listed = len([b for b in blocks if b[2] != "was produced by a script generator"])
    msg = (f"This launch script does a lot of work that PortMaster already does for every port: {n_code} lines of code where most merged ports "
           f"need about {data.SCRIPT_MEDIAN} (99% stay under {(p99 + 9) // 10 * 10})"
           + (f", {funcs} shell functions" if funcs >= 3 else "")
           + (f", and {listed} block{'s' if listed != 1 else ''} that PortMaster's own files already cover (see the list)" if listed else "")
           + (f"; the other notes in this report point out {others} more" if others else "") + ". "
           "Blocks like these are hard to test on every CFW and stop working when a CFW changes, while PortMaster's files are kept up to date "
           "for all ports at once, so reviewers will ask for a shorter script built on them. Scripts like this usually come from an AI assistant "
           "that wasn't given PortMaster's conventions; using one is fine, it just needs the right reference.")
    peer, _ = peers.closest(text, exclude=port.gamedir.name if port.gamedir is not None else None)
    example = f", or a merged port of the same kind such as {peer['name']}: {peers.url(peer)}" if peer else ""
    tpl = templates.pick(text, [x.name for x in port.files()])[0]
    fix = (f"1) Start from {templates.name(tpl)}{example}. "
           f"2) If you work with an AI assistant, give it the PortMaster porting reference pinned in #your-first-port ({data.FIRST_PORT_CHANNEL}). "
           "3) Replace each listed block with what PortMaster provides, and remove any block you can't explain; most merged scripts are short. "
           "4) If AI helped, mention it in the PR: that's welcome and helps the reviewers. Questions are welcome in #compile-help before you submit.")
    blocks.sort(key=lambda b: (b[0] != port.rel(s), b[0], b[1]))
    snippet = "\n".join(f"{where}{':' + str(n) if n else ''}: {what} -> {instead}" for where, n, what, instead in blocks) or None
    first = next((b for b in blocks if b[1]), None)
    return Finding("sh.reinvented", sev, msg, file=port.rel(s), line=first[1] if first and first[0] == port.rel(s) else 0, fix=fix,
                   snippet=snippet)


@check
def script_lean(port):
    """Steps a shorter script would not need: copying the port's libraries into the game data, steam_appid.txt next to
    a Steam stub, save copies inside the port folder, long custom functions, and length against the closest merged port."""
    box64 = any(re.search(r"\bbox64\b", port.read_text(sc)) for sc in port.scripts)
    stub = any(f.name.startswith("libsteam_api") and "gamedata" not in port.rel(f).lower() for f in port.files())
    for s in port.scripts:
        f = port.rel(s)
        text = port.read_text(s)
        code = [(n, l) for n, l in enumerate(text.splitlines(), 1) if not l.strip().startswith("#")]
        if len([l for _, l in code if l.strip()]) <= 8:
            continue
        # the port's own libraries copied or moved into the player's game files on every launch
        def _dest(l):
            try:
                toks = shlex.split(l.split(" #")[0])
            except ValueError:
                return ""
            return toks[-1] if toks else ""
        lib_moves = [(n, l) for n, l in code if re.match(r"\s*(\$\{?ESUDO\}?\s+)?(cp|mv)\b[^#]*\.so\b", l)
                     and not re.search(r"\s/(tmp|dev)/|\$\{?(TMPDIR|RUNDIR)\b|\bmonodir\b|MONOMODDED|\.dll\.so", l)
                     and not re.match(r"\s*(\$\{?ESUDO\}?\s+)?cp\b[^#]*\s/usr/lib", l)
                     and not re.search(r"/libs?(\.[\w]+)?(/|$)", _dest(l))]   # within the port's own library folder
        if lib_moves:
            how = ("box64 loads them where they are: `BOX64_LD_LIBRARY_PATH=\"$GAMEDIR/libs.x86_64\"` for libraries and `BOX64_LD_PRELOAD=\"$GAMEDIR/<stub>.so\"` "
                   "for a stub that has to win, as the Papers, Please port does") if box64 else \
                  "`LD_LIBRARY_PATH`, or `LD_PRELOAD` on the game's command, loads them from the port folder"
            more = f" (also lines {', '.join(str(n) for n, _ in lib_moves[1:4])})" if len(lib_moves) > 1 else ""
            yield Finding("sh.player-files", INFO, f"The script copies or renames libraries inside the game files on every launch{more}. "
                          f"That changes the player's own copy of the game, and it isn't needed: {how}.",
                          file=f, line=lib_moves[0][0], fix="Load the libraries from the port folder and leave the game files as the player copied them.")
        appid = next(((n, l) for n, l in code if re.search(r"(>|tee\s)\s*\"?[^\s\"]*steam_appid\.txt", l)), None)
        if appid and stub:
            yield Finding("sh.steam-appid", INFO, "The script writes `steam_appid.txt`, but the port ships its own `libsteam_api` stub, and only Steam's real library reads that file.",
                          file=f, line=appid[0], fix="Drop the line.")
        # saves copied out of a folder inside the port and back in: that folder already lives on the SD card
        conf_rx = r"\$\{?CONFDIR\}?|\$\{?GAMEDIR\}?/conf\b"
        cps = [(n, m.group(0).strip()) for n, l in code for m in re.finditer(r"(?:^|;|&&|\bdo\b|\bthen\b)\s*(?:cp|rsync)\s[^;&|]+", l)]
        to_conf = [n for n, c in cps if re.search(r"(" + conf_rx + r")[^\s\"]*/?\"?\s*$", c)]
        from_conf = [n for n, c in cps if re.search(r"\s\"?(" + conf_rx + r")", c) and not re.search(r"(" + conf_rx + r")[^\s\"]*/?\"?\s*$", c)]
        loops = [n for n, l in code if re.match(r"\s*for\s+\w+\s+in\s[^#]*(" + conf_rx + r")", l)]
        if (to_conf and from_conf) or (to_conf and loops):
            yield Finding("sh.save-mirror", INFO, "The script copies save files into `conf/` and back. The folder the game writes to is already inside the port folder, "
                          "so the saves are kept without the copies.", file=f, line=min(to_conf + from_conf + loops),
                          fix="Let the game keep its saves where it writes them; use `bind_directories` only when the game writes outside the port folder.")
        for name, (a, b) in _functions(code).items():
            body = [l for n, l in code if a < n < b and l.strip()]
            if len(body) > 20:
                yield Finding("sh.long-function", INFO, f"`{name}()` is {len(body)} lines, a feature of its own inside the launch script. Reviewers will ask whether players need it; "
                              "most merged scripts have no functions at all.", file=f, line=a,
                              fix="Keep it only if the port needs it, and say in the PR what it does.")
        # $HOTKEY is set per device by control.txt; gptokeyb2's default otherwise is Select (state.c)
        hk = next(((n, l) for n, l in code if re.match(r"\s*(export\s+)?HOTKEY=", l)), None)
        if hk:
            yield Finding("sh.hotkey-override", WARN, "The script sets `HOTKEY` itself. `control.txt` sets it on the devices that need another button (L3 on the OGA 1.0 "
                          "and Gameforce Chi, Guide on the RGB10 Max with ArkOS); elsewhere gptokeyb2 uses Select. A fixed value moves the exit combo on every "
                          "other device, e.g. Guide + Start on handhelds without a Guide button.", file=f, line=hk[0], fix="Drop the line; `control.txt` picks the hotkey per device.")
        # the port downloading its own updates: PortMaster installs and updates ports
        upd = next(((n, l) for n, l in code if re.search(r"autoinstall|\b(curl|wget)\b[^#]*https?://|update\.py", l)
                    and not re.search(r"harbourmaster|runtime_check", l)), None)
        if upd:
            yield Finding("sh.self-update", WARN, "The launch script fetches or installs updates by itself. PortMaster installs and updates ports, "
                          "so a port that does it alone can bypass review and break when the device is offline.", file=f, line=upd[0],
                          fix="Drop the update step and publish new versions through PortMaster.")
        # every logic line that neither the engine's template, the documented patterns nor the closest merged port has
        n_code = len([l for _, l in code if l.strip()])
        k = peers.kind(peers.tags(text))
        med = peers.kind_median(k)
        limit = max(data.SCRIPT_P95, int(1.5 * med)) if med else data.SCRIPT_P99
        peer, _ = peers.closest(text, exclude=port.gamedir.name if port.gamedir is not None else None)
        keys = templates.pick(text, [x.name for x in port.files()])
        extra = templates.extra_lines(text, keys, peer["keys"] if peer else (), frozenset(data.SCRIPT_LINES["lines"]))
        ind = peers.indirect_launch(text)   # reported by sh.launch-indirection
        extra = [(n, raw) for n, raw in extra if not ind or n != ind[0]]
        ref = f"the closest merged port, {peer['name']}: {peers.url(peer)}" if peer else "merged ports of the same kind"
        length = (f"{n_code} lines of code, where merged {k.replace('+', ' + ')} ports have a median of {med or data.SCRIPT_MEDIAN}. ") if n_code > limit else ""
        if len(extra) >= data.TEMPLATE_DIFF_MIN:
            blocks = []
            for n, raw in extra:
                if blocks and n - blocks[-1][1] <= 2:
                    blocks[-1][1] = n
                else:
                    blocks.append([n, n, raw])
            compare = f"Compare it with {templates.describe(keys)}" + (f" and with {peer['name']}, the closest merged port: {peers.url(peer)}" if peer else "")
            yield Finding("sh.template-diff", INFO, f"{length}Nothing below is an error. {len(extra)} lines differ from the template and the closest merged port, so reviewers will ask what each one is for. "
                          "The ones PortMaster or the runtime already handle can go; the rest are fine with a one-line comment.",
                          file=f, line=extra[0][0], snippet=_listing(blocks),
                          fix=f"{compare}. Keep a block when a real device needs it, with a one-line comment saying which.")
        elif length:
            yield Finding("sh.length", INFO, f"{length}It follows its template otherwise.", file=f, fix=f"Compare it with {ref} to see what can be shorter.")


@check
def launch_indirection(port):
    """The script hands the game over to another script. Merged ports run helpers (patching, settings) before the
    engine's own command; none starts the game through a script (tools/build_port_files.py)."""
    for s in port.scripts:
        hit = peers.indirect_launch(port.read_text(s))
        if not hit:
            continue
        n, line = hit
        total = data.PORT_FILES["indirect_launch"]["scripts"]
        hidden = []
        m = re.search(r"[^\s\"']+\.(?:py|sh)\b", line)
        target = next((c for c in ((port.gamedir / m.group(0)), (port.root / m.group(0))) if m and c.is_file()), None) if port.gamedir is not None else None
        if target is not None:
            body = port.read_text(target)
            for rx, what in ((r"GPTOKEYB", "starts gptokeyb (so the kill-switch name rules cannot be checked)"),
                             (r"LD_PRELOAD", "sets `LD_PRELOAD` for the game"), (r"\bsubprocess\b|os\.system|os\.exec", "starts other processes")):
                if re.search(rx, body):
                    hidden.append(what)
        extra = (f" `{port.rel(target)}` also {', '.join(hidden[:-1]) + (' and ' if len(hidden) > 1 else '') + hidden[-1]}: that happens where the script checks do not look." if hidden else "")
        yield Finding("sh.launch-indirection", WARN, f"The script starts the game through another script (`{line[:80]}`) and then waits for it. "
                      f"None of the {total} merged launch scripts does that: they run helpers for patching or settings first, then start the engine "
                      "or the game binary from the script itself, so reviewers and testers can read what runs." + extra,
                      file=port.rel(s), line=n,
                      fix="Start the game binary or runtime from the launch script, as the template for this kind of port does, and move what the extra script "
                          "adds into the game or into PortMaster's own helpers.")


@check
def extra_code(port):
    """Python of the port's own, beyond the helpers merged ports share (gmKtool.py, GMblob.py ...): ports of an ordinary kind
    ship at most data.PORT_FILES['own_code']['max'] lines of it."""
    if port.gamedir is None or not port.scripts:
        return
    if peers.kind(peers.tags(port.read_text(port.scripts[0]))) in peers.ENGINE_SCRIPT_KINDS or _runs_python_game(port.read_text(port.scripts[0])):
        return
    shared, own = data.PORT_FILES["shared"], []
    for p in port.logical_files():
        if p.suffix != ".py":
            continue
        text = p.read_bytes().decode("utf8", "replace")
        if hashlib.sha1(text.encode()).hexdigest() in shared:
            continue
        own.append((len([l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]), p))
    total, ref = sum(n for n, _ in own), data.PORT_FILES["own_code"]
    if total <= ref["max"]:
        return
    top = sorted(own, key=lambda x: -x[0])[:3]
    yield Finding("files.extra-code", WARN, f"The package ships {total} lines of Python of its own in {len(own)} files "
                  f"({', '.join(f'{port.rel(p)} {n}' for n, p in top)}). Merged ports of this kind ship at most {ref['max']} lines "
                  f"outside the shared patcher helpers (gmKtool.py, GMblob.py ...), and only {ref['ports']} of {data.PORT_FILES['scripts']} ports ship any, "
                  "mostly small game tools. Code like this has to be read line by line in review, and it runs on the handheld as root.",
                  file=port.rel(top[0][1]),
                  fix="Keep the launch in the script and PortMaster's helpers; put game features into the game itself. If a patch step needs a tool, "
                      "use a shared Patcher helper or a short `tools/patchscript`.")


# rm -r on "$VAR/*", "$VAR"/* or "$VAR/": with an empty VAR that is /* (the ports run as root)
_RM_BELOW = re.compile(r"(?<![\w$])\"?\$\{?([A-Za-z_]\w*)(:\?[^}]*)?\}?\"?(?:/\*|/\"?\*|/)\"?(?=\s|$|;|&|\)|\|)")
_RM_PM_VARS = {"controlfolder", "directory", "DEVICE_ARCH", "CFW_NAME", "PWD", "HOME"}


def _var_safe(text, v, launch, depth=0):
    """True when the script itself gives VAR a value that cannot be empty: PortMaster's own variables, GAMEDIR in a launch
    script, $PWD, a literal absolute path, or a path below one of those."""
    if v in _RM_PM_VARS or (v == "GAMEDIR" and launch):
        return True
    values = re.findall(r"^\s*(?:export\s+|local\s+|declare\s+(?:-\w+\s+)?)?" + re.escape(v) + r"=(.*?)\s*(?:#.*)?$", text, re.M)
    if not values:
        return False
    for x in (x.strip().strip("\"'") for x in values):
        m = re.match(r"^\$\{?(\w+)\}?/\S", x)
        if m and depth < 4 and _var_safe(text, m.group(1), launch, depth + 1):
            continue
        if x in ("$PWD", "$(pwd)", "$(pwd -P)") or re.match(r"^\$\{?PWD\}?/\S", x):
            continue
        if re.match(r"^/[\w.\-]+(/[\w.\-]+)+$", x):
            continue
        return False
    return True


def rm_below_variable(text, launch):
    """[(line, variable, line text)] for rm -r on a variable's contents where the variable may be empty."""
    out, lines = [], text.splitlines()
    for i, l in enumerate(lines):
        t = l.strip()
        if t.startswith("#"):
            continue
        # only the operands of the rm itself: not a case pattern or an mv on the same line
        ops = [x.group(1) for x in re.finditer(r"\brm\s+(?:-\w+\s+)*-\w*[rR]\w*\s+((?:[^;&|)]|\\\n)*)", t)]
        for m in (m for o in ops for m in _RM_BELOW.finditer(o)):
            v = m.group(1)
            ctx = " ".join(x.strip() for x in lines[max(0, i - 3):i + 1])
            if m.group(2) or re.search(r"\[\[?\s+(?:!\s+)?-[dnze]\s+\"?\$\{?" + re.escape(v) + r"\b", ctx) or _var_safe(text, v, launch):
                continue
            out.append((i + 1, v, t[:100]))
    return out


def _script_files(port):
    """[(path, text, is_launch_script)] for the launch scripts and the patchscripts they hand to PortMaster's Patcher."""
    out, seen = [], set()
    for s in port.scripts:
        text = port.read_text(s)
        out.append((s, text, True))
        for m in re.finditer(r"PATCHER_FILE=[\"']?([^\"'\s]+)", text):
            t = _resolve(port, m.group(1))
            if t is not None and t.is_file() and t not in seen:
                seen.add(t)
                out.append((t, port.read_text(t), False))
    return out


@check
def rm_variable(port):
    """rm -rf "$DIR"/* where DIR is not known to hold a path: 1 of 1428 merged scripts (Wargus) has one, tools/build_port_files.py."""
    if port.gamedir is None:
        return
    for path, body, launch in _script_files(port):
        for n, v, line in rm_below_variable(body, launch):
            origin = ("is never given a value in this script" if not re.search(r"^\s*(?:export\s+|local\s+)?" + re.escape(v) + r"=", body, re.M)
                      else "is set from something that can be empty")
            yield Finding("sh.rm-variable", WARN, f"`{line}` removes everything below ${v}, and {v} {origin}. If it is ever empty the command becomes "
                          "`rm -rf /*`, and ports run as root.", file=port.rel(path), line=n,
                          fix=f'Write `rm -rf "${{{v}:?}}"/*` (the script stops when {v} is empty) or test `[ -d "${v}" ]` first, as the merged Patcher scripts do.')


def _code_lines(text):
    return [(n, l.strip()) for n, l in enumerate(text.splitlines(), 1) if l.strip() and not l.strip().startswith("#")]


@check
def script_hygiene(port):
    """Practices measured on the merged launch scripts and patchscripts (docs/patchscripts.md): chmod 777 on files, downloads while
    running, unquoted rm -r, a patchscript that detects PortMaster again, a patchscript longer than any merged one."""
    if port.gamedir is None:
        return
    for path, body, launch in _script_files(port):
        f, code = port.rel(path), _code_lines(body)
        # chmod 777 on files (chmod 666 /dev/uinput is the boilerplate and fine)
        c = [(n, l) for n, l in code if re.search(r"\bchmod\s+(?:-\w+\s+)*777\b", l)]
        if c:
            rec = any(re.search(r"\s-\w*R", l) for _, l in c)
            yield Finding("sh.chmod-777", INFO, f"`{c[0][1][:70]}` (line {c[0][0]}" + (f", and {len(c) - 1} more" if len(c) > 1 else "") + ") sets mode 777. "
                          "The ports partition is FAT/exFAT and ignores modes, and on a CFW that honours them 777 makes the files writable by everyone"
                          + (" (here recursively for a whole folder)" if rec else "") + ". Executables only need `+x`.",
                          file=f, line=c[0][0], fix='$ESUDO chmod +x "$GAMEDIR/tools/<tool>"')
        # a download while the script runs
        net = [(n, l) for n, l in code if re.search(r"(?:^|[\s;&|(])(?:curl|wget)\s|\bgit\s+clone\b|\bpip3?\s+install\b|\bapt(?:-get)?\s+install\b", l)]
        if net:
            yield Finding("sh.network", WARN, f"The {'script' if launch else 'patchscript'} downloads while it runs (`{net[0][1][:80]}`). The file is not reviewed with the port, "
                          "the handheld may be offline, and the source can change or disappear. 4 of 1428 merged launch scripts and 1 patchscript do this.",
                          file=f, line=net[0][0],
                          fix="Ship the file in the port if its licence allows, or ask the player to copy it as with other game files. If a download is unavoidable, "
                              "check that it worked and show `pm_show_error` when it did not.")
        # unquoted variables after rm -r
        def _unquoted(l):
            m = re.search(r"\brm\s+((?:-\w+\s+)+)(.*)", l)
            if not m or not re.search(r"-\w*[rR]", m.group(1)):
                return False
            rest = re.split(r"\s*(?:[;&|>]|2>)", m.group(2))[0]
            for _ in range(3):   # a command substitution inside quotes may hold quotes of its own
                rest = re.sub(r"\$\([^()]*\)", "", rest)
            return "$" in re.sub(r'"[^"]*"|\'[^\']*\'', "", rest)
        uq = [(n, l) for n, l in code if _unquoted(l)]
        if uq:
            yield Finding("sh.unquoted-rm", INFO, f"`{uq[0][1][:70]}` (line {uq[0][0]}" + (f", and {len(uq) - 1} more lines" if len(uq) > 1 else "") + ") removes files "
                          "with a variable outside quotes. A path with a space splits into several arguments, and an empty variable drops out of the command.",
                          file=f, line=uq[0][0], fix='Quote it: `rm -rf "$DATADIR"/*.exe`.')
        if launch:
            # the PortMaster detection block: all but 2 of the 1423 merged scripts that have it use only the standard branches
            hdr, found = [], False
            for n, l in code:
                if re.match(r"(source|\.)\s+\"?\$\{?controlfolder\}?/control\.txt", l.strip()):
                    found = True
                    break
                hdr.append((n, l.strip()))
            if found and any(l.startswith("XDG_DATA_HOME") for _, l in hdr):
                std = ('XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}', 'if [ -d "/opt/system/Tools/PortMaster/" ]; then', 'controlfolder="/opt/system/Tools/PortMaster"',
                       'elif [ -d "/opt/tools/PortMaster/" ]; then', 'controlfolder="/opt/tools/PortMaster"', 'elif [ -d "$XDG_DATA_HOME/PortMaster/" ]; then',
                       'controlfolder="$XDG_DATA_HOME/PortMaster"', "else", 'controlfolder="/roms/ports/PortMaster"', "fi")
                odd = [(n, l) for n, l in hdr if l and l not in std and re.match(r"(?:if|elif|else|\[|\[\[|\$|controlfolder=|[a-z_]+\()", l)]
                if odd:
                    yield Finding("sh.header-modified", WARN, f"The PortMaster detection block at the top of the script is not the standard one: {len(odd)} line{'s' if len(odd) > 1 else ''} "
                                  f"differ (`{odd[0][1][:70]}`, line {odd[0][0]}). All but 2 of the 1423 merged scripts that have the block use exactly these branches. "
                                  "A port with its own search order can pick another PortMaster folder than every other port on the same device, and nobody can tell from the "
                                  "script alone which CFW needs the extra branch.",
                                  file=f, line=odd[0][0], fix="Use the header from the template unchanged. If a CFW installs PortMaster somewhere the header misses, that fix belongs in the template, for every port.")
            gc = [(n, l) for n, l in code if re.match(r"get_controls\b", l.strip())]
            if gc:
                nxt = next(((n, l) for n, l in code if n > gc[0][0]), None)
                if nxt and re.match(r"\w+=\$\?\s*$", nxt[1].strip()):
                    yield Finding("sh.controls-status", WARN, f"The script keeps the result of `get_controls` (`{nxt[1].strip()}`, line {nxt[0]}) and stops later when it is not 0. None of the "
                                  f"{data.PORT_FILES['scripts']} merged scripts does this. `get_controls` sets up the controls and the script does not need its exit code: "
                                  "a failure there shows as a game without controls, and the port keeps running on every PortMaster version the other ports support.",
                                  file=f, line=nxt[0], fix="Call `get_controls` on its own line, as the template does, and drop the status checks.")
            gd = [(n, l) for n, l in code if re.search(r"(?:^|&&\s*|;\s*|\bthen\s+)(?:export\s+)?GAMEDIR=", l.strip())]
            if len(gd) > 1:
                yield Finding("sh.gamedir-search", WARN, f"The script looks for its own game folder: `GAMEDIR` is set a second time, e.g. from a search loop (line {gd[-1][0]}). "
                              f"Merged scripts set it once, `GAMEDIR=\"/$directory/ports/<name>\"`, because `control.txt` already says where the ports folder is. "
                              "A search over `$0` and relative folders finds a different copy of the port than the one PortMaster installed, and has to be re-checked on every CFW.",
                              file=f, line=gd[-1][0], fix='GAMEDIR="/$directory/ports/portname"')
            lp = next(((n, l) for n, l in code if re.match(r"exec\s*>\s*>\(", l.strip()) and not re.match(r"exec\s*>\s*>\(\s*tee\b", l.strip())), None)
            if lp:
                yield Finding("sh.log-pipeline", WARN, f"The log goes through a pipeline of its own (`{lp[1].strip()[:70]}`, line {lp[0]}). The template and the other merged scripts use "
                              "`exec > >(tee \"$GAMEDIR/log.txt\") 2>&1`. A custom pipeline cuts or loses the log exactly when something went wrong, and a tester cannot send it.",
                              file=f, line=lp[0], fix='exec > >(tee "$GAMEDIR/log.txt") 2>&1')
            pg = next(((n, l) for n, l in code if re.search(r"\b(?:declare\s+-F|type|command\s+-v)\s+pm_\w+|pm_(?:show_error|message)\b[^#\n]*\|\|\s*:", l)), None)
            if pg:
                yield Finding("sh.pm-guard", INFO, f"The script asks whether `pm_*` functions exist before it calls them (`{pg[1].strip()[:70]}`, line {pg[0]}). `control.txt` loads `funcs.txt`, "
                              "and the template calls `pm_message`, `pm_show_error` and `pm_finish` directly. 1 of 1428 merged scripts guards them.",
                              file=f, line=pg[0], fix="Call the functions directly, as the template does.")
            tr = next(((n, l) for n, l in code if re.match(r"trap\s+(?:'[^']*'|\"[^\"]*\")\s+(?:\w+\s+)*(?:TERM|INT|SIGTERM|SIGINT)\b", l.strip())), None)
            if tr:
                yield Finding("sh.signal-handling", WARN, f"The script handles TERM/INT itself and forwards them to a child (`{tr[1].strip()[:70]}`, line {tr[0]}). None of the merged scripts does: "
                              "gptokeyb2 stops the game with its hotkey, and `pm_finish` cleans up afterwards. Own signal code has to be right on every shell the CFWs ship.",
                              file=f, line=tr[0], fix="Start the game in the foreground as the template does and let gptokeyb2 and `pm_finish` end it.")
            um = next(((n, l) for n, l in code if re.match(r"umask\s+\d+", l)), None)
            if um:
                yield Finding("sh.umask", WARN, f"`{um[1][:40]}` (line {um[0]}) changes the file mode for everything the script and the game create. None of the "
                              f"{data.PORT_FILES['scripts']} merged launch scripts does this. The ports partition ignores modes, and on a CFW that honours them "
                              "saves and logs become unreadable for the other users of the device (file manager, FTP, SMB, the next PortMaster update).",
                              file=f, line=um[0], fix="Drop the line.")
            mk = next(((n, l) for n, l in code if re.search(r"\bmktemp\b[^#]*(?:GAMEDIR|logs?/|\.log)", l)), None)
            if mk and not any(re.search(r"\b(?:rm|find)\b[^#]*(?:logs?\b|launch\.)", l) for _, l in code):
                yield Finding("sh.log-per-launch", WARN, f"Every launch writes a new log file (`{mk[1][:70]}`, line {mk[0]}) and nothing deletes the old ones. Merged ports write "
                              "one `log.txt` and truncate it on the next launch; here the folder grows by a file on every launch, on the SD card.",
                              file=f, line=mk[0], fix='Write one file: `> "$GAMEDIR/log.txt" 2>&1` (the template does `exec > >(tee "$GAMEDIR/log.txt") 2>&1`).')
        if not launch:
            # control.txt already exported controlfolder and DEVICE_ARCH to the patchscript
            det = [(n, l) for n, l in code if re.match(r"(?:export\s+)?controlfolder=|source\s+\"?\$\{?controlfolder\}?/control\.txt", l)]
            if det:
                yield Finding("patcher.controlfolder", INFO, f"The patchscript looks for PortMaster again (line {det[0][0]}). The launch script has already sourced control.txt, "
                              "which exports `controlfolder` and `DEVICE_ARCH`, so the patchscript can use them as they are.", file=f, line=det[0][0],
                              fix='Delete the detection block and use `"$controlfolder/xdelta3"`.')
            L = [(n, l.strip()) for n, l in code]
            fn_of, cur = {}, None
            for n, raw in enumerate(body.splitlines(), 1):
                m = re.match(r"\s*(?:function\s+)?(\w+)\s*\(\)\s*\{?", raw)
                if m:
                    cur = m.group(1)
                if cur:
                    fn_of[n] = cur
                if cur and re.match(r"\}", raw):
                    cur = None
            xd = [i for i, (_, l) in enumerate(L) if re.search(r"(?:^|[;&|(]\s*|\$ESUDO\s+|\bif\s+!?\s*)\"?(?:[^\s\"=]*/)?xdelta3?\"?\s+(?:-\S+\s+)*-\w*d\b", l)]
            if xd:
                setE = re.search(r"^\s*set\s+-\w*e", body, re.M)
                def _checked(i):
                    l = L[i][1]
                    if l.rstrip().endswith("&"):   # started in the background and waited for
                        return True
                    nxt = " ".join(x for _, x in L[i + 1:i + 3])
                    prev = L[i - 1][1] if i else ""
                    if setE or re.search(r"\|\||&&|\bif\b|\$\?", l) or re.search(r"\$\?|^\s*if\b", nxt) or re.match(r"if\b", prev):
                        return True
                    fn = fn_of.get(L[i][0])   # the function ends with the call: its callers decide
                    if fn and i + 1 < len(L) and L[i + 1][1].startswith("}"):
                        return any(re.search(rf"(?:\|\||&&|\bif\s+!?\s*){fn}\b|\b{fn}\b[^\n]*(?:\|\||&&)", x) or (re.match(rf"{fn}\b", x) and re.match(r"(?:if\b|\$\?)", y))
                                   for (_, x), (_, y) in zip(L, L[1:] + [(0, "")]))
                    return False
                bad = [i for i in xd if not _checked(i)]
                if bad:
                    rm = any(re.match(r"(?:\$ESUDO\s+)?rm\s", x) for _, x in L[bad[0] + 1:])
                    yield Finding("patcher.xdelta-unchecked", WARN, f"The result of xdelta3 is not checked (`{L[bad[0]][1][:70]}`, line {L[bad[0]][0]}). "
                                  "When the patch does not fit the player's files, the script goes on" + (" and deletes files afterwards, so the original can be gone for nothing" if rm else "")
                                  + " and the Patcher shows a success screen. 19 of the 83 merged patchscripts that run xdelta3 do this; the rest check it.",
                                  file=f, line=L[bad[0]][0],
                                  fix='"$controlfolder/xdelta3" -d -s "$IN" -f "$PATCH" "$OUT" || { echo "PATCH_FAIL_MSG:The patch does not fit these game files."; echo "Patching process failed!"; exit 1; }')
            if xd and not any(re.search(r"\[\[?\s+!?\s*-[fedrs]\s|\btest\s+-[fed]\s", l) for _, l in L):
                yield Finding("patcher.no-input-check", INFO, "The patchscript runs xdelta3 but never checks that the game file it patches exists (2 of the 83 merged ones). "
                              "A missing file turns into a tool error that the Patcher reports as success.", file=f,
                              fix='[ -f "$DATADIR/data.win" ] || { echo "PATCH_FAIL_MSG:data.win is missing."; echo "Patching process failed!"; exit 1; }')
            hp = next(((n, l) for n, l in L if re.search(r"(?:^|[\s\"'=])/(?:roms|storage|mnt)\b", l) and not re.match(r"(?:export\s+)?controlfolder=", l)), None)
            if hp:
                yield Finding("patcher.hardcoded-path", INFO, f"The patchscript names a device path (`{hp[1][:70]}`, line {hp[0]}). The ports folder is `/roms`, `/storage` or `/mnt/...` depending on the CFW, "
                              "so the path is wrong on the others. 1 of 135 merged patchscripts does this.", file=f, line=hp[0], fix='Use `$GAMEDIR`, `$directory` or `$controlfolder`.')
            top = data.PORT_FILES["patchscript"]["max"]
            if len(code) > top:
                yield Finding("patcher.length", INFO, f"The patchscript has {len(code)} lines of code. Merged patchscripts have a median of {data.PORT_FILES['patchscript']['p50']} and at most {top}.",
                              file=f, fix="Split the work the game itself could do out of the patch step, and keep the patchscript to extracting, patching and cleaning up.")


@check
def bundled_tools(port):
    """PortMaster ships xdelta3 and 7zzs next to control.txt; 33 and 22 merged ports bundle their own copies anyway."""
    if port.gamedir is None:
        return
    for p in port.logical_files():
        n = p.name.lower()
        if re.match(r"xdelta3(\.\w+)?$", n):
            yield Finding("files.bundled-tool", INFO, f"{port.rel(p)} is xdelta3, which PortMaster already ships next to control.txt.", file=port.rel(p),
                          fix='Drop the copy and call `"$controlfolder/xdelta3"`.')
        elif re.match(r"7z(?:a|z|zs|r)(\.\w+)?$", n):
            yield Finding("files.bundled-tool", INFO, f"{port.rel(p)} is 7-Zip, which PortMaster already ships as `7zzs.$DEVICE_ARCH` next to control.txt.", file=port.rel(p),
                          fix='Drop the copy and call `"$controlfolder/7zzs.$DEVICE_ARCH"`.')




@check
def helper_copy(port):
    """gmKtool.py / GMblob.py that differ from every version merged ports share: the patch step runs a changed copy of the shared tool."""
    if port.gamedir is None:
        return
    shared = data.PORT_FILES["shared"]
    for p in port.logical_files():
        if p.name not in ("gmKtool.py", "GMblob.py"):
            continue
        if hashlib.sha1(p.read_bytes().decode("utf8", "replace").encode()).hexdigest() in shared:
            continue
        yield Finding("files.helper-changed", INFO, f"{port.rel(p)} differs from every version of {p.name} that merged ports share "
                      f"({sum(1 for v in shared.values() if v == p.name)} versions). The patch step runs this changed copy as root on the player's game files.",
                      file=port.rel(p), fix=f"Use one of the shared versions of {p.name} unchanged. If the port needs a change, say in the README what it changes and why.")


_PLACEHOLDER = re.compile(r"\b(?:PORTER_NAME|PROJECT_URL|YOUR_NAME|YOUR_HANDLE|GAME_NAME|PORT_NAME|TODO-[\w-]+)\b|<(?:porter|project|game)[ _-](?:name|url)>", re.I if False else 0)


@check
def placeholders(port):
    """Template text the porter never filled in (PORTER_NAME in port.json and the licence, PROJECT_URL in the testing thread)."""
    if port.gamedir is None:
        return
    seen = []
    for d in port.meta_dirs():
        files = [p for p in d.iterdir() if p.is_file()]
        files += [p for lic in (d / "licenses", d / "license", d / "LICENSE") if lic.is_dir() for p in lic.iterdir() if p.is_file()]
        for p in files:
            if p.suffix.lower() not in (".json", ".md", ".txt", ".xml", ".ini") or p.stat().st_size > 300_000:
                continue
            for n, line in enumerate(port.read_text(p).splitlines(), 1):
                m = _PLACEHOLDER.search(line)  # case-sensitive: licence texts say "your name"
                if m:
                    seen.append((port.rel(p), n, m.group(0)))
    if seen:
        where = ", ".join(f"`{f}:{n}` ({w})" for f, n, w in seen[:4])
        yield Finding("files.placeholder", WARN, f"{len(seen)} placeholder{'s' if len(seen) > 1 else ''} from the template never replaced: {where}"
                      f"{', ...' if len(seen) > 4 else ''}. They end up on the website and in the licence file.", file=seen[0][0], line=seen[0][1],
                      fix="Put in the real porter name and project URL, or delete the line.")


def _runs_python_game(text):
    """The command that ends the script, before pm_finish, is Python running the port's own file: `python3 game.py`, `"$PY" "$GAMEDIR/oregon.py"`.
    A python helper that runs before a native game does not count."""
    tail = [l for _, l in _code_lines(text) if not re.match(r"(?:pm_finish\b|exit\b|fi\b|done\b|\}|esac\b|else\b|unset\b|\$ESUDO\s+(?:kill|umount|systemctl)|rm\b|printf\b|echo\b)", l)]
    return bool(tail) and bool(re.search(r"(?:^|[\s;&|(])(?:/usr/bin/)?(?:python3?[\d.]*|\"?\$\{?PY(?:THON)?\}?\"?)\s+(?:-[A-Za-z]+\s+)*[\"']?[^\s\"']*\.py\b", tail[-1]))


@check
def system_python(port):
    """The game is a Python program run by whatever python3 the device has. Merged Python ports use PortMaster's python runtime
    (python_3.x.squashfs, pyxel): 0 of 33 scripts that run Python start the game with the system's."""
    if port.gamedir is None:
        return
    for s in port.scripts:
        text = port.read_text(s)
        if not _runs_python_game(text) or re.search(r"python_?3[\d.]*\.squashfs|pyxel|PYTHONHOME|runtime_check", text):
            continue
        code = _code_lines(text)
        n = next((n for n, l in code if re.search(r"command\s+-v\s+python|which\s+python|/usr/bin/python|\bPY=", l)), None) \
            or next(n for n, l in code if re.search(r"\.py\b", l))
        kill = next((l for _, l in code if re.search(r"GPTOKEYB2?\b.*(?:basename|readlink|python)", l)), None)
        yield Finding("sh.system-python", WARN, "The game is started with the python3 the device happens to have. CFWs ship different Python versions with different modules, "
                      "and PortMaster's Python runtime (`python_3.11.squashfs`, mounted with `runtime_check`) exists so that every device runs the same one. "
                      "None of the merged scripts that run Python uses the system's."
                      + (" The kill switch is also given the interpreter's name, so Start+Select ends every process of that name, not just this game." if kill else ""),
                      file=port.rel(s), line=n,
                      fix="Use the python runtime as the merged Python ports do (see the template for Python/Pyxel ports), and start gptokeyb with the name of the process the runtime starts.")

@check
def loader_build(port):
    """A shared runtime loader (gmloadernext.aarch64) that no merged port ships byte for byte."""
    if port.gamedir is None:
        return
    for p in port.logical_files():
        ref = data.KNOWN_BINARIES.get(p.name)
        if not ref or not p.name.endswith(".aarch64"):
            continue
        raw = p.read_bytes()
        sha = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()[:12]
        if sha in ref["hashes"]:
            continue
        yield Finding("files.loader-build", INFO, f"{port.rel(p)} is not the same file as any of the {ref['copies']} copies in merged ports ({ref['builds']} builds; "
                      f"{ref['own_build']} ports ship a build of their own). A rebuilt loader runs as root with the game's whole access, and a reviewer cannot see in a "
                      "binary what was changed.",
                      file=port.rel(p),
                      fix="Use the loader from the template. If the port needs a patched one, link its source or diff in the README and the PR (the loader is GPL) "
                          "and say what the patch changes and which device problem it fixes.")


_MD_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(\s*<?([^)\s>]+)")


@check
def dead_links(port):
    """Relative links in the package's Markdown files that point at files the package does not contain (licence and source notices
    that promise `artifacts/...` or `third_party/...` are the usual case)."""
    if port.gamedir is None:
        return
    from urllib.parse import unquote
    for p in port.logical_files():
        if p.suffix.lower() != ".md" or p.stat().st_size > 1_000_000:
            continue
        if any(part.lower() in ("licenses", "license") for part in p.relative_to(port.root).parts[:-1]):
            continue   # upstream licence texts and READMEs copied as they are; their links point into their own repository
        text = re.sub(r"```.*?```", "", port.read_text(p), flags=re.S)
        missing = []
        for m in _MD_LINK.finditer(text):
            tgt = m.group(1)
            if re.match(r"[a-z][a-z0-9+.-]*:|#|/|\{|\$", tgt, re.I):
                continue
            rel = unquote(tgt.split("#")[0].split("?")[0])
            if rel and not (p.parent / rel).exists() and rel not in missing:
                missing.append(rel)
        if missing:
            yield Finding("files.dead-link", WARN, f"{port.rel(p)} links to {len(missing)} file{'s' if len(missing) > 1 else ''} the package does not contain: "
                          f"{', '.join('`' + x + '`' for x in missing[:5])}{', ...' if len(missing) > 5 else ''}. A licence or source notice that points at a missing file "
                          "does not give anyone the text or the source it promises.",
                          file=port.rel(p), fix="Add the files, or change the notice to a link that works (the upstream repository and tag) and delete the rest.")


@check
def unstripped_binaries(port):
    """Native files with debug sections: size the player downloads and copies to the SD card for nothing."""
    if port.gamedir is None:
        return
    big = []
    for p in port.logical_files():
        try:
            if p.stat().st_size < 1_000_000:
                continue
            with open(p, "rb") as fh:
                head = fh.read(4)
                if head != b"\x7fELF":
                    continue
                fh.seek(0)
                raw = fh.read()
        except OSError:
            continue
        if b".debug_info" not in raw:
            continue
        ref = data.KNOWN_BINARIES.get(p.name)   # the shared Android libs (libc++_shared.so ...) ship with debug sections in 360+ merged ports
        if ref and hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()[:12] in ref["hashes"]:
            continue
        big.append((len(raw), p))
    if big:
        total = sum(n for n, _ in big)
        yield Finding("libs.unstripped", INFO, f"{', '.join(f'{port.rel(p)} ({n / 1048576:.1f} MB)' for n, p in sorted(big, reverse=True)[:3])} "
                      f"{'has' if len(big) == 1 else 'have'} debug sections that nothing on the device reads"
                      f"{f' ({len(big)} files, {total / 1048576:.1f} MB together)' if len(big) > 1 else ''}.",
                      file=port.rel(sorted(big, reverse=True)[0][1]), fix="Run `strip --strip-unneeded` on it and ship the stripped file.")

@check
def script_platform(port):
    """Launch-script lines that redo or undo what control.txt / device_info.txt / funcs.txt / mod_*.txt already do."""
    armhf_exes = {p.name for p, i in elves(port) if i["arch"] == "armhf" and ".so" not in p.name
                  and (not data.PREBUILT_RE.match(p.name) or p.name.startswith("box86"))}
    for s in port.scripts:
        f = port.rel(s)
        text = port.read_text(s)
        lines = text.splitlines()
        code = [(n, l) for n, l in enumerate(lines, 1) if not l.strip().startswith("#")]
        body = "\n".join(l for _, l in code)
        if len([l for _, l in code if l.strip()]) <= 8:
            continue   # a wrapper that runs another launch script
        if len(lines) > 1 and lines[1].startswith("# PORTMASTER:"):
            yield Finding("sh.signature", INFO, "Line 2 is harbourmaster's install signature (`# PORTMASTER: <zip>, <script>`); the script was copied back from a handheld. "
                          "PortMaster writes it on the device at install time.", file=f, line=2, fix="Delete the line.")
        for n, l in code:
            if re.match(r"\s*cd\s+\"?\$\{?GAMEDIR\}?/?\"?\s*\|\|\s*(exit|return)\b", l):
                yield Finding("sh.cd-exit", INFO, "`cd \"$GAMEDIR\" || exit` is not the template (11 of 1536 merged ports); `$GAMEDIR` is the port's own folder and always exists.",
                              file=f, line=n, fix="`cd $GAMEDIR`")
                break
        # 32-bit programs: mod_<CFW>.txt sets up the 32-bit sound/GL libraries when PORT_32BIT=Y comes before it
        mod_n = next((n for n, l in code if re.search(r"mod_\$\{?CFW_NAME\}?\.txt", l)), None)
        # lib32 first on the path is the 32-bit loader's search order; appended at the end it is a habit of 64-bit Mono/FNA ports
        lib32 = next((n for n, l in code if re.search(r"LD_LIBRARY_PATH=[\"']?(/usr/config/emuelec)?/(usr/)?lib32\b", l)), None)
        runs32 = next((n for n, l in code for e in armhf_exes if re.search(r"(?<![\w.-])" + re.escape(e) + r"(?![\w.-])", l)), None)
        set32 = [n for n, l in code if re.search(r"PORT_32BIT=[\"']?Y", l)]
        if mod_n and (lib32 or runs32) and not any(n < mod_n for n in set32):
            late = f" It is set on line {set32[0]}, after mod_${{CFW_NAME}}.txt (line {mod_n}), which has already run." if set32 else ""
            yield Finding("sh.port-32bit", WARN, "The port runs a 32-bit program, but PORT_32BIT=\"Y\" isn't set before mod_${CFW_NAME}.txt is sourced. On ROCKNIX, JELOS, "
                          "UnofficialOS and Batocera that file then points PipeWire at the 32-bit plugins in /usr/lib32 (213 merged ports set it); without it the game has no sound there." + late,
                          file=f, line=runs32 or lib32,
                          fix='export PORT_32BIT="Y" before the mod_ line (only on the 32-bit route when the script picks one); then no SDL_AUDIODRIVER override is needed.')
        probe = next(((n, l) for n, l in code if re.search(r"-[edfx]\s+\"?/(usr/)?lib(32\b|/ld-linux-armhf\.so\.3)", l)), None)
        if probe and "DEVICE_HAS_ARMHF" not in body:
            yield Finding("sh.has-armhf", INFO, "The script looks for a 32-bit userland itself; device_info.txt (sourced by control.txt) already sets $DEVICE_HAS_ARMHF from four paths.",
                          file=f, line=probe[0], fix='[ "$DEVICE_HAS_ARMHF" = Y ] (keep a glibc version test if the 32-bit build needs a newer one)')
        # pm_finish mid-script: also restarts oga_events and clears the console; pm_gptokeyb_finish only stops gptokeyb
        funcs = _functions(code)
        starts = r"\$\{?GPTOKEYB2?\b|\bpm_platform_helper\b"
        starters = {name for name, (a, b) in funcs.items() if any(re.search(starts, l) for n, l in code if a < n <= b)}
        start_rx = re.compile(starts + (r"|^\s*(" + "|".join(map(re.escape, starters)) + r")\b" if starters else ""))
        for i, (n, l) in enumerate(code):
            if not re.match(r"\s*pm_finish\b", l) or re.search(r"\bpm_finish\b.*[;&|]\s*(exit|return)\b", l):
                continue
            nxt = [x for _, x in code[i + 1:] if x.strip()][:2]
            if any(re.match(r"\s*(exit|return|exec)\b", x) for x in nxt) or (nxt and re.match(r"\s*(else|elif)\b|\s*;;", nxt[0])):
                continue   # ends the script, or ends one branch of an if/case (the other branch starts the game)
            owner = next((name for name, (a, b) in funcs.items() if a < n <= b), None)
            if owner:
                calls = [k for k, x in code if re.match(r"\s*" + re.escape(owner) + r"\b", x) and not (funcs[owner][0] <= k <= funcs[owner][1])]
                later = any(start_rx.search(x) for c in calls for k, x in code if k > c and not any(a <= k <= b for a, b in funcs.values()))
            else:
                later = any(start_rx.search(x) for k, x in code if k > n and not any(a <= k <= b for a, b in funcs.values()))
            if later:
                yield Finding("sh.pm-finish-mid", WARN, "pm_finish runs before the game (or another tool) starts; besides stopping gptokeyb it restarts oga_events and clears the console.",
                              file=f, line=n, fix="pm_gptokeyb_finish (funcs.txt) stops gptokeyb only; keep pm_finish for the end of the script.")
                break
        # files the script sources from the port folder are part of it
        assigns = _assigns(code)
        parts = _script_parts(port, s, code)
        all_code = "\n".join(l for _, c in parts for _, l in c)
        # funcs.txt's EXIT trap is pm_message_end; pm_finish calls it too. Replacing the trap only loses something when, after
        # it, a pm_message is followed by an exit without pm_finish (the card is cut off).
        def _bare_exit_after_msg(lines):
            for i, (k, x) in enumerate(lines):
                if re.search(r"\bpm_message\b(?!_)", x):
                    for _, y in lines[i + 1:i + 6]:
                        if re.search(r"\bpm_finish\b", y):
                            break
                        if re.match(r"\s*exit\b", y):
                            return k
            return None
        for n, l in code:
            if not re.match(r"\s*trap\s+.*\bEXIT\b", l) or "pm_message_end" in l or "pm_finish" in l:
                continue
            handler = re.match(r"\s*trap\s+[\"']?(\w+)", l)
            hb = funcs.get(handler.group(1)) if handler else None
            if hb and any(re.search(r"\bpm_(message_end|finish)\b", x) for k, x in code if hb[0] < k <= hb[1]):
                continue
            after = [(k, x) for k, x in code if k > n and not any(a <= k <= b for a, b in funcs.values())]
            called = {name for name in funcs if any(re.match(r"\s*" + re.escape(name) + r"\b", x) for _, x in after)}
            bodies = [[(k, x) for k, x in code if funcs[name][0] < k < funcs[name][1]] for name in called]
            hit = _bare_exit_after_msg(after) or next((h for h in map(_bare_exit_after_msg, bodies) if h), None)
            if hit:
                yield Finding("sh.trap-exit", INFO, "`trap ... EXIT` replaces funcs.txt's own `trap pm_message_end EXIT`, and the message on line "
                              f"{hit} is followed by an exit without `pm_finish`, so the card is cut off.",
                              file=f, line=n, fix="Add it to the trap: `trap '<your cleanup>; pm_message_end' EXIT`, or call `pm_finish` before that exit.")
        for where, c in parts:
            hit = next(((n, l) for n, l in c if re.search(r"\b(swapon|mkswap|zramctl)\b|/sys/block/zram|modprobe\s+zram", l)), None)
            if hit:
                dd = " It also writes a swapfile with dd/fallocate: check where it lands (never outside the port folder) and that it is removed." if re.search(r"\b(dd\s+if=/dev/zero|fallocate)\b", all_code) else ""
                yield Finding("sh.swap", INFO, "The port sets up swap or zram on the device." + dd + " Reviewers ask whether it's needed, and whether every exit path turns it off again.",
                              file=where, line=hit[0], fix="Keep it only for a measured out-of-memory problem; prefer zram, and switch it off on exit.")
                break
        # a long helper run before the game: setup logic reviewers have to maintain
        ph = next((n for n, l in code if re.search(r"\bpm_platform_helper\b", l)), None)
        for n, l in code:
            if ph and n > ph:
                break
            m = re.match(r"\s*(?:\$ESUDO\s+)?(?:python3?|bash|sh)\s+(\"[^\"]+\"|'[^']+'|\S+\.(?:py|sh))(?=\s|;|$)", l)
            t = _port_path(port, m.group(1), assigns) if m else None
            if t is None or re.search(r"PATCHER_FILE", body) and t.name in body.split("PATCHER_FILE", 1)[1][:200]:
                continue
            count = len(port.read_text(t).splitlines())
            if count > 300:
                yield Finding("sh.setup-helper", INFO, f"{port.rel(t)} ({count} lines) runs before the game: first-launch logic reviewers have to read and maintain. "
                              "PortMaster already has the pieces: utils/patcher.txt (progress screen, PATCH_FAIL_MSG), $controlfolder/xdelta3 for binary patches, "
                              "$controlfolder/7zzs.$DEVICE_ARCH for archives.", file=f, line=n, fix="Shrink it to what this port needs, built on those.")
                break


def _listing(blocks, limit=12, width=70):
    """Line blocks [(first, last, first line's text)] as a code listing: '79-100  apply_button_swaps() {'."""
    rows = []
    for a, b, t in blocks[:limit]:
        nums = f"{a}-{b}" if a != b else f"{a}"
        rows.append(f"{nums:<8}{t[:width]}{'...' if len(t) > width else ''}")
    if len(blocks) > limit:
        rows.append(f"... and {len(blocks) - limit} more")
    return "\n".join(rows)


# PortMaster's own folder: control.txt, funcs.txt, libs/, harbourmaster. The header of every launch script picks the first of
# /opt/system/Tools/PortMaster, /opt/tools/PortMaster, $XDG_DATA_HOME/PortMaster, /roms/ports/PortMaster that exists as a folder.
_PM_DIR = (r"(\$\{?controlfolder\}?|\$\{?XDG_DATA_HOME\}?/PortMaster|(\$\{?HOME\}?|~|/root|/home/\w+)/\.local/share/PortMaster"
           r"|/roms/ports/PortMaster|/opt/(system/Tools|tools)/PortMaster|/mnt/\w+/MUOS/PortMaster)\b")
_PM_WRITERS = re.compile(r"(?:^|[;&|(]\s*|\bsudo\s+|\$ESUDO\s+|\bthen\s+|\bdo\s+)(mkdir|touch|ln|install|tee|rsync|rm)\b([^;&|]*)")
_PM_COPIERS = re.compile(r"(?:^|[;&|(]\s*|\bsudo\s+|\$ESUDO\s+|\bthen\s+|\bdo\s+)(cp|mv)\b([^;&|]*)")


def controlfolder_writes(code):
    """[(line number, line)] that create, write or delete anything in PortMaster's own folder.
    A folder made at $XDG_DATA_HOME/PortMaster by a port makes every other port's header pick that empty folder
    ("control.txt: No such file", then GAMEDIR=//ports/<name> on the rootfs)."""
    out = []
    for n, l in code:
        hit = False
        for m in _PM_WRITERS.finditer(l):
            if re.search(_PM_DIR, m.group(2)):
                hit = True
        for m in _PM_COPIERS.finditer(l):
            args = [a for a in m.group(2).split() if not a.startswith("-")]
            if args and re.search(_PM_DIR, args[-1]):   # the destination is the last argument; reading from it is fine
                hit = True
        if re.search(r"(?<![&\d])\d?>>?\s*\"?" + _PM_DIR, l):
            hit = True
        if re.search(r"\b(unzip\s[^;&|]*-d|tar\s[^;&|]*-C)\s*\"?" + _PM_DIR, l):
            hit = True
        if hit:
            out.append((n, l.strip()))
    return out


def _script(port, s):
    f = port.rel(s)
    raw = Path(s).read_bytes()
    if b"\r\n" in raw:
        yield Finding("sh.crlf", ERROR, "Windows (CRLF) line endings; bash fails on device.", file=f, fix="dos2unix the script.")
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    # a short wrapper that runs another of the port's launch scripts (e.g. "Game MP.sh" -> exec "Game.sh" MP):
    # the header, gptokeyb and pm_finish live in the script it runs
    others = [o.name for o in port.scripts if o != s]
    real = [l for l in lines[1:] if l.strip() and not l.strip().startswith("#")]
    if others and len(real) <= 8 and any(o in l and re.search(r"\bexec\b|^\s*\"?\$", l) for o in others for l in real):
        return
    if not lines or not lines[0].startswith("#!/bin/bash"):
        env_bash = bool(lines) and re.match(r"#!\s*/usr/bin/env\s+bash\b", lines[0])
        yield Finding("sh.shebang", WARN if env_bash else ERROR, "First line must be #!/bin/bash.", file=f, line=1)
    for n, line in enumerate(lines[1:], 2):
        st = line.strip()
        if not st or st.startswith("# PORTMASTER:"):
            continue
        if not BOILER.match(st):
            yield Finding("sh.boilerplate", WARN if st.startswith("#") else ERROR, "Nothing may come before the PortMaster header (XDG_DATA_HOME=... / controlfolder block).",
                          file=f, line=n)
        break
    code = [(n, l) for n, l in enumerate(lines, 1) if not l.strip().startswith("#")]
    body = "\n".join(l for _, l in code)

    def grep(rx):
        return [(n, l) for n, l in code if re.search(rx, l)]

    for need, rid, msg in (
        (r"controlfolder=\"?/opt/system/Tools/PortMaster", "sh.controlfolder", "Missing the standard controlfolder detection block."),
        (r"source\s+\"?\$\{?controlfolder\}?/control\.txt", "sh.control", "control.txt is not sourced."),
        (r"mod_\$\{?CFW_NAME\}?\.txt", "sh.mod", "mod_${CFW_NAME}.txt is not sourced."),
        (r"^\s*get_controls\b", "sh.get_controls", "get_controls is not called."),
    ):
        if not re.search(need, body, re.M):
            if rid == "sh.control" and "control.txt" in body and re.search(r"^\s*(source|\.)\s+\"?\$\{?\w+\}?\"?\s*$", body, re.M):
                continue   # found by a search loop, sourced through a variable
            yield Finding(rid, WARN, msg, file=f)
    if not re.search(r"^\s*pm_finish\b", body, re.M):
        yield Finding("sh.pm_finish", WARN, "pm_finish is not called at the end.", file=f)
    if not re.search(r"^\s*(export\s+)?GAMEDIR=", body, re.M):
        yield Finding("sh.gamedir", WARN, "GAMEDIR is not set; the template uses GAMEDIR for the game folder.", file=f,
                      fix=f"GAMEDIR=/$directory/ports/{port.gamedir.name if port.gamedir else '<gamedir>'}")
    if not re.search(r"\bpm_platform_helper\b", body):
        yield Finding("sh.platform-helper", WARN, "pm_platform_helper is not called before the game starts.", file=f,
                      fix='pm_platform_helper "$GAMEDIR/$BINARY"')
    for n, l in grep(r"^\s*(\[[^]]*\]\s*&&\s*)?(source|\.)\s+\"?\$\{?controlfolder\}?/device_info\.txt"):
        yield Finding("sh.device-info", WARN, "control.txt already sources device_info.txt.", file=f, line=n, fix="Delete the line.")
    for n, l in grep(r"chmod\s+\S+\s+/dev/uinput"):
        yield Finding("sh.uinput", WARN, "control.txt already makes /dev/uinput writable.", file=f, line=n, fix="Delete the line.")
    # Classic vs gptokeyb2 is the porter's choice; only blank .gptk bindings are a reason to switch
    # (blank values don't unbind in classic gptokeyb, its compiled-in default keys stay live).
    cd_gd = re.search(r"^\s*cd\s+\"?\$\{?GAMEDIR\}?/?\"?\s*(;|&&|\|\||$)", body, re.M) or (port.gamedir is not None and port.gamedir.name in body)
    for n, l in grep(r"^\s*\$\{?GPTOKEYB\}?\"?\s.*\s-c\s"):
        m = re.search(r"\s-c\s+(\"[^\"]+\"|'[^']+'|\S+)", l)
        arg = m.group(1).strip("\"'")
        target = _resolve(port, arg) if "$" in arg else (port.gamedir / arg if cd_gd and port.gamedir is not None else None)
        if target is None or not target.is_file():
            continue
        entries = [x.strip() for x in port.read_text(target).splitlines() if x.strip() and not x.strip().startswith("#")]
        blank = [x for x in entries if re.fullmatch(r"\S+\s*=\s*", x)]
        if blank or not entries:
            what = f"{len(blank)} blank binding{'s' if len(blank) != 1 else ''}" if blank else "no bindings"
            yield Finding("sh.gptokeyb-classic", WARN, f"Classic gptokeyb with {port.rel(target)}, which has {what}. Blank values don't unbind: classic gptokeyb's compiled-in default keys stay active (double input).",
                          file=f, line=n, fix=f'Use gptokeyb2: $GPTOKEYB2 "<binary>" & with no -c for the kill switch alone, or an .ini that maps only what is needed.')
    # Old end-of-script cleanup that pm_finish does itself (gptokeyb kills are sh.kill-gptokeyb)
    tail_rx = re.compile(r"\s*($|fi\b|\}|exit\b|pm_finish\b|unset\s|printf\s|if\s+command\s+-v\s+systemctl|.*\boga_events\b|.*\b(kill|pkill|killall)\b.*gptokeyb)")
    tail_from = len(code)
    while tail_from > 0 and tail_rx.match(code[tail_from - 1][1]):
        tail_from -= 1
    old = [n for n, l in code if re.search(r"\boga_events\b", l)]
    old += [n for n, l in code[tail_from:] if re.match(r"\s*unset\s+SDL_GAMECONTROLLERCONFIG\b", l)
            or (re.match(r"\s*printf\s+[\"']\\033c", l) and not re.search(r"^\s*pm_finish\b", body, re.M))]
    if old:
        old = sorted(set(old))
        more = f" (also lines {', '.join(map(str, old[1:]))})" if len(old) > 1 else ""
        yield Finding("sh.old-cleanup", WARN, f"Old end-of-script cleanup (unset SDL_GAMECONTROLLERCONFIG / oga_events restart / printf \\033c){more}.",
                      file=f, line=old[0], fix="Delete it; pm_finish does this.")
    shim_fwd = re.search(r"SDL3SHIM_SDL2_(VIDEO|AUDIO)DRIVER=", body)
    for n, l in grep(r"\bSDL_(VIDEO|AUDIO)DRIVER="):
        if re.match(r"\s*(echo|printf)\b", l):
            continue   # logging the value, not setting it
        if shim_fwd:
            continue   # sdl3-sdl2-backend pattern: the CFW's driver goes to SDL3SHIM_SDL2_*, the game gets sdl2
        sev = WARN if "sdl2" in l.lower() and "SDL3SHIM" in body else ERROR
        if sev == ERROR and re.search(r"DRIVER=\"?\$\{SDL_(VIDEO|AUDIO)DRIVER:-", l):
            if "AUDIODRIVER" in l and re.search(r"/lib32\b|ld-linux-armhf|PORT_32BIT", body):
                yield Finding("sh.sdl-driver", WARN, "Sets an SDL audio driver default for a 32-bit program. When the CFW sets a driver it is kept anyway, and when it doesn't, SDL falls back to ALSA "
                              "by itself if the 32-bit PulseAudio/PipeWire client is missing; on ROCKNIX/JELOS/Batocera, PORT_32BIT=Y before mod_${CFW_NAME}.txt makes the 32-bit PipeWire work.",
                              file=f, line=n, fix='Drop it and export PORT_32BIT="Y" before sourcing mod_${CFW_NAME}.txt.')
                continue
            yield Finding("sh.sdl-driver", WARN, "Sets an SDL driver default; when the CFW leaves it unset SDL would pick the backend itself.", file=f, line=n,
                          fix="Drop it unless a device needs it, and say which in a short comment.")
            continue
        yield Finding("sh.sdl-driver", sev, "Never force SDL_VIDEODRIVER/SDL_AUDIODRIVER; the CFW selects the backend.", file=f, line=n)
    cf = controlfolder_writes(code)
    if cf:
        yield Finding("sh.controlfolder-write", ERROR, "The script creates or writes inside PortMaster's own folder. A folder made at $XDG_DATA_HOME/PortMaster "
                      "(e.g. ~/.local/share/PortMaster) makes the header of every other port pick that empty folder, and every port then fails with "
                      "`control.txt: No such file` and writes into //ports on the rootfs.", file=f, line=cf[0][0],
                      snippet=_listing([[n, n, l] for n, l in cf], 8),
                      fix="Write only below $GAMEDIR. PortMaster and harbourmaster manage their own folder; use `harbourmaster runtime_check` to fetch a runtime.")
    for n, l in grep(r"^\s*export\s+LD_PRELOAD="):
        yield Finding("sh.ld_preload", ERROR, "export LD_PRELOAD leaks into gptokeyb; set it as a prefix on the game command only.", file=f, line=n)
    # How much of the script is neither template nor game-specific: unusual logic reviewers will ask about
    common = data.SCRIPT_LINES["lines"]
    rare = [(n, raw) for n, k, raw in scriptnorm.lines("\n".join(lines)) if scriptnorm.counted(k, raw, common)]
    pc = data.SCRIPT_LINES["percentiles"]
    if len(rare) > pc["95"]:
        blocks = []
        for n, raw in rare:
            if blocks and n - blocks[-1][1] <= 3:
                blocks[-1][1] = n
            else:
                blocks.append([n, n, raw.strip()])
        sev = WARN if len(rare) > pc["99"] else INFO
        yield Finding("sh.nonstandard", sev,
                      f"{len(rare)} lines reach into the system (system paths, driver or audio variables, system tools, CFW checks) in a way no template "
                      f"and fewer than {data.SCRIPT_LINES['min_scripts']} of {data.SCRIPT_LINES['scripts']} merged ports do. Merged ports have "
                      f"{pc['50']} such lines at the median and {pc['99']} at most (99th percentile). The blocks are listed below.",
                      file=f, line=rare[0][0], snippet=_listing(blocks, 8),
                      fix="For each block, note which device problem it fixes. If `control.txt`, `funcs.txt`, `libgl_*.txt` or `mod_*.txt` already handle it, the block can go.")
    # Reinventing what PortMaster's own files already do (the CFW's libgl_*.txt / mod_*.txt decide GPU and gl4es)
    libgl_set = [(n, l) for n, l in grep(r"^\s*(export\s+|unset\s+)?[^#]*\bLIBGL_(ES|GL|FB|EGL|GLES)\b\s*=?")
                 if re.search(r"\bLIBGL_(ES|GL|FB|EGL|GLES)=|\bunset\b.*\bLIBGL_(ES|GL|FB|EGL|GLES)\b|export\s+LIBGL_(ES|GL|FB|EGL|GLES)\b", l)
                 and not re.match(r"\s*(echo|printf)\b", l)]
    if libgl_set:
        more = f" (also lines {', '.join(str(n) for n, _ in libgl_set[1:6])})" if len(libgl_set) > 1 else ""
        yield Finding("sh.libgl-manual", WARN, f"The script sets or unsets gl4es' LIBGL_ES/GL/FB/EGL/GLES itself{more}; libgl_${{CFW_NAME}}.txt sets them per device (or skips gl4es on purpose).",
                      file=f, line=libgl_set[0][0], fix="Source libgl_${CFW_NAME}.txt (libgl_default.txt fallback) from $GAMEDIR and drop the manual lines.")
    probes = grep(r"/sys/(module|bus/platform/drivers)/(panfrost|mali|lima|msm|adreno)|libmali[^\s\"']*\.so|/dev/mali")
    if probes:
        more = f" (also lines {', '.join(str(n) for n, _ in probes[1:6])})" if len(probes) > 1 else ""
        yield Finding("sh.gpu-probe", WARN, f"The script probes for GPU drivers (Panfrost/Mali/libmali){more}; picking the GPU stack is the CFW's job (its libgl_*.txt / mod_*.txt).",
                      file=f, line=probes[0][0], fix="Delete it; source libgl_${CFW_NAME}.txt and let the CFW decide.")
    # X="${X:-default}" only defaults the outside value, it is still a knob
    assigned = {m.group(1) for m in re.finditer(r"(?:^|[\s;(&|])(?:export\s+|local\s+|declare\s+(?:-\w+\s+)?)?([A-Z][A-Z0-9_]*)\+?=(\S*)", body, re.M)
                if not re.match(r"[\"']?\$\{" + m.group(1) + r":?-", m.group(2))}
    assigned |= set(re.findall(r"\b(?:read(?:\s+-\w+)*|for)\s+([A-Z][A-Z0-9_]*)\b", body))
    assigned |= set(re.findall(r":\s+\"?\$\{([A-Z][A-Z0-9_]*):?=", body))   # : "${X:=default}" sets X
    knobs = {}
    for n, l in code:
        for m in re.finditer(r"\$\{([A-Z][A-Z0-9_]*):?[-=]", l):
            v = m.group(1)
            if v in assigned or v in data.PM_ENV or v.startswith(data.PM_ENV_PREFIX):
                continue
            knobs.setdefault(v, n)
    if knobs:
        names = sorted(knobs, key=knobs.get)
        yield Finding("sh.env-knobs", WARN, f"Override switches read from the environment that nothing sets: {', '.join(names[:8])}{' and more' if len(names) > 8 else ''}. "
                      "Players start ports from the menu, where these can't be set, so they look like switches from testing.",
                      file=f, line=knobs[names[0]], fix="Keep the one path the port uses and drop the switches.")
    # libgl_default.txt finds gl4es.<arch>/ and libs.<arch>/ through $PWD
    gl_lines = grep(r"^\s*(source|\.)\s+.*libgl_(\$\{?CFW_NAME\}?|default)\.txt")
    if gl_lines and port.gamedir is not None and any(d.is_dir() and d.name.startswith(("gl4es", "libs")) for d in port.gamedir.iterdir()):
        first = gl_lines[0][0]
        cds = [(n, l) for n, l in code if n < first and re.match(r"\s*cd\s", l)]
        if cds:
            n_cd, l_cd = cds[-1]
            arg = re.split(r";|&&|\|\|", l_cd.split(None, 1)[1])[0].strip().strip("\"'").rstrip("/")
            assigns = dict(re.findall(r"^\s*(?:export\s+)?(\w+)=\"?([^\"\s]+)\"?\s*$", "\n".join(x for k, x in code if k < n_cd), re.M))
            m = re.fullmatch(r"\$\{?(\w+)\}?", arg)
            val = assigns.get(m.group(1), arg) if m and m.group(1) != "GAMEDIR" else arg
            val = val.rstrip("/")
            ok = re.fullmatch(r"\$\{?GAMEDIR\}?|/?\$\{?directory\}?/ports/" + re.escape(port.gamedir.name), val)
            if not ok:
                yield Finding("sh.libgl-cwd", WARN, f"libgl_*.txt is sourced after cd {arg}; libgl_default.txt looks for gl4es/ and libs/ in $PWD, so it doesn't find the port's folders.",
                              file=f, line=first, fix='cd "$GAMEDIR" before sourcing it (cd into the data folder afterwards).')
    if re.search(r"libgl_default\.txt", body) and not re.search(r"libgl_\$\{?CFW_NAME\}?\.txt", body):
        n = grep(r"libgl_default\.txt")[0][0]
        yield Finding("sh.libgl", ERROR, "Source libgl_${CFW_NAME}.txt with a libgl_default.txt fallback, never libgl_default.txt alone.", file=f, line=n)
    # every libgl_*.txt sets LIBGL_ES in exactly the branch that puts gl4es on LD_LIBRARY_PATH, so either guard works
    gl_guard = '":$LD_LIBRARY_PATH:"' in body or re.search(r"(\[\[?|test)\s+(-n\s+|!\s+-z\s+)?\"?\$\{?LIBGL_ES\}?\"?", body)
    gl_exports = grep(r"export\s+SDL_VIDEO_(GL|EGL)_DRIVER")
    sys_gles = [(n, l) for n, l in gl_exports if re.search(r"_DRIVER=[\"']?lib(GLESv2|GLESv1_CM|EGL)\.so[\d.]*[\"']?\s*$", l)]
    for n, l in sys_gles:
        yield Finding("sh.gl-driver-gles", INFO, "SDL_VIDEO_GL/EGL_DRIVER points at the device's own GLES/EGL library; SDL already loads it for a GLES context, "
                      "and an unversioned .so name (a dev symlink) is often missing on device, so SDL ignores it and falls back.",
                      file=f, line=n, fix="Drop the line, or say which device needed it.")
    if len(gl_exports) > len(sys_gles) and not gl_guard:
        n = [x for x in gl_exports if x not in sys_gles][0][0]
        yield Finding("sh.gl-driver", WARN, "SDL_VIDEO_GL/EGL_DRIVER is exported even when the CFW's libgl script skipped gl4es (a device with native GL, e.g. ROCKNIX on some GPUs); gl4es then gets forced in anyway.",
                      file=f, line=n, fix="Export them only when gl4es is in use, after sourcing libgl_${CFW_NAME}.txt:",
                      snippet='if [[ ":$LD_LIBRARY_PATH:" == *":$GAMEDIR/gl4es.${DEVICE_ARCH}:"* ]]; then\n'
                              '  export SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1"\n'
                              '  export SDL_VIDEO_EGL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libEGL.so.1"\nfi')
    for n, l in grep(r"\btar\s+-?[a-zA-Z]*z[a-zA-Z]*f?\b|\btar\b.*\s-z\b"):
        if re.search(r"\btar\s+(c|-c)", l):
            continue
        yield Finding("sh.tar-z", ERROR, "tar -z is unsupported on some BusyBox builds.", file=f, line=n,
                      fix='gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -')
    tars = [n for n, l in grep(r"\btar\b.*\bx[a-z]*f\b|\btar\s+-x") if "--no-same-owner" not in l]
    if tars:
        more = f" (also lines {', '.join(map(str, tars[1:]))})" if len(tars) > 1 else ""
        yield Finding("sh.tar-owner", WARN, f"Extract with tar --no-same-owner{more}.", file=f, line=tars[0],
                      fix='gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -')
    hits = grep(r"(^|\s|export\s+)HOME=|(^|\s|export\s+)XDG_CONFIG_HOME=")
    # an "else" fallback after testing for bind_directories only runs on PortMaster before 2024-08 (funcs.txt without it)
    def _fallback(n):
        i = next(k for k, (m, _) in enumerate(code) if m == n)
        before = [x for _, x in code[max(0, i - 4):i]]
        return any(re.search(r"(type|command\s+-v|declare\s+-F)\s+bind_directories", x) for x in before) and any(re.match(r"\s*else\b", x) for x in before)
    fb = [(n, l) for n, l in hits if _fallback(n)]
    hits = [(n, l) for n, l in hits if not _fallback(n)]
    if hits:
        more = f" (also lines {', '.join(str(n) for n, _ in hits[1:])})" if len(hits) > 1 else ""
        yield Finding("sh.home", ERROR, f"Don't redirect HOME/XDG_CONFIG_HOME (PulseAudio symlink fails on FAT); use bind_directories{more}.", file=f, line=hits[0][0])
    if fb:
        yield Finding("sh.home", INFO, "HOME/XDG_CONFIG_HOME redirect as a fallback for a PortMaster without bind_directories. Every PortMaster since 2024-08 has it, so the fallback never runs and can go.",
                      file=f, line=fb[0][0], fix="Call bind_directories directly and drop the if/else.")
    for n, l in grep(r"^\s*bind_(directories|files)\s"):
        try:
            args = shlex.split(l.split("#")[0] if " #" in l else l)
        except ValueError:
            continue
        if len(args) < 3:
            continue
        m = re.match(r"\s*bind_(directories|files)", l)
        src = args[2]
        vars_ = dict(re.findall(r"^\s*(?:export\s+)?(\w+)=\"?([^\"\s]+)\"?\s*$", "\n".join(x for k, x in code if k < n), re.M))
        for _ in range(3):
            src = re.sub(r"\$\{?(\w+)\}?", lambda v: vars_.get(v.group(1), v.group(0)) if v.group(1) not in ("GAMEDIR", "HOME", "directory") else v.group(0), src)
        src = src.rstrip("/")
        before = "\n".join(x for k, x in code if k < n)
        verb = "mkdir" if m.group(1) == "directories" else "touch"
        shipped = _resolve(port, src)
        if shipped is not None and shipped.exists():
            continue
        before_r = before
        for k, v in vars_.items():
            if k not in ("GAMEDIR", "HOME", "directory"):
                before_r = re.sub(r"\$\{?" + k + r"\}?(?!\w)", v.replace("\\", "\\\\"), before_r)
        sub = r"(/[^\"\s]*)?" if verb == "mkdir" else ""   # mkdir -p of a path below the source creates it too
        if not re.search(rf"{verb}\b[^\n]*{re.escape(src)}{sub}/?\"?(\s|$)", before_r, re.M):
            yield Finding("sh.bind-source", WARN, f"bind_{m.group(1)} source {src} must exist first ({verb} it before this line), or the bind silently no-ops.",
                          file=f, line=n)
    for i, (n, l) in enumerate(code):
        if not re.match(r"\s*echo\s+[\"']", l) or re.search(r"[>|]|\)\s*$", l):
            continue   # echo that writes a file or feeds a pipe is not a player message
        # Only an echo that is the last thing before an error exit: nothing but cleanup in between.
        nxt = None
        for _, x in code[i + 1:i + 6]:
            if re.match(r"\s*$|\s*(echo\b|\$ESUDO\s+umount|umount|rm\s|sleep\s|pm_finish\b|\}|fi\b)", x):
                continue
            nxt = x
            break
        near = [x for _, x in code[max(0, i - 2):i + 4]]
        if (nxt is not None and re.match(r"\s*exit\s+[1-9]", nxt)
                and not any(re.search(r"\bpm_(message|show_error)\b", x) for x in near)):
            yield Finding("sh.echo-message", WARN, "This message goes to the log, the player never sees it before the exit.", file=f, line=n,
                          fix='pm_message "..." then sleep 5 before the exit (works on every PortMaster version)')
    launch = re.compile(r"^\s*(?:\w+=\S+\s+)*(?:\$\{?TASKSET\}?\s+|\$ESUDO\s+)?(?:\"?\$\{?GAMEDIR\}?/|\./|\"?\$\{?BINARY\}?\b|mono\b|java\b|\$\{?LOVE_RUN\}?|\$\{?GMLOADER\}?)")
    text_cmd = re.compile(r"\s*(printf|echo|cat)\b")
    for i, (n, l) in enumerate(code):
        if not launch.match(l):
            continue
        j = i   # a printf/echo/cat continued over lines writes a file, whatever its last line starts with
        while j > 0 and code[j - 1][1].rstrip().endswith("\\"):
            j -= 1
        if text_cmd.match(code[j][1]):
            continue
        for m in re.finditer(r"(?:^|\s)(?:[12&]?>>?)\s*\"?([^\"\s;&|)]+)", l):
            target = m.group(1)
            if re.search(r"^/dev/(null|tty|std)|(^|/)log\.txt$|^>?\(", target):
                continue   # process substitution (> >(tee ...)) still reaches the log
            base = re.escape(target.rsplit("/", 1)[-1])
            if any(re.search(r"\b(cat|sed|grep|awk|tail|head|read)\b.*" + base + r"|<\s*\"?\S*" + base, x) for k, x in code if k > n):
                continue   # captured on purpose and read back (e.g. into an error message)
            yield Finding("sh.log-split", WARN, f"The game's output goes to {target} instead of log.txt; testers send log.txt, so errors from the game itself are missing from it.",
                          file=f, line=n, fix="Drop the redirection; the template's exec > >(tee \"$GAMEDIR/log.txt\") 2>&1 already logs everything.")
            break
    home = r"(~|\$\{?HOME\}?)/\.asoundrc\b"
    for i, (n, l) in enumerate(code):
        m = re.search(r"\b(cp|mv|ln)\b[^;&|]*\s\"?" + home + r"\"?\s*$|>\s*\"?" + home, l)
        if not m or re.search(r"asoundrc\.?bak|asoundrc\.\w*bak", l.split(m.group(0))[0] + m.group(0).rsplit(" ", 1)[0]):
            continue
        near = " ".join(x for _, x in code[max(0, i - 2):i + 1])
        if re.search(r"!\s+-[ef]\s+\"?" + home, near):
            continue   # only creates one when the CFW has none
        src = re.search(r"\b(?:cp|mv|ln)\s+(?:-\w+\s+)*\"?([^\"\s]+)", l)
        card = ""
        if src:
            target = _resolve(port, src.group(1))
            if target is not None and target.is_file():
                hw = re.findall(r"hw:([\w-]+)", port.read_text(target))
                card = f" {port.rel(target)} hard-codes the sound card ({', '.join(sorted(set(hw)))}), so it only works on devices with that codec." if hw else ""
        yield Finding("sh.asoundrc", WARN, "Overwrites the CFW's ~/.asoundrc (on ArkOS/dArkOS that is the device's own ALSA setup); if the game crashes or the device "
                      "is switched off, the port's copy stays and breaks sound in every other port." + card,
                      file=f, line=n, fix="Ask which device and symptom it fixes; a CFW audio problem belongs in the CFW or mod_<CFW>.txt. "
                      "Merged ports only restore the CFW's own file: [ ! -f ~/.asoundrc ] && [ -f ~/.asoundrcbak ] && cp ~/.asoundrcbak ~/.asoundrc")
    for n, l in grep(r"^\s*((echo|printf)\b.*|\})\s*>\s*\"?(\$\{?CUR_TTY\}?|/dev/tty\d*)\"?"):
        if re.search(r"\\033c|\\e\[|\\033\[", l):
            continue   # clearing the console
        yield Finding("sh.tty-message", WARN, "Message written to the console TTY (old style); many CFWs show EmulationStation or nothing there.", file=f, line=n,
                      fix='pm_message "..." then sleep 5 before the exit (works on every PortMaster version)')
        break
    for n, l in grep(r"\bpm_(message|show_error)\s+--"):
        yield Finding("sh.pm_message-order", ERROR, "pm_message/pm_show_error take the message first, options after.", file=f, line=n)
    for n, l in grep(r"portmsg\.\$\{?DEVICE_ARCH|\./portmsg"):
        yield Finding("sh.portmsg", ERROR, "Don't call portmsg directly; use pm_message/pm_show_error.", file=f, line=n)
    for n, l in grep(r"(^|[;&|]\s*)sudo\s"):
        yield Finding("sh.sudo", WARN, "Use $ESUDO, not sudo.", file=f, line=n)
    for n, l in grep(r"\bpaste\b"):
        if "|" in l:
            yield Finding("sh.paste", WARN, "ROCKNIX's paste uploads stdin to dpaste.com; don't pipe into paste.", file=f, line=n)
    # Comment noise: long comment blocks belong in docs, not the script.
    run, blocks = 0, []
    for n, l in enumerate(lines, 1):
        if l.strip().startswith("#") and n > 1 and not l.strip().startswith("# PORTMASTER:"):
            run += 1
            if run == 3:
                blocks.append(n - 2)
        else:
            run = 0
    if blocks:
        more = f" (also lines {', '.join(map(str, blocks[1:]))})" if len(blocks) > 1 else ""
        yield Finding("sh.comments", INFO, f"Multi-line comment block{'s' if len(blocks) > 1 else ''}; keep comments to one short line per fix{more}.", file=f, line=blocks[0])
    # CRLF is reported once by sh.crlf; parse a stripped copy so the real errors still show
    src, tmpd = str(s), None
    raw = s.read_bytes()
    if b"\r" in raw:
        tmpd = tempfile.mkdtemp(prefix="pmcheck-sc-")
        src = os.path.join(tmpd, "script.sh")
        Path(src).write_bytes(raw.replace(b"\r\n", b"\n"))
    sc_out = None
    try:
        if not shutil.which("shellcheck") and shutil.which("bash"):
            # parse only (-n): nothing in the script runs
            r = subprocess.run(["bash", "-n", src], capture_output=True, text=True, timeout=30)
            for m in re.finditer(r"line (\d+): (.+)", r.stderr):
                yield Finding("sh.syntax", ERROR, f"bash: {m.group(2)}", file=f, line=int(m.group(1)))
        if shutil.which("shellcheck"):
            sc_out = _run(["shellcheck", "-S", "error", "-f", "json", "-s", "bash", src])
    finally:
        if tmpd:
            shutil.rmtree(tmpd, ignore_errors=True)
    if sc_out is not None:
        out = sc_out
        try:
            by_code = {}
            for item in json.loads(out or "[]"):
                by_code.setdefault((item["code"], item["message"]), []).append(item.get("line", 0))
            for (sc_code, msg), ns in by_code.items():
                more = f" (also lines {', '.join(map(str, ns[1:6]))}{', ...' if len(ns) > 6 else ''})" if len(ns) > 1 else ""
                yield Finding("sh.shellcheck", ERROR, f"SC{sc_code}: {msg}{more}", file=f, line=ns[0])
        except ValueError:
            pass
    if not re.search(r"gptokeyb", body, re.I):
        yield Finding("sh.no-gptokeyb", ERROR, "No gptokeyb launched, so there is no hotkey exit. A game that quits on Select+Start itself still misses devices whose "
                      "hotkey is another button (control.txt sets $HOTKEY: L3 on the OGA 1.0 and Gameforce Chi, Guide on the RGB10 Max with ArkOS), and can't be "
                      "killed when it hangs.", file=f,
                      fix='Launch it before the game, e.g. $GPTOKEYB2 "$BINARY" & (no -c: kill switch only, a game reading the pad itself keeps working), or $GPTOKEYB "$BINARY" &.')
    for n, l in grep(r"\b(kill\b.*\$\(\s*pidof\s+gptokeyb|pkill\b.*gptokeyb|killall\b.*gptokeyb)"):
        i = next(k for k, (m, _) in enumerate(code) if m == n)
        after_patcher = any("patcher.txt" in x for x in [x for _, x in code[:i] if x.strip()][-1:])
        if not after_patcher and any(re.search(r"\$\{?GPTOKEYB2?\b", x) for _, x in code[i + 1:]):
            continue   # stops one gptokeyb (e.g. a launcher's) before the game starts its own
        yield Finding("sh.kill-gptokeyb", WARN, "Obsolete: pm_finish and patcher.txt stop gptokeyb themselves (pm_gptokeyb_finish).", file=f, line=n,
                      fix="Delete the line; end the script with pm_finish (it replaces the old kill / oga_events / printf cleanup).")
    for n, l in grep(r"^\s*exec\s*>\s*\"?\$\{?(GAMEDIR\}?/log\.txt|\w*LOG\w*\}?)\"?\s*2>&1\s*$"):
        yield Finding("sh.log-old", WARN, "Old logging line.", file=f, line=n,
                      fix='> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1')
    for n, l in grep(r"^\s*exec\s*>\s*>\(\s*tee\b"):
        if not re.search(r"\$\{?GAMEDIR\}?/log\.txt", l):
            yield Finding("sh.log-old", WARN, "Old logging line (log path not $GAMEDIR/log.txt).", file=f, line=n,
                          fix='> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1')
    # -c pointing at a control file the package doesn't have: gptokeyb then maps nothing
    cd_gamedir = re.search(r"^\s*cd\s+\"?\$\{?GAMEDIR\}?/?\"?\s*(;|&&|\|\||$)", body, re.M)
    for n, l in code:
        m = re.search(r"GPTOKEYB2?\}?\"?\s.*?\s-c\s+(\"[^\"]+\"|'[^']+'|\S+)", l)
        if not m:
            continue
        arg = m.group(1).strip("\"'")
        target = _resolve(port, arg) if "$" in arg else (port.gamedir / arg if cd_gamedir and port.gamedir is not None else None)
        base = arg.rsplit("/", 1)[-1]
        made = any(base in x for k, x in code if k != n)   # copied, generated or chosen elsewhere in the script
        if target is not None and not made and not target.exists():
            yield Finding("sh.gptk-missing", ERROR, f"gptokeyb is started with -c {arg!r}, but the package has no such file, so no button is mapped.",
                          file=f, line=n, fix="Ship the file, fix the name, or drop -c if gptokeyb is only the hotkey exit.")
    # Control files referenced by the script
    if port.gamedir is not None and not re.search(r"GPTOKEYB2?\}?\"?\s.*\s-c\b", body):
        for p in sorted(port.gamedir.glob("*.ini")):
            t = port.read_text(p)
            if "[controls" in t and p.name not in body:
                yield Finding("ini.unused", WARN, f"{port.rel(p)} looks like a gptokeyb2 config, but gptokeyb2 is launched without -c and nothing else uses it.",
                              file=port.rel(p))


def _resolve(port, path):
    """Map a script path like $GAMEDIR/conf/x or /$directory/ports/foo/x into the package, if possible."""
    if port.gamedir is None:
        return None
    p = re.sub(r"^/?\$\{?directory\}?/ports/", str(port.root) + "/", path)
    p = re.sub(r"\$\{?(GAMEDIR|gamedir)\}?", str(port.gamedir), p)
    return None if "$" in p or "~" in p else Path(p)


def _gptk_config(name, scripts):
    """Is a control file with this name passed to gptokeyb with -c (by name, via a variable, or a path we can't resolve)?"""
    code = "\n".join(l for l in scripts.splitlines() if not l.strip().startswith("#"))
    c_lines = [l for l in code.splitlines() if re.search(r"gptokeyb", l, re.I) and re.search(r"\s-c\b", l)]
    if not c_lines:
        return False
    if any(name in l for l in c_lines):
        return True
    holders = {m.group(1) for m in re.finditer(r"^\s*(?:export\s+|local\s+)?(\w+)=.*" + re.escape(name), code, re.M)}
    if any(re.search(r"\$\{?" + v + r"\b", l) for v in holders for l in c_lines):
        return True
    # Not named anywhere in the script: assume a computed path like "$GAMEDIR/$BINARY.ini".
    return name not in code


def _gptk_unused(name, scripts):
    """Certainly unused: every -c argument is a plain file name (no variables beyond $GAMEDIR) and this one is named nowhere."""
    code = "\n".join(l for l in scripts.splitlines() if not l.strip().startswith("#"))
    args = [m.group(1) for m in re.finditer(r"GPTOKEYB2?\}?\"?\s.*?\s-c\s+(\"[^\"]+\"|'[^']+'|\S+)", code)]
    if not args or name in code:
        return False
    plain = [re.sub(r"\$\{?GAMEDIR\}?", "", a.strip("\"'")) for a in args]
    return all("$" not in a and "`" not in a for a in plain)


def _gptk_by_g2(name, scripts):
    """Is this .gptk started with $GPTOKEYB2 (gptokeyb2 reads the old format too, by its own rules)?"""
    stem = re.escape(name.rsplit(".", 1)[0])
    for l in scripts.splitlines():
        if l.strip().startswith("#") or not re.search(r"\s-c\s", l):
            continue
        if name in l or re.search(r"\$\{?BINARY\}?\.gptk", l) or re.search(stem, l):
            return bool(re.search(r"GPTOKEYB2", l))
    return False


@check
def ini_files(port):
    if port.gamedir is None:
        return
    scripts = "\n".join(script_text(port, s) for s in port.scripts)
    for p in sorted(port.gamedir.glob("*.ini")):
        text = port.read_text(p)
        if "[controls" not in text or not _gptk_config(p.name, scripts):
            continue
        section, entries, settings = "", [], []
        for l in text.splitlines():
            st = l.strip()
            if not st or st.startswith(("#", ";")):
                continue
            if st.startswith("["):
                section = st.strip("[]").strip().lower()
                continue
            (entries if section.startswith("controls") else settings).append(st)
        if not entries:
            what = "no settings or mappings" if not settings else "only [config] settings and no button mapped (deadzones only act on a mapped stick)"
            yield Finding("ini.empty", INFO, f"{port.rel(p)} has {what}; gptokeyb2 only needs the binary name for the kill switch. "
                          "Without -c it maps nothing (its Start + D-pad text entry only comes with TEXTINPUTINTERACTIVE).",
                          file=port.rel(p), fix='Delete the file and drop -c: $GPTOKEYB2 "$BINARY" &')
            continue
        yield from check_ini(text, port.rel(p), scripts)
    for p in sorted(port.gamedir.rglob("*.gptk")):
        text = port.read_text(p)
        if _gptk_unused(p.name, scripts):
            yield Finding("gptk.unused", INFO, f"{port.rel(p)} isn't passed to gptokeyb by the launch script, so its mappings never apply.",
                          file=port.rel(p), fix="Delete it, or pass it with -c if it was meant to be used.")
            continue
        if "[controls" in text:      # gptokeyb2 reads any file name; sections mean gptokeyb2 format
            yield from check_ini(text, port.rel(p), scripts)
        else:
            yield from check_gptk(text, port.rel(p), g2=_gptk_by_g2(p.name, scripts))


def run_all(port):
    out = []
    for fn in CHECKS:
        try:
            out.extend(fn(port))
        except Exception as e:  # a crashing rule must not hide the others
            out.append(Finding(f"internal.{fn.__name__}", WARN, f"Check {fn.__name__} crashed: {e!r}"))
    try:
        r = reinvent_score(port, out)
        if r:
            out.insert(0, r)   # the first thing the porter reads
    except Exception as e:
        out.append(Finding("internal.reinvent_score", WARN, f"Check reinvent_score crashed: {e!r}"))
    return out
