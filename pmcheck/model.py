"""Load a port (zip, testing-zip folder or PR folder) into one model. Never executes anything."""
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_ZIP_ENTRIES = 50_000
MAX_UNCOMPRESSED = 6 * 1024 ** 3  # 6 GiB
MAX_RATIO = 200  # per-entry compression ratio (zip bomb guard)
JUNK = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}
PART_RE = re.compile(r"\.part\.\d+$")


class LoadError(Exception):
    pass


@dataclass
class Port:
    root: Path               # folder holding the .sh file(s)
    layout: str              # "zip" (metadata inside gamedir) or "pr" (metadata next to .sh)
    scripts: list = field(default_factory=list)   # Paths of top-level .sh files
    gamedir: Path = None
    meta: Path = None        # folder holding port.json/README/gameinfo/screenshot
    top_files: list = field(default_factory=list)
    top_dirs: list = field(default_factory=list)
    junk: list = field(default_factory=list)
    symlinks: list = field(default_factory=list)
    zip_issues: list = field(default_factory=list)
    inner_scripts: list = field(default_factory=list)   # .sh files wrongly placed inside the game folder
    pr: bool = False         # strict PR layout (GitHub check); False = testing zip, either layout is fine
    _tmp: object = None

    def meta_dirs(self):
        """Where metadata may sit: PR mode only `meta`; testing zips also accept the other spot."""
        dirs = [d for d in (self.meta,) if d is not None]
        if not self.pr:
            for d in (self.gamedir, self.root):
                if d is not None and d not in dirs:
                    dirs.append(d)
        return dirs

    def where(self):
        if self.pr:
            return "next to the .sh"
        return "next to the .sh or in the game folder"

    def rel(self, p):
        return str(Path(p).relative_to(self.root))

    def files(self):
        """All regular files below root, skipping junk; split .part.NN files counted once."""
        out = []
        for p in sorted(self.root.rglob("*")):
            if any(part in JUNK or part == ".git" for part in p.relative_to(self.root).parts):
                continue
            if p.is_symlink() or not p.is_file():
                continue
            out.append(p)
        return out

    def logical_files(self):
        seen, out = set(), []
        for p in self.files():
            key = PART_RE.sub("", str(p))
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    def meta_file(self, name):
        for d in self.meta_dirs():
            for p in d.iterdir():
                if p.name.lower() == name.lower() and p.is_file():
                    return p
        return None

    def read_text(self, p, limit=2_000_000):
        with open(p, "rb") as fh:
            return fh.read(limit).decode("utf-8", "replace")

    def cleanup(self):
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)


def safe_extract(zip_path, dest):
    """Extract with path, symlink, count and size checks. Returns list of issue strings."""
    issues = []
    dest = Path(dest).resolve()
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise LoadError(f"not a valid zip: {e}")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise LoadError(f"zip has {len(infos)} entries (limit {MAX_ZIP_ENTRIES})")
        total = sum(i.file_size for i in infos)
        if total > MAX_UNCOMPRESSED:
            raise LoadError(f"zip expands to {total >> 20} MiB (limit {MAX_UNCOMPRESSED >> 20} MiB)")
        for info in infos:
            name = info.filename
            pp = PurePosixPath(name)
            if name.startswith("/") or ".." in pp.parts or re.match(r"^[A-Za-z]:", name) or "\\" in name:
                raise LoadError(f"unsafe path in zip: {name!r}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                issues.append(name)
                continue
            if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 50 << 20:
                raise LoadError(f"suspicious compression ratio for {name!r}")
            target = (dest / name).resolve()
            if dest not in target.parents and target != dest:
                raise LoadError(f"unsafe path in zip: {name!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > info.file_size + (1 << 20):
                        raise LoadError(f"{name!r} is larger than its header claims")
                    dst.write(chunk)
            # keep only the exec bit, never setuid etc.
            target.chmod(0o755 if mode & 0o111 else 0o644)
    return issues


GAMEDIR_RE = re.compile(r"^\s*GAMEDIR=.*?/ports/([^/\"'\s]+)", re.M)


def load(path, pr=False):
    path = Path(path)
    tmp = None
    symlinks = []
    if path.is_file():
        if not zipfile.is_zipfile(path):
            raise LoadError("input is not a zip file or folder")
        tmp = Path(tempfile.mkdtemp(prefix="pmcheck-"))
        symlinks = safe_extract(path, tmp)
        root = tmp
    elif path.is_dir():
        root = path
    else:
        raise LoadError(f"{path} not found")

    # A zip that wraps everything in one extra folder: descend if there is no .sh at the top.
    entries = [p for p in root.iterdir() if p.name not in JUNK]
    inner_scripts = []
    if not any(p.suffix == ".sh" for p in entries) and len([p for p in entries if p.is_dir()]) == 1:
        inner = next(p for p in entries if p.is_dir())
        # The .sh sitting inside the game folder (its GAMEDIR names that folder) is a packaging
        # mistake, not a wrapper folder: keep the zip root so the report says so.
        for s in sorted(inner.glob("*.sh")):
            m = GAMEDIR_RE.search(s.read_text(errors="replace"))
            if m and m.group(1) == inner.name:
                inner_scripts.append(s)
        if not inner_scripts:
            root = inner

    port = Port(root=root, layout="zip", pr=pr, _tmp=tmp)
    port.symlinks = list(symlinks)
    for p in sorted(root.iterdir()):
        if p.name in JUNK:
            port.junk.append(p.name)
            continue
        if p.is_symlink():
            port.symlinks.append(p.name)
        elif p.is_dir():
            port.top_dirs.append(p)
        elif p.suffix.lower() == ".sh":
            port.scripts.append(p)
        else:
            port.top_files.append(p)
    for p in root.rglob("*"):
        if p.name in JUNK and p.parent != root:
            port.junk.append(str(p.relative_to(root)))
        elif p.is_symlink() and p.parent != root:
            port.symlinks.append(str(p.relative_to(root)))

    if inner_scripts:
        port.scripts = inner_scripts
        port.inner_scripts = inner_scripts
    names = {p.name.lower() for p in port.top_files}
    if "port.json" in names:
        port.layout = "pr"
        port.meta = root

    # The game folder: the one named in the script's GAMEDIR, else the only folder, else root name.
    gd_name = None
    for s in port.scripts:
        m = GAMEDIR_RE.search(port.read_text(s))
        if m:
            gd_name = m.group(1)
            break
    for d in port.top_dirs:
        if gd_name and d.name == gd_name:
            port.gamedir = d
    if port.gamedir is None and len(port.top_dirs) == 1:
        port.gamedir = port.top_dirs[0]
    if port.gamedir is None and port.layout == "pr":
        for d in port.top_dirs:
            if d.name == root.name:
                port.gamedir = d
    if port.meta is None:
        port.meta = port.gamedir
    return port
