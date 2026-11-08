"""All checks. Each check takes a Port and yields Findings. Nothing here executes port code."""
import json
import re
import shutil
import struct
import subprocess
import tarfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from . import data
from .findings import Finding, ERROR, WARN, INFO
from .ini import check_ini

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
    if not port.scripts:
        yield Finding("structure.no-script", ERROR, "No launch script (.sh) at the top level.")
    if port.gamedir is None:
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
    for s in port.symlinks:
        yield Finding("structure.symlink", ERROR, f"Symlink {s!r}: symlinks break on FAT/exFAT and across zip/copy.",
                      fix="Ship one real file named after the exact SONAME.")
    for p in port.files():
        size = p.stat().st_size
        if size > data.GIT_FILE_LIMIT:
            yield Finding("structure.file-too-big", ERROR, f"{port.rel(p)} is {size >> 20} MB; GitHub rejects files over 100 MB.",
                          file=port.rel(p), fix="Split into several .tar.gz archives along content boundaries.")
    count = len(port.logical_files())
    if count > data.LOOSE_FILE_LIMIT:
        biggest = _biggest_subdirs(port)
        folders = " ".join(f"{d}/" for d in biggest) or "gamedata/"
        yield Finding(
            "structure.too-many-files", WARN,
            f"{count} files in the package (limit {data.LOOSE_FILE_LIMIT}). Pack the bulk data into a .tar.gz extracted on first launch."
            + (f" Largest folders by file count: {', '.join(biggest)}." if biggest else ""),
            fix="Leave the binary, libs.aarch64/, licenses/ and the control .ini outside the archive.",
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
        if len(rel.parts) > 1 and not rel.parts[0].startswith(("libs.", "gl4es", "licenses", "license")):
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
            yield Finding("files.missing", sev, f"Missing {name} ({where}).")
    for c in port.files():
        if c.name.lower() == "cover.png" and c.parent not in port.meta_dirs():
            yield Finding("files.cover-location", WARN, f"{port.rel(c)} is in the wrong place; cover.png goes {where}.", file=port.rel(c))
    if port.gamedir is not None:
        lic = [d for d in port.gamedir.iterdir() if d.is_dir() and d.name.lower() in ("licenses", "license")]
        loose = [f for f in port.gamedir.iterdir() if f.is_file() and re.search(r"licen[cs]e|copying", f.name, re.I)]
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
    if gd and pj.get("name") != f"{gd}.zip":
        yield Finding("port.json.name", ERROR, f"name is {pj.get('name')!r}, must be {gd + '.zip'!r}.", file=f)
    items = [str(i).rstrip("/") for i in (pj.get("items") or [])]
    actual = [s.name for s in port.scripts] + ([gd] if gd else [])
    for i in items:
        if i not in actual:
            yield Finding("port.json.items", ERROR, f"items lists {i!r}, which is not in the package.", file=f)
    for a in actual:
        if a not in items:
            yield Finding("port.json.items", ERROR, f"{a!r} is in the package but not in items.", file=f)
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
        elif data.RUNTIME_ARCH_SUFFIX.search(r) and not r.startswith("mono-"):
            yield Finding("port.json.runtime", ERROR, f"runtime {r!r} has an arch suffix; use the generic key.", file=f)
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
    if found and not arch and not bad:
        yield Finding("port.json.arch", ERROR, f"Native binaries for {', '.join(found)} but arch is empty.", file=f,
                      fix=f'"arch": {json.dumps(found)}')
    for a in found:
        if arch and a not in arch:
            yield Finding("port.json.arch", WARN, f"Ships {a} binaries but arch does not list {a}.", file=f)
    # min_glibc
    need = [(i["glibc"], p) for p, i in elves(port) if i["glibc"]]
    if need:
        top, top_file = max(need, key=lambda x: version_tuple(x[0]))
        mg = str(attr.get("min_glibc") or "")
        if not mg:
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
    for u in sorted(used - listed):
        yield Finding("port.json.runtime", WARN, f"Script uses runtime {u!r} but port.json runtime does not list it.", file=f)


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
    game = root.find("game") if root.tag == "gameList" else None
    if game is None:
        yield Finding("gameinfo.structure", ERROR, "Expected <gameList><game>...</game></gameList>.", file=f)
        return
    for child in game:
        if child.tag not in data.GAMEINFO_TAGS:
            yield Finding("gameinfo.tag", WARN, f"Undocumented tag <{child.tag}>.", file=f)
    get = lambda t: (game.findtext(t) or "").strip()
    for t in ("name", "desc", "developer", "releasedate", "genre"):
        if not get(t):
            yield Finding("gameinfo.field", WARN, f"<{t}> is missing or empty.", file=f)
    scripts = {f"./{s.name}" for s in port.scripts}
    if get("path") and scripts and get("path") not in scripts:
        yield Finding("gameinfo.path", ERROR, f"<path> {get('path')!r} does not match the script ({', '.join(sorted(scripts))}).", file=f)
    if get("releasedate") and not re.fullmatch(r"\d{8}T\d{6}", get("releasedate")):
        yield Finding("gameinfo.releasedate", WARN, f"<releasedate> {get('releasedate')!r}: use YYYYMMDDT000000.", file=f)
    if port.gamedir is not None:
        gd = port.gamedir.name
        want = f"./{gd}/screenshot.png"
        img = get("image")
        ok = {f"./{gd}/{n}": n for n in ("screenshot.png", "screenshot.jpg", "cover.png")}
        target = img[len(f"./{gd}/"):] if img.startswith(f"./{gd}/") else None
        if not img:
            yield Finding("gameinfo.image", ERROR, "<image> is missing.", file=f, fix=f"<image>{want}</image>")
        elif img not in ok and not (target and "/" not in target and port.meta_file(target)):
            yield Finding("gameinfo.image", ERROR, f"<image> {img!r} points to a file that is not in the package.", file=f, fix=f"<image>{want}</image>")
        elif img not in ok:
            yield Finding("gameinfo.image", WARN, f"<image> is {img!r}; use {want!r} (or ./{gd}/cover.png).", file=f, fix=f"<image>{want}</image>")
        elif port.meta_file(ok[img]) is None:
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
        head = fh.read(24)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
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
    for p in (p for d in port.meta_dirs() for p in d.iterdir()):
        if p.is_file() and re.match(r"^(screenshot|cover)(\..+)?\.(png|jpe?g)$", p.name, re.I):
            kb = p.stat().st_size
            if kb > data.IMAGE_MAX_BYTES:
                yield Finding("images.size", WARN, f"{p.name} is {kb // 1024} KB (limit 100 KB).", file=port.rel(p),
                              fix=f"Compress it with {data.PNG_COMPRESSOR}")


# ---------------------------------------------------------------- README
@check
def readme(port):
    p = port.meta_file("README.md") if port.meta else None
    if p is None:
        return
    text = port.read_text(p)
    heads = {h.strip().lower() for h in re.findall(r"^#{1,3}\s*(.+?)\s*#*$", text, re.M)}
    need = ["notes", "controls"]
    if any(not data.PREBUILT_RE.match(p.name) and p.parent == port.gamedir for p, _ in elves(port)):
        need.append("compile")
    for h in need:
        if not any(x.startswith(h) for x in heads):
            yield Finding("readme.section", WARN if h != "compile" else INFO, f"README has no '## {h.title()}' section.", file=port.rel(p))


# ---------------------------------------------------------------- binaries / libs
def _in_gl4es(p):
    return any(part.startswith("gl4es") for part in p.parts)


@check
def binaries(port):
    scripts_all = "\n".join(script_text(port, s) for s in port.scripts)
    bundled = {}
    for p, info in elves(port):
        if info["type"] == "DYN" and (".so" in p.name):
            bundled[p.name] = p
            if info["soname"]:
                bundled.setdefault(info["soname"], p)
    for name, p in sorted(bundled.items()):
        if p.name != name:
            continue
        rel = port.rel(p)
        if data.GL_LIBS.match(name) and not _in_gl4es(p):
            yield Finding("libs.banned", ERROR, f"{rel}: libGL/libEGL outside a gl4es.<arch>/ folder.", file=rel)
        for rx, why in data.BANNED_LIBS:
            if rx.match(name):
                yield Finding("libs.banned", ERROR, f"{rel} must not be bundled: {why}.", file=rel, fix="Delete it.")
        for rx in data.COMMON_LIBS:
            if rx.match(name):
                yield Finding("libs.common", WARN, f"{rel} is near-universal on CFW images; bundling only bloats the port.", file=rel,
                              fix="Remove it and test on device; add back only if a device reports it missing.")
        so = elf_info(p)["soname"]
        if so and p.name != so and p.name not in scripts_all:
            if (p.parent / so).exists():
                yield Finding("libs.duplicate", WARN, f"{rel} duplicates {so} in the same folder; ship only {so}.", file=rel, fix="Delete it.")
            else:
                yield Finding("libs.soname", WARN, f"{rel} should be named after its SONAME {so!r}.", file=rel)
    for p, info in elves(port):
        rel = port.rel(p)
        for n in info["needed"]:
            if n in bundled or any(rx.match(n) for rx in data.CFW_PROVIDED):
                continue
            yield Finding("bin.needed", WARN, f"{rel} needs {n}, which is not bundled and not a known CFW library.", file=rel,
                          fix=f"Bundle {n} in libs.aarch64/ (one real file, named {n}) or confirm every CFW ships it.")
    # Bundled language runtimes where PortMaster ships a squashfs
    for p in port.logical_files():
        rel = port.rel(p)
        if p.name == "java" and p.parent.name == "bin" and is_elf(p):
            yield Finding("runtime.bundled", WARN, f"{rel}: bundled Java. PortMaster provides JDK/JRE runtimes (squashfs).", file=rel)
        elif re.match(r"^libmonosgen-2\.0\.so|^libcoreclr\.so", p.name):
            yield Finding("runtime.bundled", WARN, f"{rel}: bundled Mono/.NET. PortMaster provides runtime squashfs files.", file=rel)


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
    lic = next((d for d in port.gamedir.iterdir() if d.is_dir() and d.name.lower() in ("licenses", "license")), None)
    if lic is None:
        return
    corpus = " ".join(f.name.lower() for f in lic.rglob("*"))
    for f in lic.rglob("*"):
        if f.is_file() and f.stat().st_size < 2_000_000:
            corpus += " " + port.read_text(f).lower()
    squashed = re.sub(r"[^a-z0-9]", "", corpus)
    main_bins = {f"{port.gamedir.name}.aarch64", port.gamedir.name}
    for p, info in elves(port):
        if p.name in main_bins:
            continue
        is_lib = ".so" in p.name
        if not is_lib and p.parent == port.gamedir:
            continue  # the port's own executables
        stem = re.sub(r"^lib", "", p.name.split(".so")[0]).lower()
        stem = re.sub(r"[-.]\d+(\.\d+)*$", "", stem)
        cands = {re.sub(r"[^a-z0-9]", "", stem), re.split(r"[_\-.]", stem)[0], re.sub(r"file$", "", stem)}
        cands = {c for c in cands if len(c) > 2}
        if cands and not any(c in squashed for c in cands):
            yield Finding("licenses.component", WARN, f"No licence found mentioning {stem!r} ({port.rel(p)}).", file=port.rel(p),
                          fix=f"Add {port.rel(lic)}/LICENSE.{stem}.")


# ---------------------------------------------------------------- launch script
BOILER = re.compile(r"^XDG_DATA_HOME=")


@check
def launch_script(port):
    for s in port.scripts:
        yield from _script(port, s)


def _script(port, s):
    f = port.rel(s)
    raw = Path(s).read_bytes()
    if b"\r\n" in raw:
        yield Finding("sh.crlf", ERROR, "Windows (CRLF) line endings; bash fails on device.", file=f, fix="dos2unix the script.")
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#!/bin/bash"):
        yield Finding("sh.shebang", ERROR, "First line must be #!/bin/bash.", file=f, line=1)
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
            yield Finding(rid, WARN, msg, file=f)
    if not re.search(r"^\s*pm_finish\b", body, re.M):
        yield Finding("sh.pm_finish", WARN, "pm_finish is not called at the end.", file=f)
    for n, l in grep(r"\bSDL_(VIDEO|AUDIO)DRIVER="):
        sev = WARN if "sdl2" in l.lower() and "SDL3SHIM" in body else ERROR
        yield Finding("sh.sdl-driver", sev, "Never force SDL_VIDEODRIVER/SDL_AUDIODRIVER; the CFW selects the backend.", file=f, line=n)
    for n, l in grep(r"^\s*export\s+LD_PRELOAD="):
        yield Finding("sh.ld_preload", ERROR, "export LD_PRELOAD leaks into gptokeyb; set it as a prefix on the game command only.", file=f, line=n)
    if re.search(r"libgl_default\.txt", body) and not re.search(r"libgl_\$\{?CFW_NAME\}?\.txt", body):
        n = grep(r"libgl_default\.txt")[0][0]
        yield Finding("sh.libgl", ERROR, "Source libgl_${CFW_NAME}.txt with a libgl_default.txt fallback, never libgl_default.txt alone.", file=f, line=n)
    if re.search(r"export\s+SDL_VIDEO_(GL|EGL)_DRIVER", body) and '":$LD_LIBRARY_PATH:"' not in body:
        n = grep(r"SDL_VIDEO_(GL|EGL)_DRIVER")[0][0]
        yield Finding("sh.gl-driver", WARN, "SDL_VIDEO_GL/EGL_DRIVER export should be guarded on gl4es being in LD_LIBRARY_PATH.", file=f, line=n)
    for n, l in grep(r"\btar\s+-?[a-zA-Z]*z[a-zA-Z]*f?\b|\btar\b.*\s-z\b"):
        if re.search(r"\btar\s+(c|-c)", l):
            continue
        yield Finding("sh.tar-z", ERROR, "tar -z is unsupported on some BusyBox builds.", file=f, line=n,
                      fix='gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -')
    for n, l in grep(r"\btar\b.*\bx[a-z]*f\b|\btar\s+-x"):
        if "--no-same-owner" not in l:
            yield Finding("sh.tar-owner", WARN, "Extract with tar --no-same-owner.", file=f, line=n)
    for n, l in grep(r"(^|\s|export\s+)HOME=|(^|\s|export\s+)XDG_CONFIG_HOME="):
        yield Finding("sh.home", ERROR, "Don't redirect HOME/XDG_CONFIG_HOME (PulseAudio symlink fails on FAT); use bind_directories.", file=f, line=n)
    for n, l in grep(r"XDG_DATA_HOME=|XDG_CACHE_HOME="):
        if BOILER.match(l.strip()) and "${XDG_DATA_HOME:-" in l:
            continue
        yield Finding("sh.xdg", INFO, "Redirecting a whole XDG root; prefer bind_directories for the game's own folder.", file=f, line=n)
    for n, l in grep(r"^\s*bind_(directories|files)\s"):
        m = re.match(r"\s*bind_(directories|files)\s+(\S+)\s+(\S+)", l)
        if not m:
            continue
        src = m.group(3).strip("\"'")
        before = "\n".join(x for k, x in code if k < n)
        verb = "mkdir" if m.group(1) == "directories" else "touch"
        shipped = _resolve(port, src)
        if shipped is not None and shipped.exists():
            continue
        if not re.search(rf"{verb}\b[^\n]*{re.escape(src)}", before):
            yield Finding("sh.bind-source", WARN, f"bind_{m.group(1)} source {src} must exist first ({verb} it before this line), or the bind silently no-ops.",
                          file=f, line=n)
    for i, (n, l) in enumerate(code):
        after = [x for _, x in code[i + 1:i + 4]]
        near = [x for _, x in code[max(0, i - 2):i]] + after
        if (re.match(r"\s*echo\s+[\"']", l) and ">" not in l and any(re.match(r"\s*exit\s+[1-9]", x) for x in after)
                and not any(re.search(r"\bpm_(message|show_error)\b", x) for x in near)):
            yield Finding("sh.echo-message", WARN, "This message goes to the log, the player never sees it before the exit.", file=f, line=n,
                          fix='pm_show_error "..." --title "..."   (or pm_message on older templates)')
    for n, l in grep(r"\bpm_(message|show_error)\s+--"):
        yield Finding("sh.pm_message-order", ERROR, "pm_message/pm_show_error take the message first, options after.", file=f, line=n)
    for n, l in grep(r"portmsg\.\$\{?DEVICE_ARCH|\./portmsg"):
        yield Finding("sh.portmsg", ERROR, "Don't call portmsg directly; use pm_message/pm_show_error.", file=f, line=n)
    for n, l in grep(r"\$GPTOKEYB\b(?!2)|\.gptk\b"):
        yield Finding("sh.gptokeyb1", WARN, "Classic gptokeyb/.gptk is superseded; new ports use $GPTOKEYB2 with an .ini.", file=f, line=n)
    for n, l in grep(r"(^|[;&|]\s*)sudo\s"):
        yield Finding("sh.sudo", WARN, "Use $ESUDO, not sudo.", file=f, line=n)
    for n, l in grep(r"\bpaste\b"):
        if "|" in l:
            yield Finding("sh.paste", WARN, "ROCKNIX's paste uploads stdin to dpaste.com; don't pipe into paste.", file=f, line=n)
    # Comment noise: long comment blocks belong in docs, not the script.
    run = 0
    for n, l in enumerate(lines, 1):
        if l.strip().startswith("#") and n > 1 and not l.strip().startswith("# PORTMASTER:"):
            run += 1
            if run == 3:
                yield Finding("sh.comments", INFO, "Multi-line comment block; keep comments to one short line per fix.", file=f, line=n - 2)
        else:
            run = 0
    if shutil.which("shellcheck"):
        out = _run(["shellcheck", "-S", "error", "-f", "json", "-s", "bash", str(s)])
        try:
            for item in json.loads(out or "[]"):
                yield Finding("sh.shellcheck", ERROR, f"SC{item['code']}: {item['message']}", file=f, line=item.get("line", 0))
        except ValueError:
            pass
    # Control files referenced by the script
    for n, l in grep(r"\$GPTOKEYB2\b"):
        if "-c" not in l and port.gamedir is not None and any(port.gamedir.glob("*.ini")):
            yield Finding("ini.unused", WARN, "An .ini ships but $GPTOKEYB2 is launched without -c.", file=f, line=n)


def _resolve(port, path):
    """Map a script path like $GAMEDIR/conf/x or /$directory/ports/foo/x into the package, if possible."""
    if port.gamedir is None:
        return None
    p = re.sub(r"^/?\$\{?directory\}?/ports/", str(port.root) + "/", path)
    p = re.sub(r"\$\{?(GAMEDIR|gamedir)\}?", str(port.gamedir), p)
    return None if "$" in p or "~" in p else Path(p)


@check
def ini_files(port):
    if port.gamedir is None:
        return
    scripts = "\n".join(script_text(port, s) for s in port.scripts)
    for p in sorted(port.gamedir.glob("*.ini")):
        text = port.read_text(p)
        if "[controls" not in text:
            continue
        yield from check_ini(text, port.rel(p), scripts)
    for p in sorted(port.gamedir.glob("*.gptk")):
        yield Finding("ini.gptk", WARN, f"{port.rel(p)}: classic .gptk; new ports use gptokeyb2 .ini.", file=port.rel(p))


def run_all(port):
    out = []
    for fn in CHECKS:
        try:
            out.extend(fn(port))
        except Exception as e:  # a crashing rule must not hide the others
            out.append(Finding(f"internal.{fn.__name__}", WARN, f"Check {fn.__name__} crashed: {e!r}"))
    return out
