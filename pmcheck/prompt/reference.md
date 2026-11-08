# Complete PortMaster Porting Reference (for AI-assisted porting)

This is a single, self-contained reference covering everything needed to take a game from
source/binary to a submittable PortMaster port: the exact file structure, full worked examples
of every required file, launch-script patterns for the common engine types, and the real-world
gotchas that the official site's porting.html/packaging.html pages don't mention. Nothing here
assumes access to any other document — copy what you need directly.

**Revision 2026-10-22.** Merged in every later finding (real-device rounds on AmberELEC, dArkOS,
muOS, Knulli and ROCKNIX from 2026-08 to 2026-10). Where an older statement was overturned, the old
text was replaced, not kept beside the new one.

**Policy *(project convention)*: every new port uses gptokeyb2 (`$GPTOKEYB2`, `.ini` config) for control mapping, not
classic gptokeyb (`.gptk`).** All launch-script examples below reflect this. Classic `.gptk`
material is kept, but demoted to a clearly-labeled legacy section for reading or maintaining an
already-shipped port that still uses it (§1.8.5) — don't use it as a template for a new port.

**Every player-facing message in a launch script uses `pm_message`/`pm_show_error` with the
message first and portmsg options after it** (`--title`, `--type`, `--timeout`, §1.7.13).

**Requirement or convention?** This document was written alongside one porter's ports, so it mixes
three kinds of rule. Know which one you're looking at before telling someone their port is wrong:
- **PortMaster requirement**: enforced by PortMaster's own tools (harbourmaster, `funcs.txt`,
  the runtime catalog) or asked for by PortMaster reviewers and templates: the `port.json` schema
  and runtime keys, `gameinfo.xml`, the PR template, the README template, licenses, real
  screenshots, the standard launch-script header, never bundling SDL2.
- **Device-proven fix**: a real failure on a real device and the fix that solved it (most of
  Part 2, the Westonpack `weston_prefix` block, the stick deadzones, the `tar` flags).
- **Project convention** (marked *(project convention)* where it appears): a consistent choice
  this document's ports make, and a good default, but not something PortMaster requires or that
  other porters' ports are wrong to do differently. The list is in "Project conventions" below.

**Where to find things:** Part 1 is the package (files, launch-script patterns per engine/runtime,
control mapping, helper tools). Part 2 is the gotchas by topic (input, graphics, audio,
filesystem, debugging, packaging, the CFW environment, methodology). Part 3 covers building in the
aarch64 chroot (toolchain, glibc floor, profiling tools).

**Project conventions** (good defaults, not PortMaster requirements; other merged ports do
some of these differently):
- gptokeyb2 `.ini` for every new port instead of classic `.gptk` (§1.8).
- Bulk data as a `gamedata.tar.gz` by default (§2.4). Shipping files loose is valid; packing them is
  a size/file-count choice, and the archive *flags* (`--owner=0 ...`, `gunzip -c | tar
  --no-same-owner`) are device-proven fixes once you do pack.
- A `patches/` folder with every patch the README's Compile section uses (§1.1).
- Testing zips in the installed layout: only the `.sh` and the game folder at the top, all
  metadata, `patches/` and `licenses/` inside the game folder (§1.1.1).
- The fixed mouse buttons (A left click, B right click, X slow) and the standard mouse `[config]`
  block values (§1.8.1). The stick deadzone *problem* is device-proven; the exact numbers are
  this project's tested choice.
- gptokeyb2 output sent to `/dev/null` (§1.7.2) and `CRUSTY_BLOCK_INPUT=1` on every Westonpack
  script (§1.7.4).
- No `.ini` for a kill-switch-only port; one short line per comment in a launch script; no em
  dashes in generated text; one `.sh` per port, with gamepad-picker for startup choices.
- `pm_message`/`pm_show_error` with portmsg options for every player-facing message (§1.7.13).
  The functions are PortMaster's own; using them everywhere is this project's choice.

---

# PART 1 — Complete Port Structure & File Examples

## 1.1 Directory layout

There are three layouts, and people mix them up (see §1.1.1). The tree below is the **PR/submission
layout**: a port's folder in the PortMaster-New repository (named after the game, matching the
`.sh`'s title) contains:

```
portname/
├── port.json
├── README.md
├── screenshot.png          (4:3, min 640x480, real gameplay capture — never generated/fabricated)
├── cover.png                (optional but expected for a real submission)
├── gameinfo.xml
├── testing_thread.txt       (temporary — content for the Discord testing-thread post, not launched)
├── Port Name.sh              (capitalized, ends in .sh — this is what actually launches the game)
├── patches/                  (every patch/helper file the README's Compile section uses)
└── portname/                 (lowercase, squashed: no underscores, no dashes — e.g. "daserbe" not "das_erbe")
    ├── portexecutable.aarch64          (binary renamed with .$DEVICE_ARCH suffix)
    ├── libs.aarch64/                    (bundled shared libraries, minimum needed only)
    │   └── libfoo.so.2                  (flattened real file, not a symlink chain — name matches DT_NEEDED SONAME exactly)
    ├── gl4es.aarch64/                   (only if the engine has no native GLES path — see §2.2)
    │   ├── libGL.so.1
    │   └── libEGL.so.1
    ├── licenses/                        (one file per bundled component, not one blanket file)
    │   ├── LICENSE-portname.txt
    │   └── LICENSE-libfoo.txt
    ├── gamedata.tar.gz                  (bulk data, extracted on first launch — see §2.4)
    └── portname.ini                     (plain filename, no arch suffix — see §1.8)
```

`patches/` *(project convention)* sits next to `README.md` and holds every patch or helper script
the README's Compile section refers to, regenerated whenever the source changes. A README that
references a patch the package doesn't contain is a real, flagged packaging bug; a `*-build/`
side folder outside the package doesn't count. **Don't put `patches/` (or any second folder) at the
top level of a zip that harbourmaster installs**, such as a testing zip: harbourmaster treats every
top-level folder as part of the port, so it would be installed as `ports/patches/`, and its
metadata fix-up uses the *first* folder in the zip (below). In a testing zip, put it inside the game
folder or leave it out.

### 1.1.1 The three layouts: PR, testing zip, installed

Read from harbourmaster's own install code (`captain.py`'s `check_port()`, `harbour.py`'s
`_install_port()`):

1. **PR/submission layout** (the tree above): metadata files next to the `.sh` and the game folder.
   This is what goes into the PortMaster-New repository.
2. **Installed layout** on the device: harbourmaster puts the `.sh` in the ports folder and moves
   the metadata *into* the game folder: `ports/Port Name.sh`, `ports/portname/port.json`,
   `ports/portname/gameinfo.xml`, `ports/portname/screenshot.png`, and so on. This is why
   `gameinfo.xml`'s `<image>` is `./portname/screenshot.png` (§1.3), and why released ports
   look like this when you browse a device.
3. **A zip that harbourmaster installs** (a testing zip in the autoinstall folder, or
   `harbourmaster install <zip>`): **both forms work.**
   - Metadata at the zip's top level: `port.json`, `gameinfo.xml`, `readme.md`, `cover.png`/`.jpg`
     and `screenshot.png`/`.jpg` (the only non-`.sh` names harbourmaster accepts at the top
     level, case-insensitive) are moved into the game folder on install.
   - Metadata already inside the game folder (`portname/port.json`, `portname/gameinfo.xml`,
     exactly one level deep) is found there and used as-is.

   Either way the zip needs at least one top-level `.sh` and one top-level folder, or the install
   is rejected. Other top-level files (`testing_thread.txt`, notes) only produce a warning and are
   extracted loose into the ports folder, so keep them out of the zip. A `.sh` inside the game
   folder also gives a warning. When metadata is at the top level, it goes into the **first
   top-level folder in the zip's order**, so with more than one folder, add the game folder to the
   zip first (`zip -r portname.zip "Port Name.sh" portname/ ...`).

Some porters build testing zips in the PR layout, others move the metadata into the game folder
first (the installed layout); neither is wrong for testing. **This document's testing zips always
use the installed layout** *(project convention)*: only `Port Name.sh` and the game folder at the
top, with everything else inside the game folder next to the binary — `port.json`, `README.md`,
`gameinfo.xml`, `screenshot.png`/`cover.png`, `testing_thread.txt`, `patches/`, `licenses/`.
That also avoids the two top-level warnings above (a loose `testing_thread.txt`, `patches/`
installed as its own folder). Before opening the PR, move the PR-level files (`port.json`,
`README.md`, `gameinfo.xml`, the images) up one folder to get the PR layout; `screenshot.png`
dropped at `portname/screenshot.png` already matches `gameinfo.xml`'s `./portname/screenshot.png`.
```
kondor/                      (testing zip)
├── Kondor.sh
└── kondor/
    ├── README.md, gameinfo.xml, port.json, testing_thread.txt
    ├── gamedata.tar.gz, kondor.aarch64, kondor.ini
    ├── licenses/
    └── patches/
```
How PortMaster's own release build turns a PR folder into the released zip isn't covered here;
follow the PR layout for the PR itself.

Notes on this layout:

- **`port.json`'s `items` array only lists what's needed to launch the game** — the `.sh` and its
  data folder. `README.md`, `gameinfo.xml`, `cover.png`, `screenshot.png`, `testing_thread.txt`,
  and `licenses/` are all real files in the structure but are **not** listed in `items`.
- **The inner folder name is independent of the `.sh` filename.** The `.sh` keeps title case and
  spaces for display (`Das Erbe.sh`), the inner folder is always lowercase-squashed (`daserbe`).
- **`licenses/` lives inside the game subfolder**, at the same level as `libs.$DEVICE_ARCH`, not
  at the top level next to `port.json`.
- **Ask "does this need to be bundled at all" before asking "how do I build a leaner version."**
  Check the near-universal list first: `libexpat`, `libfreetype`, `libpng`, `libbz2`, `zlib`,
  **and `SDL2_image`/`SDL2_mixer`/`SDL2_ttf` themselves** are near-universal on any real CFW base
  image already — bundling them "just in case" only adds bloat. The CFW baseline PortMaster
  expects (from its CFW-author guide): glibc 2.29+, `libstdc++.so.6` with `GLIBCXX_3.4.21`+,
  `libgcc_s.so.1`, `libm`/`libpthread`/`libdl`/`librt`, `libz.so.1`, the SDL2 family
  (`libSDL2-2.0.so.0`, `libSDL2_mixer-2.0.so.0`, `libSDL2_image-2.0.so.0`, `libSDL2_ttf-2.0.so.0`),
  and commonly `libpng16.so.16`, `libjpeg.so.62`, `libfreetype.so.6`, `libfontconfig.so.1`,
  `libasound.so.2`. dArkOS-style CFWs also add Debian 11-era compat libs (`libFLAC.so.8`,
  FFmpeg 4.3 `libavcodec.so.58`/`libavformat.so.58`/`libavutil.so.56`/`libswresample.so.3`/
  `libswscale.so.5`, `libvpx.so.6`, `libwebp.so.6`, `libaom.so.0`, `libdav1d.so.4`,
  `libcodec2.so.0.9`, `libx264.so.160`/`libx265.so.192`, `libwavpack.so.1`, `libjpeg.so.8`), but
  not every CFW does (current AmberELEC prereleases ship `libjpeg.so.8` too, so it no longer needs
  bundling there). Libraries ports commonly bundle themselves: OpenSSL 1.1
  (`libcrypto.so.1.1`/`libssl.so.1.1`), `libSDL-1.2.so.0`, `libogg`/`libvorbis`/`libvorbisfile`,
  `libzip.so.5`/`.4`, `libluajit-5.1.so.2`, `libfluidsynth.so.1`/`.2`, `libFNA3D.so.0`/
  `libFAudio.so.0`.
- **Not near-universal, confirmed by real "cannot open shared object file" errors:**
  `libphysfs.so.1` (missing on Retroid Pocket 5/ROCKNIX, `critter` port: `error while loading
  shared libraries: libphysfs.so.1`), `libopenal.so.1` (don't count on it), `libprotobuf.so.23`,
  `libcrypto.so.3`, newer `libstdc++.so.6` builds, `libsndio.so.7` (+ `libbsd`/`libmd`, pulled in
  by a distro OpenAL Soft build's hard-linked sndio backend) on RG351V/AmberELEC, and
  `libbrotlidec.so.1`/`libbrotlicommon.so.1` (freetype's WOFF2 support, via SDL3_ttf) on R36S/dArkOS.
  Bundle these when a port links them, resolved down to the real file and renamed to the exact
  SONAME. Only bundle libraries a real device error names, or that a `readelf -d` walk shows are
  hard `NEEDED` and absent from the baseline above — don't pre-emptively bundle a whole transitive
  chain (e.g. harfbuzz's glib/graphite2) "just in case."
- **Never bundle anything the device's own GPU/display stack links**: `libEGL`, `libGLESv2`,
  `libGLESv1_CM`, `libdrm`, `libgbm`, `libmali`, **and `libwayland-client`/`libwayland-egl`/
  `libwayland-cursor`** on Wayland-compositor devices (ROCKNIX). A bundled `libwayland-client` from
  the build chroot shadowed the device's own and produced `undefined symbol:
  wl_display_create_queue_with_name`. Same reasoning as never bundling SDL2 (below): the
  device-specific copy is the one that works with that device's driver. Also never build against
  a CFW's vendor driver blob; build against the chroot's generic `-dev` packages.
- **Check a library against `readelf -d`, not `ldd`, when deciding what to bundle.** `ldd` in the
  build chroot resolves against the chroot's own `/usr/lib`, hiding exactly the gaps that matter
  on the device. Walk the `NEEDED` closure recursively with `readelf -d` over every shipped binary
  *and* every bundled `.so` and plugin.
- **Don't reuse another port's bundled `.so` without checking it does what this port needs.** A
  reused `SDL2_image` couldn't decode TGA ImageType 9 (RLE true-colour) and the game's sprites
  silently failed to load. Test decode of the game's actual files against the exact `.so` being
  shipped (§2.5 has a headless chroot test for this).
- **`licenses/` covers every shipped third-party component**, including every managed .NET DLL
  (use the project's `PackageReference` list as the authoritative inventory, not just the `.so`
  files). **Don't ship a license for gptokeyb2 or portmsg** — PortMaster itself provides both
  tools, they are never inside the port. Don't trust a NuGet/packaging layer's bundled license
  file as complete (§2.6).
- **Eliminate a dead dependency at its source rather than bundling it.** If a binary hard-links
  a library it never actually calls (X11 is the classic case: a Pascal binding unit, an engine's
  SConscript, or a distro build pulling `libX11.so.6` in on a device with no X server), patch the
  build so the `NEEDED` entry disappears (verify with `readelf -d`), instead of shipping a six-file
  X11 chain to a KMS/DRM-only device. Concrete fixes: §1.7.18 (OHRRPGCE `no_x11=1`), §1.7.19
  (Free Pascal X11 unit stubs).
- Confirmed real case for the bundling question: the `dreamchess` port built a whole custom, dependency-trimmed
  `SDL2_image`/`SDL2_mixer` pair to avoid a bloated distro `SDL_mixer`'s MIDI-synth dependency
  chain, without ever checking whether the CFW already had a working copy — a real-device test
  (deleting both bundled `.so` files from the installed port) proved byte-identical launch
  behavior, meaning the entire custom-build step was unnecessary. Only *after* confirming bundling
  is genuinely necessary (the library isn't on the base image, or the base image's copy is missing
  a codec/feature actually needed) does "build a leaner version from source" become the right move
  over shipping a distro package's full, bloated dependency chain.
- **Never bundle a port's own `libSDL2-2.0.so.0` (or any core `libSDL2*.so`) in `libs.$DEVICE_ARCH`,
  under any circumstances — even paired with an `sdl12-compat` shim.** The CFW already ships its
  own SDL2, built and patched specifically for that device's KMS/DRM, input, and audio stack; a
  port-bundled copy shadows it via `LD_LIBRARY_PATH` and can silently break things the CFW's own
  build already handles correctly. Confirmed real failure on the `amphetamine` port (SDL 1.2 engine
  + bundled `sdl12-compat` shim): bundling a chroot-built SDL2 2.26.2 alongside the shim produced a
  real on-device PulseAudio failure (`Failed to symlink ... Unknown error 524`) that disappeared
  once the bundled SDL2 was removed and the shim was left to `dlopen()` the device's own system
  SDL2 instead. This holds even when the chroot has a known-good custom SDL2 build used for
  compiling this project's other native SDL2 ports — that build is for linking against at compile
  time only, never for shipping in a port's `libs.$DEVICE_ARCH`. If a port needs `sdl12-compat`,
  bundle *only* the `sdl12-compat`-built `libSDL-1.2.so.0` shim and let it find the system SDL2 on
  its own. The same principle applies to the `sdl3-sdl2-backend` shim (§1.7.12): never bundle a real
  SDL2 alongside it either — it `dlopen`s the device's own system SDL2 the same way.
- **Never compile or link a port's own code against `sdl12-compat` (or gl4es).** Both are runtime
  drop-in replacements (`libSDL-1.2.so.0` and `libGL.so.1` respectively), not SDKs. Compile against
  the build environment's real SDL 1.2 (`libsdl1.2-dev`/`libsdl-mixer1.2-dev`, plain
  `sdl-config`) exactly as upstream's build expects; `sdl12-compat`'s own `include/`/`build/`
  directories never appear in a `-I`/`-L` flag. It only belongs in the finished package's
  `libs.$DEVICE_ARCH/`, picked up via `LD_LIBRARY_PATH` at launch. This mistake produces no build
  error and an identical `readelf -d` result (`NEEDED libSDL-1.2.so.0` either way, the ABI is the
  same), so it has to be caught by checking the actual `-I`/`-L` paths in the build, not the
  output (real case: the `fanwor` port's `src/Makefile` pointed `CFL_sdl`/`LIBS_sdl` at the
  sdl12-compat checkout; fixed by going back to plain `sdl-config`).
- **Build the shipped `sdl12-compat` from a tagged upstream release** (e.g. `release-1.2.76`),
  not a distro `libsdl1.2-compat` package: the distro 1.2.52 build segfaulted on video init on a
  real device (ASC port). And if a locally patched sdl12-compat adds a software-cursor present on
  every mouse motion, ship the **stock** build for games that draw their own cursor
  (`SDL_ShowCursor(0)` or an empty cursor): the extra `PresentScreen()` per motion event starved
  LGeneral (about 28% of samples spent in `eglSwapBuffers`).

## 1.2 port.json — current schema (v4)

Generated conceptually via the Port JSON Generator, but hand-editable. Don't trust an older
port's committed `port.json` as a schema reference without checking its own `version` field
first — the schema has changed over time, and older merged ports can still be on `version: 3`.

Full real example, current schema:

```json
{
  "version": 4,
  "name": "portname.zip",
  "items": [
    "Port Name.sh",
    "portname"
  ],
  "items_opt": [],
  "attr": {
    "title": "Port Name",
    "porter": [
      "YourHandle"
    ],
    "desc": "Plain text description shown in the PortMaster app itself. No markdown, no literal \\n escapes.",
    "desc_md": null,
    "inst": "Plain text instructions shown in the PortMaster app itself. No markdown, no literal \\n escapes.",
    "inst_md": null,
    "genres": [
      "action"
    ],
    "image": null,
    "rtr": true,
    "exp": false,
    "runtime": [],
    "store": [],
    "availability": "full",
    "reqs": [],
    "arch": [
      "aarch64"
    ],
    "min_glibc": ""
  }
}
```

Field notes:

- **`name`**: the zip filename, `<foldername-from-.sh>.zip`.
- **`items`**: the `.sh` and the game data folder — nothing else.
- **`title`**: display name. It can be the game's full title even when the `.sh` keeps a short
  name (`DMOMD.sh` with the full title in `port.json` and `gameinfo.xml`).
- **`porter`**: array of porter handle(s), never a placeholder.
- **`desc` / `inst`**: shown **in the PortMaster app itself**. Plain text only — no markdown, no
  literal `\n` escapes. **`inst` is setup instructions, not controls**: one sentence on how to get
  the game running and which files (if any) the player must supply ("Ready to run out of the box,
  no additional files needed." / "Copy your legally obtained data files to ports/portname/ before
  launching."). Controls go in `README.md` and `testing_thread.txt`, never a button table here.
- **`desc_md` / `inst_md`**: shown **on portmaster.games** instead of the plain versions, if
  filled in (markdown supported, e.g. bullet lists). If left `null`, the plain version is used on
  the website too. These are two different renderings for two different surfaces — only set the
  `_md` variant when it genuinely adds something (real markdown formatting, or more content) over
  the plain one. Don't paste in a reformatted duplicate of the same text.
- **`genres`**: one or more of `action`, `adventure`, `arcade`, `casino-card`, `fps`, `platformer`,
  `puzzle`, `racing`, `rhythm`, `rpg`, `simulation`, `sports`, `strategy`, `visual-novel`, `other`
  (exact lowercase slugs may vary slightly by generator version — cross-check against the actual
  generator form if precision matters).
- **`rtr`**: "Ready To Run" — true if the port launches with everything bundled, no user-supplied
  game files needed.
- **`exp`**: experimental flag — true hides the port unless the user enables experimental ports.
  **This is for a *released* port PortMaster wants hidden from the default listing** (e.g.
  known-broken-on-most-devices, or deliberately soft-launched), **not** a general "still in
  testing/not yet verified" flag. Never set this true on a port still being developed/tested — that
  is the normal, expected state for every port before its first PR. Leave it `false` unless the
  port itself, not its testing status, should ship hidden.
- **`runtime`**: a **list**, not a single string. Leave `[]` unless a runtime squashfs is used and
  not already fully handled inside the `.sh`. **Critical gotcha**: this must be the literal
  runtime *catalog key*, not the generator's display label. E.g. the display label "Westonpack
  0.2" is not what goes here — the real key is `weston_pkg_0.2`. PortMaster's runtime-check code
  (`check_runtime()` in `harbourmaster/harbour.py`) does an exact, untranslated lookup of this
  string (plus `.squashfs`) against the device's cached runtime catalog (`PortMaster/config/
  runtimes.json`) — there is no nicename-to-key translation anywhere in that path. Using the
  display label instead of the real key **fails silently** on any device that doesn't already
  happen to have that runtime cached from an unrelated port install — a launch script's own
  `if [ ! -f .../weston_pkg_0.2.squashfs ]; then ... runtime_check ...` guard correctly uses the
  real key and only runs when the file is missing, so a device that already has it hides the bug
  entirely; only harbourmaster's own post-install runtime check, driven directly by this
  `port.json` field, actually exercises the broken path. If in doubt, check a real device's own
  `PortMaster/config/runtimes.json` for the actual key before trusting a generator's dropdown text.
  The generator's runtime labels include: Mesapack 0.1, Mono (6.12.0.112), Pyxel 2.2.8, RenPY
  8.3.4, Real Live VM, Solarus 1.6.5, Westonpack 0.2, Godot/FRT (2.1.6 through 4.1.3 variants),
  Java (jdk11.0.11, jdk17.0.10, jre17.0.13). Real keys seen in shipped ports: `weston_pkg_0.2`,
  `mesa_pkg_0.1`, `frt_2.1.6`, `frt_3.2.3`, `zulu11.48.21-ca-jdk11.0.11-linux`,
  `zulu17.54.21-ca-jre17.0.13-linux`, `dotnet-8.0.12`, `gmtoolkit`, `python_3.11`, `pyxel_2.2.8`.
  - **The key is generic, with no architecture suffix** (`frt_3.3.4`, not `frt_3.3.4.aarch64`).
    `check_runtime()` looks the generic key up in the catalog, then resolves the current device's
    `primary_arch` against that entry's own `arch` dict to pick the right per-arch file, URL and
    checksum, so one `port.json` works on aarch64, armhf and x86_64. The catalog entry's shape is
    `name`/`default`/`arch` (dict of per-arch file info). `mono-6.12.0.122-aarch64` (arch baked
    into the key) is the **one** legacy exception the maintainer keeps for backwards
    compatibility; don't model a new key on it. A real merged PR had to be fixed for exactly this.
  - `.squashfs` is auto-appended if omitted, so `"python_3.11"` and `"renpy_8.1.3.squashfs"` both
    work; cosmetic, not two conventions.
  - The master catalog is `PortsMaster/PortMaster-New/runtimes/runtimes.json` (the submission
    repo). A device's `PortMaster/config/runtimes.json` is only a synced local cache. Its MD5 fast
    path makes an unconditional `runtime_check` cheap when the file is already present.
- **`store`**: list of purchase links, `[]` if freeware/fully bundled. **Not a bare list of URL
  strings** — flagged directly on a live PR review (`arcanumce`) by a PortMaster team member. Each
  entry is an object:
  ```json
  "store": [
    {
      "name": "GOG",
      "gameurl": "https://www.gog.com/game/example",
      "developerurl": "https://example-studio.com/"
    }
  ]
  ```
  Fall back to a Wikipedia page for `developerurl` when the studio is defunct and its old domain
  has been squatted/redirected elsewhere — don't link a squatted domain.
- **`availability`**: e.g. `"full"` for a complete free/bundled game.
- **`reqs`**: leave `[]` unless the game or the `.sh` explicitly needs one of: a resolution
  requirement (generator label "Not Lowres" excludes 480x320/351p/OGA/zpg pro/rgb10; "Highres"
  requires above 640x480; "Any Resolution" is the default), a RAM minimum (No Minimum/2GB
  Minimum/4GB Minimum), "Power" (any device above rk3326), or "OpenGL" (real desktop OpenGL, not
  just GLES). **Same label-vs-token trap as `runtime`: the JSON holds a short token, not the form
  label.** Tokens seen in real shipped ports: `"!lowres"` (Not Lowres, e.g. a game whose UI can't
  fit 480x320) and `"power"`. Check a real merged port or the generator's JSON output for any
  other token before writing it by hand.
- **`arch`**: `aarch64`, `armhf`, `x86_64`, `x86` — whichever the binary actually targets.
  **`runtime` and `arch` are mutually exclusive: if `runtime` is set, leave `"arch": []`**, even
  when the port also ships a native binary (e.g. a Westonpack or Qt-runtime port); the runtime's
  catalog entry already carries the per-arch resolution. Confirmed against real merged ports
  (`angrydd`, `cavelotf`). Only set `arch` for a port with no runtime. harbourmaster ORs the
  entries (`'|'.join(arch)`), so `["armhf"]` means "needs armhf support" (box86 ports, §1.7.14).
- **`min_glibc`**: leave `""` unless a specific minimum glibc version is actually known/required.

## 1.3 gameinfo.xml

Feeds the CFW's frontend (EmulationStation-style) metadata on install, including the cover.
Generated via the Port Metadata Editor (https://portmaster.games/metadata-editor.html). Whatever
the form accepts as input, **the XML itself always holds `YYYYMMDDT000000`** (EmulationStation
format, e.g. `20060606T000000`), never `dd/mm/yyyy`; every finished package uses this form.

```xml
<?xml version="1.0" encoding="utf-8"?>
<gameList>
  <game>
    <path>./Port Name.sh</path>
    <name>Port Name</name>
    <desc>A real, specific description of the game — genre, what it plays like, notable features. Not a copy of port.json's desc verbatim if you can do better here.</desc>
    <releasedate>20230819T000000</releasedate>
    <developer>Original Developer or Team Name</developer>
    <publisher>Original Publisher (use "Open Source" for a self-published/community project)</publisher>
    <genre>Action</genre>
    <image>./portname/screenshot.png</image>
  </game>
</gameList>
```

Notes:

- **`<path>`** matches the `.sh` filename exactly, relative (`./Port Name.sh`).
- **`<image>`** path is relative to `gameinfo.xml`'s own top-level location. If a real,
  purpose-made `cover.png` exists, reference that instead of `screenshot.png`; if no cover was
  made, referencing `screenshot.png` as the fallback is the convention — PortMaster falls back to
  the screenshot automatically if no cover is provided anyway, but being explicit here is fine.
  Never invent a path to a `cover.png` that doesn't actually exist in the package. **The path must
  include the game-subfolder prefix** (`./portname/screenshot.png`, not a bare `./screenshot.png`),
  even though the file physically sits at the zip's top level next to `port.json`/`README.md` —
  PortMaster's own install step, not the submitted zip's own layout, is what EmulationStation's
  gamelist image lookup actually resolves against. The zip's internal layout and the on-device path
  `gameinfo.xml` needs to describe are two different things — don't reason from one to the other
(harbourmaster moves `gameinfo.xml` and the images into the game folder on install, §1.1.1).
- **`<releasedate>`** format is `YYYYMMDDT000000`.
- **Developer/Publisher**: research the actual original game/engine's info online if unknown —
  don't leave placeholders.
- **`<desc>`** must be present in the XML itself even if the same text exists elsewhere (`port.json`)
  — don't skip it assuming it's redundant.
- **Don't copy extra fields from a real merged reference port without checking they're still part
  of the current schema.** A real, already-merged port's `gameinfo.xml` once picked up a stray
  `<players>2</players>` tag this way, copied from an older/non-conformant reference port even
  though no current schema documentation mentions a `players` field at all. Cross-check every
  field a reference port has against the actual current field list above before including it —
  don't include something just because a real example port happens to have it.

## 1.4 README.md

The real, current README template starts directly at `## Notes` — **no top-level `# GameName`
title above it.**

````markdown
## Notes

Thanks to [OriginalAuthorName](https://github.com/example/repo) for creating this game, a tight, replayable [genre] with [one genuine, specific, positive detail about what makes it worth playing].

## Controls

| Key | Action |
|--|--|
| D-Pad | Move |
| A | Confirm / Jump |
| B | Cancel / Attack |
| X | Use Item |
| Y | Special |
| L1 | Previous |
| R1 | Next |
| Start | Pause |
| Select | Menu |

## Compile

```bash
git clone --recurse-submodules https://github.com/example/yourgame.git
cd yourgame
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make
```
````

Rules that matter here:

- **The first section is always a one-sentence thank-you to whoever actually wrote the thing
  being ported** — the original game/engine author or reimplementation maintainer, not (only)
  whoever packaged it for PortMaster. Verify the actual repo URL before linking it (e.g.
  `curl -s https://api.github.com/repos/<org>/<repo>`), don't guess or infer it from local git
  config/session context. Name them, link their site, add one genuine specific positive detail
  about the game — not a generic filler adjective ("this classic game"), and not a multi-clause
  elaboration either. Before crediting a fork with "adds features on top of upstream," actually
  diff it against upstream (e.g. the GitHub compare API) — a fork's own commit history existing
  doesn't mean it diverged; sometimes the commits are byte-identical to upstream (same SHAs) and it
  adds nothing.
- **No "Known Limitations" or similar meta-commentary section.** That's PR/session review
  content, not something that belongs in a shipped README.
- **Keep Notes to genuinely user-facing information.** Don't restate facts that only matter
  internally — "the original game files are bundled in this folder" tells a user nothing they
  don't already have in front of them once the port is installed.
- **The Controls table lists actual bindings.** Omit rows for buttons the port doesn't bind to
  anything — don't fill a row in with "Unused"; a button with no row is already understood to do
  nothing.
- **Source code doesn't go in the package.** The PR template's file structure has no sources
  folder, and nothing in PortMaster's tooling uses one. The README's Compile section points at the
  upstream repository (pin the exact tag or commit you built, so the steps stay reproducible), and
  the port's own changes ship as `patches/` (§1.1). Don't invent a separate `portname-sources.zip`
  or a second archive. If there's no upstream repo to point at (e.g. source from a forum post or a
  dead site), publishing a repo or fork is the cleanest place for it. Licence obligations are a
  separate question: a GPL program's binaries must have their corresponding source available,
  which an upstream link plus the shipped patches normally covers; check the licence when it
  doesn't.
- **The Build/Compile section is a reproduction guide, not a packaging checklist.** It documents
  how to get from source to the finished build artifact, as a complete bootstrap from a bare
  environment (e.g. for a .NET port: installing the matching SDK, building any bundled translation
  layer from source, then the publish step) — stop there. Don't include: how the final port folder
  gets assembled from the build output (file-tree diagrams, "copy X here" — that's an internal
  packaging note, not something a reader compiling from source needs, and it goes stale the moment
  the layout changes), or post-build cleanup detail (stripping symbols, deleting a bundled library,
  content-pipeline quirks — that's build-script documentation, not README content). Every
  dependency that needs more than "install the distro package" gets its own numbered subsection
  with a real, complete, copy-pasteable command block — not a prose bullet describing what to do
  instead of showing the actual commands. Each subsection runs in order: download, any workaround
  with a one-line reason why, then configure/build/install.
- **Every command block is a fenced ```` ```bash ```` code block, never bare or indented lines.**
  Bare lines look fine in a plain-text editor but break once GitHub renders the markdown (`*`/`_`
  inside a command turn into formatting, no copy button).
- **Patches the Compile section applies live in the package's top-level `patches/` folder** (§1.1)
  and the commands reference them from there.
- *(project convention)* **Never use an em dash anywhere in generated port content** (README, `port.json` fields, any
  other doc). Use a period, comma, colon, semicolon, or parentheses instead.

## 1.5 testing_thread.txt

Easy to skip entirely — nothing else in a port's file set implies it needs to exist, since no
game logic reads it and no other file references it, but it's expected content for the Discord
`#testing-n-dev` post before opening a PR:

```
Instructions to install the Testing Zip:
Drop the .zip into your Portmaster autoinstall folder and run Portmaster.
or
run via ssh: harbourmaster install "zip url from discord"

Game Information
Title: Port Name
URL: https://github.com/example/yourgame

Instructions:
Ready to run. No additional setup required.

| Button | Action |
|--|--|
|A| Jump |
|B| Shoot |
|X| Run (hold) |
|Y| Activate |
|L1| Previous weapon |
|R1| Next weapon |

CFW Tests:
[ ] AmberELEC
[ ] dArkOS
[ ] MuOS
ROCKNIX
-> [ ] Libmali
-> [ ] Panfrost
-> [ ] Adreno (Optional)
[ ] Knulli

Resolutions:
[ ] 480x320 (Optional)
[ ] 640x480
[ ] 720x720 (RGB30) (Optional)
[ ] Higher resolutions (e.g., 1280)
```

**The combined `A/B/X/Y` row format is only for the rare case where all four face buttons
genuinely do the same kind of thing** (e.g. all four fire the same action in different
directions) — it is not a template to fill in literally when the four buttons do different
things, which is the normal case. When each face button binds a different action (as in the
example above), give each one its own row so a reader can look up "what does X do" without
parsing a combined cell — this matches the same rule already applied to README.md's own Controls
table in §1.4.

Omit table rows entirely for buttons the port doesn't bind to anything at all, same rule as the
README — don't write "Unused" rows, and don't put a dash or other placeholder in the Action cell
either. Add a `|DPAD| <action> |` row when the D-pad does something. ROCKNIX has no single
pass/fail checkbox of its own; it's tested per GPU driver variant (Libmali, Panfrost, Adreno)
since behavior can genuinely differ between them on the same CFW. The no-em-dash rule from §1.4
applies to this file too.

## 1.6 The GitHub Pull Request template

This is the section the official site's porting/packaging pages don't mention at all, and it's
the most important one for an AI-assisted port specifically. This is the current PortMaster repo
PR template (`.github/PULL_REQUEST_TEMPLATE.md` upstream) — it supersedes the older
checklist-only style that just mirrored the Discord testing thread; it now also requires an
authorship/self-review attestation, a specific file-structure listing, and a script-conventions
check. Paste this into the PR description when opening the port PR:

```markdown
## Game Information
- **New Port for**: { Game Title }
- **URL**: { Link to project page or source control page }

## Authorship & Testing

- [ ] I wrote and understand this script/patch myself, or clearly marked which parts came from an AI assistant and reviewed them
- [ ] I can explain every non-standard line in my launch script

## Submission Requirements

### CFW Tests
Ensure your game has been tested on all major CFWs:
- [ ] ArkOS
- [ ] AmberELEC
- [ ] ROCKNIX
- [ ] muOS
- [ ] Knulli
- [ ] Crossmix (Optional)
- [ ] Other (add here)

### Resolution Tests
Test all major resolutions:
- [ ] 480x320 (Optional)
- [ ] 640x480
- [ ] 720x720 (RGB30) (Optional)
- [ ] Higher resolutions (e.g., 1280x720)

## File Structure
- Your port should have the following structure:
  - portname/
    - port.json
    - README.md
    - screenshot.png
    - cover.png
    - gameinfo.xml
    - Port Name.sh
    - portname/
      - <portfiles here>

## Script Conventions

Before submitting, check your launch script against a few recently merged ports of a similar type.
If your script is significantly longer that or does over complicate things that don't appear in any merged port, remove that logic unless you can point to a game-specific reason it's needed. Reviewers will ask why non-standard logic is there.

## Additional Resources
For an in-depth guide on creating a pull request, refer to: [PortMaster Game Packaging Guide](https://portmaster.games/packaging.html#creating-a-pull-request)
```

`screenshot.png` and `cover.png` are `.png` files (not `.jpg`).

**If AI wrote or helped write the launch script, that box genuinely needs to be checked
honestly, and it means you need to actually be able to explain every non-standard line, not just
paste what the AI produced.** This is exactly the checkbox an AI-assisted-porting user is most
likely to gloss over, and reviewers do ask.

**Upstream projects can have their own AI policy.** Some forbid AI-generated code in
contributions outright (e.g. SDL_sound: AI may help find issues, but fixes must be written by a
human and contributed under Zlib). Read an upstream project's contribution rules before offering
a fix you found while porting back to it. Report a suspected upstream bug only after confirming it
is real; maintainers there have seen many hallucinated AI bug reports.

## 1.7 The Launch Script (.sh)

### 1.7.1 Standard boilerplate header (identical in every port)

```bash
#!/bin/bash

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
```

Nothing — no comment, no variable assignment, nothing at all — goes above this block. It's the
one part of every launch script that should look completely identical across every port; a
diff against any recently-merged port's boilerplate should show zero differences here. The
`mod_${CFW_NAME}.txt` line is part of the current standard header (every recent port has it): it
pulls in the CFW's own overrides (TTY handling, library paths, its own `pm_platform_helper`,
e.g. ROCKNIX's sway fullscreen helper). The only thing that may go between `control.txt` and the
`mod_` line is `export PORT_32BIT="Y"` for an armhf-only port.

`source $controlfolder/control.txt` provides `$ESUDO`, `$directory`, controller-config helpers,
and the `$GPTOKEYB`/`$GPTOKEYB2` variables, and it already sources `device_info.txt` and
`funcs.txt` (never source those again yourself). `get_controls` pulls the correct SDL2
GameControllerDB GUID/config for the current device into `$sdl_controllerconfig`. See §2.7 for
the full environment-variable and helper-function contract these scripts rely on.

#### Launch-script conventions (all patterns below)

Reviewers compare a new script against recently merged ports of the same type and ask about
anything non-standard. The script should read like a normal, unremarkable PortMaster script:

- *(project convention)* **Comments: at most one short line per fix, only where the why isn't
  obvious from the code.**
  Never a paragraph, never a "here's what I found" narrative; that belongs in the PR or the
  port's own notes. This has drawn repeated, frustrated review pushback even after a first trim.
- **Define `BINARY=portname.${DEVICE_ARCH}` once** and use `$BINARY` for the gptokeyb2 target,
  `pm_platform_helper` and the launch line. The `.ini` is a plain `portname.ini` (no arch
  suffix — a PortMaster reviewer: "I dont remember anyone ever using $DEVICE_ARCH in the gptk
  name").
- **No CFW-name or device-name branching in a port's fixes.** Detect the capability instead (grep
  a library for a symbol, probe for a file, fall back after a failed GL probe). Hardcoded
  `CFW_NAME`/`DEVICE_NAME` branches were rejected outright in review ("would you stop hardcoding
  cfw device names into code"); CFW-specific behaviour belongs in the CFW's own
  `mod_${CFW_NAME}.txt`. Same for controller GUIDs: don't ship GUID-specific workarounds.
- **One `.sh` per port.** For a choice at startup (language, variant, mod), use gamepad-picker
  (§1.9), not a second launch script.
- **Don't re-implement what PortMaster already does.** Don't re-source `device_info.txt`; trust
  `DISPLAY_WIDTH`/`DISPLAY_HEIGHT` (always set, no `fbset` fallback); don't `mkdir` a
  `libs.aarch64` folder from the script (ship it, with a `.keep` file if it starts empty); don't
  add `tasksetter`/CPU-governor lines; don't kill gptokeyb2 yourself (`pm_finish` does).
- **Don't add a `CONFDIR`/XDG/`HOME` redirect by reflex.** Grep the game for where it actually
  writes (`SpecialFolder`, `XDG_`, `getenv("HOME")`, `user://`) and redirect exactly that path
  with `bind_directories`/`bind_files` (§2.4). **Never `export HOME=...`** as a substitute.
- **Don't invent a `bin/` subfolder** or other layout the build output doesn't have.
- **Don't invent folder nesting.** `$GAMEDIR` already *is* the port's game folder; a
  `cd "$GAMEDIR/portname"` that "works" usually works only because some earlier `mkdir` created a
  phantom directory. Check every path in the script against the real package tree.
- **Prefer a static, shipped config file over generating one with a heredoc at first launch.**
  Use `sed -i` on the shipped file for per-device values (resolution, deadzone). Write
  per-device values (e.g. `DISPLAY_WIDTH`/`DISPLAY_HEIGHT` into the game's ini) on **every**
  launch, not just the first: an SD card moved between devices otherwise keeps the old values.
- **Every player-facing message uses `pm_message`/`pm_show_error`** with portmsg options
  (§1.7.13). Bulk data ships as a `.tar.gz` extracted with the canonical block (§2.4).
- **Never set `SDL_VIDEODRIVER`/`SDL_AUDIODRIVER`** (§2.2; the one scoped exception is the
  SDL3 shim's forwarding pattern, §1.7.12), and **never `export LD_PRELOAD`** (§2.1).
- **Fullscreen is the game's job.** Grep every window/display-creation call and make sure each
  requests fullscreen (§2.2).

### 1.7.2 Pattern A — basic native binary, own SDL2 input, no GL

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname
BINARY=portexecutable.${DEVICE_ARCH}

cd $GAMEDIR

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$GPTOKEYB2 "$BINARY" -c "$GAMEDIR/portname.ini" > /dev/null 2>&1 &

pm_platform_helper "$GAMEDIR/$BINARY"

./$BINARY

pm_finish
```

`$GPTOKEYB2` (like `$GPTOKEYB`) is a multi-word command line, not a bare path (it expands to
`$ESUDO env LD_PRELOAD=$controlfolder/libinterpose.${DEVICE_ARCH}.so $controlfolder/gptokeyb2
$ESUDOKILL2`) — never quote it as `"$GPTOKEYB2"`, that turns the whole string into one
nonexistent literal filename.

**`> /dev/null 2>&1` on the gptokeyb2 line** *(project convention)*: the gptokeyb2 binary PortMaster currently ships
prints a debug line for every button press, emitted key, mouse move and state change, which
floods `log.txt`. There is no quiet flag on that binary (`-v` prints the version and **exits**,
which kills the kill switch too). Upstream made debug output opt-in (`-D`, PR #19, §1.8.2); once
devices run that binary, drop the redirect so gptokeyb2's real errors reach `log.txt`. **Never add
`-D` to a shipped script yet**: older binaries exit on the unknown option, taking every mapping and
the kill switch with them.

**Logging line**: `> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1` is the standard
form. One port (OpenSoldat) captured nothing through the `tee` process substitution and switched
to a plain `exec > "$GAMEDIR/log.txt" 2>&1`; treat that as a port-specific workaround when the log
stays empty, not a new default. Use `${PIPESTATUS[0]}`, not `$?`, when checking a command piped
into `tail`/`tee`.

**gptokeyb2 kill-switch-only form** *(project convention)*: if the game reads the gamepad natively and nothing needs
mapping, drop `-c` and ship **no** `.ini` at all: `$GPTOKEYB2 "$BINARY" > /dev/null 2>&1 &`. An
empty `[controls]`-only `.ini` is dead weight that reviewers flag (§1.8.2).

### 1.7.3 Pattern B — gl4es, standalone (no Westonpack)

Use this only when the engine has no native GLES path at all (see §2.2 for when gl4es is/isn't
the right call). PortMaster centralizes the actual `LIBGL_ES`/`LIBGL_GL`/`LIBGL_FB` tuning via
`libgl_default.txt` (or a per-CFW override) — source it rather than hand-rolling those exports,
since it also contains a DRM-device existence check a hand-rolled script would miss. It must be
sourced *after* `cd`-ing into the game folder, since it resolves the bundled gl4es folder
relative to `$PWD`.

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname
BINARY=portexecutable.${DEVICE_ARCH}

cd $GAMEDIR

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

if [ -f "${controlfolder}/libgl_${CFW_NAME}.txt" ]; then
  source "${controlfolder}/libgl_${CFW_NAME}.txt"
else
  source "${controlfolder}/libgl_default.txt"
fi

$GPTOKEYB2 "$BINARY" -c "$GAMEDIR/portname.ini" > /dev/null 2>&1 &

pm_platform_helper "$GAMEDIR/$BINARY"

./$BINARY

pm_finish
```

`libgl_default.txt`'s real contents (PortMaster-provided, not something a port ships, shown here
so the `gl4es.$DEVICE_ARCH`/`libs.$DEVICE_ARCH` naming requirement is clear — it looks for those
exact folder names via `$PWD`):

```bash
export LIBGL_ES=2
export LIBGL_GL=21
export LIBGL_FB=4

# Fall back off GBM if there's no DRM device.
if [ ! -e "/dev/dri/card0" ]; then
  export LIBGL_FB=2
fi

if [ -d "$PWD/gl4es.$DEVICE_ARCH" ]; then
  export LD_LIBRARY_PATH="$PWD/gl4es.$DEVICE_ARCH:$LD_LIBRARY_PATH"
elif [ -d "$PWD/gl4es" ]; then
  export LD_LIBRARY_PATH="$PWD/gl4es:$LD_LIBRARY_PATH"
fi

if [ -d "$PWD/libs.$DEVICE_ARCH" ]; then
  export LD_LIBRARY_PATH="$PWD/libs.$DEVICE_ARCH:$LD_LIBRARY_PATH"
elif [ -d "$PWD/libs" ]; then
  export LD_LIBRARY_PATH="$PWD/libs:$LD_LIBRARY_PATH"
fi
```

**Always source `libgl_${CFW_NAME}.txt` with the `libgl_default.txt` fallback, never a bare
`source libgl_default.txt`.** Some CFWs ship a real override: `libgl_ROCKNIX.txt` runs
`glxinfo | grep "OpenGL version string"` and skips gl4es entirely when the device has a working
native GL driver (Panfrost/Adreno/freedreno). Sourcing the default directly forces gl4es onto
those devices.

**Don't add an explicit `SDL_VIDEO_GL_DRIVER`/`SDL_VIDEO_EGL_DRIVER` export by default.**
`LD_LIBRARY_PATH` from the sourced file is enough for most engines, and forcing these vars has
actively broken ports: on OpenSoldat (RG351V/AmberELEC) the override broke SDL2's GL loading
outright (no gl4es banner, empty log, instant exit) and removing it fixed the port. Only add it
after a confirmed, isolated symptom, the known case being MonoGame DesktopGL, whose FBO-extension
query failed to resolve through gl4es via `LD_LIBRARY_PATH` alone on RG351V (§1.7.11). When it is
needed, **guard it on gl4es actually having been put on `LD_LIBRARY_PATH` by the sourced file**,
not on the `gl4es.$DEVICE_ARCH` folder existing — a folder check re-forces gl4es on a device where
the CFW's own script just skipped it. Real failure: a blue-screen-only render on Retroid Pocket
5/ROCKNIX (Adreno, native GL present, `tuxaqfh` port) caused by exactly the pair of mistakes
(bare `libgl_default.txt` plus an unconditional driver export):

```bash
if [[ ":$LD_LIBRARY_PATH:" == *":$GAMEDIR/gl4es.${DEVICE_ARCH}:"* ]]; then
  export SDL_VIDEO_GL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libGL.so.1"
  export SDL_VIDEO_EGL_DRIVER="$GAMEDIR/gl4es.${DEVICE_ARCH}/libEGL.so.1"
fi
```

**Check the package really contains `gl4es.$DEVICE_ARCH/`.** A script that sources
`libgl_*.txt` silently does nothing gl4es-related when the folder was never shipped (found on
OpenSoldat: the script looked right, the folder was missing).

Don't hand-edit the gl4es tuning either: the `LIBGL_FB=4`/`LIBGL_ES=2`/`LIBGL_GL=21` values from
`libgl_default.txt` are what works across devices. When running gl4es by hand outside the launch
script (e.g. a debugging session over SSH), set those three yourself, or gl4es hangs on
`eglInitialize: EGL_BAD_DISPLAY`.

### 1.7.4 Pattern C — Westonpack

Westonpack is a runtime providing a full Wayland/X11 environment plus GL compatibility layers, for
apps that need X11/Wayland/OpenGL and can't reach the display through plain SDL2. Controlled via
`westonwrap.sh <backend> <renderer> <shell> <gl_library>`. Known to work for (non-exhaustive):
Godot 4, Java, LibGDX, SFML, SDL2 (X11), SDL3, Allegro.

**Backend**: `drm` renders the desktop on screen via DRM/GBM (through Crusty into an SDL2
context; does NOT work with GL4ES); `headless` runs Weston/Xwayland in the background only (use
with GL4ES's GBM mode to render directly to screen).

**Renderer**: `auto` (usually `gl` for drm, `noop` for headless); `gl` (assembles output using
GLES, doesn't mean the app itself is accelerated); `pixman` (software CPU compositing, currently
not working correctly); `noop` (no output rendering, headless only).

**Shell**: `desktop` (full Wayland desktop, taskbar/resizable windows); `kiosk` (minimal, renders
only the started app, auto-fullscreens if possible).

**GL Library**: `system` (whatever the system provides — without Panfrost likely no GL at all;
GLES 3.2 on native platforms; can also carry the port's own graphics libs via
`LD_LIBRARY_PATH`/`LD_PRELOAD`, e.g. a port's own already-working gl4es build); `llvmpipe` (needs
mesapack — software GL4.5+GLES3.2, works with more apps including GLX-background ones like
firefox/nwjs, very slow); `virgl` (needs mesapack — virtualized GL2.1+GLES2 via LLVMPipe, works
with most GL2.1 apps, more stable than GL4ES but slower); `zink` (needs mesapack — Vulkan-based
GL4.5, falls back to software if no Vulkan, very slow); `crusty_gbm` (implements GBM/DRMKMS via
SDL2, GLES 3.2 and lower, near-native perf, meh compatibility); `crusty_glx_gl4es` (implements
GLX via SDL2 with bundled GL4ES for OpenGL 2.1, decent perf/compat); `crusty_x11egl` (implements
EGL with X11 extensions via SDL2, GLES 3.2 and lower, near-native perf/compat); `gl4es` (**do not
use**, low device support — DRM backend usage may cause empty windows/crashes); `crusty_virgl` (in
development, not yet included).

**Mode-combination table**:

| App does | Mode |
|---|---|
| Uses Xlib, no OpenGL | `drm gl kiosk system` |
| OpenGL 2 + GLX, no Xlib drawing | `headless noop kiosk crusty_glx_gl4es` |
| OpenGL ES + EGL (X11), no Xlib drawing | `headless noop kiosk crusty_x11egl` |
| Made for GBM/DRMKMS directly | `headless noop kiosk crusty_gbm` |
| OpenGL 2 + GLX/EGL, Xlib drawing, low reqs | `drm gl kiosk virgl` |
| OpenGL 3/4 + GLX/EGL, Xlib drawing, very low reqs | `drm gl kiosk llvmpipe` (needs mesapack) |
| Unknown/high compatibility needed, don't care about speed | `drm gl kiosk llvmpipe` (needs mesapack) |

Real merged ports confirm one pairing rule: every port using the `headless` backend pairs it with
`crusty_x11egl` or `crusty_glx_gl4es`; none uses `headless` with `system`. `system` has no
presentation bridge when there's no X11/GLX/EGL traffic for Crusty to intercept, so a genuine
native-Wayland client (e.g. Qt with `QT_QPA_PLATFORM=wayland`) has no way onto the screen under
`headless`.

**Three things every Westonpack script below has, all confirmed on real devices:**
1. **`pm_platform_helper "$GAMEDIR/$game_executable"` right after the gptokeyb2 line**, before
   `westonwrap.sh`. Older examples (including upstream's) left it out; a real merged port
   (`alex3`) has it, and it is also what closes a `pm_message` card (§1.7.13).
2. **`CRUSTY_BLOCK_INPUT=1` on the `$ESUDO env` line** (Westonpack 0.2.7+; the double-input bug
   is device-proven, turning it on in every script is a project convention). It blocks every
   input device from reaching the wrapped app except the virtual devices gptokeyb/gptokeyb2
   create. Without it, a physical controller whose udev tags show both `Keyboard` and `Joystick`
   capability (common on PortMaster handhelds) gets read a second time by Crusty's own
   `CONTROLLER_HOOK` inside Weston's process, and its raw `BTN_SOUTH`/`BTN_TL`/`BTN_TR` codes
   arrive as pointer/keyboard events next to gptokeyb2's translated ones: every press doubles (a
   menu opens and instantly closes). gptokeyb2's own `exclusive = true` can't stop this, it only
   grabs the device from gptokeyb2's own fd. It also blocks external USB keyboards, which is
   intended. It goes on the `env` line so it reaches Weston's process, not on the game's own
   command line.
3. **For every `drm`-backend port: the `weston_prefix` block, passed as `strace="$weston_prefix"`.**
   Without it, Weston crashes on RK3566 dArkOS from the 08/27/2026 update on (`fatal: failed to
   create compositor`, then a SIGSEGV in `weston_compositor_destroy(compositor=0x0)`). Root
   cause: that update's libmali `g29p1` exports ~46 `wl_*` libwayland symbols from
   `libGLESv2.so`, so in Weston's process `wl_global_create` binds into the GPU driver instead of
   libwayland-server. It is device-wide (an unmodified merged port, `alex1`, crashes the same way)
   and renderer-independent (`gl` and `pixman` both crash). The fix preloads Westonpack's own
   Wayland libraries ahead of Crusty, **client first, then server, then Crusty**: preloading only
   the server library fixes Weston, but Xwayland inherits the preload and segfaults in
   `libwayland-client`'s dispatch (`ffi_prep_cif_machdep`). The check greps the driver for the
   string (`nm` isn't on every CFW) and is a no-op on unaffected devices (`strace=""` expands to
   nothing). It relies on westonwrap's `$strace` debug hook, the only way into Weston's
   `LD_PRELOAD`. The released Westonpack (0.2.7.1) does not do this itself, so keep the block
   until a released Westonpack does, and check the *released* runtime's `westonwrap.sh` before
   removing any workaround (a test device can be running an unreleased build). Confirmed on
   `divercity` and `alex4` (RGB30/dArkOS). Swapping an older libmali (`g13p0`) over the system's
   also works but replaces a system-wide GPU driver, so it is a diagnostic, never something a port
   does.

If the port bundles libraries **Weston itself** needs, pass them as `LD_LIBRARY_PATH` on the same
`$ESUDO env` line; `WRAPPED_LIBRARY_PATH` only reaches the game.

#### Variant 1: Xlib-only, no OpenGL (`drm gl kiosk system`)

Prerequisites: game must not use OpenGL or OpenGL ES. Required runtime: Westonpack 0.2.1+
(`weston_pkg_0.2.squashfs`; `port.json` `"runtime": ["weston_pkg_0.2"]`, `"arch": []`).

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname
game_executable="portexecutable.${DEVICE_ARCH}"
ini_filename="portname.ini"
game_libs=$GAMEDIR/libs.${DEVICE_ARCH}/:$LD_LIBRARY_PATH

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

CONFDIR="$GAMEDIR/conf/"
$ESUDO mkdir -p "${CONFDIR}"

weston_dir=/tmp/weston
$ESUDO mkdir -p "${weston_dir}"
weston_runtime="weston_pkg_0.2"
if [ ! -f "$controlfolder/libs/${weston_runtime}.squashfs" ]; then
  if [ ! -f "$controlfolder/harbourmaster" ]; then
    pm_show_error "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info." --title "PortMaster update needed"
    exit 1
  fi
  pm_message "Downloading the Westonpack runtime, this can take a few minutes..." --title "Please wait"
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${weston_runtime}.squashfs"
fi
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
    $ESUDO umount "${weston_dir}"
fi
$ESUDO mount "$controlfolder/libs/${weston_runtime}.squashfs" "${weston_dir}"

# Mali drivers exporting their own wl_* symbols break Weston unless Wayland is preloaded first
weston_prefix=""
gles_lib=$($weston_dir/tools/findlib libGLESv2.so.2)
if [ -n "$gles_lib" ] && grep -q wl_global_create "$gles_lib"; then
  weston_prefix="env LD_PRELOAD=$weston_dir/lib_aarch64/libwayland-client.so.0:$weston_dir/lib_aarch64/libwayland-server.so.0:$weston_dir/lib_aarch64/graphics/crusty_gbm/libcrusty.so"
fi

cd $GAMEDIR
$GPTOKEYB2 "$game_executable" -c "$GAMEDIR/$ini_filename" > /dev/null 2>&1 &
pm_platform_helper "$GAMEDIR/$game_executable"

$ESUDO env strace="$weston_prefix" CRUSTY_BLOCK_INPUT=1 WRAPPED_LIBRARY_PATH=$game_libs \
$weston_dir/westonwrap.sh drm gl kiosk system \
XDG_DATA_HOME=$CONFDIR $GAMEDIR/$game_executable

$ESUDO $weston_dir/westonwrap.sh cleanup
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
    $ESUDO umount "${weston_dir}"
fi
pm_finish
```

The `pm_message` before `runtime_check` matters: without it a first launch sits on a black screen
for minutes while the runtime downloads, which testers report as a hang. Do the same for every
runtime download in any pattern.

Passing extra env vars (`XDG_RUNTIME_DIR`, `ULTRADIR`, `JAVA_HOME`, etc.) to the wrapped game
process, not to Weston itself, has to be done as **positional `VAR=value` arguments right before
the binary path** in the `westonwrap.sh` invocation, exactly like `XDG_DATA_HOME` above — an
`export` earlier in the script gets silently overridden, since `control.txt` is sourced a second
time inside `westonwrap.sh` itself (which also resets `LD_LIBRARY_PATH`, e.g. to
`/usr/lib/compat/`).

**westonwrap changes the working directory to `/tmp/weston`** before starting the game, so any
cwd-relative file access in the game (`new File("data/x")`, `fopen("data/x")`) breaks. Load
from absolute paths, the classpath, or an in-binary `chdir` (§2.4).

#### Variant 2: OpenGL 2 (GLX), GL4ES (`headless noop kiosk crusty_glx_gl4es`)

Prerequisites: game uses OpenGL 2.1 or lower. Required runtime: Westonpack 0.2.5+. Same boilerplate
and mount/cleanup as Variant 1, but **no `weston_prefix` block** (the `headless` backend never
preloads Crusty into Weston's own process, so the dArkOS symbol collision can't happen). Only the
launch line differs:

```bash
$GPTOKEYB2 "$game_executable" -c "$GAMEDIR/$ini_filename" > /dev/null 2>&1 &
pm_platform_helper "$GAMEDIR/$game_executable"

$ESUDO env CRUSTY_BLOCK_INPUT=1 WRAPPED_LIBRARY_PATH=$game_libs \
$weston_dir/westonwrap.sh headless noop kiosk crusty_glx_gl4es \
XDG_DATA_HOME=$CONFDIR $GAMEDIR/$game_executable
```

#### Variant 3: OpenGL 2 (GLX), VirGL (`drm gl kiosk virgl`)

Prerequisites: game uses OpenGL 2.1 or lower. Required runtimes: Westonpack 0.2.5+ **and**
Mesapack 0.1.1+ (`mesa_pkg_0.1.squashfs`) — this variant needs a **second, simultaneous** squashfs
mount alongside `weston_pkg_0.2` (both keys go in `port.json`'s `runtime` list). It's a `drm`
backend, so it needs the `weston_prefix` block too:

```bash
# ... boilerplate and weston_pkg_0.2 mount block exactly as Variant 1, including weston_prefix ...

mesa_dir=/tmp/mesa
mesa_runtime="mesa_pkg_0.1"
if [ ! -f "$controlfolder/libs/${mesa_runtime}.squashfs" ]; then
    if [ ! -f "$controlfolder/harbourmaster" ]; then
        pm_show_error "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info." --title "PortMaster update needed"
        exit 1
    fi
    $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${mesa_runtime}.squashfs"
fi
$ESUDO mkdir -p "${mesa_dir}"
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
    $ESUDO umount "${mesa_dir}"
fi
$ESUDO mount "$controlfolder/libs/${mesa_runtime}.squashfs" "${mesa_dir}"

cd $GAMEDIR
$GPTOKEYB2 "$game_executable" -c "$GAMEDIR/$ini_filename" > /dev/null 2>&1 &
pm_platform_helper "$GAMEDIR/$game_executable"

$ESUDO env strace="$weston_prefix" CRUSTY_BLOCK_INPUT=1 WRAPPED_LIBRARY_PATH=$game_libs \
$weston_dir/westonwrap.sh drm gl kiosk virgl \
XDG_DATA_HOME=$CONFDIR $GAMEDIR/$game_executable

$ESUDO $weston_dir/westonwrap.sh cleanup
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
    $ESUDO umount "${weston_dir}"
    $ESUDO umount "${mesa_dir}"
fi
pm_finish
```

#### Variant 4: OpenGL ES (EGL/X11) (`headless noop kiosk crusty_x11egl`)

Prerequisites: game uses OpenGL ES 3.2 or lower. Required runtime: Westonpack 0.2.5+. Same shape
as Variant 2 (headless, no `weston_prefix`); the mode becomes `headless noop kiosk crusty_x11egl`:

```bash
$ESUDO env CRUSTY_BLOCK_INPUT=1 WRAPPED_LIBRARY_PATH=$game_libs \
$weston_dir/westonwrap.sh headless noop kiosk crusty_x11egl \
XDG_DATA_HOME=$CONFDIR $GAMEDIR/$game_executable
```

#### Variant 5: SDL2-over-X11 (GL2 / GLES)

Overlays an X11-built SDL2 on top of the system SDL2, via Crusty loading the system SDL2 in a
separate namespace hidden from the game — Crusty then treats the game + bundled X11 SDL2 as a
normal X11 app with a GLX or EGL(X11) dependency. Near-native performance; also works with games
run under Box64 (no x64 SDL2 build needed). Prerequisites: a build of SDL2 that supports X11; game
must support OpenGL 2 or OpenGL ES 3.2. Required runtime: Westonpack 0.2.5+. Setup: create a
folder called `x11sdllib/` in the port directory and place the X11 SDL2 library there. (This is
the one sanctioned case of shipping an SDL2 build: it is only ever loaded inside Westonpack's
wrapped namespace, never on `LD_LIBRARY_PATH`.)

```bash
GAMEDIR=/$directory/ports/portname
game_executable="portexecutable.${DEVICE_ARCH}"
ini_filename="portname.ini"
game_libs=$GAMEDIR/libs.${DEVICE_ARCH}/:$LD_LIBRARY_PATH
x11sdl_path="$GAMEDIR/x11sdllib/"

# ... mkdir/log/mount block as Variant 1 (no weston_prefix: both variants are headless) ...

cd $GAMEDIR
$GPTOKEYB2 "$game_executable" -c "$GAMEDIR/$ini_filename" > /dev/null 2>&1 &
pm_platform_helper "$GAMEDIR/$game_executable"

# OpenGL 2 variant:
$ESUDO env WRAPPED_LIBRARY_PATH_MALI="$x11sdl_path" WRAPPED_PRELOAD_MALI="$x11sdl_path/libSDL2-2.0.so.0" \
CRUSTY_BLOCK_INPUT=1 WRAPPED_LIBRARY_PATH=$game_libs \
$weston_dir/westonwrap.sh headless noop kiosk crusty_glx_gl4es \
WAYLAND_DISPLAY= XDG_DATA_HOME=$CONFDIR $GAMEDIR/$game_executable

# OpenGL ES variant instead adds SDL_VIDEO_X11_FORCE_EGL=1 and targets crusty_x11egl:
$ESUDO env WRAPPED_LIBRARY_PATH_MALI="$x11sdl_path" WRAPPED_PRELOAD_MALI="$x11sdl_path/libSDL2-2.0.so.0" \
SDL_VIDEO_X11_FORCE_EGL=1 CRUSTY_BLOCK_INPUT=1 WRAPPED_LIBRARY_PATH=$game_libs \
$weston_dir/westonwrap.sh headless noop kiosk crusty_x11egl \
WAYLAND_DISPLAY= XDG_DATA_HOME=$CONFDIR $GAMEDIR/$game_executable
```

`WRAPPED_LIBRARY_PATH_MALI`/`WRAPPED_PRELOAD_MALI` scope the X11 SDL2 override to Mali devices
specifically (a `_PANFROST` variant also exists, useful to exclude X11-related libs on Panfrost);
`WAYLAND_DISPLAY=` is explicitly unset for the wrapped process.

### 1.7.5 Westonpack: env vars, terminology, platform behaviour, and debugging

**Useful env vars**: `CRUSTY_RESOLUTION=320x240` (virtual screen resolution given to crusty/
weston; it does **not** apply to `system` GL mode, and can't make Weston's output larger than the
real display); `CRUSTY_SHOW_CURSOR=1` (software mouse cursor, useful headless); `CRUSTY_FPS=1`
(prints FPS every second); `CRUSTY_GLES=32` (GLES version for Crusty: 1,10,11,2,20,21,3,30,31,32,
default 32; 11 for SFML apps, 31 for Panfrost); `CRUSTY_BLOCK_INPUT=1` (see above);
`WESTON_HEADLESS_WIDTH`/`WESTON_HEADLESS_HEIGHT` (virtual desktop resolution for weston headless
mode); `WESTON_NO_HEADLESS_INPUT=1` (disables input capture in headless mode, fixes some SDL2
double-input issues); `WESTON_KIOSK_NO_RESIZE=1` (disables auto-resize in kiosk mode, fixes some
SDL2 startup segfaults); `WRAPPED_LIBRARY_PATH`/`WRAPPED_PRELOAD` (like `LD_LIBRARY_PATH`/
`LD_PRELOAD` but scoped to the wrapped app only, not Weston/supporting programs;
**`WRAPPED_PRELOAD` takes a colon-separated list** — a space-separated value corrupts the
shell-wide `LD_PRELOAD` it is merged into); `WRAPPED_LIBRARY_PATH_MALI`/`_PANFROST`
(device-specific variants); `XCURSOR_SIZE=24` (cursor size); `crustydebug=_debug` (enables a
debug crusty build with tracelog); `strace=<prefix>` (westonwrap's debug hook: whatever it holds
is put in front of `./wp_weston` and an initial `printenv`).

**Useful files inside the mounted runtime**: `$weston_dir/lib_aarch64/` (aarch64/armhf X11 and
Wayland libraries); `$weston_dir/lib_aarch64/graphics/` (the different crusty and gl4es builds);
`$weston_dir/tools/drmd` (simulates a DRM device being present); `$weston_dir/tools/xtrace`
(traces X11 traffic); `$weston_dir/tools/findlib <soname>` (prints where the device's own copy of
a library lives); `$weston_dir/libexec/` (terminal and virtual keyboard programs for Weston);
`$mesa_dir/lib/aarch64-linux-gnu/` (Mesa libraries); `$mesa_dir/virgl/` (`virgl_test_server`,
needed for VirGL).

**Terminology**: X11 (classic Linux GUI display system); Wayland (newer display system, different
protocol — SDL2/GTK3/QT5 apps use it); GLX (X11 extension for GL(ES) in an X11 window, driver
support usually absent on these devices); EGL (graphics driver API for GL(ES) across FBO/GBM/
Wayland/X11 contexts, each needing separate driver extension support); SDL (every PortMaster
device ships a native SDL2 build); GBM (API for GL(ES) with no display system, via the EGL GBM
extension); fbdev (API for GL(ES) with no display system, via the "fbdev" EGL_PLATFORM); Weston
(flexible Wayland display server, supports Xwayland); Xwayland (compatibility layer for X11 apps
on Wayland); seatd (manages display/input resources for Weston); GL4ES (ptitSeb's library letting
GL1/GL2 apps run on GLES-only hardware, includes a GLX wrapper); Mesa (general-purpose Linux
GL(ES) library, software or virtualized); Gallium (a graphics driver within Mesa — Panfrost,
LLVMPipe, VirGL, Zink, v3d); VirGL (Mesa gallium driver virtualizing OpenGL, normally for VMs —
this setup's virpipe/vtest variant passes GL commands through a socket to a render server, final
compositing on CPU); LLVMPipe/Lavapipe (Mesa gallium software renderers, for OpenGL/Vulkan
respectively); Zink (Mesa gallium driver providing OpenGL on Vulkan-capable hardware); Crusty
(custom wrapper bringing GLX/Wayland EGL/GBM-DRMKMS support to devices lacking it, highly
experimental); Mali/Panfrost (graphics drivers for Rockchip handhelds — Panfrost mostly supports
EGL Wayland extensions, Mali mostly does not).

**Platform behaviour worth knowing before testing:**
- **ROCKNIX on Panfrost bypasses Weston entirely** (`Rocknix (Panfrost/SD) detected, bypassing
  weston setup entirely!`): the app runs directly under ROCKNIX's own sway compositor with Mesa
  GL, Xwayland started on demand. `CRUSTY_*`, `strace=`, and the kiosk shell then do nothing, and
  sway doesn't put X11 windows inside frame windows (breaks Java AWT without
  `_JAVA_AWT_WM_NONREPARENTING=1`, §1.7.15). westonwrap already handles this; don't add a
  `CFW_NAME == ROCKNIX` path of your own.
- **ROCKNIX on Mali: `westonwrap.sh` silently rewrites `drm` to `wayland` and `gl` to
  `pixman`.** Weston's `wayland-backend.so` then needs `wl_egl_window_destroy`, which the Mali
  blob doesn't export (`Failed to load module: .../wayland-backend.so: undefined symbol:
  wl_egl_window_destroy` / `fatal: failed to create compositor backend`): a black screen. No
  retro-handheld Mali blob has `wl_egl_window_*` (checked on X55/RK3566 and RG351V/RK3326).
  Westonpack ships a vendor-agnostic implementation in `lib_aarch64/extra_wayland/`, but
  westonwrap only adds it outside this ROCKNIX branch. Fix (confirmed playable on a Powkiddy X55,
  ROCKNIX Mali): inject westonwrap's own `weston_backendlib`/`weston_preload` variables through
  `env` — they are the only two that survive the second `control.txt` sourcing inside westonwrap
  (which resets `LD_LIBRARY_PATH` to `/usr/lib/compat/`), and it must be a preload, since
  `wayland-backend.so` never names `libwayland-egl.so.1` in its `NEEDED` list:
  ```bash
  $ESUDO env WRAPPED_LIBRARY_PATH=$game_libs \
  weston_backendlib="$weston_dir/lib_aarch64/extra_wayland" \
  weston_preload="$weston_dir/lib_aarch64/extra_wayland/libwayland-egl.so.1" \
  $weston_dir/westonwrap.sh drm gl kiosk system \
  XDG_DATA_HOME=$CONFDIR $GAMEDIR/$BINARY
  ```
  The same forced path composites in software (pixman) at `DISPLAY_WIDTH`x`DISPLAY_HEIGHT`;
  overriding both down to the game's native size on that `env` line took a small-resolution game
  from single-digit FPS to smooth. (`nm -D` misparsed the Mali blob on one device;
  `readelf --dyn-syms` read it correctly. On a device with neither, `strings` still works.)
- **Kiosk shows no modal dialogs.** An app that pops an error/message dialog under Westonpack
  kiosk looks hung: the dialog is never shown. Read the log, or patch the dialog to a log line.
- **An app-managed "fullscreen" X window isn't managed by Weston and never gets keyboard focus
  under Xwayland** (old Irrlicht 1.x). Run the app windowed; kiosk fills the screen anyway.
- **Unbind the texture before the buffer swap with gl4es under Westonpack.** gl4es held back the
  last draw batch until after the swap, so the last-drawn element of every frame (the HUD) was
  missing. `glBindTexture(GL_TEXTURE_2D, 0)` before swapping fixed it; `glFlush()` also works but
  cost about 60% FPS.
- **`westonwrap.sh cleanup` doesn't find a game run under Box64** (Box64 renames the process,
  §1.7.14), and `pkill` warns on names over 15 characters. Kill the game by PID or process group
  if the script does its own cleanup.
- **The GLFW/X11 wall (Ebitengine and other GLFW-on-X11-only engines).** Under Xwayland on Mali,
  glamor fails (`glamor: 'wl_drm' not supported`) and every EGLConfig offered has only
  `EGL_PIXMAP_BIT`, so GLFW stops with `glfw: EGL: Failed to find a suitable EGLConfig`. No
  Westonpack mode gets past this; it's a structural limit, not a configuration mistake. Pick a
  different build target for such an engine (an SDL2 backend) or a different game.
- **SFML 1.x under Crusty**: a global constructor in SFML 1.x raced Crusty's own constructor
  (fixed upstream in Crusty). If an SFML game crashes before `main`, suspect constructor order.
  SFML joystick retries against Crusty's input block stall the game (`synchronize_rcu`); mark the
  joystick as unplugged after the first failed open. Released Crusty (0.4) reports no
  double-buffered GLX visual, and SFML then passes a NULL visual (`BadMatch X_CreateColormap`);
  fall back to the default visual.

**Debugging under Westonpack:**
- Unknown dependencies → try `drm gl kiosk llvmpipe` (with mesapack) first, slow but very high
  compatibility; `headless noop kiosk crusty_glx_gl4es` has decent compat/perf for GL2/GLES2
  games; `strace -f -e file` for library-loading issues, `crustydebug=_debug` for GL context
  issues, `gdb --args` for segfaults (see §2.5 for the full GDB workflow).
- **When Weston or Xwayland fails to start, the port hangs on a black screen that Start+Select
  can't exit.** westonwrap waits for gptokeyb to exit ("using it as a kill signal"), and the
  kill targets a game process that never started. Recover over SSH by killing the leftover
  `gptokeyb2`, `westonwrap.sh` and `seatd` processes; the script then runs its own cleanup and
  unmounts. The same hang happens if a runtime mount failed and the game never launched.
- **See which library every call binds to**: `$ESUDO env strace="env LD_DEBUG=bindings
  LD_DEBUG_OUTPUT=/tmp/wpbind" ...` writes one `/tmp/wpbind.<pid>` per process (Weston, and
  Xwayland since it inherits the environment). Match the PID against the segfault line in the
  log. This is how the dArkOS `wl_global_create` collision was confirmed.
- **gdb inside Weston**: `strace="gdb -batch -x /path/to/script.gdb --args"`. Expect (and ignore)
  a first, irrelevant gdb session for westonwrap's own `printenv`. Breaking inside a library that
  isn't loaded yet needs `set breakpoint pending on` first and the exact source path from a real
  backtrace (`../libweston/compositor.c:9749`, not a bare `compositor.c`).
- **gdb on the wrapped game**: the `$strace` hook only wraps Weston, so make the wrapped command a
  two-line wrapper script that runs `gdb -batch -x cmds --args ./real_binary`. Remove it
  afterwards: the window then belongs to a gdb child, which breaks focus.
- Unsetting `LD_PRELOAD=` inside the westonwrap env can help in rare cases where the app loads
  libEGL/libGLX at runtime (some OSes fail if crusty is in `LD_PRELOAD`).
- Force an app to link against Crusty instead of system libs by patching `libEGL.so`/`libGLX.so`
  references to `libCRU.so` in the binary (useful for GLAD EGL/GLX loaders that hardcode those
  names):
```python
python3 -c "f=open('game_executable','r+b'); d=f.read().replace(b'libEGL.so', b'libCRU.so').replace(b'libGLX.so', b'libCRU.so'); f.seek(0); f.write(d); f.close()"
```
- **Screenshots on device**: ROCKNIX `XDG_RUNTIME_DIR=/run/0-runtime-dir WAYLAND_DISPLAY=wayland-1
  grim out.png`; AmberELEC `fbgrab`; dArkOS has neither.

### 1.7.6 Pattern D — Godot 2/3 (FRT runtime)

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname
cd $GAMEDIR

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

runtime="frt_3.2.3"
if [ ! -f "$controlfolder/libs/${runtime}.squashfs" ]; then
  if [ ! -f "$controlfolder/harbourmaster" ]; then
    pm_show_error "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info." --title "PortMaster update needed"
    exit 1
  fi
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${runtime}.squashfs"
fi
$ESUDO mkdir -p /tmp/${runtime}
$ESUDO mount "$controlfolder/libs/${runtime}.squashfs" /tmp/${runtime}

$GPTOKEYB2 "${runtime}" -c "$GAMEDIR/portname.ini" > /dev/null 2>&1 &

pm_platform_helper "/tmp/${runtime}/${runtime}"

"/tmp/${runtime}/${runtime}" --main-pack "$GAMEDIR/portname.pck"

$ESUDO umount /tmp/${runtime}
pm_finish
```

`port.json`: `"runtime": ["frt_3.2.3"]`, `"arch": []`. Real merged FRT ports mount the runtime at
`$HOME/godot` instead (`$ESUDO umount "$godot_file" || true` before mounting, `PATH` prepended);
either works, as long as the gptokeyb2 kill target is the runtime binary's name (`frt_3.2.3`)
and `pm_platform_helper` gets its full path.

Verify the exact FRT binary/runtime filename against PortMaster's current runtime catalog before
shipping — version numbers in squashfs names do change. All control must go through gptokeyb2:
**every FRT build has joysticks disabled** (`sdl2_adapter.h`'s `dispatch_events()` has
`js_event(ev)` commented out, "Disabled all Joysticks to allow GPTOKEYB remapping for broken SDL
Mappings on RK3326 devices"), so Godot never sees gamepad input. Don't blame native joypad input
for a control bug in an FRT port. FRT dynamically links the system SDL2.

#### Godot 2 (FRT 2.1.6) specifics

Verified from the Godot 2.1.6-stable source, the real `frt_2.1.6` squashfs, and a real device
(TowerJumper port, RG351V/AmberELEC). Existing reference scripts for Godot 2 ports are misleading
on several of these:
- **The runtime squashfs holds one binary, `frt_2.1.6`** (`port.json` `"runtime": ["frt_2.1.6"]`).
- **The pack flag is `-main_pack`** (underscore). The `-path data.pck` some merged ports use only
  works by accident, through the cwd `data.pck` fallback in `Globals::setup`.
- **Don't export `SDL_GAMECONTROLLERCONFIG` for an FRT 2 port**: it made `frt_2.1.6` segfault at
  startup on RG351V/AmberELEC (bisected over SSH; root cause unknown). gptokeyb2 still reads the
  controller through its own SDL2, so set the variable only on the gptokeyb2 command line if a
  mapping needs it, never exported for the game.
- **Exit-shortcut env var is `FRT_EXIT_SHORTCUT`** (`none|shift-enter|win-q|esc`; unset means
  none). The `FRT_NO_EXIT_SHORTCUTS` that existing ports export doesn't exist in the source.
- **`user://` is `$HOME/.godot/app_userdata/<name>`** (`use_shared_user_dir` defaults to true)
  and ignores XDG vars, so redirect it with `bind_directories` (§2.4), not `XDG_DATA_HOME`.
- A template (non-editor) build loads raw `.png`/`.ogg`/text `.tscn` directly, so no editor
  export is needed. PCK v0 layout, for building or inspecting a pack by hand: magic `GDPC`,
  version 0, then major/minor/rev, 16 reserved `u32`, file count; each entry is `u32` length +
  `"res://path"` + `u64` offset + `u64` size + 16-byte MD5.
- Stick-to-key bindings need a real deadzone (§1.8.1): with gptokeyb2's default 1000 the tower
  in TowerJumper spun non-stop; `deadzone = 8000` fixed it.

### 1.7.7 Pattern E — Love2D

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname

mkdir -p "$GAMEDIR/conf/.identity"
cd $GAMEDIR

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

bind_directories "$XDG_DATA_HOME/love/identity" "$GAMEDIR/conf/.identity"

source "$controlfolder/runtimes/love_11.5/love.txt"   # provides $LOVE_BINARY / $LOVE_RUN / $LOVE_GPTK

$LOVE_RUN "$GAMEDIR/portname.love"

pm_finish
```

`love.txt` starts gptokeyb2 itself with `$LOVE_GPTK`; the script above never calls
`pm_platform_helper`, so if it shows a `pm_message` card (e.g. during an extraction) the card stays
up until the script ends. Call `pm_platform_helper "$LOVE_BINARY"` before `$LOVE_RUN` in that case.

Verify the exact `love_<version>` runtime folder name against what's actually installed/available
— match it to whichever Love2D API version the game was actually built against
(11.4/0.10.2/0.9.2/0.8/0.7.2 all exist as separate runtimes with real API differences). If the
game manages its own mouse cursor under KMS/DRM/FBDEV (no cursor by default there), implement a
software cursor: load a cursor image in `love.load()`, `love.mouse.setVisible(false)`, draw the
cursor at the mouse position at the end of `love.draw()`, and scale mouse coordinates against the
render scale in `love.update()`.

**Always redirect saves/config into the port's own folder with `bind_directories`, for every
Love2D port, not just when a game happens to need it.** A Love2D game's save/settings location is
whatever `conf.lua`'s `t.identity` sets (e.g. `t.identity = "bab"`), which LÖVE resolves to
`$XDG_DATA_HOME/love/<identity>` (normally `~/.local/share/love/<identity>`) — check the actual
port's `conf.lua` for its real identity string rather than assuming. Per the standing
`bind_directories` gotcha elsewhere in this doc, the port's own side (`$GAMEDIR/conf/.<identity>`)
must be `mkdir -p`'d with its *exact* full path before the call, or the bind mount silently
no-ops; the target (`$XDG_DATA_HOME/love/<identity>`) gets created by `bind_directories` itself.
Confirmed real-device (RG351V/AmberELEC): `bind_directories "$XDG_DATA_HOME/love/bab"
"$GAMEDIR/conf/.bab"` logs `successful bind mount from .../conf/.bab to
/storage/.local/share/love/bab` on first launch (the preceding `umount: can't unmount ...:
Invalid argument` line is just the function's own harmless pre-unmount-before-mount step, not an
error to chase). Without this, saves/settings live in the generic, port-independent LÖVE identity
folder and don't travel with the port (reinstall, backup, multiple LÖVE ports sharing an identity
collision, etc.).

### 1.7.8 Pattern F — GameMaker (gmloader-next)

GameMaker Studio (GMS) exports share the same bytecode/asset format across platforms
(`data.win` on desktop, `game.droid` on Android, `game.unx` on Linux) interpreted by a
per-platform native runner. gmloader-next doesn't reimplement that runner — it takes the real
**Android** runner binary (`libyoyo.so`) unmodified and runs it under glibc via a custom ELF
loader (`loader/`, `so_util`), an incomplete-but-functional fake-JNI shim (`jni/`), and
GameMaker-specific glue (`gmloader/libyoyo.cpp`, resolving `CreateDsMap`, `YYGetInt32`,
`Graphics_DisplayWidth`, audio/gamepad/mouse/texture hooks). **`gmloader-next` (not the old
`droidports`/`gmloader`) is the correct choice for aarch64**: the old loader's CMake hardcodes
`-mthumb -mcpu=cortex-a9 -mfpu=vfpv3-d16` (ARMv7, GMS ≤ 2022.x); gmloader-next supports armhf (all
GMS versions) and aarch64 (GMS ≥ 2.2.1).

**Status: confirmed on real hardware.** The first device-tested port (Dijeweled Remastered, a GMS
2024.13 project, RG351V/AmberELEC) boots and plays with native controller input, both
audiogroups and saves. Normal device testing by the porter is the default. Don't claim more than
was actually tried: in that port, four "it works" reports were wrong, each time because a crash sat
in a mode nobody had opened yet. That repeated failure is what justified the automated suite below.

#### Step zero: VM or YYC?

A YYC (YoYo Compiler) build compiles the GML into native code inside the runner (the `.exe`, or
the Android build's own `libyoyo.so`), so its data file carries **no code at all** and cannot run
on any other runner. List the `FORM` chunks first:

```bash
python3 -I - data.win <<'EOF'
import struct, sys
f = open(sys.argv[1], 'rb').read()
p, out = 8, []
while p < len(f):
    n, s = f[p:p+4].decode('latin1'), struct.unpack('<I', f[p+4:p+8])[0]
    out.append((n, s)); p += 8 + s
print(out); print('bytecode ver', f[17])
EOF
```

A VM build has `CODE`, `VARI` and `FUNC` chunks; a YYC build doesn't. This chunk check is the
reliable test. Don't judge by the `.exe` size: it depends on the GameMaker version, and recent VM
runners are already over 12MB, about the size of a YYC build (one YYC game was ~15-16MB).
UndertaleModTool also warns when it opens YYC data. Device symptom if missed (2024.13 runner): the runner parses the data, then segfaults in
`Code_Variable_FindAlloc_Slot_From_Name` via `LoadGameData` → `Create_StandardBuiltInObjectPrototype`
(no `VARI` chunk, so `g_instanceVarLookup` stays NULL). What other platforms do with YYC:
an Android APK of the game runs as-is (its own `libyoyo.so` contains the game; PS Vita's
yoyoloader, which gmloader descends from, works this way); a PC VM build can be "asset-swapped"
into a blank Android export of a similar GMS version; PC YYC builds aren't supported anywhere;
GML can't be recovered from YYC (UndertaleModTool/Underanalyzer only compile into VM data);
Butterscotch/Cinnamon reimplement the runner but only for bytecode, GMS 1.4-era. PortMaster
porters' usual answer is asking the developer for a VM re-export. **For an open-source game,
rebuild it from source as VM** (below).

#### Building gmloader-next

```bash
git clone --recursive https://github.com/JohnnyonFlame/gmloader-next.git
```
`--recursive` matters (submodules: `3rdparty/json`, `libzip`, `libbsd`/`libmd`,
`SDL_kitchensink` for optional video, `FMOD_SDL` for optional FMOD). The build needs a real
**LLVM/Clang library** plus Python `clang` bindings, not just GCC: `scripts/generate_libc.py`
parses `thunks/libc/common.hpp` and `c_prototypes.h` with libclang to generate the softfp/hardfp
thunk tables.

**Build it in an older-glibc root, not a current distro.** The thunk tables bind every libc symbol
at the build host's version, so a binary built on Ubuntu 22.04 needs `GLIBC_2.34`, above what
PortMaster targets (≤ 2.29, §3.2). Build it the way upstream CI does, in a Debian bullseye root
(`debootstrap --variant=minbase bullseye`, then `python3 python3-clang build-essential pkg-config
libsdl2-dev libzip-dev zlib1g-dev`), which gives `GLIBC_2.27`/`GLIBCXX_3.4.26` max:
```bash
make -f Makefile.gmloader ARCH=aarch64-linux-gnu \
  LLVM_FILE=/usr/lib/llvm-11/lib/libclang-11.so \
  LLVM_INC=/usr/include/aarch64-linux-gnu/c++/10 \
  -j$(nproc)
```
(It also builds on Ubuntu 22.04 with `python3-clang-14`, `LLVM_FILE=/usr/lib/llvm-14/lib/libclang-14.so.1`
and `LLVM_INC=/usr/include/aarch64-linux-gnu/c++/12` — the GCC 12 dir, or it fails on
`_GLIBCXX23_CONSTEXPR` — but don't ship that binary.) Output:
`build/${ARCH}/gmloader/gmloadernext.${DEVICE_ARCH}`; `NEEDED` is base system libs only
(`libSDL2-2.0.so.0`, `libz`, `libstdc++`, libc family), so no `libs.aarch64/`. Upstream has no
GitHub releases. Optional flags, only when a game needs them: `USE_FMOD=1` (needs `3rdparty/fmod`
populated by hand from `fmodstudioapi.tar.gz`), `USE_LUA=1`, `VIDEO_SUPPORT=1` (ffmpeg libs at
link time), `STATIC_LIBSTDCXX=1`. `armeabi-v7a-r19` runner note: GMS runner builds r21+ ship
AArch32 code that SIGILLs on VFPv3-only cores (Cortex-A7); irrelevant on aarch64 devices.

#### Building an open-source GameMaker project headless with gm-cli

`YoYoGames/gm-cli` (npm `@gamemaker/gm-cli`, Apache-2.0, needs Node.js 24) is YoYo Games' own
CLI, and the whole toolchain runs natively on aarch64 (worked first time under a QEMU aarch64
chroot):
- **It fetches a guest licence itself** (built-in guest key, cached, renewed within 7 days of
  expiry): no account, no sign-in. Enough for `linux` VM builds, **not** for Android packaging
  (`Permission Error : Unable to obtain permission to execute`).
- **It downloads Igor per host, including `igor_linux-arm64.zip`**, plus the runtime from YoYo's
  feeds (`Zeus-Runtime-LTS2026.rss` default, `Zeus-Runtime.rss` monthly back to 2.1.4,
  `Zeus-Runtime-NuBeta.rss`). List a version's modules:
  `curl -s https://gms.yoyogames.com/Zeus-Runtime.rss | awk '/Version 2024.13.1.242/,/<\/item>/' | grep -o 'module name="[^"]*"'`
  (you need `base-module-linux-arm64`, `linux` and `android`).
- **Pin the runtime to the project's IDE version** (`.yyp` `"IDEVersion":"2024.13.1.193"` →
  runtime `2024.13.1.242`).

```bash
npm install -g @gamemaker/gm-cli@latest
cd <copy of the project>
gm-cli compile --target=linux --runtime=vm --toolchain=GMS2@2024.13.1.242 --verbose --cache-dir <build>/gmcache project.yyp
```
Output `gmcache/build-gms2-linux-VM/output/<project>.zip`: `assets/game.unx` (VM data, same
format as `game.droid`), `assets/audiogroupN.dat` (numbered, not named), loose `.ogg` streams and
included files. `Error : Unable to find ms_miHandleMacOSExtensions method` is harmless on Linux.
Fixes needed, in the order they were hit:
1. **Case-sensitive paths.** Windows-developed projects reference resources in a different case
   than on disk. Igor fails with `Failed to load file …` → `NullReferenceException at
   GMAssetCompiler.Loader.LoadGMS2CreateAssets`, **and gm-cli still exits 0**. Scan every
   `"path":"….yy"` in the `.yyp`/`.yy` files against the disk case-sensitively (ignore
   `folders/*.yy`, virtual IDE folders) and rename to match.
2. **FFmpeg ≥ 5.1.** The asset compiler converts audio with the system `ffmpeg` using
   `aresample=ochl=1c`; Ubuntu 22.04's FFmpeg 4.4 gives only `Failed to convert audio file` and
   endless retries (it hides ffmpeg's stderr; a logging wrapper first on `PATH` shows the real
   command). Put a static FFmpeg ≥ 5.1 (e.g. BtbN's linuxarm64 builds) first on `PATH`.
3. **Desktop-only extensions** (e.g. NekoPresence/Discord RPC) crash the runner in
   `Extension_Initialize` → `Ext_Call`; with `"disable_extensions": true` the game then dies on
   `Unable to find function np_initdiscord`. Drop the extension from the `.yyp` and add a GML
   script defining every function the game calls from it as a no-op. **Grep every `.gml`,
   including `rooms/*/RoomCreationCode.gml`**: the compiler doesn't reject unknown functions.
4. **The VM is stricter than YYC.** Room creation code reading instance variables (`depth`, `x`)
   is a fatal error under the VM (`Variable <unknown_object>.depth not set before reading it`),
   and a GML `try`/`catch` doesn't catch it; `instance_exists(self)` isn't a fix either (room code
   runs on a dummy instance). Replace room-code `instance_create(a,b,obj)` with
   `instance_create_depth(a,b,-1,obj)` and don't read instance variables there. Expect a few of
   these in any YYC-only game rebuilt as VM.
5. **`os_type` is folded to the build target at compile time**, so with `--target=linux` every
   `if (os_type == os_android)` branch is gone and the game runs its Linux paths under the Android
   runner. Never guard a port-only GML fix on `os_android`. Check what made it into the bytecode
   instead: called function names appear in `game.unx` as plain strings.

#### Packaging

**Take the runner from the same runtime**, not from a wrapper APK: the runtime's `android` module
holds the official VM runner at `android/runner/ProjectFiles/src/main/jniLibs/arm64-v8a/libyoyo.so`,
an exact version match for data built with the same toolchain. The module zip is
password-protected; let gm-cli unpack it by running the same compile with `--target=android`, which
installs the module into `gmcache/runtimes-gms2/runtime-<ver>/` before failing on the licence. (The
community's bucketed "wrapper APKs" — real GameMaker Android APKs from other games reused as engine
shells — are the older route; reusing one is redistribution of someone else's binary, so check its
origin before shipping it.)

`gmloader.json` (all fields optional):
```json
{
    "save_dir" : "gamedata",
    "apk_path" : "game.apk",
    "shader_dir": "./shaders/",
    "show_cursor" : false,
    "disable_controller" : false,
    "disable_depth" : false,
    "disable_extensions" : false,
    "disable_joystick" : true,
    "disable_rumble" : false,
    "disable_texhack" : false,
    "rumble_scale" : 1.0,
    "force_platform" : "os_android"
}
```
`apk_path` (default `"game.apk"`; `"game.port"` in upstream's template is only a filename) **must
be a real zip containing `lib/arm64-v8a/libyoyo.so` plus `assets/`**. `force_platform` accepts
`os_unknown`/`os_windows`/`os_macosx`/`os_ios`/`os_android`/`os_linux`/`os_psvita`/`os_ps4`/
`os_xboxone`/`os_tvos`/`os_switch` (but see the `os_type` folding above). Runtime CLI: `-c <path>`
for the config, `-a <path>` overrides `apk_path`.

**Facts proven on hardware:**
- **`game.droid`, `options.ini` and every audiogroup must be inside the APK's `assets/`.** With
  `game.droid` loose, the runner looks for `options.ini` only inside the APK, finds nothing, and
  segfaults in `IniFile::GetSection("IPAD_OPTIONS")`. gmloader-next's `AAssetManager_open` only
  searches the zip (`[AAsset] Cannot locate assets/audiogroup1.dat`). `save_dir` only holds files
  the game writes; read-only lookups of those still try `assets/` first and log a harmless
  "Cannot locate". Rename the Linux build's `game.unx` to `game.droid`.
- **`options.ini` needs an `[Android]` section** (a desktop `[Windows]`/`[Linux]` file isn't
  enough): `DisplayName`, `MajorVersion`/`MinorVersion`/`BuildVersion`,
  `PackageDomain`/`PackageCompany`/`PackageProduct`, `OrientLandscape=-1`, `OrientPortrait=0`,
  `Debug=False`, `YYUse24Bit=1`, `SplashscreenTime=0`, `YYiCadeSupport=TRUE`, `NewDebugger=0`,
  `UseShaders=True`, then one empty `[<ExtensionName>]` section per extension.
- **Build the APK as a stored zip** (`zip -0 -r`): `lib/arm64-v8a/libyoyo.so` plus `assets/`
  (`game.droid`, `options.ini`, audiogroups, loose `.ogg`s, included files, `splash.png`).
- **Over 100MB** (OGG doesn't compress, so a stored APK can't shrink): a zip can't be
  content-split like the tar.gz pattern, so byte-split it (`split -b 60000000 -d game.apk
  game.apk.part`) and join it once at first launch with `cat game.apk.part* > game.apk` behind a
  `pm_message` (1.5s on RG351V), then delete the parts. `cat` exists on every CFW, `zip` doesn't.
- The 2024.13 runner on Mali-G31 reports `OpenGL ES 3.2`, takes the controller natively, and picks
  up the screen resolution itself.
- **GameMaker maps the pad by label, not position.** With PortMaster's `SDL_GAMECONTROLLERCONFIG`,
  `gp_face1` is the button *labelled* A, which is the right-hand button on the Nintendo-style
  layout most handhelds use (`gp_face2` = B bottom, `gp_face3` = X top, `gp_face4` = Y left). A game
  whose defaults assume Xbox positions (directional gem swaps: face1 down, face2 right) comes out
  rotated; patch the defaults. Menu confirm on `gp_face1` stays on A, which is correct.
- **No mouse cursor is drawn.** gptokeyb2 mouse motion reaches the game, but `"show_cursor": true`
  shows nothing (SDL's KMSDRM cursor needs a cursor plane these devices don't have; Android has no
  OS cursor). Build a cursor sprite in the game at startup (`surface_create`, two
  `draw_triangle`s, `sprite_create_from_surface`), set `cursor_sprite`, and keep
  `"show_cursor": false` so a device that does have a cursor plane doesn't show two.
- **Mixed mouse/keyboard + controller input**: pre-seed the game's `options.ini`/`save.ini`
  (generated by picking controller-only in the Windows build) into `save_dir`.
- Known from the GameMakerPorts bug list: GM 2.3 data is "quite unstable"; some games only find
  `.ogg` sounds when they're moved into `assets/` inside the archive.

**Loader patches a real port needed** (upstream gmloader-next is missing these; keep them as a
patch file in `patches/`):
- **Hardware keyboard text**: `update_inputs()` sets `keyboard_lastkey` a frame late and never
  sets `keyboard_lastchar`/`keyboard_string`, so GMS1-style name entry types nothing. The patch
  sets `_IO_LastKey` on key down, maps keysym + Shift/Caps to a character, and feeds the runner's
  own `IO_Char_Last_Set` and `IO_String_Get`/`IO_String_Set` (resolved with `FIND_SYMBOL`, so a
  runner without them still works).
- **GML `try`/`catch` segfaults**: the runner raises GML errors as C++ exceptions whose unwinder
  finds `.eh_frame_hdr` via `dl_iterate_phdr`, which is stubbed (`-- dl_iterate_phdr was called!
  --`), ending in `libunwind: unsupported .eh_frame_hdr version`. Report each loaded guest module,
  and hand the unwinder a copy of the program headers with every `p_vaddr` made relative again:
  `so_load()` rebases `PT_LOAD[0].p_vaddr` to an absolute address before copying the segment that
  holds the header table, so otherwise libc++ terminates with `uncaught exception of type
  YYGMLException`.
- **`Cannot seek NULL asset` spam**: Ogg streams seek before their first read, but the thunk only
  opened the zip entry on read; open it in `AAsset_seek` too.
- **Random segfaults after `Bitstream/page/packet is not Vorbis data`**: every `AAsset` shares one
  libzip handle and the runner streams audio from its own thread; put one `std::recursive_mutex`
  around all `AAsset_*` thunks.
- **Read the `Missing: <symbol>` lines at the top of every gmloader log.** Each is a guest import
  with no thunk; calling it ends the game (`so_util.cpp: Unknown symbol "<name>"`) only in the
  feature that uses it. In the generated `build/<arch>/thunks/libc/impl_tab.h`,
  `// THUNK_MISSING(name)` means add the bionic prototype to `thunks/libc/c_prototypes.h` (only when
  the struct layout matches glibc on aarch64); `// (TODO impl variadic)` (`open`, `fcntl`, `ioctl`,
  `syslog`) means write a `<name>_impl` in `thunks/libc/*.cpp` that pulls the optional argument with
  `va_arg`. Zlib symbols such as `zError` go in `thunks/zlib/zlib.cpp`'s `THUNK_DIRECT` list.
- **A `THUNK_DIRECT` call can still be wrong when a struct layout differs**: bionic's
  `struct addrinfo` has `ai_canonname` before `ai_addr`, glibc the other way round, so any runner
  networking (`yySocket::Resolve`) segfaulted with no log line. Wrap `getaddrinfo`/`freeaddrinfo`
  and swap the two pointers.
- Not fixed: after `game_end` a runner thread segfaults in `Engine::GetDebugMode` during teardown
  (saves are already written).

**Port folder layout** (deliberately different from other ports — don't "fix" it):
```
portname/
├── gmloadernext.aarch64
├── gmloader.json
├── game.apk                (stored zip: lib/arm64-v8a/libyoyo.so + assets/)
├── lib/arm64-v8a/          (guest Android libs from gmloader-next/lib: libc++_shared.so, libcompiler_rt.so, libm.so)
├── gamedata/               (save_dir)
├── license/                (singular: bionic.LICENSE Apache-2.0, gmloader-next.LICENSE GPLv2, the game's license)
└── portname.ini
```
`lib/arm64-v8a/` is a **guest** (Android-ABI) library set the loader resolves against, not a
host-side `libs.aarch64` bundle.

```bash
#!/bin/bash

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

GAMEDIR="/$directory/ports/portname"

cd "$GAMEDIR"
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

$ESUDO chmod +x "$GAMEDIR/gmloadernext.aarch64"

if [ -f "$GAMEDIR/game.apk.part00" ]; then
  pm_message "Preparing game data, this can take a minute..." --title "Please wait"
  if ! cat "$GAMEDIR"/game.apk.part* > "$GAMEDIR/game.apk"; then
    $ESUDO rm -f "$GAMEDIR/game.apk"
    pm_show_error "Could not prepare the game data. Check that there is enough free space, then launch again." --title "Preparation failed"
    exit 1
  fi
  $ESUDO rm -f "$GAMEDIR"/game.apk.part*
elif [ ! -f "$GAMEDIR/game.apk" ]; then
  pm_show_error "Game data is missing. Reinstall the port." --title "Game data missing"
  exit 1
fi

mkdir -p "$GAMEDIR/gamedata"

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$GPTOKEYB2 "gmloadernext" -c "$GAMEDIR/portname.ini" > /dev/null 2>&1 &

pm_platform_helper "$GAMEDIR/gmloadernext.aarch64"

./gmloadernext.aarch64 -c gmloader.json

pm_finish
```
`gmloadernext.aarch64` is 20 characters and the kernel `comm` keeps 15, so gptokeyb2's kill target
is the prefix `gmloadernext` (§1.8.2). The game reads the pad natively, so the `.ini` usually only
maps what the game lacks (a stick-driven mouse for mouse-only menus); if nothing needs mapping,
drop `-c` and the `.ini`.

**Upstream's template** (`GameMakerPorts`) differs: it ships a classic `.gptk` with every mapping
blank (which does *not* disable classic gptokeyb's compiled-in defaults — double input, §1.8.5 —
so convert it to a gptokeyb2 `.ini`), a `tools/splash` binary
(`$ESUDO "$GAMEDIR/tools/splash" "$GAMEDIR/splash.png" 8000 &`, with a blocking
`... splash.png 1` call first on muOS) shown before a slow first-run step, and an on-device
first-run **patcher**: on first launch (gated on `patchlog.txt` not existing) the script sources
`$controlfolder/utils/patcher.txt`, which runs the port's `tools/patchscript`. That mounts
`gmtoolkit.squashfs` and `dotnet-8.0.12.squashfs`, cleans junk from `assets/`, runs
`dotnet UndertaleModCli.dll dump data.win -e textures game.droid` (externalizing texture pages),
recompresses audio with `gmKtool.py`, and re-zips `assets/` into the archive with `zip -r -0`. That
flow converts a user-supplied desktop `data.win` on the device; **when the APK is built on the build
machine as above, no patcher is needed.**

**Debugging libyoyo crashes:**
- `GMLOADER_TRACE_VM=1` traces Runner VM execution; `GMLOADER_DUMP_SHADERS=1` + `shader_dir` dumps
  shaders that fail on weak GPUs so edited versions can be loaded back. The loader's git hash:
  `strings gmloadernext.aarch64 | grep -E '(GIT_|BUILD_)'`.
- The guest `.so` is loaded by gmloader's own ELF loader, so gdb has no symbols and `bt` stops at
  frame 1 ("corrupt stack?"). Run under `gdb -batch` with `run`, `info registers sp x29 pc lr` and
  `x/1024gx $sp`. libyoyo loads at **base `0x40000000`** (the `Missing: <sym> (0x40d…)` log lines
  confirm it). Walk the frame-pointer chain (`[x29]` = previous fp, `[x29+8]` = return address),
  subtract the base, and look each offset up in `nm -D --defined-only libyoyo.so | sort` (the
  runner keeps rich dynamic symbols); `objdump -d` around it, resolve GOT slots with
  `readelf -rW`. Upstream's `debug.gdb` instead breaks on `gdb_push` and `add-symbol-file`s the
  guest `.so` at its load address.
- For a caught-exception crash, break on the runner's `__cxa_throw` and walk the chain.
- **Memory that climbs per round**: wrap `glGen*`/`glDelete*`/`glTexImage2D` in
  `thunks/khronos/gles2.cpp` and log `__builtin_return_address(0)`, size and id. On Mali the GPU
  allocations show only in `VmRSS`, not `/proc/<pid>/smaps` Rss, so a flat heap with rising RSS
  means GPU memory. (The real cause was game code: `instance_deactivate_all` on pause made
  `instance_exists()` false, so every Pause → Main Menu created another persistent object with a
  1280x720 surface.)
- To read game state from gdb, find the runner global (e.g. `Current_Room`) with `nm -D` + base.

**Automated on-device testing — only when manual testing keeps turning up new crashes.** It takes
hours to build and run, so don't do it by default; reach for it once several errors in different
modes have shown that a few manual screens aren't representative (the Dijeweled case). The setup
that worked:
- A static lint over every `.gml` against the runtime's `GmlSpec.xml` and the runner's exported
  symbols. Errors: room creation code that reads instance variables or calls `instance_create`, a
  call that's neither a builtin nor a project function (a missing extension), a builtin the
  Android runner doesn't register. Info: `try` sites, `os_type`, runtime-built asset names.
- An in-game driver object, created only when the save dir holds a trigger file, that starts each
  case the way a player does (`event_perform(ev_mouse, ev_left_press)` on the game's own buttons),
  plays real moves, leaves via pause, and logs `START/PASS/FAIL`; `exception_unhandled_handler`
  logs GML errors. Pause deactivates every instance, so keep the driver alive with a repeating
  `time_source`.
- A device-side runner that loops the game through the case list, recovers after a crash or hang
  (watchdog), and records the GML error; plus a real-input test that runs gptokeyb2 and writes
  presses to the pad's `/dev/input/eventN` (button ids from ES's `es_input.cfg`, recorded by
  label). Report the resulting table, not an impression.

**Other Android native-library ports: Bogodroid.** `JanTrueno/Bogodroid` is a GameMaker-agnostic
sibling of gmloader (TOML-configured loaders for Unity/Mono, Super Hexagon, Limbo, Crazy Taxi).
Its main-branch README calls it "very early, very non-functional", but that's out of date: per its
author, work lives on other branches, and it's a workable base for a Unity or other native-library
Android port. Check the active branches and ask its author before judging it by the README.

**Out of scope for this approach**: gmloader-next and Bogodroid only run a prebuilt native `.so`
the app already ships. A 100%-Java/DEX Android
game (e.g. Replica Island) has nothing for them to load; Waydroid/Redroid/Anbox need kernel
`binder`/`ashmem` and a container runtime, and Robolectric is headless. Porting such a game means
recompiling its Java against a hand-written Android-API layer on PortMaster's JRE, a project of
its own.

### 1.7.9 Pattern G — Pyxel

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname
cd $GAMEDIR

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

pyxel_runtime="pyxel_2.2.8"
python_runtime="python_3.11"
if [ ! -f "$controlfolder/libs/${pyxel_runtime}.squashfs" ]; then
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${pyxel_runtime}.squashfs"
fi
if [ ! -f "$controlfolder/libs/${python_runtime}.squashfs" ]; then
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${python_runtime}.squashfs"
fi
$ESUDO mkdir -p /tmp/${python_runtime} /tmp/${pyxel_runtime}
$ESUDO mount "$controlfolder/libs/${python_runtime}.squashfs" /tmp/${python_runtime}
$ESUDO mount "$controlfolder/libs/${pyxel_runtime}.squashfs" /tmp/${pyxel_runtime}

pyxel_dir="/tmp/${pyxel_runtime}"
source "${pyxel_dir}/bin/activate"
export PYTHONHOME="/tmp/${python_runtime}"
export PYTHONPYCACHEPREFIX="$GAMEDIR/conf/pycache"

$GPTOKEYB2 "pyxel" -c "$GAMEDIR/portname.ini" > /dev/null 2>&1 &

pm_platform_helper "${pyxel_dir}/bin/pyxel"

"${pyxel_dir}/bin/pyxel" play "${GAMEDIR}/gamedata/portname.pyxapp"

$ESUDO umount /tmp/${pyxel_runtime}
$ESUDO umount /tmp/${python_runtime}
pm_finish
```

Verify exact runtime version folder names against the current PortMaster runtime catalog
(`port.json`: `"runtime": ["pyxel_2.2.8", "python_3.11"]`, `"arch": []`). The kill target is the
process name the interpreter actually runs as; check it with `ps` on a device if Start+Select
doesn't quit (same rule as Python 2 ports, §1.7.20).

### 1.7.10 Pattern H — mkxp-z (RPG Maker XP/VX/VXAce)

mkxp-z is a cross-platform reimplementation of the RGSS runtime (embedded MRI Ruby + C++ engine)
that plays RPG Maker XP/VX/VXAce games. One mkxp-z build is the *engine*; each individual RPG
Maker game gets its own PortMaster port bundling a copy of it plus that game's own data.
**Confirmed on real Mali-G31 hardware.**

Build is Meson-based, in two stages — `linux/Makefile` first statically builds ~15 third-party
libs (mostly lightly-patched forks) into `linux/build-<arch>/`, then Meson builds the app itself:
```bash
cd linux
make -j$(nproc)                # builds deps-core + ruby into build-<arch>/
source vars.sh                 # sets PKG_CONFIG_LIBDIR/PATH/LD_LIBRARY_PATH
cd ..
meson setup build -Dgfx_backend=gles -Denable-https=false --bindir=. --prefix=$PWD/build/local
cd build
ninja
ninja install
```
Use mkxp-z's own Ruby fork (`github.com/mkxp-z/ruby`, branch `mkxp-z-3.1.3`), not a stock build —
`linux/Makefile`'s `ruby` target clones it automatically. Ruby's own build needs a host "baseruby"
to bootstrap (`apt-get install ruby`, build-time only, never shipped). LTO makes this build very
slow under this chroot's QEMU emulation (the full Ruby build took over an hour in practice) — real,
not a hang; verify forward progress via `ps aux | grep lto1` rather than assuming it's stuck.
It is a native build in an aarch64 chroot: `linux/target-arm64.sh`/`linux/meson-arm64.txt` are
for cross-compiling from x86_64 and aren't needed. Build traps, in the order they bite:
- **No baseruby on the first attempt**: if Ruby's `configure` already ran once without a host
  `ruby`, delete the stale `downloads/*/ruby/Makefile` before retrying, or Make reuses its broken
  `BASERUBY = echo ...; false` line.
- **A stale 0-byte `probes.dmyh`** from that failed attempt (its generator needs Ruby) survives
  every retry, and the link of `miniruby` then fails with `undefined reference to
  'RUBY_DTRACE_METHOD_ENTRY_ENABLED'`. Delete the empty file (`find -newermt` around the failed
  attempt finds it) and rebuild.
- **`make install` nests Ruby one level too deep** (`$PREFIX/$PREFIX/lib/...`) when meson's
  `--prefix` and the Makefile's `DESTDIR` point at the same path; `vars.sh` copies it back, so
  re-`source vars.sh` after `ninja install` and check `find $PREFIX -iname 'libruby*'` before
  assuming the install is broken.

**Graphics: native GLES2 via SDL2, no gl4es needed.** `-Dgfx_backend=gles` is purely a compile-time
header/context-request switch (`SDL_opengles2.h` instead of `SDL_opengl.h`, requests a real
`SDL_GL_CONTEXT_PROFILE_ES` context) — no separate GLES library is linked, every GL function is
resolved dynamically via `SDL_GL_GetProcAddress` either way. Confirmed on real Mali-G31 hardware:
`GL Vendor: ARM / GL Renderer: Mali-G31 / GL Version: OpenGL ES 3.2` — zero gl4es involvement.

**SDL2 must be patched to link dynamically against the system SDL2**, or you bundle a bad one.
mkxp-z's own `linux/Makefile` clones and statically links its own SDL2 fork (X11+dbus, wrong for
this target). Two-part fix: in `src/meson.build`, force `dependency('SDL2', static: false)`; in
`linux/Makefile`, drop `sdl2` from the `sdl2image`/`sdlsound`/`sdl2ttf`/`deps-core` prerequisite
lists so their CMake configs fall through to the system SDL2 via pkg-config. Verify with
`readelf -d build/mkxp-z.aarch64 | grep NEEDED` — want `libSDL2-2.0.so.0` with no static SDL2
symbols baked in.

**Audio backend tuning** — don't just disable everything to save dependencies; ALSA is required
on every CFW (§2.7) and stripping it caused a confirmed real-hardware regression
(`Could not detect an available audio device` even with `SDL_AUDIODRIVER` forced). Correct flags
(`linux/Makefile`'s CMake invocations):
```
-DALSOFT_BACKEND_ALSA=yes -DALSOFT_BACKEND_PULSEAUDIO=no -DALSOFT_BACKEND_OSS=no -DALSOFT_BACKEND_SDL2=yes
-Denable-openmp=no -Denable-alsa=no -Denable-pulseaudio=no -Denable-oss=no    # FluidSynth
```
Why the flags matter: without them OpenAL Soft compiles in PulseAudio as a hard dependency
(`libpulse.so.0`/`libpulse-simple.so.0` in `NEEDED`), and FluidSynth's `enable-openmp` (default on,
DSP parallelization only) pulls in `libgomp.so.1`. OpenAL-soft loads backends via `dlopen()` at runtime, not link-time — `readelf -d` on the final
binary correctly shows no hard `libasound.so.2` dependency even with ALSA compiled in, so the
minimal-dependency goal and "ALSA works" aren't actually in tension.

**MIDI needs a bundled soundfont via mkxp-z's own config**, not an env var — `"midiSoundFont"` in
`mkxp.json` (talks to FluidSynth directly, unlike `SDL_mixer`'s `SDL_SOUNDFONTS` covered in §2.3).
Same `TimGM6mb.sf2` recommendation as §2.3 applies here. Symptom without one: `Warning: No
soundfont specified, sound might be mute` at boot, then `fluidsynth: warning: No preset found on
channel N [bank=X prog=Y]` once a MIDI track plays, while sample-based sound effects keep working
(easy to misread as "audio is broken" when only MIDI BGM is).

**`mkxp.json`'s `"patches"` array** is the correct mechanism for shipping a fixed script without
re-encrypting/touching the original `Game.rgssad` — a list of directories/zips mounted with higher
priority than the main archive. Drop a patched, unencrypted `Data/Scripts.rxdata` at
`patches/Data/Scripts.rxdata`, set `"patches": ["patches"]`, and mkxp-z transparently prefers it.
RPG Maker XP's `Game.rgssad` (RGSSAD v1) is a simple XOR-keyed container, not real encryption:
- Header `"RGSSAD\0"` (7 bytes) + 1 version byte. A 32-bit key starts at `0xDEADCAFE`; every use
  advances it via `key = (key * 7 + 3) & 0xFFFFFFFF` and returns the *old* value.
- Each directory entry: `u32 filename_length` (XOR'd with the next key value), then that many
  filename bytes (each XOR'd with `key & 0xFF`, advancing once per byte), then `u32 file_size`
  (XOR'd with the next key value). The key value at that point becomes the file's own key.
- File bodies: XOR each group of up to 4 bytes with the little-endian bytes of the file's key,
  advancing the key once per 4-byte group.
- Paths inside use backslashes (`Data\Scripts.rxdata`; match with a regex, not a literal `/`).
  `Scripts.rxdata` is a `Marshal.dump`ed array of `[section_id, section_name, zlib_source]`. To
  patch: `Marshal.load`, find the section, `Zlib::Inflate.inflate`, edit, check it parses
  (`RubyVM::InstructionSequence.compile`), `Zlib::Deflate.deflate`, `Marshal.dump` it back.

A patched `Scripts.rxdata` contains the game's **entire** script bundle, not a diff, so shipping
it redistributes all of the game's scripts. If that's not acceptable for the game, generate it on
the device at first launch from the player's own `Game.rgssad` instead: mkxp-z's Ruby build
includes a ~13KB standalone `ruby` CLI (`linux/build-<arch>/bin/ruby`) that links only against
libraries the port already ships.

**Script errors: triage before assuming a Ruby-version problem.** When an old game's scripts fail
with `SyntaxError`, syntax-check every section (`RubyVM::InstructionSequence.compile(src, name)`
inside `begin/rescue SyntaxError`) rather than stopping at the first failure. In the one real
case (Last Scenario, 139 sections) exactly one section failed, a dead argument (`str (true)` on a
zero-argument accessor), a one-line fix — not a reason to build a Ruby 1.8. A second common RGSS
bug class: a custom `attr_accessor` with no default in every initializer (`comparison of Integer
with nil failed`). Fix the initializers *and* the read site (`$game_system.foo || 0`): RPG Maker
saves are a raw `Marshal.dump`, and `Marshal.load` never calls `initialize`, so existing saves
still lack the variable.

**Controls need no remapping at all** — `src/eventthread.cpp` already uses the high-level
`SDL_GameControllerAddMappingsFromFile`/`SDL_GameControllerOpen` API (the "known good" case, not
the `SDL_JoystickOpen` problem case from §2.1), with an `xxd`-embedded `gamecontrollerdb.txt`.
Default mapping (physical labels): **A → RGSS C** (confirm/interact), **B → RGSS B** (cancel),
**Y → RGSS X**, **X → RGSS A**, **L3/R3 → RGSS Y/Z**, **L1/R1 → RGSS L/R**, D-pad and left stick
move. A launch script only needs gptokeyb2 for the Start+Select kill switch, so it ships **no
`.ini`**.

```bash
#!/bin/bash

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

GAMEDIR=/$directory/ports/portname
BINARY=mkxp-z.${DEVICE_ARCH}

mkdir -p "$GAMEDIR/conf"
cd $GAMEDIR

> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

$GPTOKEYB2 "$BINARY" > /dev/null 2>&1 &

pm_platform_helper "$GAMEDIR/$BINARY"

./$BINARY

pm_finish
```

Game data (`Game.ini`/`Data/`/`Graphics/`/`Audio/`) sits **flat, directly alongside the binary**
by default (`getDefaultGameRoot()` is just `SDL_GetBasePath()`), unless `mkxp.json`'s
`"gameFolder"` option is set. The Meson build's own install rpath (`$ORIGIN/lib64`) doesn't match
this project's `libs.$DEVICE_ARCH` convention, but it's a non-issue: the binary uses `DT_RUNPATH`,
and glibc's loader searches `LD_LIBRARY_PATH` before `RUNPATH`, so the standard
`export LD_LIBRARY_PATH=...` line above is all that's needed. **Minimal real `libs.aarch64/`
contents**: `libruby.so.3.1` (~9MB, hard dependency), plus `libcrypt.so.1` and `libffi.so.8`
(small transitive deps not on the near-universal list) — everything else (physfs, openal,
theora/vorbis/ogg, sdl2_ttf/image/sound, freetype, pixman, libpng, uchardet, fluidsynth) is
statically embedded into the engine binary. Ship the Ruby stdlib too
(`linux/build-<arch>/lib/ruby/3.1.0`, as e.g. `stdlib/`). `mkxp.json`'s `"enable-https"` (default
on) pulls in OpenSSL and forces GPLv3 licensing instead of GPLv2+ — set `-Denable-https=false`
unless a specific game's custom scripts actually need HTTP, since RPG Maker games essentially
never do. The icon, `gamecontrollerdb.txt` and fallback font are embedded in the binary with `xxd`
(no loose files). Licenses: mkxp-z itself is GPLv2+ (`COPYING`); copy each statically linked
dependency's license from its cloned source under `linux/downloads/<arch>/<dep>/`, and
`libffi`/`libcrypt`'s from the distro's `/usr/share/doc/<package>/copyright`. The game's own data
is a separate licensing question: an old freeware RPG Maker game often has no explicit
redistribution license, in which case ship the engine (+ script patches, soundfont) and have the
player supply the game files, with a `pm_show_error` that names the missing file.

### 1.7.11 .NET ports — three real shapes, not one recipe

A modern .NET game published with `dotnet publish -r linux-arm64 --self-contained
-p:PublishAot=true` produces one native ELF binary with no managed-runtime dependency at all —
this uses **Pattern A or B directly** (basic native binary, or gl4es standalone if the graphics
stack needs it), not a runtime-mount pattern. Which of A/B, and what else needs handling, depends
on the specific framework:

**Runtime choice** (pick based on target framework, before assuming Native AOT is always right):
- **`mono-6.12.0.122-aarch64.squashfs`**: the old Mono JIT, for legacy FNA/XNA-style ports. Only
  works for old-style .NET Framework/netstandard2.0-era assemblies — cannot load `net8.0`+
  assemblies using newer BCL/language features (e.g. `System.Threading.Lock`). Check the target's
  `<TargetFramework>` and grep for very-recent BCL types first.
- **`dotnet-8.0.12.squashfs`**: a real .NET 8 shared runtime for framework-dependent deployment
  (`dotnet Game.dll`), proven on the OpenRA port below. **The local file is
  `$controlfolder/libs/dotnet-8.0.12.squashfs`, without an arch suffix**, even though the file
  downloaded from GitHub is `dotnet-8.0.12.aarch64.squashfs`: `check_runtime()` saves it under the
  generic key. A script testing for `dotnet-8.0.12.aarch64.squashfs` never finds it, re-downloads
  every launch, and then fails at `mount` with a plain `No such file or directory`. (Mono's key is
  arch-suffixed in the catalog itself; that's the legacy exception, don't reason by analogy.) An
  app targeting an older major (`net6.0`) needs `DOTNET_ROLL_FORWARD=LatestMajor` to start against
  the net8 runtime at all.
- **Native AOT, self-contained** (the common case): `dotnet publish -r linux-arm64
  --self-contained -p:PublishAot=true -p:PublishReadyToRun=false -p:TieredCompilation=false`
  (some projects gate AOT behind a custom MSBuild property like `EnableNativeAot` instead — check
  the `.csproj`/CI workflow first, don't assume the flag name; some have no gate at all, then
  verify AOT happened by the `Generating native code` build step and the absence of
  `libcoreclr`/`hostfxr` in the output's `NEEDED`). If the build chroot is itself aarch64, this is
  a native build, not a cross-compile — install the matching-arch SDK via `dotnet-install.sh` and
  publish directly. Prerequisites: `clang`, `zlib1g-dev`. Before publishing, check that each native
  dependency package actually ships `linux-arm64`: open the `.nupkg` and look for
  `runtimes/linux-arm64/native/*.so` (MonoGame's `MonoGame.Library.SDL` 2.32.10.2 and
  `MonoGame.Library.OpenAL` 1.24.3.4 do).

**Never bundle .NET's own pulled-in SDL2.** `dotnet publish --self-contained` copies MonoGame's
native SDL2 binary into the publish output; delete it before packaging — same rule as §1.1's
never-bundle-libSDL2 rule.

**A `BINARY=<name>` variable declared once and referenced everywhere** (gptokeyb2's argument,
`pm_platform_helper`'s argument, the final launch line) beats repeating the (often
arch-suffixed) executable filename three separate times inline.

**Port subfolder naming, `licenses/` placement, and image-path conventions are exactly as
described in §1.1-§1.3** — a real reference port's own layout has one extra nesting level specific
to how that port separates PortMaster-supplied vs. user-supplied files; don't copy that literally
if the port's data doesn't need the same split.

#### MonoGame.Framework.DesktopGL — needs gl4es, no way around it

Checked whether MonoGame or its forks can request a GLES context directly instead of needing
translation — they can't. `MonoGame.Framework.DesktopGL`'s context-creation code
(`GraphicsContext.SDL.cs`) always calls `Sdl.GL.CreateContext` with no ES option, throwing
`PlatformNotSupportedException` if it can't resolve FBO entry points. The open MonoGame PR #9137
("Add OpenGL ES 3.x support") doesn't touch that file (it only extends Android/iOS code), so it
won't help a desktop port even once merged. **KNI** (a MonoGame fork with WebGL support) has the
same gap on desktop (`Kni.Platform.SDL2.GL.csproj` defines `OPENGL;DESKTOPGL` only; its GLES path
is Android/Blazor). FNA needs FNA3D/FAudio built from source for `linux-arm64` (no official
prebuilt aarch64 binaries found). **FNA** (a different, non-MonoGame XNA
reimplementation) does have a native ES path (`FNA3D_OPENGL_FORCE_ES3=1`, no gl4es, no
Westonpack) — the technically cleanest end state if a game can be migrated to it, at the cost of a
real engine migration.

Build gl4es (no X11, GBM/EGL direct-to-screen):
```
cmake .. -DNOX11=ON -DGLX_STUBS=ON -DEGL_WRAPPER=ON -DGBM=ON
make
```
Needs the `libdrm`, `gbm` and `egl` dev packages; produces `libGL.so.1`/`libEGL.so.1`. The
FBO-requirement concern is a non-issue: gl4es explicitly advertises
`GL_ARB_framebuffer_object`/`GL_EXT_framebuffer_object`/`GL_EXT_framebuffer_blit` in its
`GL_EXTENSIONS` string and implements them via GLES2's native FBO support — verify with
`strings lib/libGL.so.1 | grep framebuffer_object` and
`nm -D lib/libGL.so.1 | grep -E 'glGenFramebuffers$|glBindFramebuffer$'`. Standalone gl4es vs
Westonpack: no compositor abstracting device quirks, but zero mount/compositor overhead; reach
for Westonpack only when the app needs X11/Wayland or this simpler path fails. Use Pattern B (§1.7.3) for the launch script, **plus** its guarded
`SDL_VIDEO_GL_DRIVER`/`SDL_VIDEO_EGL_DRIVER` block, which MonoGame specifically needs (confirmed on
RG351V/AmberELEC: `FramebufferHelper.Create()` threw `PlatformNotSupportedException: MonoGame
requires either ARB_framebuffer_object or EXT_framebuffer_object` without it even though gl4es
itself initialized fine). Use the `LD_LIBRARY_PATH`-guarded form from §1.7.3, not a folder check.

**Song content pipeline gotcha**: if the game uses `Song`/`MediaPlayer` (background music, not
`SoundEffect`), MGCB's `SongProcessor` output for DesktopGL is **two files** — a tiny `.xnb` stub
(~100 bytes) and a full-size companion audio file (e.g. `intro.ogg`) sitting next to it. `Song`'s
runtime playback opens that companion file directly by path; it is not embedded in the `.xnb`.
Easy to miss when assembling a minimal port tree — always check the publish output's `Content/`
folder for every file next to each processed asset, not just the `.xnb`.

**License check**: don't assume a NuGet package's own bundled `LICENSE` file is complete/correct
for the native binary it ships — `MonoGame.Library.OpenAL`'s nupkg includes only a BSD-3-Clause
notice for one ambisonics-related portion, while OpenAL Soft's actual primary license is LGPL v2.
Go to the actual upstream project's repo for the real license.

**MonoGame mouse UI**: map with the standard mouse defaults (§1.8.1). Before flagging a
keyboard-only feature as unmapped in the README, check whether the game's UI also handles the same
interaction by mouse (a `PrimaryClick`/hover handler on the same on-screen buttons): a working
stick-mouse mapping already covers it; don't add one gamepad button per digit.

#### Raylib-cs — has a native GLES path, use it instead of gl4es

Raylib-cs is a genuine fork point from MonoGame: raylib **can** request GLES directly. Three
approaches were tried in order on a real port (`DasErbe2`) — don't repeat this exploration:

1. **`PLATFORM_DRM`** (raylib's own native KMS/GBM/EGL backend, no SDL2). Built cleanly, **failed
   on device**: `Failed to find a suitable DRM connector mode` / `Failed to initialize platform`,
   then a double-free crash. A second confirmed real case for the "never use an engine's own
   native DRM backend" rule (§1.7.4's Westonpack section exists partly because of this same class
   of failure).
2. **`PLATFORM_DESKTOP_SDL` + `OPENGL_VERSION=2.1` + gl4es** (mirroring the MonoGame recipe).
   Got much further (SDL2 init, gl4es loaded, textures/audio loaded) but **ended in a black
   screen**: `Shader: Compile error: Language version '120' unknown` and `FBO: Framebuffer has
   incomplete attachment`. Root cause (from reading `rlgl.h`): with `GRAPHICS_API_OPENGL_21`
   defined, raylib internally aliases to `GRAPHICS_API_OPENGL_33`, routing depth-renderbuffer
   creation into a code path that only picks a sized format under an ES2-only guard that never
   fires here — falls through to an unsized `GL_DEPTH_COMPONENT` token that GLES rejects. This is
   the confirmed source of a real bug specific to the OpenGL-2.1-through-gl4es combination on
   GLES-only hardware — don't use this combination for a Raylib-cs port even though it's what the
   MonoGame recipe effectively does under the hood.
3. **Winning recipe: `PLATFORM_DESKTOP_SDL` + `OPENGL_VERSION="ES 2.0"`, no gl4es at all.**
   ```
   cmake .. -DPLATFORM=SDL -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DBUILD_EXAMPLES=OFF -DOPENGL_VERSION="ES 2.0"
   make -j"$(nproc)"
   ```
   raylib's `rcore_desktop_sdl.c` requests a genuine GLES2-profile context from SDL2 and calls the
   device's real GLESv2 entry points directly — no translation layer, and it takes the ES2-specific
   sized-format branch instead of the buggy one above. SDL2 still owns all windowing (satisfying
   the never-bypass-SDL2 rule). Confirmed working on two GPU vendors: RK3566/Mali-G31 and a Retroid
   Pocket 5 on ROCKNIX (Snapdragon 865/Adreno via freedreno). `readelf -d libraylib.so` shows only
   `libSDL2-2.0.so.0`/libc/ld-linux as `NEEDED` — no GLES/EGL link-time dependency. Confirm in the
   CMake configure output: `PLATFORM=PLATFORM_DESKTOP_SDL`, `GRAPHICS=GRAPHICS_API_OPENGL_ES2`. A
   healthy device log shows `GLAD: OpenGL ES 2.0 loaded` and `TEXTURE: [ID 1] Depth renderbuffer
   loaded successfully (24 bits)`. The failure strings from the two rejected recipes, for
   recognising them: `SHADER: [ID 1] Compile error: 0:1: P0007: Language version '120' unknown`
   (gl4es's `ConvertShader()` should rewrite `#version 120` but didn't in this call path, never
   resolved) and, for `PLATFORM_DRM`, `free(): double free detected in tcache 2`.

Packaging consequence: **no** `gl4es.$DEVICE_ARCH/` folder, no `SDL_VIDEO_GL_DRIVER`/
`SDL_VIDEO_EGL_DRIVER`, no `libgl_default.txt` sourcing — plain Pattern A (§1.7.2), just
`libs.$DEVICE_ARCH/libraylib.so` and a normal `LD_LIBRARY_PATH` export.

Other Raylib-cs specifics: the NuGet package ships no `linux-arm64` native library at all (unlike
MonoGame's SDL/OpenAL packages) — `libraylib.so` must always be built from source, matching the
Raylib-cs version's own pinned upstream raylib tag (Raylib-cs 8.0.0 pins raylib `6.0`; check its
README, don't assume `master`). `DllImport("raylib")` finds `libraylib.so` on `LD_LIBRARY_PATH`
by itself; no `NativeLibrary.SetDllImportResolver` or env var needed.
raylib's audio is `miniaudio`, statically linked — no separate `libopenal.so` to bundle. Add
`#define MA_NO_PULSEAUDIO` next to raylib's existing `#define MA_NO_JACK` in `raudio.c` (same
PipeWire-probing friction as the general miniaudio gotcha in §2.3 — this is that finding's actual
source). On touchscreen devices, the touch rule from §2.1 applies here too — raylib itself is fine (its
`SDL_FINGER*` handlers keep touch separate), the snap comes from SDL2 synthesizing mouse events
from touch by default, so `SDL_TOUCH_MOUSE_EVENTS=0` on the game's command line is enough. Before
assuming a native-gamepad double-input risk (§2.1's `SDL_JoystickOpen` gotcha doesn't even apply
here — raylib uses the high-level API), grep for whether the specific game actually calls raylib's
gamepad functions at all (`IsGamepadButtonPressed`, `GetGamepadAxisMovement`,
`SetGamepadMappings`, `IsGamepadAvailable`); a mouse/keyboard-only game has nothing to conflict
with gptokeyb2's mouse emulation.

#### Old .NET Framework + Mono squashfs + hand-rolled SDL2 P/Invoke — cautionary case study, not a recommended pattern

**High risk. The real attempt this is drawn from was ultimately abandoned** after real progress
(built, ran on hardware, reached the main menu, survived three separate confirmed crashes) because
the three-layer debugging surface (managed C#, a hand-rolled P/Invoke SDL2 binding, and whatever
native `.so` actually loads at runtime) made every new symptom a multi-hour excavation with no
guarantee of being the last one. This is a different problem shape from the MonoGame/Native-AOT
case above — it applies to old-style `.NET Framework 4.5.2`-class projects with their own
hand-rolled SDL2 binding, not a maintained framework. Budget for this depth of debugging, or
prefer a target where the binding layer is maintained (FNA, MonoGame) over a single game's own
bespoke SDL2 wrapper.

What's still worth reusing if this shape of port is attempted: the **Mono launch pattern itself**,
validated end-to-end (game reached its main menu on real hardware). Build fixes needed on **every**
`.csproj` in the dependency chain:
```xml
<ItemGroup>
  <PackageReference Include="Microsoft.NETFramework.ReferenceAssemblies" Version="1.0.3">
    <PrivateAssets>all</PrivateAssets>
    <IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
  </PackageReference>
</ItemGroup>
```
and **force `<PlatformTarget>` from `x86` to `AnyCPU`** if set (a real confirmed blocker — `x86`
sets a 32-bit-required CLR flag that won't load on ARM64 Mono). `MSB3276` assembly-version
conflicts between a polyfill package (e.g. `System.Memory`) and a transitive dependency are fixed
with an `app.config` `bindingRedirect` (`<assemblyIdentity name="System.Memory"
publicKeyToken="cc7b13ffcd2ddd51" .../><bindingRedirect oldVersion="0.0.0.0-4.0.1.2"
newVersion="4.0.1.2"/>`). Sibling `ProjectReference` repos: clone them at the same relative depth
the `.csproj` expects. Build the game's own `.csproj`, not the `.sln`, if test projects need the
old `Microsoft.CSharp.Targets`. **Check for an actively maintained community fork first**: here a
fork 68 commits ahead had already fixed real gameplay bugs, crashes and audio. Launch script:
```bash
monodir="$HOME/mono"
mono_runtime="mono-6.12.0.122-aarch64"
monofile="$controlfolder/libs/${mono_runtime}.squashfs"
if [ ! -f "$monofile" ]; then
  if [ ! -f "$controlfolder/harbourmaster" ]; then
    pm_show_error "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info." --title "PortMaster update needed"
    exit 1
  fi
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${mono_runtime}.squashfs"
fi
$ESUDO mkdir -p "$monodir"
$ESUDO umount "$monofile" || true
$ESUDO mount "$monofile" "$monodir"
```
`umount "$monofile"` (the squashfs *file*, not the mount directory) is intentional; Linux's
`umount` accepts either, and the first-run `Invalid argument` it prints is harmless. **The runtime
provisioning guard is not optional**, even though the real upstream `Celeste.sh` this pattern
derives from doesn't visibly include one — launching outside PortMaster's own install flow
skips the runtime download otherwise. `$GPTOKEYB2`'s kill-switch target should be `"mono"`, the
actual OS process name, not the game's exe name.

**`SDL_CreateRenderer` auto-picking the Mali/GLES2 renderer is a hard `SIGSEGV` under Mono**, not
the soft `SDL_CreateTexture` error from §2.2 — same root cause, worse failure mode since a
P/Invoke crash mid-native-call has no managed exception to catch. Same fix: force
`SDL_RENDERER_SOFTWARE`. If porting any game to this device class that creates its own
`SDL_Renderer`, force software rendering preemptively.

Three more real bugs from this attempt, each a general lesson:
- **`SDL_FreeSurface()` on a surface from `SDL_GetWindowSurface()`** (owned by the window, freed
  with it) — undefined behaviour on every teardown path; an upstream engine bug. Don't free it.
- **Stale enum values in a hand-rolled P/Invoke binding**: an SDL2#-style binding had
  `MIX_INIT_MP3 = 0x4`/`MIX_INIT_OGG = 0x8`, the real ABI is `0x8`/`0x10`, so `Mix_Init(OGG)` asked
  for MP3 (`Mix_Init(OGG): MP3 support not available`). Check every constant in a binding against
  the installed header before blaming the native library.
- **Silent loader failures**: an image loader with `if (ptr != IntPtr.Zero) { ... }` and no `else`
  left a 0×0 image, which caused 27,000 `DivideByZeroException`s in 23 minutes three frames away.
  Grep a legacy engine for this pattern before porting and add a log line on the failure path.
  (The image failed because a `libSDL2_image` reused from another port couldn't decode TGA
  ImageType 9; §1.1.)

Reusable debugging technique from this attempt: when a Mono crash produces a `mono_crash.json`
with managed-stack tokens but no method names and no `monodis`/`ildasm` is available, a from-scratch
ECMA-335 metadata table reader can decode `MethodDef` tokens to real names directly from the
crashing assembly's own bytes (cross-check the assembly's MVID against the crash report's `guid`
to confirm you're decoding the exact binary that crashed), then reading the `TypeDef` table's
`MethodList` ranges to find each method's owning class. Watch for an off-by-one in the
Event/Property table region if writing one: `0x12 EventMap, 0x13 EventPtr (unused), 0x14 Event,
0x15 PropertyMap, 0x16 PropertyPtr (unused), 0x17 Property, 0x18 MethodSemantics, 0x19
MethodImpl` — shifting any of these by one table number (easy to do from memory, e.g. by
forgetting the unused `*Ptr` slots) silently corrupts every later table's row-size calculation, including the commonly-present `NestedClass` (`0x29`). (The decoded crash turned out
to be in teardown, not gameplay.)

#### OpenRA engine mods — framework-dependent .NET 8, two-pass publish

From the OpenOP2 port (an Outpost 2 mod, `net6.0`), confirmed on RG351V/AmberELEC (Mali GLES) and
Retroid Pocket 5/ROCKNIX (Adreno, desktop GL).
- **Framework-dependent, not self-contained.** Self-contained output was 231 top-level files
  (~95MB), and 188 of 190 DLLs were genuine dependencies per `OpenRA.deps.json`; that's what an
  untrimmed self-contained .NET app looks like. Framework-dependent on `dotnet-8.0.12.squashfs`
  cut it to 39-58 files (~11MB). IL trimming (`-p:PublishTrimmed=true`) was rejected: OpenRA loads
  mod assemblies by reflection, exactly what trimmers silently break.
- **Two publish passes into the same output folder**: the engine's `OpenRA.sln`
  (`install_assemblies`) then the mod's own `.sln` (`install_mod_assemblies`). The mod pass alone
  silently drops `SDL2-CS.dll`, `OpenAL-CS.dll`, `soft_oal.so`, `lua51.so`, `freetype6.so`,
  `SDL2.so`. `-p:CopyGenericLauncher=False` belongs on the engine pass only; on a combined single
  pass it also suppresses the `OpenRA` binary.
- **`DOTNET_ROLL_FORWARD=LatestMajor`** is required (`runtimeconfig.json` asks for 6.0.0; the default
  policy won't cross majors).
- **GL profile probe**: OpenRA's `Sdl2PlatformWindow` probes `{ANGLE, Modern, Embedded}` with
  throwaway contexts, and on Mali-G31, Mali-G52 and others every probe failed (`Failed loading
  eglGetPlatformDisplayEXT`) although real context creation works. A merged vanilla-OpenRA port
  patched this with CFW-name branches in engine code — don't. The generic fix: when the probe finds
  zero profiles, log the errors and fall back to a real `GLProfile.Embedded` attempt, throwing only
  if that fails (`if (supportedProfiles.Length == 0) { ...; supportedProfiles = new[] {
  GLProfile.Embedded }; }`). Works on Mali (Embedded) and Adreno (Modern, desktop GL 4.6) alike.
- **`freetype6` name mismatch**: the managed binding loads `freetype6`, the device has
  `libfreetype.so.6`, and CoreCLR ignores Mono's `<dllmap>`. Real failure: `DllNotFoundException:
  Unable to load shared library 'freetype6'`. Fix without hardcoding a path:
  ```bash
  FREETYPE_LIB=$(find /usr/lib /lib /usr/local/lib -name "libfreetype.so*" 2>/dev/null | head -1)
  [ -n "$FREETYPE_LIB" ] && bind_files "$GAMEDIR/libs.${DEVICE_ARCH}/freetype6.so" "$FREETYPE_LIB"
  ```
  (`libs.aarch64/` ships in the package with a `.keep` file; the script never creates it). The
  same static-analysis concern for `SDL2` did **not** materialize on any device, so no fix was
  added: real-device evidence beats a plausible theory.
- **Controls**: take bindings from the engine's own `mods/common/hotkeys/*.yaml`, not from another
  port's `.ini`; OpenRA's `Return` is gptokeyb2's `"enter"` (`"return"` isn't a valid key).
- **Packaging**: archive everything except `gamedata/` (the player's own asset drop folder) and the
  bind target folder (337 files → 8); keep the frequently tuned `.ini` loose. A nested
  `IP2LOCATION-*.BIN.ZIP` is how upstream ships it (opened via `ZipFile`), but it's only for
  hosted-lobby country tags, so it was dropped. Case mismatches inside the mod (`op2_art.bmp` vs
  the real `OP2_ART.BMP`) worked on FAT storage and failed on case-sensitive ext4: normalize every
  reference to the shipped filename. `licenses/` needs every managed DLL too (~15 were missing on
  the first pass); take package identities from the `.csproj` `PackageReference`s.
- **Known unresolved**: RGB30/dArkOS OOM-kills the game right after `LoadMaps` (confirmed in
  `dmesg`), unaffected by `Graphics.SheetSize=1024`; an unrelated ~160MB `fluidsynth` process and
  `[ALSOFT] (EE) available update failed: Broken pipe` at the crash point suggest audio, not
  textures.

### 1.7.12 sdl3-sdl2-backend — for genuinely SDL3-only engines

A fork of the SDL3 source tree (`bmdhacks/SDL`, branch `sdl2-backend`) that replaces SDL3's video/
audio/joystick backends with ones that `dlopen` the device's already-installed system SDL2 at
runtime; GPU is a standalone GLES 3.x backend via SPIRV-Cross that does not go through SDL2 at
all. **Only reach for this when an engine is genuinely SDL3-only with no SDL2 path** — if it has
an SDL2 path (MonoGame/raylib effectively do), build against system SDL2 directly instead, no
translation layer needed.

**Status: real-device confirmed on several ports**: arcanum-ce (RG351V/AmberELEC), Insaniquarium
(x55/ROCKNIX, both Panfrost and Libmali; there the shim was the *fix* for a broken native SDL3
KMSDRM path, `SDL_CreateWindowWithProperties: Parameter 'props' is invalid` on R36S/dArkOS),
Rail Road Rampage (BennuGD64) and Cortex Command. Three bugs found and fixed: a build-flag issue,
the shim's mouse-motion translation, and a shutdown segfault (all below). Known limitations from
the fork's README: no compute pipelines, some copy/blit operations unimplemented, no joystick
hot-plug (state comes from SDL2's cache), and the GLES GPU backend is immediate-mode (not for
multi-threaded rendering). Engines rendering through SDL3's 2D `SDL_Renderer` still ride on the
GPU backend (`-DSDL_RENDER_GPU=ON`).

**Critical: never tune `-mcpu` to a single SoC**, despite what the fork's own README recommends.
This project ships one binary across its entire device matrix. A build with `-mcpu=cortex-a55`
(the project's primary RK3566 target) crashed with `SIGILL` on an RG351V (Cortex-A35) — an inlined
ARMv8.1 LSE atomic instruction (`swpa`) that Cortex-A35 can't execute. Fix: build with the generic
`-march=armv8-a` baseline, which makes GCC emit libgcc outline-atomics helper calls that check CPU
support at runtime instead of inlining the instruction.

```bash
git clone --recursive https://github.com/bmdhacks/SDL.git -b sdl2-backend
cd SDL
git clone https://github.com/KhronosGroup/SPIRV-Cross.git /path/to/SPIRV-Cross
mkdir build && cd build
cmake .. \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_FLAGS="-march=armv8-a" \
  -DSDL_SDL2_BACKEND=ON \
  -DSDL_SPIRV_CROSS_DIR=/path/to/SPIRV-Cross \
  -DSDL_X11=OFF -DSDL_WAYLAND=OFF -DSDL_KMSDRM=OFF \
  -DSDL_PIPEWIRE=OFF -DSDL_PULSEAUDIO=OFF -DSDL_ALSA=OFF \
  -DSDL_SNDIO=OFF -DSDL_OSS=OFF -DSDL_JACK=OFF \
  -DSDL_OFFSCREEN=OFF -DSDL_DUMMYVIDEO=OFF \
  -DSDL_DUMMYAUDIO=OFF -DSDL_DISKAUDIO=OFF \
  -DSDL_VULKAN=OFF -DSDL_GPU=ON -DSDL_RENDER_GPU=ON \
  -DSDL_UNIX_CONSOLE_BUILD=ON
make -j$(nproc)
```
The last flag is **not mentioned in the fork's README** but is required — without it, SDL's own
build summary hard-errors demanding X11/Wayland dev libraries even with all display backends off,
since it doesn't otherwise know a windowless/console-style Unix build is intentional.

Configure output to expect: `Video drivers: sdl2`, `Audio drivers: sdl2`, `Joystick drivers:
hidapi sdl2 virtual`, `Render drivers: gpu ogl ogl_es2`, `GPU drivers: gles openxr`, shared library
only. The result's `NEEDED` is only `libm`/`libgcc_s`/`libc`/`ld-linux`, with an undefined
`dlopen@GLIBC_2.34` (SDL2 is loaded at runtime, never linked). SPIRV-Cross is not vendored: the
build hard-errors (`SDL_SDL2_BACKEND GPU requires SPIRV-Cross`) without `-DSDL_SPIRV_CROSS_DIR`,
and an incremental rebuild fails the same way if that checkout was deleted.

Runtime env vars the shim reads: `SDL3SHIM_SDL2_LIB` (path to dlopen), `SDL3SHIM_SDL2_VIDEODRIVER`,
`SDL3SHIM_SDL2_AUDIODRIVER`, and `SDL3SHIM_ENABLE_MOUSE=1` (undocumented opt-in: without it the
cursor vtable — `CreateCursor`/`ShowCursor`/`WarpMouse` — isn't wired up; only needed if the game
uses the native SDL cursor). `LD_LIBRARY_PATH` must include the folder holding the shim.

**The launch-script driver pattern (required, proven on ROCKNIX):** the shim compiles in exactly
one video and one audio driver, both named `sdl2`. SDL3's own driver selection reads the plain
`SDL_VIDEODRIVER`, so a CFW value like ROCKNIX's `SDL_VIDEODRIVER=wayland` (set in its
`/etc/profile.d/050-sway.conf`) makes the shim fail: `SDL failed to start: wayland not available`
/ `video drivers compiled in: 1 / 1: sdl2`. So the script **forwards** the CFW's own values to
the inner SDL2 and sets `SDL_VIDEODRIVER`/`SDL_AUDIODRIVER` to `sdl2` **on the game's command line
only** (never `export`ed, so gptokeyb2 keeps the CFW's real values). This is forwarding, not
hardcoding a driver choice, and it is the one sanctioned exception to §2.2's rule:
```bash
GAME_SDL_VIDEODRIVER=""
if [ -n "$SDL_VIDEODRIVER" ]; then
  export SDL3SHIM_SDL2_VIDEODRIVER="$SDL_VIDEODRIVER"
  GAME_SDL_VIDEODRIVER=sdl2
fi
GAME_SDL_AUDIODRIVER=""
if [ -n "$SDL_AUDIODRIVER" ]; then
  export SDL3SHIM_SDL2_AUDIODRIVER="$SDL_AUDIODRIVER"
  GAME_SDL_AUDIODRIVER=sdl2
fi

$GPTOKEYB2 "$BINARY" > /dev/null 2>&1 &

pm_platform_helper "$GAMEDIR/$BINARY"

SDL_VIDEODRIVER="$GAME_SDL_VIDEODRIVER" SDL_AUDIODRIVER="$GAME_SDL_AUDIODRIVER" ./$BINARY
```
Forwarding only `SDL3SHIM_SDL2_VIDEODRIVER` without the `sdl2` override reproduces the ROCKNIX
failure. Never put a literal driver name (`kmsdrm`, `wayland`) into `SDL3SHIM_SDL2_*` either.

**A port's Libmali exclusion guard may become unnecessary once shimmed**: such guards exist because
an engine creating its own native GL context against KMSDRM/EGL hits Libmali-specific failures;
through the shim, video goes through the CFW's own working SDL2. Insaniquarium's ROCKNIX/Libmali
guard was removed and the game was then confirmed working on Libmali. Retest on a Libmali device
before removing such a guard from any other port.

Confirmed real bug in the shim's own event code: `SDL_sdl2events.c`'s `SDL2_MOUSEMOTION` case used
`e.motion.which != 0` (the device instance ID, not a relative-mode flag) to decide relative vs.
absolute mouse motion, and passed absolute `x`/`y` even when relative was intended instead of
`xrel`/`yrel` — the cursor raced toward one corner. Fixed via a local patch tracking real
relative-mode state through `SDL2Mouse_SetRelativeMouseMode()` (a `bool SDL2_relative_mouse_mode`
in `SDL_sdl2mouse.c`, `extern` in its header; forward `xrel`/`yrel` with `relative=true` only when
it's set, `x`/`y` with `relative=false` otherwise); reapply on any fresh clone.

**Confirmed bug: shutdown segfault in SDL2's audio thread when the app quits video before audio.**
Symptom (Rail Road Rampage/BennuGD64): every exit crashed, gdb showed `Thread "SDLAudioP2" received
signal SIGSEGV` at a PC outside every mapped library, with `libSDL2` already gone from
`info sharedlibrary`. Only the shim's video driver owns the SDL2 `dlopen` handle, and SDL3 video
quit called `SDL2_UnloadLibrary()` → `dlclose()` while SDL2's audio device and its playback thread
were still open. Fix: make `SDL2_UnloadLibrary()` a no-op (never `dlclose` SDL2; the mouse code
already did this). Older shim builds shipped in some ports still have this bug; it only shows at
exit, and only for apps that quit video first.

Packaging: ship the built `libSDL3.so.0` in `libs.aarch64/` — **never** ship a bundled SDL2 alongside
it, same shadowing risk as the `sdl12-compat` gotcha. The shim is a build-standalone, swap-in
artifact — the consuming port's own build keeps linking dynamically against real upstream SDL3
(a chroot-wide SDL3 build, §3.1, or the port's own FetchContent with `SDL_SHARED ON`/`SDL_STATIC
OFF`; a vendored static SDL3 leaves nothing to swap), never against this fork, and never against
an engine author's patched SDL3 fork (PopLib's `SaMeiers/SDL` `mali-fbdev` fork was avoided).
Switching a port from static to shared SDL3 can expose a latent missing `-lm` (`undefined
reference to symbol 'sqrt@@GLIBC_2.17'` / `DSO missing from command line`, masked before by the
static target's propagated link deps): add `if(UNIX) target_link_libraries(<target> PUBLIC m)
endif()` to the port. Libraries the shimmed game needs beyond the shim come from real device
errors (Insaniquarium needed `libbrotlidec.so.1`/`libbrotlicommon.so.1` for SDL3_ttf's freetype).

**PopLib/SDL3 engine notes (Insaniquarium Deluxe, WinFish decompilation)**: re-derived from the
engine source rather than upstream's script (§2.8). `POPLIB_FULLSCREEN` overrides the saved
windowed setting; `POPLIB_SOFTWARE_CURSOR` forces the software cursor (auto-detected on
kmsdrm/offscreen, set anyway); `POPLIB_ONSCREEN_KEYBOARD` (presence-only) enables the engine's
built-in OSK, so no OmniOSK is needed. Saves go to `XDG_CONFIG_HOME` used as-is (no app subfolder),
pointed at `$GAMEDIR/conf`. Audio is OpenAL directly (`SDL_AUDIODRIVER` is a no-op); set
`ALSOFT_DRIVERS="${ALSOFT_DRIVERS:-alsa}"` and `ALSOFT_CONF="$GAMEDIR/alsoft.conf"` (a bundled
`alsoft.conf` on no search path does nothing). Build with `-DPOPLIB_WITH_BASS=OFF`: BASS
auto-enables because `libbass.so` sits in the repo, and it's closed-source and opens its own audio
device. OpenAL Soft's `alc.cpp` needs C++20 `<ranges>`, so build with gcc-12 (§3.1). The repo's
own `copy-assets.sh`/`verify-assets.py`/`properties/resources.xml` are the source of truth for the
missing-assets check (GOG copies have 65 case mismatches, handled by `--fix-case`). Its Python
fixup scripts assumed CRLF (`wrap_win32()` hardcoded `\r\n`; byte literals with embedded `\r\n`
defeated the fallback) and called `python` (only `python3` exists: put a `python` shim on `PATH`).

### 1.7.13 Launch-script messages — `pm_message` / `pm_show_error` (portmsg)

PortMaster's own `pm_message`/`pm_show_error` (in `funcs.txt`) draw **portmsg** cards since
PortMaster-GUI PR #349 (merged): a native SDL2 binary, software renderer only (no GL, works
whatever the game's graphics stack is), anti-aliased text, `NEEDED` only SDL2/libm/libc. Every
player-facing message in a new port uses them, **message first, options after**:

```bash
pm_message    "MESSAGE" [--title TITLE] [--type error|warning|info] [--timeout SECONDS]
pm_show_error "MESSAGE" [--title TITLE] [--type error|warning|info] [--timeout SECONDS]
```

- **Never put options before the message.** An older PortMaster's functions only read `$1`: with
  the message first, the player still sees the text (in pugwash, options ignored — confirmed on
  device); with options first, they see `--title`.
- **Don't ship `portmsg.aarch64` or its licenses** in a port; it lives in PortMaster's folder.
  Ports that call `./portmsg.${DEVICE_ARCH}` directly still work; switch them when touched.
- `--title` adds a coloured badge, bold title and divider. `--type` defaults to `info` for
  `pm_message` and `error` for `pm_show_error`. `--timeout N` shows a countdown and closes the
  card. `\n` breaks a line, `\n\n` starts a paragraph; long text wraps and scrolls (D-pad, sticks,
  L1/R1). Characters: Basic Latin, Latin-1, Latin Extended-A, general punctuation, arrows, €, ™
  (anything else renders as `?`).
- **`pm_message`** runs in the background (the script carries on, e.g. during `tar`). By default
  it has no close button and ignores buttons; it stays until the next `pm_message`/
  `pm_show_error`, until `pm_platform_helper` (called just before the game starts), or until the
  script ends (then it stays 3 s and closes). Each call replaces the previous card. With
  `--timeout` it closes itself. Don't pass `--wait` yourself; the function already does.
- **`pm_show_error`** runs in the foreground and blocks until the player closes it (A, B, Start or
  Select, on *release* of a press that started on that card, ignoring the first 300 ms), or the
  timeout runs out; with no controller detected it closes itself after 20 s. It closes any
  `pm_message` card first. No `sleep` needed after it.
- **Every runtime pattern must call `pm_platform_helper` before the game**, or a "please wait"
  card stays on screen over the game until the script ends.
- Exit status is 0 (2 if no display could be opened); the text appears twice in `log.txt` (once
  from the function's `echo`, once from portmsg's stderr with the title). `PORTMSG_DEBUG=1` logs
  startup timings. Card startup takes ~0.4-0.5 s, so messages less than ~0.5 s apart replace each
  other before they're drawn.
- On armhf/x86_64 (no portmsg binary yet) the functions fall back to pugwash; spruce overrides
  `pm_message` in its own `mod_spruce.txt`. Known open issue: on sudo CFWs (ArkOS/dArkOS, script
  runs as a normal user) closing a `pm_message` card uses plain `kill`, untested there — if a
  report mentions a message stuck over the game on those CFWs, suspect this first.
- **Older pugwash hang**: on a CFW build whose pugwash crashes at startup (seen on an AmberELEC
  prerelease whose SDL2_image couldn't load PNGs), the old `pm_message` path polled its done-pipe
  6000 × 0.3 s, a 30-minute hang. Not a port bug, but worth recognising.

Standard patterns:

```bash
# missing user-supplied files (blocking)
if [ ! -f "$GAMEDIR/gamedata/data.win" ]; then
  pm_show_error "Copy data.win from your copy of the game to ports/portname/gamedata/ and launch the game again." --title "Game files missing" --type warning
  exit 1
fi

# first-launch work: card stays up while the work runs, replaced or closed by the next call
pm_message "Extracting game data, this can take a few minutes..." --title "Please wait"

# short confirmation that doesn't block
pm_message "Settings reset." --title "Done" --timeout 3
```

The canonical extraction block with these messages is in §2.4.

### 1.7.14 box64 / box86 — x86 Linux binaries

Run `file` on the guest binary: `ELF 64-bit ... x86-64` → **box64**; `ELF 32-bit ... Intel
80386` → **box86** (or box64's BOX32 mode, but see below). Both are bundled port payload, not
PortMaster runtimes (`port.json` `"runtime": []` unless Westonpack is also used).

**box64 mechanism** (from a merged box64 port, World of Goo, and real-device rounds on
RG351V/AmberELEC and RP5/ROCKNIX):
- Ship a prebuilt aarch64 `box64` in the port (`$GAMEDIR/box64/box64`) and call it by full path,
  never a system or `PATH` copy: `$GAMEDIR/box64/box64 gamedata/<binary>`.
- **Two separate library paths, never mixed**: `LD_LIBRARY_PATH` is the host (aarch64) side —
  box64 itself and other native tools; `BOX64_LD_LIBRARY_PATH` is the guest (x86_64) side, box64's
  own variable that never reaches the real linker. Keep the folders strictly split (e.g.
  `box64/native/` aarch64, `box64/x64/` x86_64). Check what box64 itself needs with `readelf -d`
  (just libc/libm/libresolv/ld-linux) before adding system paths.
- **box64 renames its own process to the guest binary** (`[BOX64] Rename process to "<guest>"`),
  so gptokeyb2's kill target is the guest binary's name (15-character `comm` rule applies, §1.8.2).
  `westonwrap.sh cleanup` doesn't find it under that name; kill by PID if needed.
- **`SDL_GAMECONTROLLERCONFIG` is still needed** even for an SDL 1.2 guest: gptokeyb2 reads the
  controller with its own real SDL2. Check every env var against every process the script runs.
- **Debug vars: leave unset, and don't ship them commented out either.** For a real-device
  troubleshooting pass: `BOX64_LOG` (what loaded, wrapped vs emulated), `BOX64_SHOWSEGV`/
  `BOX64_SHOWBT` (register dump/backtrace; silence plus an exit means a clean `exit()`, not a
  lost-output crash), `BOX64_DLSYM_ERROR` (unresolved symbols), `BOX64_PREFER_EMULATED` (emulate a
  library instead of using box64's wrapper, when a wrapper misbehaves); the `BOX64_TRACE_*`/
  `BOX64_DYNAREC_LOG` tier only once the others point at where. No dynarec tuning
  (`BOX64_DYNAREC_BIGBLOCK`/`SAFEFLAGS`/`STRONGMEM`) by default. Verify any var name in box64's
  `src/include/env.h`, not from a copied list. (A merged box86 port shipped `BOX86_LOG=1`/
  `DLSYM_ERROR`/`SHOWSEGV`/`SHOWBT` permanently on: don't copy it.)
- **GL override is `BOX64_LIBGL`** (default `libGL.so.1` via the host search path).
  `SDL_VIDEO_GL_DRIVER` only matters for an SDL2 guest that calls `SDL_GL_LoadLibrary`; an SDL 1.2
  guest or one with `libGL.so.1` as a direct `NEEDED` never reads it.
- **Wrapped libraries still need a real host `.so`.** box64 substitutes native implementations
  for many libraries (`src/wrapped/`: SDL 1/2/3 + image/mixer/ttf/net, GL/GLU/GLX/EGL, X11 and
  several extensions, ALSA, ...), but its loader still `dlopen`s each `NEEDED` entry at load time,
  so a matching aarch64 library must exist on the device or in the port. For X11 libraries a
  `.so` is necessary but not sufficient: a real display is needed for anything beyond loading. A
  guest's "can't open X display, continuing anyway" proves only that *that* call site tolerates
  it.
- Build, generic first (the named SoC profiles don't match RK3566 — `RK3326` is a Cortex-A35):
  ```bash
  git clone https://github.com/ptitseb/box64
  cd box64 && mkdir build && cd build
  cmake .. -DARM64=1 -DCMAKE_BUILD_TYPE=RelWithDebInfo
  make -j$(nproc)
  ```
  `-DBAD_SIGNAL=ON` (for Android-derived kernels) only after real-device evidence. Prebuilt
  `box64-generic-arm` debs exist (Pi-Apps-Coders repo), also generic-only. One huge generated
  source file takes 10+ minutes under QEMU; that's normal.

**Does the guest really need a real X server? Decide by evidence before reaching for Westonpack:**
1. Bundle a real host `.so` for every missing `NEEDED` entry first, no Westonpack.
2. `readelf -d` the *bundled* libraries too, to catch transitive needs before device rounds.
3. Watch for a distro library that is architecturally incompatible, not just bloated: a GLU
   linked against GLVND (`libOpenGL.so.0`/`libGLdispatch.so.0`) can never work with gl4es's
   classic `libGL.so.1`; rebuild it from source with the classic-GL option (e.g. meson
   `gl_provider`).
4. A graceful "continuing anyway" message isn't proof X isn't needed later.
5. If a working reference platform exists (the same binary on desktop Linux with real X11), diff
   the two logs; a message from a GUI alert widget (`libXt`) that only appears there is strong
   evidence of a real `Display*` requirement.
6. Only then use Westonpack: `drm gl kiosk system` gives a real `Display*` while keeping the
   port's own gl4es on `LD_LIBRARY_PATH`; if the guest's GL goes through real **GLX** ("GLX
   extension missing" once a display exists), use `crusty_glx_gl4es` instead.
7. What one CFW provides varies: a library resolved on one CFW (e.g. via its `sdl12-compat`) can be
   absent on another. Verify per CFW tested.

**Fetching one foreign-arch library without touching the chroot's dpkg/apt state**:
```bash
curl -sL http://archive.ubuntu.com/ubuntu/dists/<release>-updates/main/binary-<arch>/Packages.gz -o Packages.gz
gunzip -f Packages.gz
grep -A20 '^Package: <pkgname>$' Packages       # -> Filename:, MD5sum:, Version:
curl -sL "http://archive.ubuntu.com/ubuntu/<Filename>" -o pkg.deb
echo "<md5sum>  pkg.deb" | md5sum -c -
ar x pkg.deb && tar xf data.tar.zst              # or .xz/.gz
```
Use `dists/<release>/<component>/source/Sources.gz` for source packages; check both `main` and
`universe`. Use `dpkg --add-architecture` only once many interdependent libraries are needed.

**Trimming a bloated or wrong distro library** (e.g. a distro SDL_mixer 1.2 pulling in
fluidsynth/glib/jack/systemd/an ASCII-art library/a whole Wayland stack for a game that only needs
WAV/OGG): rebuild from source with `./configure --help`/`meson_options.txt` options disabling
what isn't plausibly needed, and verify the result with `readelf -d`. A 2009-era tarball's
`config.guess`/`config.sub` don't know aarch64: replace both with current copies (e.g. from
`/usr/share/misc/` or `/usr/share/automake-1.16/`). SDL 1.2.15's `SDL_x11sym.h` declares
`_XData32` with `long*` where a modern `Xlibint.h` has `const long*` (hard "conflicting types"
error): patch the constness.

**BOX32 (box64 `-DBOX32=ON`) cannot create a GL/EGL context on libmali devices.** BOX32 reserves
the whole address space above 4 GB (`BOX64_RESERVE_HIGH`), so every native allocation including
libmali's lands below 4 GB, and the kbase driver refuses GPU mappings there for a 64-bit process
(`mmap` on `/dev/mali0` returns `EINVAL`, retries `EPERM`; `eglInitialize: EGL_NOT_INITIALIZED`,
SDL2 `Can't load EGL/GL library on window creation`). Everything else (SDL1 wrapper, joystick,
OpenAL) worked; Panfrost (no kbase) is untested. A Postal 2 (UE2) port moved to box86 for this
reason. Build in a separate dir (`cmake .. -DARM64=1 -DBOX32=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo`);
the 32-bit wrapped list is `src/library_list_32.h`.

**`./`-prefixed or path-qualified `NEEDED`/`dlopen` names skip the wrapper** (box64 and box86
treat any name with `/` as "precise" and only try that emulated file). Old Loki/LGP-era binaries do
this (`NEEDED ./libSDL-1.2.so.0`, `dlopen("../../System/openal.so")`). Fix:
`BOX64_PREFER_WRAPPED=1` / `BOX86_PREFER_WRAPPED=1` as a prefix on the game command only.

**box86** (32-bit x86, first used on Postal 2):
- **box86 itself must be an armhf binary** even on an aarch64 device, and it needs a 32-bit armhf
  userspace there. Cross-compile it (no multiarch needed; `gcc-arm-linux-gnueabihf` brings its own
  armhf glibc under `/usr/arm-linux-gnueabihf`) with a toolchain file (`CMAKE_SYSTEM_PROCESSOR
  armv7l`, `arm-linux-gnueabihf-gcc/g++`, `CMAKE_FIND_ROOT_PATH /usr/arm-linux-gnueabihf`):
  `cmake .. -DARM64=1 -DCMAKE_TOOLCHAIN_FILE=armhf-toolchain.cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo`.
  Build gl4es and sdl12-compat for armhf with the same toolchain file. box86's RK3326 profile is
  called `GOA_CLONE` (not `RK3326`); there's no RK3566 profile. Debs: `box86-generic-arm:armhf`.
- Device side: AmberELEC ships a full armhf stack in `/usr/lib32` (SDL2, libmali, libdrm, OpenAL,
  `ld-linux-armhf.so.3`); `control.txt` only adds it on some CFWs, so add
  `/usr/lib32:/usr/lib/arm-linux-gnueabihf` to `LD_LIBRARY_PATH` for the box86 command yourself.
  `libgl_*.txt` uses `$DEVICE_ARCH` for the folder names, so set `DEVICE_ARCH=armhf` before
  sourcing it to get `gl4es.armhf`/`libs.armhf` while the CFW's own gl4es decision still runs.
- Guest side: `BOX86_LD_LIBRARY_PATH`, same split as box64 (`box86/native` vs `box86/x86`).
- box86 also renames its process to the guest (`prctl(PR_SET_NAME)`), so gptokeyb2 targets the
  game's binary name. **But** under ROCKNIX's sway the window's `app_id` is `box86` (the real
  executable), so `pm_platform_helper "$GAMEDIR/box86/box86"`.
- `port.json`: `"arch": ["armhf"]`, `"runtime": []`.
- **UE2 black screen**: Loki-era Unreal Engine 2 builds open a non-GL splash window, then replace
  it with the GL window; through sdl12-compat on KMSDRM the game kept running but the screen stayed
  black. `-nosplash` fixed it (`SDL12COMPAT_OPENGL_SCALING=0` didn't). Check other UE2-era binaries
  for a `nosplash` string and pass it from the start.
- ROCKNIX's `sway_fullscreen` retries only 5 × 1 s; a game that takes ~27 s to open its window
  under box86 is never matched, harmless when the game requests fullscreen itself. A window stuck
  small in a corner meant the UE2 ini still held another device's resolution: write
  `DISPLAY_WIDTH`/`DISPLAY_HEIGHT` into it before every launch.

### 1.7.15 Java Swing/AWT games (PortMaster JDK + Westonpack)

From the DiverCity port (a MicropolisJ fork), tested on RG351V/RG351P (AmberELEC), RP5 (ROCKNIX),
RGB30 (dArkOS). Plain Swing/AWT (no LWJGL/libGDX/OpenGL) draws through X11 with no GL, so it runs
under Westonpack `drm gl kiosk system` (Variant 1, including the `weston_prefix` block).

- **JVM**: mount PortMaster's Java runtime squashfs at `/tmp/javaruntime` the same way as Weston.
  Keys: `zulu11.48.21-ca-jdk11.0.11-linux` (JDK 11), `zulu17.54.21-ca-jre17.0.13-linux` (JRE 17).
  `port.json`: `"runtime": ["weston_pkg_0.2.squashfs", "zulu11.48.21-ca-jdk11.0.11-linux.squashfs"]`,
  `"arch": []`.
- **Kill target is `java`**: `$GPTOKEYB2 "java" -c ...` and `pm_platform_helper "$JAVA_HOME/bin/java"`.
- **Settings**: `-Djava.util.prefs.userRoot="$CONFDIR"` (lands in `conf/.java/.userPrefs/`), a
  per-process JVM flag: no `HOME` override, no bind mount.
- **westonwrap's cwd is `/tmp/weston`**, so `new File("graphics/splash.png")` fails
  (`IIOException: Can't read input file`); load from the classpath
  (`Foo.class.getResource("/splash.png")`) or absolute paths.
- **High-res**: `-Dsun.java2d.uiScale=$(( DISPLAY_HEIGHT / 480 ))`, minimum 1 (2 at 1080p, so a
  1080p screen behaves like 960x540).
- **ROCKNIX (sway + Xwayland, Weston bypassed)**: `_JAVA_AWT_WM_NONREPARENTING=1` is required
  (without it: an empty floating frame with the content drawn offset); harmless under Weston, so
  set it unconditionally on the app command line. ROCKNIX's fullscreen helper
  (`swaymsg '[app_id=java] fullscreen enable'`, 5 tries) never matches X11 windows (they have a
  `class`, not an `app_id`) and logs `No matching node`; harmless, sway tiles the window full
  screen anyway.
- **Keyboard focus lost after a modal dialog**: showing the main window *before* `dispose()` on a
  still-open modal dialog made sway focus a window Java rejected; when the dialog closed, Java
  never got a focus event, so no key events arrived (mouse still worked). Dispose the dialog
  first, then show the frame.

```bash
GAMEDIR=/$directory/ports/portname
java_runtime="zulu11.48.21-ca-jdk11.0.11-linux"
# ... log, CONFDIR, weston mount block and weston_prefix exactly as Variant 1 ...

export JAVA_HOME="/tmp/javaruntime"
$ESUDO mkdir -p "${JAVA_HOME}"
if [ ! -f "$controlfolder/libs/${java_runtime}.squashfs" ]; then
  if [ ! -f "$controlfolder/harbourmaster" ]; then
    pm_show_error "This port requires the latest PortMaster to run, please go to https://portmaster.games/ for more info." --title "PortMaster update needed"
    exit 1
  fi
  pm_message "Downloading the Java runtime, this can take a few minutes..." --title "Please wait"
  $ESUDO $controlfolder/harbourmaster --quiet --no-check runtime_check "${java_runtime}.squashfs"
fi
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
    $ESUDO umount "${JAVA_HOME}"
fi
$ESUDO mount "$controlfolder/libs/${java_runtime}.squashfs" "${JAVA_HOME}"

ui_scale=$(( ${DISPLAY_HEIGHT:-480} / 480 ))
[ "$ui_scale" -lt 1 ] && ui_scale=1

$GPTOKEYB2 "java" -c "$GAMEDIR/portname.ini" > /dev/null 2>&1 &
pm_platform_helper "$JAVA_HOME/bin/java"

$ESUDO env strace="$weston_prefix" CRUSTY_BLOCK_INPUT=1 LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH" \
$weston_dir/westonwrap.sh drm gl kiosk system \
_JAVA_AWT_WM_NONREPARENTING=1 JAVA_HOME="$JAVA_HOME" \
"$JAVA_HOME/bin/java" -Dsun.java2d.uiScale="$ui_scale" -Djava.util.prefs.userRoot="$CONFDIR" -jar "$GAMEDIR/game.jar"

$ESUDO $weston_dir/westonwrap.sh cleanup
if [[ "$PM_CAN_MOUNT" != "N" ]]; then
    $ESUDO umount "${weston_dir}"
    $ESUDO umount "${JAVA_HOME}"
fi
pm_finish
```

**Building** with a newer JDK and no `ant`: compile with `javac --release 11` so class files run on
the device's JDK 11 (`javap -v` should show `major version: 55`); replicate `build.xml` in a shell
script (old `source="1.6"` builds can't use a modern JDK's ant targets anyway). `native2ascii` is
gone since JDK 9 and unneeded (`ResourceBundle` reads `.properties` as UTF-8): copy `*.utf8`
string files to `.properties`. Compare the rebuilt jar with the shipped one (`unzip -Z1 | sort`)
and grep for every `getResource`/`getBundle` path before deciding a missing file matters.

**Modern-Java bugs**: `clip.start(); while (clip.isRunning()) Thread.yield(); clip.close();` plays
nothing on Java 11 with ALSA (`isRunning()` is still false right after `start()`); register a
`LineListener` that closes the clip on `LineEvent.Type.STOP` and drop the loop. To separate "Java
can't make sound" from game bugs, run a standalone class with the device's JVM that lists
`AudioSystem.getMixerInfo()` and plays one of the game's WAVs. Check an engine's sound enum before
blaming the port for a silent action (some are `null` upstream).

**Small screens**: 2014-era Swing layouts assume 800x600+, and Westonpack can't give a bigger
virtual desktop (`CRUSTY_RESOLUTION` only resizes Crusty's window), so fix it in the game: a
`SMALL = width < 800 || height < 600` switch, collapsible side panels, a `JScrollPane` for tool
palettes, scaled splash images *and* their click bounds, dialogs capped to the screen. Grep for
hardcoded pixel constants before changing a size. Measure with
`GraphicsEnvironment...getDefaultConfiguration().getBounds()` (user-space, already includes
`uiScale`), not `Toolkit.getScreenSize()`.

**Controls**: check the game's `InputMap` before binding (DiverCity's `ENTER` opens a cheat box,
so Start can't send Enter). gptokeyb2's `"+"` (Shift+`=`) didn't trigger a Swing `shift EQUALS`
zoom binding; `"numpad+"` did. Text entry for a `JFileChooser`: OmniOSK doesn't apply (it hooks
SDL2), so use gptokeyb2's own text-input state on Start + D-pad Down (§1.8.3). **Input debugging
without rebuilding**: a tiny `-javaagent` jar (`Premain-Class` in the manifest) whose `premain`
adds an `AWTEventListener` for `KEY_EVENT_MASK | FOCUS_EVENT_MASK | WINDOW_FOCUS_EVENT_MASK` and
prints each event plus `KeyboardFocusManager...getFocusOwner()`; comparing its `KEY_PRESSED` lines
with gptokeyb2's `PRESSED` lines separates "not sent" from "not received" from "wrong focus".
Remove it afterwards.

Other JVM ports on PortMaster's runtimes (Mindustry, Shattered Pixel Dungeon, Unciv) prove the
runtime path. A 1 GB device that silently dies mid-load under a JVM is usually the OOM killer
(`dmesg | grep -i oom`); cap the heap (`-Xmx192m` fixed a Westonpack Java port).

### 1.7.16 Allegro — Allegro 4 under Westonpack, Allegro 5 over SDL2

#### Allegro 4 (plain software-2D, no AllegroGL)

Allegro 4's Unix X11 driver (`GFX_XWINDOWS`) is exactly Westonpack's Xlib-no-GL mode:
`drm gl kiosk system` (Variant 1), no gl4es. Findings from two Allegro 4 ports (RG351V/AmberELEC,
RG CubeXX/Knulli, X55/ROCKNIX), cross-checked against a merged one:
- **Keyboard input needs both a from-source `liballeg.so.4.4` (4.4.3.1) and
  `set_gfx_mode(GFX_AUTODETECT_WINDOWED, ...)`**; with the Ubuntu runtime library or plain
  `GFX_AUTODETECT`, no key reaches `key[]` at all (all four combinations were tested on a device;
  only that one works). The distro `liballegro4-dev` headers/`allegro-config` are fine at compile
  time; ship the from-source runtime `.so`.
- **`_WINDOWED` doesn't fill the screen** (Weston reports `arbitrary resolutions: no`, and
  `CRUSTY_RESOLUTION` doesn't apply to `system` mode). Request the desktop size and scale inside
  the game, aspect-correct and centred:
  ```c
  int phys_w = 640, phys_h = 480;
  get_desktop_resolution(&phys_w, &phys_h);   /* after allegro_init(), before set_gfx_mode() */
  set_gfx_mode(GFX_AUTODETECT_WINDOWED, phys_w, phys_h, 0, 0);

  void present_screen(BITMAP *src)            /* src = the game's native-resolution bitmap */
  {
    int dst_w = phys_w, dst_h = dst_w * src->h / src->w, dst_x, dst_y;
    if (dst_h > phys_h) { dst_h = phys_h; dst_w = dst_h * src->w / src->h; }
    dst_x = (phys_w - dst_w) / 2;
    dst_y = (phys_h - dst_h) / 2;
    stretch_blit(src, screen, 0, 0, src->w, src->h, dst_x, dst_y, dst_w, dst_h);
  }
  ```
  Redirect every final `blit(..., screen, ...)` to the logical bitmap plus one `present_screen()`.
- **`packfile_password()` is global and sticky**: after loading encrypted datafiles, later
  unrelated reads (e.g. DIGMID's `patches.dat`) fail with "not found". Call
  `packfile_password(NULL)` right after the encrypted loads.
- **DIGMID needs a bundled `patches.dat`, found through `ULTRADIR`**: the search order is the
  `[sound] patches` config value, the executable's directory, `ALLEGRO`, then `ULTRADIR`, and the
  exe-directory lookup doesn't resolve inside Westonpack. Pass `ULTRADIR=$GAMEDIR` as a positional
  argument in the `westonwrap.sh` line. A full freepats-derived set is ~29MB.
- **`ALLEGRO_MODULES` is ignored when running as root** (`geteuid() != 0` check in
  `src/unix/umodules.c`), so no digital driver loads and `install_sound()` reports a misleading
  `Insufficient digital voices available`. Even the compiled-in module path
  (`strings liballeg.so.4.4 | grep -i modules`, e.g. `./lib/allegro/4.4.3`) didn't load reliably.
  Load the driver yourself before `install_sound()`; only `alleg-alsadigi.so` is needed for DIGMID
  (`MIDI_DIGMID` is in the core library), and no `modules.lst` or `lib/<ver>/` tree:
  ```c
  #include <dlfcn.h>
  #include "allegro/platform/alunix.h"   /* SYSTEM_XWINDOWS */
  void *alsadigi = dlopen("./alleg-alsadigi.so", RTLD_NOW);
  if (alsadigi) {
    void (*mod_init)(int) = dlsym(alsadigi, "_module_init");
    if (mod_init) mod_init(SYSTEM_XWINDOWS);
  }
  install_sound(DIGI_AUTODETECT, MIDI_AUTODETECT, NULL);
  ```
- **No sound on PipeWire/Pulse CFWs (Knulli) even with the module loaded**: westonwrap overrides
  `XDG_RUNTIME_DIR` for Weston's socket, so the ALSA plugin can't find the audio daemon's socket
  (`Host is down` on `"default"` when wrapped; `plughw:0,0` says `busy` because the daemon holds
  the hardware). Capture the real value before westonwrap and pass it positionally:
  `REAL_XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}` … `XDG_RUNTIME_DIR=$REAL_XDG_RUNTIME_DIR`.
  Don't hardcode a path (Knulli's socket is `/var/run/pipewire-0`). Diagnose with a standalone ALSA
  probe (`snd_pcm_open`/`snd_pcm_set_params`) run plain vs wrapped.
- **Constant crackling** (from the first menu sound, not load-related; seen on SM8250/ROCKNIX): set
  `alsa_numfrags = 4` and `alsa_fragsize = 2048` under `[sound]` in `allegro.cfg` (read from the
  game's directory); safe to ship everywhere; try 4096 next.
- **ROCKNIX Mali**: needs the `extra_wayland` preload from §1.7.5.
- **ROCKNIX Panfrost leak**: repeated scaled presents through Allegro 4's X11 driver grow `Shmem`
  without bound until the device runs out of RAM (1-2 fps within seconds); reproduced with a
  70-line `stretch_blit` loop with no game code, not fixable from the port. Precedented mitigation:
  detect Panfrost with the same `glxinfo` check westonwrap uses and refuse to launch:
  ```bash
  if [[ "$CFW_NAME" = "ROCKNIX" ]] && glxinfo 2>/dev/null | grep -q "OpenGL version string"; then
    pm_show_error "This port does not support the Panfrost graphics driver due to a ROCKNIX bug. Switch to libMali to play." --title "Panfrost not supported"
    exit 1
  fi
  ```
- Debugging: Allegro's `TRUE` is `-1` (a `-1` from `file_exists()` means found); check
  `install_sound()`'s return and print `allegro_error`; print `digi_driver->name` after success
  (empty = silently the dummy driver); call the lower-level pieces (`.detect()`,
  `al_findfirst()`) directly; read a `.so` with `objdump -d --disassemble=<fn>`, `readelf -S/-d`
  and `strings`. Ruled out: `CRUSTY_BLOCK_INPUT` isn't the cause of missing input; the voice
  ceilings (64) are never the real limit.

#### Allegro 5 over SDL2 + native GLES2 (`ALLEGRO_SDL`)

Used for Open Surge and ZQuestClassic (device-tested on muOS and ROCKNIX). Allegro 5's default
Linux backend is X11+GLX (desktop GL); its `ALLEGRO_SDL` backend (what Allegro's web builds use)
gives SDL2 windowing, gamepads through `SDL_GameController`, SDL audio, and native GLES2, so no
X11/gl4es/OpenAL:
```bash
cmake .. -DALLEGRO_SDL=ON -DGL_BUILD_TYPE=gles2+ -DWANT_X11=OFF -DWANT_OPENAL=OFF -DWANT_NATIVE_DIALOG=OFF
```
Trim codecs to what the data uses. `liballegro.so.5.2` then `NEED`s only `libSDL2-2.0.so.0` and
`libGLESv2.so.2`. The native dialog addon needs GTK and isn't built under `ALLEGRO_SDL`; stub
message boxes/file choosers in the game (a `WANT_NATIVE_DIALOG` option, or guards on whether the
`allegro_dialog` target exists). If the engine vendors its own static SDL2 for joysticks, skip it
(check `nm -D --defined-only` shows no `SDL_` symbols in any shipped binary) and give the engine's
target the system SDL2 include dir and `-lSDL2`. Pass the engine's own fullscreen flag (ZC:
`-fullscreen`, `ALLEGRO_FULLSCREEN_WINDOW`).
- **Textures go blank after a display resize (real Allegro SDL backend bug, upstream as of
  2026-10).** `sdl_acknowledge_resize()` re-uploads every non-memory bitmap from its memory
  backup, but the backup is only refreshed on flip (`al_backup_dirty_bitmaps()` in
  `sdl_flip_display()`), so every bitmap loaded since the last flip comes back blank. Symptom:
  random-looking invisible sprites/tiles (the set depends on load order), or a missing title logo
  on ROCKNIX, whose `pm_platform_helper` fullscreens the window via sway after creation. libpng and
  every GL call succeed. Fix in `src/sdl/sdl_display.c`: call `al_backup_dirty_bitmaps(display)`
  at the start of `sdl_acknowledge_resize()`. Confirmed with an `LD_PRELOAD` GL/libpng probe and
  `grim` screenshots. Red herrings ruled out: GPU memory, max texture size, depth buffer, shader
  precision, FBO read-lock attachments, texture-unit state, a loader thread.
- **Choppy audio**: Allegro's SDL audio driver hardcodes `want.samples = 4096` (~93 ms), longer
  than a typical engine stream (`kcm_stream.c ... _al_kcm_refill_stream Out of buffers` every
  ~93 ms in the log). Patch `addons/audio/sdl_audio.c` to read `[sdl] buffer_size` from Allegro's
  system config and ship `allegro5.cfg` (loaded from `SDL_GetBasePath()`) with `buffer_size = 1024`.
- Open Surge specifics: build with `-DGAME_RUNINPLACE=ON -DWANT_GLES=ON -DWANT_NATIVE_DIALOG=OFF
  -DWANT_PLAYMOD=OFF -DSURGESCRIPT_STATIC=ON` (run-in-place: data and `surge.prefs` next to the
  binary, no binds); SurgeScript needs `-DCMAKE_POLICY_VERSION_MINIMUM=3.5`; PhysFS **3.2.0** built
  and bundled (game zips with a top-level folder need `PHYSFS_setRoot`; CMake finds the system
  `/usr/include/physfs.h` first, so pass `-DPHYSFS_INCDIR`/`-DLPHYSFS` and rebuild clean, then check
  `nm -D opensurge | grep PHYSFS_setRoot`). No `.ini`: the game reads the pad natively, gptokeyb2
  runs kill-switch-only (`$GPTOKEYB2 "opensurge" &`). An exit screen's `Web.launchURL()` forked a
  browser and garbled the display; patched out. Third-party Open Surge games (`--game <folder|zip>`)
  are offered through gamepad-picker (§1.9).
- ZQuestClassic specifics (built from 3.0.0-prerelease; 2.55 needed ~1GB for large quests vs
  ~300-500MB on 3.0): source guarded by `__EMSCRIPTEN__` really meant "no GTK/dbus" and needed real
  feature guards (`HAS_NFD`, `HAS_NATIVE_DIALOG`); `-DCMAKE_DISABLE_FIND_PACKAGE_CURL=ON`,
  `-DCMAKE_DISABLE_FIND_PACKAGE_TBB=ON` (an installed `libtbb-dev` was silently picked up and added
  `libtbb.so.12`), `WANT_WEBSOCKETS=OFF` (else `libssl.so.3`/`libcrypto.so.3`); x86-only SSE/JIT
  code gated (3.0 has a NEON path and an ARM64 JIT; on 229 the JIT costs ~+20MB RSS, but one quest
  script needed ~7GB to compile on 226, so measure); `-fsigned-char` was a real build symptom
  (`narrowing conversion of '-1' from 'int' to 'char'`) and `-DWANT_ERROR_CHECKING=FALSE` silences
  a GCC 12 `-Warray-bounds` false positive; release data comes from the release tarball (git has
  LFS pointers). **Don't ship `gamecontrollerdb.txt` when the engine loads it**
  (`al_set_joystick_mappings()` would override the CFW's `SDL_GAMECONTROLLERCONFIG`). The engine's
  GUI already turns stick 0 (= D-pad under Allegro's mapping) into arrow keys, so mapping the
  D-pad in gptokeyb2 doubled every press in dialogs: don't map what the engine already maps.
  The hardware cursor plane is invisible on H700/muOS: a `[gui] software_cursor` option that draws
  the cursor before each flip (and hashes cursor position into the frame-skip signature so idle
  frames redraw). Mouse clicks in-game opened the system menu (`clicktofreeze`), so the shipped
  base config sets `clicktofreeze = 0`. Quest `.zip`s dropped in `quests/` are unpacked by the
  script with `unzip -qo`. MIDI: see §2.3 (Timidity layout).

### 1.7.17 Qt6 games — a shared `eglfs`/Wayland Qt6 runtime

No Qt runtime existed in the ecosystem; one was built (`qt6-eglfs-6.6.3`, GLES2/3, no desktop GL)
and proven with DustRacing2D across 8 devices, 3 GPU vendors and all 3 display architectures.
Build order: Qt6 qtbase+qttools, then qtwayland against that install, then OpenAL Soft, then the
game against the finished runtime.
```bash
git clone git://code.qt.io/qt/qt5.git qt6 && cd qt6 && git checkout 6.6
./init-repository --module-subset=qtbase,qttools
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/opt/qt6-eglfs -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_DISABLE_FIND_PACKAGE_Clang=ON \
  -DFEATURE_eglfs=ON -DFEATURE_kms=ON -DFEATURE_gbm=ON -DFEATURE_eglfs_egldevice=ON \
  -DFEATURE_linuxfb=ON -DFEATURE_libinput=ON -DFEATURE_xkbcommon=ON \
  -DFEATURE_opengl_desktop=OFF -DFEATURE_opengl_dynamic=OFF \
  -DFEATURE_opengles2=ON -DFEATURE_opengles3=ON \
  -DFEATURE_eglfs_x11=OFF -DFEATURE_egl_x11=OFF -DFEATURE_xkbcommon_x11=OFF \
  -DFEATURE_vulkan=OFF -DFEATURE_eglfs_mali=OFF \
  -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF
cmake --build . --parallel $(nproc) && cmake --install .
```
(`apt-get install libinput-dev` first; `--module-subset=default` clones far too much;
`-DCMAKE_DISABLE_FIND_PACKAGE_Clang=ON` avoids a broken partial clang CMake package breaking
`qdoc`.) **`eglfs_mali` is never built**: it links a specific vendor `libmali` at Qt build time.
**qtwayland** must be built standalone against the installed Qt (re-configuring the supermodule
build doesn't pick up a newly cloned module); bundle only the client side
(`plugins/platforms/libqwayland-egl.so`/`libqwayland-generic.so`,
`plugins/wayland-shell-integration/*`, `plugins/wayland-graphics-integration-client/*`,
`libQt6WaylandClient`, `libQt6WaylandEglClientHwIntegration`, `libQt6WlShellIntegration`), never
the compositor libs. **OpenAL Soft** from git HEAD with gcc-12 (C++20) and
`-DALSOFT_BACKEND_PIPEWIRE=ON -DALSOFT_BACKEND_PULSEAUDIO=ON -DALSOFT_BACKEND_ALSA=ON
-DALSOFT_BACKEND_OSS=ON -DALSOFT_BACKEND_SNDIO=ON -DALSOFT_UTILS=OFF -DALSOFT_EXAMPLES=OFF`: Ubuntu
22.04's `libopenal1` has no PipeWire/Pulse backend and is silent on a PipeWire-only device; those
backends `dlopen` their client libraries, so it's purely additive. Don't bundle `libpulse.so.0`
(its `libpulsecommon` hard-needs X11) or `libpipewire-0.3.so.0` (the device's own is
version-matched).

**Device integration, one auto-detecting script:**

| Device class | Example | Result |
|---|---|---|
| DRM/KMS | RG351V/AmberELEC, RGB30/dArkOS | `eglfs` auto-selects `eglfs_kms` |
| fbdev only, no `/dev/dri/card0` | RG40XXV/muOS, RGCubeXX/Knulli (H700) | `QT_QPA_EGLFS_INTEGRATION=none` |
| Wayland compositor running | X55/ROCKNIX (Panfrost and Libmali), RP5 (Adreno) | `QT_QPA_PLATFORM=wayland` (`eglfs_kms` would fight sway for DRM master) |

```bash
if [ -n "$WAYLAND_DISPLAY" ] || ls "${XDG_RUNTIME_DIR:-/tmp}"/wayland-* >/dev/null 2>&1; then
  export QT_QPA_PLATFORM=wayland
  export QT_WAYLAND_SHELL_INTEGRATION=xdg-shell
else
  export QT_QPA_PLATFORM=eglfs
  [ -e "/dev/dri/card0" ] || export QT_QPA_EGLFS_INTEGRATION=none
fi
```
`none` is Qt's documented generic fallback (plain `EGL_DEFAULT_DISPLAY`, the vendor driver handles
fbdev itself); auto-detection never falls through to it (it tries `eglfs_kms`, then the
emulator-only `eglfs_emu`, and aborts), which looks like "H700 unsupported" but isn't.
**fbdev-only devices need bundled XKB data**: with no `/usr/share/X11/xkb`, libxkbcommon logs
`Failed to create xkb context` and every synthesized key event is silently dropped (only the
kill-switch combo works). Bundle `xkb-data` (~4MB) and set `XKB_CONFIG_ROOT`.

**Runtime bundling**: bundle liberally once a device proves something missing (a shared runtime
favours compatibility; `libinput`, `libsystemd`, `libmtdev` were genuinely missing and safe), except
GPU/display-stack libraries (§1.1). Scan `readelf -d` recursively over the whole runtime tree
including lazily `dlopen`ed plugins (a plugin hid a `libmtdev.so.1` need for several rounds), with
`find ... -type f -o -type l` (Qt's SONAME links are symlinks). Building and submitting the
squashfs itself: §2.6.

**GLES bugs that only appeared under eglfs/GLES2** (DustRacing2D, a checklist for any desktop-Qt
game): `glHint(GL_PERSPECTIVE_CORRECTION_HINT, ...)` outside the GLES guard (doesn't exist in
GLES2); `format.setVersion(1, 0)` requesting an ES1 context for GLSL ES 100 shaders (use `(2, 0)`);
`uniform vec4 scale = vec4(1, 1, 1, 1);` initializers rejected by Mali (`S0052`; strip with
`sed -E 's/(uniform[^=]+) = [^;]+;/\1;/'`); **eglfs has no window manager, so `showFullScreen()`
can run the whole expose → initialize → `emit initialized()` chain synchronously inside the
constructor**, before a later `connect()` — move window creation to the end of the constructor;
and after stripping uniform initializers, a uniform nothing sets defaults to 0 (`fade` → a black
screen with zero GL errors): set it explicitly after creating each shader.
`-DDisableFramebufferBlits=ON` for DustRacing2D. Performance findings are in §2.5.

### 1.7.18 OHRRPGCE (FreeBASIC + SCons)

`scons gfx=sdl2` hard-links `libX11.so.6`, `libXinerama.so.1`, `libXext.so.6`, `libXpm.so.4`,
`libXrandr.so.2`, `libXrender.so.1` (the SConscript sets `X11 = True` for any Unix gfx backend
except `console`/`minos`, and `gfx_sdl2.bas` calls OHRRPGCE's own `set_X11_error_handlers()`).
Both X11 uses under `gfx=sdl2` are droppable on a KMS/DRM device: a desktop-X11 error-handler
safety net, and a cosmetic xfce4 fullscreen-flicker workaround (`#IFDEF USE_X11`);
`os_get_screen_size()` already has a non-X11 branch. Add a `no_x11` SCons argument that reuses the
existing `NO_X11` machinery:
```python
no_x11 = int(ARGUMENTS.get('no_x11', '0'))
...
    X11 = True
    if gfx == ['console'] or minos or no_x11:
        X11 = False
        commonenv['FBFLAGS'] += ['-d', 'NO_X11']
        commonenv['CFLAGS'] += ['-DNO_X11']
    else:
        common_modules += ['lib/x11_printerror.c']
```
```bash
scons gfx=sdl2 no_x11=1 -j$(nproc) ohrrpgce-game
```
Verify with `readelf -d`/`nm -D` (no X `NEEDED`, no undefined `X*`). Doesn't apply to `gfx=fb`,
which has real X11 dependencies.

### 1.7.19 Free Pascal games (OpenSoldat)

From the OpenSoldat port (FPC + CMake + SDL2 + GameNetworkingSockets), working on RG351V/AmberELEC:
- FPC 3.2.2 from the distro is a native aarch64 compiler (upstream's "requires 3.0.4" is stale).
  The project's own CMake needed an aarch64 option (`CROSS_LINUX_ARM64` → `-Tlinux -Paarch64`).
  With CMake 4.x, `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` for vendored libs declaring an older
  minimum. Set `-DCMAKE_BUILD_TYPE=Release` explicitly (the default was an accidental Debug build).
- GameNetworkingSockets is unconditional (`BUILD_GNS=ON`, `BUILD_STEAM=OFF`; `BUILD_GNS=OFF` leaves
  a dangling link target); needs `protobuf-compiler`/`libprotobuf-dev`.
- **aarch64 source patches**: extend existing non-x86 guards. PascalScript's `uPSRuntime.pas`
  x86 inline-asm trampoline needs `or defined(cpuaarch64)` in its `empty_methods_handler` guard
  (else `Error: (7053) Unrecognized opcode push`/`Unknown identifier "EDX"`); `Set8087CW` (x87 FPU)
  must be excluded with `{$if not (defined(CPUARM) or defined(CPUAARCH64))}` (else `Identifier not
  found "Set8087CW"`). FPC defines `CPUAARCH64` (and `CPU64`), **not** `CPUARM64`.
- **Dead X11 dependency from Pascal binding units**: `sdl2.pas` and `dglOpenGL.pas`
  unconditionally `uses X, XLib(, XUtil)` on Linux (for unused `SDL_SysWMinfo`/GLX declarations),
  and FPC's smart-linking still links a used unit's whole `external` import table, so the binary
  `NEEDED` `libX11.so.6` (`error while loading shared libraries: libX11.so.6` on device). Don't
  bundle the six-library X11 chain (rejected in review: "why are we bundling X11 on a device that
  does not need or have X11"): shadow the RTL units with local stand-ins
  (`3rdparty/x11-stub/{x,xlib,xutil}.pas`) defining only the referenced types (`TXID`,
  `PDisplay`/`PXVisualInfo`, `TXEvent` as `PtrUInt`/`Pointer`/an opaque record) with no
  `external`/`{$linklib}`, and put `-Fu<stub dir>` first in the unit search path. Find the needed
  type names by an iterative compile-and-fix loop.
- **GL**: the game parsed `glGetString(GL_VERSION)` as desktop `"<major>.<minor>"` and crashed on
  `EConvertError: "OpenGL ES 3" is an invalid integer` (skip leading non-digits). Its shaders used
  GLSL-ES-compatible syntax but `#version 120`: `#version 100` + `precision mediump float;` in the
  fragment shader.
- **Real missing libraries on RG351V/AmberELEC**: `libprotobuf.so.23`, `libcrypto.so.3`, a newer
  `libstdc++.so.6` (GNS's own dependencies), and `libsndio.so.7` + `libbsd.so.0` + `libmd.so.0`
  (the distro OpenAL Soft hard-links its sndio backend; the alternative is rebuilding OpenAL Soft
  without sndio). `libphysfs.so.1`/`libopenal.so.1` bundled too.
- **The game never connected**: `StartGame()` doesn't connect and the GUI was removed upstream
  (moved to a separate Electron launcher), so a fresh launch silently exited. The client takes
  console commands on its command line: `-connect 127.0.0.1 23073`. The launch script starts the
  bundled dedicated server first and polls its log for `is listening` (up to 20 s, every 0.5 s)
  instead of a fixed `sleep`. The server refused to run as root; a `-allowroot` flag was added
  (upstream had a TODO for it). `-fs_userpath "$GAMEDIR/conf/"` redirects all user data (a
  native cvar, no bind mounts). Bots only spawn in team game modes.
- **Proving presentation over SSH**: `strace -tt` on the client and count
  `DRM_IOCTL_MODE_PAGE_FLIP|SETCRTC|ATOMIC` — a count of 1 over 30 s means one modeset and nothing
  presented; a climbing count means real frames.
- `soldat.smod` is a 105MB single PhysFS archive (no content split possible): byte-split it with
  `split -b` and `cat` it back together at first launch if it must live in a git repo (§2.6).
- Controls: a mouse-aim dual-stick shooter (no gamepad code), so the `.ini` follows dual-stick
  conventions (fire on a trigger, right stick = mouse aim, `x = mouse_slow`) and maps onto the
  game's existing default keys (from its separate data repo), changing no game config.

### 1.7.20 Python 2 + pygame games

From Project Alexandria (Python 2, pygame, ODE physics via pyode, the old `Numeric` library), the
first Python port. **Build the original Python 2 stack from source rather than migrating the game
to Python 3**: pyode 1.2.0 with its contemporary ODE 0.7 has zero physics-API drift, where a
Python 3 migration also meant adapting to a newer ODE. Build order and traps:
1. **ODE 0.7**: replace the 2006 `config.guess`/`config.sub` (`cp /usr/share/automake-1.16/config.guess
   /usr/share/automake-1.16/config.sub .`); libtool builds both `.a` and `.so`.
2. **pyode**: `python2 setup.py build_ext --include-dirs=<ode>/include --library-dirs=<ode>/lib`
   (ships pre-generated Pyrex C, no Pyrex/Cython needed).
3. **Numeric**: delete the stale `gettimeofday` forward declaration in `Packages/RNG/Src/ranf.c`
   (`conflicting types for 'gettimeofday'` against modern glibc).
4. **numpy 1.16.6** (last Python 2 release), no BLAS/LAPACK; its x86 SIMD header probes
   (`xmmintrin.h`, AVX) fail harmlessly on aarch64.
5. **pygame**: install `python-setuptools` and `libportmidi-dev` first (pygame's `-auto` flag
   doesn't actually suppress its dependency prompt). `setup.py build` doesn't copy
   `freesansbold.ttf` and the icon files into `site-packages/pygame/`; copy them by hand, or
   `pygame.font.Font('freesansbold.ttf', ...)` fails with `IOError` on the device.
6. SDL 1.2 add-ons, built against real SDL 1.2 (§1.1) and shipped next to the sdl12-compat shim:
   **SDL_image 1.2.12** PNG-only (`--disable-bmp --disable-gif --disable-jpg ... --enable-png`),
   **SDL_ttf 2.0.11** with a `freetype-config` shim on `PATH`
   (`printf '#!/bin/sh\nexec pkg-config freetype2 "$@"\n'`), both with the `config.guess` swap.
7. **The interpreter**: the system `python2.7` binary doesn't link `libpython2.7.so`, so bundle the
   binary, the stdlib tree and a `site-packages/`, with `PYTHONHOME`/`PYTHONPATH` set explicitly.
   **Rename the interpreter to something short and unique** and use that exact name for the
   gptokeyb2 kill target, `pm_platform_helper` and the exec line: the running process is the
   interpreter, not the port's name, so `$GPTOKEYB2 "portname"` silently never kills anything.

Game-side fixes: modern pygame's `pygame.surfarray` imports numpy unconditionally (despite its
docstring claiming Numeric support), so a Numeric-era game needs **both** libraries; change
`.typecode()` to `.dtype` only on arrays that came from `surfarray`, not the game's own Numeric
math. Modern `pygame.draw.*` raises `TypeError` on a float width/radius (wrap computed values in
`int()`). Under sdl12-compat, `pygame.Surface((0, 0))` has NULL pixels and blitting it raises
`SDL_UpperBlit: passed a surface with NULL pixels`; grep for every `Surface((0, 0))` and use
`(1, 1)`. Pass `pygame.FULLSCREEN` to every `set_mode` call (two in this game; one stayed windowed
on RP5/ROCKNIX). A stick used only as a D-pad needs `deadzone_x`/`deadzone_y = 8000` (§1.8.1).
**A wholesale stdlib copy carries symlinks** (`sitecustomize.py` → `/etc/...`,
`config-*/libpython2.7.so` → a relative path, `dist-packages/*.py` → `share/pyshared`); BusyBox
`tar` failed on the relative one (`tar: can't create symlink`). Resolve or delete each (Debian's
`site.py` really does put `dist-packages` on `sys.path`, so resolve rather than delete that one),
and check the whole package with `find -type l` (§2.6). Headless repro of a crash in the chroot
(`SDL_VIDEODRIVER=dummy`) is for forensics only and needs the user's OK first (§2.5).

## 1.8 The control-mapping file

### 1.8.1 gptokeyb2 `.ini` — the format to use for every new port

Two section types: `[config]` (global settings, read once) and `[controls]`/`[controls:name]`
(button bindings — `[controls]` is the default/root state, additional named states are
`[controls:hotkey]` etc. for layered input, see §1.8.3). `#` comments are safe to use in `.ini`
files (confirmed throughout real shipped configs) — unlike classic `.gptk`, where comment support
was never confirmed.

**`[config]` fields** (real clamped ranges from source):
```ini
[config]
repeat_delay        = 500     # ms, clamped 16-3000
repeat_rate         = 60      # ms, clamped 16-3000
mouse_slow_scale    = 50      # 1-100, default 50 — how much mouse_slow/R-analog-slow scales speed
deadzone_mode       = axial | scaled_radial
deadzone_scale      = 8       # 1-32768 — real ports use 6-18
mouse_scale         = 512     # LITERAL ALIAS for deadzone_scale, same field — don't set both expecting two effects
deadzone            = 2000    # sets BOTH deadzone_x and deadzone_y at once, 500-32768 (built-in default 1000)
deadzone_x          = 2000    # X-axis only, 500-32768
deadzone_y          = 2000    # Y-axis only, 500-32768
deadzone_triggers   = 3000    # L2/R2 analog trigger deadzone, 500-32768
mouse_delay         = 16      # ms, clamped 16-3000
dpad_mouse_normalize = true   # normalizes diagonal d-pad-as-mouse speed
dpad_mouse_step     = 5       # 1-100: D-pad-as-mouse pixels per tick — NEW (upstream PR #19), ignored by the shipped binary
mouse_wheel_amount  = 1       # set inside [controls]/[controls:x] blocks, not [config]; >1 only works on post-PR-#20 binaries

# Absolute-mouse-mode tuning (only relevant if a control uses absolute_mouse_movement):
absolute_center_x, absolute_center_y, absolute_step, absolute_deadzone,
absolute_rotate, absolute_screen_width, absolute_screen_height

# Custom charset/wordset registration (built-ins listed below need no registration):
charset = "hex" "0123456789abcdef"
wordset = "level_select" "01" "02" "03" ... "10"
```
**Confirmed**: `mouse_scale` writes `current_state.deadzone_scale` directly in `config.c` — it is a
pure alias, not a separate curve-shaping vs. movement-divisor pair the way classic gptokeyb had
(see §1.8.5). Setting both just means "last one wins." Built-in charsets need no registration:
`basic` (A-Z, space, `.,-_()`, digits), `extended` (`basic` + lowercase a-z), `full` (`extended` +
symbols), `digits`, `hex`, `alpha` (defined in `input.c`). `[config:name]` sections only match a
**game-name prefix**; the format has no resolution or device conditionals (do per-device tuning
with `sed` in the launch script, below).

**Two different deadzones, two different jobs** (both confirmed on real devices):
- **Stick-as-keys** (`left_analog_up = "up"` etc., or `left_analog = arrow_keys`): the key-press
  threshold is `deadzone`/`deadzone_x`/`deadzone_y`, default only **1000** of 32768 (~3%,
  `src/state.c`), checked with no hysteresis. A stick springing back crosses the opposite threshold
  ("hit up and it goes back down", Powermanga), and a resting stick's offset can hold a key
  permanently (perma-crouch at a resting offset of ~1030, TSC; non-stop spinning, TowerJumper;
  menu auto-scroll on a Miniloong Pocket One). **Every `.ini` that maps a stick to keys sets
  `deadzone = 12000` (or `deadzone_x`/`deadzone_y = 8000`; up to 16000 seen) in `[config]`.**
  `deadzone_mode`/`deadzone_scale` do nothing for this; don't copy them from a mouse `.ini`
  expecting them to.
- **Stick-as-mouse** (`left_analog = mouse_movement`): `deadzone_mode`/`deadzone_scale`/
  `deadzone_x`/`deadzone_y` shape the cursor; the standard block below fixes resting-stick
  cursor drift (confirmed on RP5/ROCKNIX with a DualSense).
- `dpad_mouse_step` (D-pad-driven mouse speed) is hardcoded to 5 in the binary PortMaster ships
  today and `deadzone_scale` doesn't affect it, so a D-pad-only mouse (~300 px/s) can't be tuned
  until the PR-#19 binary ships. Old binaries ignore the key, so it's safe to put in an `.ini`.

**`[controls]` / `[controls:name]` button syntax**: button names are
`a b x y l1 l2 l3 r1 r2 r3 start back guide up down left right dpad left_analog right_analog
left_analog_up/down/left/right right_analog_up/down/left/right`. A field left blank (`y =`) or
omitted entirely is genuinely inert here — gptokeyb2's config structs start fully zeroed
(`gptk_malloc()` is `malloc()`+`memset(0)`), so there is **no** compiled-in default keymap to leak
through, unlike classic gptokeyb (§1.8.5). Values:
- A key name, quoted or unquoted: `a = "mouse_left"` or `a = mouse_left` — both forms are used in
  real shipped configs, quoting is cosmetic.
- `mouse_left` / `mouse_right` / `mouse_middle` / `mouse_slow` (holds to halve cursor speed for
  precision). `mouse_middle` was silently dropped by the shipped binary (the uinput mouse never
  advertised `BTN_MIDDLE`), fixed upstream in PR #18 but not yet shipped.
- Key names come from gptokeyb2's own table (`keys.c`), not the game's naming: `"enter"` (there
  is no `"return"`), `"numpad+"` etc. A typo or unknown name is silently ignored on the shipped
  binary (only the unreleased `-D config` debug output reports unknown keys).
- `dpad = mouse_movement` / `left_analog = mouse_movement` / `right_analog = mouse_movement` —
  shorthand binding all 4 directions of that input source to mouse movement at once. **This
  whole-stick form is the only stick-to-mouse form gptokeyb2 has**: the per-direction
  `left_analog_up = mouse_movement_up` (classic `.gptk` syntax) prints `warning: unknown key
  "mouse_movement_up" in binding` and is dropped, so the stick can't move the cursor at all
  (confirmed on RG351V).
- `right_analog = arrow_keys repeat` — binds all 4 directions to arrow keys with auto-repeat.
- `left_analog = absolute_mouse_movement` — moves the mouse to an absolute screen position based
  on stick deflection (uses the `absolute_*` config fields), instead of relative movement.
- A key plus a modifier token, space-separated: `l2 = f1 add_ctrl` (holds Ctrl while sending F1).
- State-machine verbs: `hold_state <name>` (switch to state `<name>` while held, revert on
  release), `push_state <name>` (switch and push current state onto a stack, for toggle-style
  layers), `pop_state` (pop back to the pushed state). `overlay = clear | parent | controls`
  controls how a named state's bindings relate to another's: `clear` starts with zero inherited
  bindings, `parent` inherits from whatever pushed/held into this state, `controls` inherits from
  the root `[controls]` state.
- Text-entry verbs inside a `text_input`-style state: `prev_letter`, `next_letter`,
  `prev_letter10`/`next_letter10` (jump 10), `add_letter`, `remove_letter`/`"backspace"`,
  `finish_text` (sends Enter), `cancel_text` (backspaces everything typed), `prev_word`,
  `next_word`.
- **`[controls:analog_0]`** (described in gptokeyb2's README for stickless devices) is **not
  implemented in the source**. For a device without sticks, branch in the launch script on
  `$ANALOG_STICKS` (exported by `device_info.txt`) and `sed` the `.ini`, e.g. to put a
  `hold_state dpad_mouse` on R2 only when `ANALOG_STICKS` is 0.

**Two real worked templates**, based directly on shipped ports:

Safe default (no mouse, digit/menu-driven game — shaped like gptokeyb2's own `test.gptk.ini`,
with the stick-as-keys deadzone raised per the rule above):
```ini
[config]
deadzone_triggers = 3000
deadzone = 12000

[controls]
a =
b =
x =
y =

l1 =
l2 =
r1 =
r2 =

start = "enter"
back = "esc"

up = "up"
down = "down"
left = "left"
right = "right"

left_analog =
right_analog = arrow_keys repeat
```

**Mouse emulation — the standard every mouse-driven port ships from the first draft**
*(project convention, proven on this project's devices)* (not after
a drift or speed report; reviewers have had to ask for these on several ports). Three parts:
1. this exact `[config]` block (from `glob2`, proven on real hardware; same values as
   `amuletsarmor.ini`);
2. **a high-resolution speed bump in the launch script**, right before the `$GPTOKEYB2` line
   (the `.ini` has no resolution conditionals):
   ```bash
   if [ "${DISPLAY_WIDTH:-640}" -gt 1280 ]; then
     sed -i "s/^deadzone_scale = .*/deadzone_scale = 18/" "$GAMEDIR/portname.ini"
   fi
   ```
3. **buttons: `a = mouse_left`, `b = mouse_right`, `x = mouse_slow`.** If the game already uses A
   natively, left click goes on `r1` (move a native R1 action elsewhere if needed); if X is taken,
   no slow mouse at all. Never put clicks on L2/R2, never slow on L3, never `mouse_slow` on R1 even
   though gptokeyb2's own advanced-usage example does. Mouse-only menus (hover/click regions, no
   item order) get stick-mouse from the first draft; don't write a "D-pad navigates the click
   regions" patch (tried on one port, each iteration broke another screen).

```ini
[config]
mouse_delay = 16
deadzone_mode = scaled_radial
deadzone_scale = 6
deadzone_x = 2000
deadzone_y = 2000

[controls]
a = "mouse_left"
b = "mouse_right"
x = mouse_slow
y = "leftctrl"

l1 = "leftshift"
l2 = "f12"
r1 = "space"
r2 = "e"

start = "enter"
back = "esc"
guide =

up = "w"
down = "s"
left = "a"
right = "d"

left_analog = mouse_movement
right_analog =
```
This is genuinely simpler than the classic-`.gptk` mouse template used to be — no inert-placeholder
trick needed at all, since blank fields are safely inert under gptokeyb2. Map the D-pad to movement
as well when the game doesn't need it for anything else — some handhelds have no analog stick.
**Don't map what the engine already maps**: if the game reads the pad natively and turns the
D-pad into arrow keys itself (Allegro 4's GUI does), an extra gptokeyb2 `up = "up"` doubles every
press. Duplicates are only harmless where the engine ORs keyboard and pad for the same action.
Keep `mouse_scale` out of new `.ini`s (it's an alias, and the standard block uses
`deadzone_scale`). When converting an old `.gptk`'s tuning, reuse a proven port's values instead
of inventing a conversion (§2.8).

**`TEXTINPUTINTERACTIVE`** (interactive D-Pad text entry, trigger Start+D-Pad Down) still
auto-works in gptokeyb2 with **zero authoring**, but only when the `.ini` has **zero** `[controls]`/
`[controls:...]` section headers at all — the gate flag flips permanently false the instant the
parser sees even one real section header. Any mouse-emulation or state-machine `.ini` (i.e. nearly
every new port) loses that free compat path and needs an equivalent `[controls:text_input]` state
hand-authored using the text-entry verbs above (see the worked examples in §1.8.3). For real
full-QWERTY text entry (character names, chat, server IPs) beyond D-Pad letter-cycling, see §1.10
(OmniOSK).

### 1.8.2 gptokeyb vs gptokeyb2 — what actually differs

PortMaster exposes both as separate binaries via separate `control.txt` variables (`$GPTOKEYB`
classic, `$GPTOKEYB2` successor) — a launch script picks one explicitly, it's not auto-resolved
per device.

- **Invocation shape and kill-switch mechanism are identical**: pass the binary/process name as
  the first positional argument alongside `-c`, no `-1`/`-k`/`-X` flag needed:
  `$GPTOKEYB2 "$BINARY" -c "$GAMEDIR/portname.ini" &`. From gptokeyb2's source: the first
  positional argument becomes `kill_process_name`, and `state_update()` checks Start + the hotkey
  button (`hotkey_gbtn`, default `GBTN_BACK` = Select) every frame, independent of `-c`;
  `process_kill()` then runs `pkill` on that name. (Classic gptokeyb's `-1`/`-k <app>` exist for a
  launcher that execs the real game under another name.)
- **`-c` is optional, and for a kill-switch-only port it should be omitted**: ship no `.ini` and
  run `$GPTOKEYB2 "$BINARY" &`. Without `-c`, gptokeyb2 stays out of config mode: it creates no
  fake keyboard/mouse device and doesn't load a user-level `~/.config/gptokeyb2.ini`, while the
  kill check still runs. An empty `[controls]`-only `.ini` gets flagged in review ("Why did you
  provide an empty .ini file if its not used at all?").
- **The kill target is the real running process name**: box64/box86 rename themselves to the
  guest binary; a JVM is `java`; Mono is `mono`; an interpreter is the interpreter binary (rename
  a bundled interpreter to something unique and use that, §1.7.20); FRT is the runtime binary
  (`frt_3.2.3`). A wrong name fails silently: Start+Select does nothing.
- **Confirmed bug in both tools: the kill switch silently fails when the target name is longer
  than 15 characters.** The Linux kernel's `comm` field (`TASK_COMM_LEN`) is hard-limited to 15
  usable characters, and both `pkill` and `ps` match against this truncated name, not the real
  filename. A binary named `arcanumce.aarch64` (17 chars) shows up in `ps`/`top` as
  `arcanumce.aarch` — silently missing the trailing `64`, so a `pkill` search for the full name can
  never match. Confirmed real-device symptom: Start+Select did nothing, and worse, all controller
  input then stopped working entirely (a manual process kill was needed to recover). **Fix**: pass
  a shorter identifying *prefix* (comfortably under 15 characters, still a literal prefix of the
  real name) as gptokeyb2's first positional argument — it only needs to be a string `pkill` can
  find as a substring of the truncated `comm`, nothing else uses that argument:
  ```bash
  $GPTOKEYB2 "arcanumce" -c "$GAMEDIR/arcanumce.ini" > /dev/null 2>&1 &
  ...
  pm_platform_helper "$GAMEDIR/$BINARY"     # still needs the real, full $BINARY
  "$GAMEDIR/$BINARY"                        # still needs the real, full $BINARY
  ```
  This does **not** affect `pm_platform_helper`/Wayland `app_id` matching — that's a separate
  name-resolution path (`readlink("/proc/pid/exe")`, the full untruncated path), not the kernel
  `comm` field. If a port's binary/process name is ever longer than 15 characters, verify
  Start+Select actually quits on a real device before shipping; don't assume the standard pattern
  just works. Two source bugs make the failure confusing (`util.c`): `process_with_pkill()` never
  checks `pkill`'s exit status, so gptokeyb2 "succeeds", stops its own loop and leaves the game
  running with no mapping; and the `-X` path's shadowed `status` always returned false. Trying
  `-P`/`-X`/`-Z` in turn doesn't help (all match the same truncated name, and `-P`'s Alt+F4 only
  helps engines that handle Alt+F4).
- **Upstream gptokeyb2 PRs #17-#20 (merged 2026-10-05) are not in the binary PortMaster ships
  yet.** Check a device with `strings <controlfolder>/gptokeyb2 | grep "comma separated debug
  output"` (a hit means PR #19 is in). What they change:
  - `-D <states,gamepad,keyboard,config,all,none>` turns debug output on; it's off by default
    after #19 (today every press is printed, hence the `> /dev/null 2>&1`, §1.7.2). `config`
    reports unknown `.ini` keys, useful for typos. **Never ship `-D` yet**: old binaries print
    `Unknown option '-D'` and exit, taking every mapping and the kill switch with them.
  - `dpad_mouse_step` (D-pad mouse speed) becomes configurable; `mouse_middle` works; held repeat
    keys keep repeating; wheel amounts above 1 work (it was a `bool`); `right_analog =
    absolute_mouse` parent lookup fixed; `-P` sends a real Alt modifier.
  - `-X`/`NO_PKILL` mode now uses `pgrep -f '<name>'` (full command line, so no 15-character
    limit; skips gptokeyb2's own process tree; but a short name can match unrelated processes) and
    returns the real result. **The default `pkill` mode is unchanged**, so the 15-character rule
    stays.
- gptokeyb2 itself is launched with PortMaster's own `LD_PRELOAD`
  (`libinterpose.${DEVICE_ARCH}.so`) — one more reason a port must never `export LD_PRELOAD`
  (§2.1). Running gptokeyb2 by hand over SSH for testing needs the same:
  `env LD_PRELOAD=$controlfolder/libinterpose.aarch64.so $controlfolder/gptokeyb2 ...`.
- **The double-input trap (§1.8.5) is classic-gptokeyb-only.** gptokeyb2's config structs start
  fully zeroed — a button never mentioned in any config file simply does nothing. The safe-default
  templates in §1.8.1 don't need the inert-placeholder trick classic gptokeyb requires.
- **`TEXTINPUTINTERACTIVE` works in both, but the gate differs** — see §1.8.1 above for
  gptokeyb2's specific condition (zero `[controls]` sections).
- `$GPTOKEYB2` (like `$GPTOKEYB`) is a multi-word command line, not a bare path — never quote it.

### 1.8.3 Layered controls and text entry — worked examples

Hotkey layering, real pattern from gptokeyb2's own advanced-usage docs:
```ini
[controls]
a = "mouse_left"
b = "mouse_right"
x = mouse_slow               # standard: slow mouse always on X (gptokeyb2's own example puts it on R1; don't copy that)
y = "q"                      # secondary action

l1 =
l2 = "end"                   # rotate CCW
l3 =

r1 =
r2 = "home"                  # rotate CW
r3 =

start = "p"                  # pause
back = "esc"

dpad         = mouse_movement
left_analog  = mouse_movement
right_analog = arrow_keys repeat

hotkey = hold_state hotkey

[controls:hotkey]
l1 = u                       # decrease game speed
l2 = f1 add_ctrl              # save
r1 = +                        # increase game speed
r2 = f1                       # load
```
A symbol key like `+` is sent as Shift+`=`; a Java/Swing `shift EQUALS` binding didn't react to it
while `"numpad+"` did. Check how the game actually reads the key before choosing a symbol name.

Simultaneous-hold combined state (L2+R2 both held produces a third state):
```ini
[controls]
overlay = clear
x = i
b = k
l2 = hold_state hotkey1
r2 = hold_state hotkey2

[controls:hotkey1]
overlay = parent
r2 = hold_state hotkey_both
x = g

[controls:hotkey2]
overlay = parent
l2 = hold_state hotkey_both
x = e

[controls:hotkey_both]
overlay = parent
x = p
```

Text entry triggered the usual PortMaster way (Start + D-pad Down), mirroring the state
gptokeyb2 auto-generates for `TEXTINPUTINTERACTIVE` (proven on a Java Save dialog). `start`
becomes a hold-button, so anything bound to it moves elsewhere:
```ini
[controls]
start = hold_state hk_start

[controls:hk_start]
overlay = parent
down = push_state text_input

[controls:text_input]
overlay = clear
charset = basic
up = prev_letter
down = next_letter
l1 = prev_letter10
r1 = next_letter10
right = add_letter
left = remove_letter
a = add_letter
b = remove_letter
start = finish_text
back = cancel_text
```

Simpler text entry state (hand-authored, needed the moment any real `[controls]` section exists):
```ini
[controls]
overlay = clear
back = hold_state text_input

[controls:text_input]
charset = extended
start = pop_state
up = prev_letter
down = next_letter
right = add_letter
left = "backspace"
a = "enter"
b = "backspace"
```

Word-list entry (digit codes, cheat words — define the wordset in `[config]`, reference by name):
```ini
[config]
wordset = cheats "enable_cheats" "set god" "unset god"

[controls:word_input]
overlay = clear
wordset = cheats
right_analog_up = "f1"
right_analog_left = "prev_word"
right_analog_right = "next_word"
right_analog_down = "finish_text"
```
(`charset =` and `wordset =` can't both be set in the same controls group.)

### 1.8.4 Choosing button placement — decision framework

Written after a real mapping pass got called out as unusable (Activate on L1, Run on R1, leaving
Jump/Shoot/weapon-cycle with no ergonomic relationship). Scope: 2D, non-analog games (platformers,
top-down action) driven through digital buttons/d-pad. Dual-stick 3D shooters have their own,
different conventions (triggers for fire, bumpers for secondary fire, stick clicks for
sprint/crouch) — don't cross-apply either direction.

**Critical PortMaster-specific caveat**: PM handhelds physically use **Nintendo-style** face-button
positions (confirmed on real hardware, RG351V/AmberELEC/OSH PB Controller: **A=east, B=south,
Y=west, X=north**, the SNES diamond), even though gptokeyb2's config keys are still literally
named `a`/`b`/`x`/`y`. The logical letter names do **not** auto-remap to compensate. The rest of
this framework (and the accessibility-tier research it cites) is written assuming the **Xbox**
diamond (A=south, B=east, X=west, Y=north) as its reference convention. **Practical instruction**:
get the real physical layout from whoever is testing on-device first (don't assume either
convention), then assign the logical `a`/`b`/`x`/`y` config keys so that whichever *physical*
positions are most reachable (the Tier 1 pair below, physically) carry the Tier 1 actions — don't
bind an action to the literal letter "A" and assume it lands physically south. (The Nintendo
layout was confirmed on the `firemadness` port, where the user reported the controls as felt on
the physical buttons.) Native-input engines see the same thing from the other side: with
PortMaster's `SDL_GAMECONTROLLERCONFIG`, SDL's (and GameMaker's) "A"/`gp_face1` is the button
*labelled* A, i.e. the east button, so a game whose defaults assume Xbox positions comes out
rotated (§1.7.8).

**Core principle**: two questions decide placement — (1) press frequency relative to the game's
other actions (most-pressed → most reachable button); (2) what it's combined with (actions
frequently held/pressed together belong on buttons the same thumb can roll between without
leaving the face-button cluster, not split across a face button and a shoulder button).

**Face buttons** (Xbox-reference terms):
- **A (south)** = the single most core action (almost always Jump, or primary confirm/interact) —
  matches player muscle memory by default.
- **A+X is the most-reachable pair, not A+B.** Game Developer's "Designing Game Controls"
  documents an explicit Xbox 360 accessibility-tier system: **Tier 1 (most accessible) = A, X, and
  the sticks; Tier 2 = B, Y, D-pad; Tier 3 (least accessible) = Start/Back, LT/RT.** The two
  most-frequent/most-combined-with-movement actions go in Tier 1 together (A+X). Historical
  precedent, position-corrected: SNES Super Mario World puts Jump=B, Run(hold)=Y on the *SNES*
  diamond (B=bottom, Y=left, A=right, X=top) — translated to Xbox-diamond physical positions
  (bottom=A, left=X), that's Jump=A/Run=X, independently landing on the same A+X pair. Carry over
  the *physical positions*, not the letters.
- Within A+X, which slot goes to Run vs. a primary attack depends on whether it's a **continuous
  hold-alongside-movement** action (earns the Tier-1 slot, functionally like Jump) vs. a
  **discrete burst-fired** combat action (fits Tier 2/B fine even at similar raw press count).
- **Y (north)**, Tier 2, is right for the *least*-frequent face-button action.

**Shoulder buttons (L1/R1)**: best for cycling/toggling a fixed option set (prev/next weapon,
prev/next item) — L1=previous, R1=next is a near-universal convention. Don't put a
frequently-combined-with-movement action on a shoulder button when a face button is available —
reaching a shoulder while holding a face button is harder than rolling a thumb between two
adjacent face buttons. L2/R2 can be left unbound rather than forcing a low-value action onto them.

**D-pad**: in a 2D game with no analog requirement, it's the natural movement input (and doubles
for menu nav) — don't overload it with extra action bindings alongside movement (it makes
"move" and "menu focus" ambiguous).

**Quit placement**: don't bind quit/Esc to a face button next to a primary, frequently-mashed
action (B next to A when A is jump/fire/throttle). If the CFW's Back/Select already quits (or
Start+Select kills), leave the face button unbound instead of doubling it (`b = esc` next to an
already-present `back = esc` was flagged on a real port).

**Mouse-driven games** follow the fixed mouse-button standard in §1.8.1 (A/B clicks, X slow), not
this tier analysis.

**Worked example** (`amphetamine`, 4 real-time actions plus weapon cycling): `a = space` (Jump,
south), `b = leftctrl` (Shoot, adjacent), `x = c` (Run-hold, adjacent-other-side, Tier-1 pair with
Jump), `y = tab` (Activate, least-frequent, opposite corner), `l1 = y` / `r1 = x` (the game's own
prev/next weapon keys). This
replaced an earlier version (Activate on L1, Run on R1 — no ergonomic relationship at all), and a
second rejected proposal (Jump=A/Run=B/Shoot=Y — checked against sources and rejected since both
the accessibility-tier research and the corrected SNES precedent independently point to A+X, not
A+B).

### 1.8.5 Classic `.gptk` (legacy — reading/maintaining an already-shipped port only, do not use for a new port)

Kept for reading or revisiting a port that already ships classic gptokeyb — **new ports use
gptokeyb2's `.ini` format (§1.8.1) per project policy.**

**Recognized key names** (from gptokeyb's own source):
- Arrow keys: `up`, `down`, `left`, `right`
- Special: `mouse_left`, `mouse_right`, `space`, `esc`, `end`, `home`, `shift`/`leftshift`,
  `rightshift`, `ctrl`/`leftctrl`, `rightctrl`, `alt`/`leftalt`, `rightalt`, `backspace`, `enter`,
  `pageup`, `pagedown`, `insert`, `delete`, `capslock`, `tab`, `pause`, `menu`
- Alphanumeric: `a`-`z`, `0`-`9`
- Numpad: `numpad0`-`numpad9`, `numpad*`, `numpad/`, `numpad+`, `numpad-`, `numpad,`, `numpad.`,
  `numpadenter`
- Function keys: `f1`-`f12`
- Symbols: `@ # % & * - + ( ) ! " ' : ; / ? . , ~ \` | { } $ ^ _ = [ ] \ < >` — each maps to the
  base key plus SHIFT modifier where noted in source (e.g. `@` → `KEY_2`+Shift, `-` → `KEY_MINUS`,
  `_` → `KEY_MINUS`+Shift)
- Unrecognized strings resolve to keycode 0 (no mapping) — no error, just silently does nothing.

**The double-input trap: compiled-in default keymaps are NOT cleared by blank config values.**
This is the single most important classic-gptokeyb-specific gotcha, and it does **not** apply to
gptokeyb2 at all (gptokeyb2's config structs start fully zeroed via `gptk_malloc()`'s
`memset(0)` — there is no struct-literal default keymap anywhere in its design). Under classic
gptokeyb, every button has a compiled-in *default* key mapping, populated before any config file
is read:
```
a = KEY_X, b = KEY_Z, x = KEY_C, y = KEY_A
l1 = KEY_RIGHTSHIFT, l2 = KEY_HOME, r1 = KEY_LEFTSHIFT, r2 = KEY_END
up/down/left/right = arrow keys
left_analog_up/down/left/right = KEY_W/KEY_S/KEY_A/KEY_D
back = KEY_ESC, start = KEY_ENTER, guide = KEY_ENTER
(hotkey variants: a_hk = KEY_ENTER, b_hk = KEY_ESC)
```
The fake keyboard/mouse device that makes these live is created when
`config_mode || xbox360_mode || textinputinteractive_mode` — so `TEXTINPUTINTERACTIVE=Y` alone,
even without `-c`, activates every compiled default, and `-c` becomes the only way to override
the dangerous ones.
A blank value (`a = ` with nothing after `=`) does not clear the mapping — the parser's
`fscanf(fp, "%s = %s", ...)` fails to match two tokens and the line is skipped, leaving whatever
was already in that struct field untouched. A key entirely absent from the file behaves
identically, for a more basic reason: `readConfigFile()` never resets or zeroes the config struct
at all — it only mutates fields it actually finds. **So a `.gptk` file that "leaves buttons blank"
does not actually disable them.** For a game that recognizes vi/WASD-style movement letters as
arrow-key synonyms, the compiled default `y = KEY_A` means pressing Y (bound in-game to something
unrelated via native `SDL_GameController`) will *also* synthesize a keyboard `a` press, which the
game's own keyboard handler may recognize as "move left" — a real, silent, simultaneous wrong
input.

**Don't fix this by mapping to the "same" key either** (`up = up`) — gptokeyb is a separate
process injecting through a separate virtual input device with its own poll/uinput latency; its
synthetic event isn't guaranteed to land in the same frame as the native one, so cross-frame
overlap can leave a bit looking "still pressed" a frame after the real release.

**The actual fix**: ship the full field list (every button and analog direction present), but
never assign a real, game-recognized key to a field just because the compiled default happens to
already match the native action. Every field gets the same inert placeholder value unless it
specifically needs a different one:
```
back = \"
start = \"
a = \"
b = \"
x = \"
y = \"
l1 = \"
l2 = \"
r1 = \"
r2 = \"
up = \"
down = \"
left = \"
right = \"
left_analog_up = \"
left_analog_down = \"
left_analog_left = \"
left_analog_right = \"
right_analog_up = \"
right_analog_down = \"
right_analog_left = \"
right_analog_right = \"
deadzone_mode = scaled_radial
deadzone = 2000
deadzone_scale = 8
deadzone_delay = 16
```
`\"` (a backslash-escaped quote) is the community-standard inert placeholder — confirmed against
gptokeyb2's own shipped `test.gptk` example. For each button, ask: (1) does the game's own
`SDL_GameController` code already handle it natively? If yes, the placeholder is enough regardless
of the compiled default. (2) If not read natively, does the compiled default collide with a key
the game's keyboard handler recognizes for something else? Either way the placeholder handles it.
Don't include a `guide` line at all (not even the placeholder) unless the target device population
genuinely has a working physical Guide button reaching the game — most PortMaster handhelds don't.
Don't use `;`/`#` comment lines inside a `.gptk` file — never confirmed the parser treats either as
a comment marker.

**Mouse-emulation variant** (classic format):
```
back = esc
start = enter
a = mouse_left
b = mouse_right
x = mouse_slow
y = \"
l1 = \"
l2 = \"
r1 = \"
r2 = \"
up = up
down = down
left = left
right = right
left_analog_up = mouse_movement_up
left_analog_down = mouse_movement_down
left_analog_left = mouse_movement_left
left_analog_right = mouse_movement_right
right_analog_up = \"
right_analog_down = \"
right_analog_left = \"
right_analog_right = \"
deadzone_mode = scaled_radial
deadzone = 2000
deadzone_scale = 8
deadzone_delay = 16
mouse_scale = 512
mouse_delay = 16
```
`x = mouse_slow` holds to slow cursor movement for precision. Map the D-pad to `mouse_movement_*`
too when the game doesn't need it for anything else. (The per-direction `mouse_movement_*` form
is classic-only; gptokeyb2 drops it, §1.8.1.)

**Classic `TEXTINPUTINTERACTIVE`**: `TEXTINPUTINTERACTIVE="Y"` (or the `textinput` CLI option),
triggered by **Start + D-pad Down**: Up/Down cycle the letter, Right advances, Left deletes and
steps back, A confirms, Select cancels. `TEXTINPUTNOAUTOCAPITALS="Y"` disables
auto-capitalization, `TEXTINPUTADDEXTRASYMBOLS="Y"` adds symbols. A pure flat `.gptk` (no
`[controls]` sections) plus `TEXTINPUTINTERACTIVE=Y` gives the same feature under either tool; the
moment the file has real `[controls]` sections, gptokeyb2 needs the hand-authored state (§1.8.3).

## 1.9 gamepad-picker — reusable startup-choice tool

A small, generic, standalone SDL2 tool for showing a gamepad-navigable choice screen before a
port's main game launches (language, difficulty, game variant — anything with a short list of
options). One C file (`gamepad-picker.c` + an embedded `font8x8_basic.h`). Not tied to any one
port — build once, copy the compiled `gamepad-picker.$DEVICE_ARCH` binary into any port that needs
a startup picker. Carries zero external assets: no bundled font, no shared library beyond
`libSDL2` itself. Build: `gcc gamepad-picker.c -o gamepad-picker.${DEVICE_ARCH} $(pkg-config
--cflags --libs sdl2)`. **Use it instead of shipping a second `.sh`** for any startup choice
(language, variant, mod/game folder).

**Why it exists**: PortMaster launch scripts have no other reliable, portable way to show an
interactive multi-choice menu — raw tty+`dialog` isn't supported everywhere, and PortMaster's own
IPC dialog system (`pugwash`, via `$PM_PIPE`/the `PortMasterDialog*` helpers) and the portmsg
cards (§1.7.13) only show messages, not selection menus.

**Design**: CLI contract `./gamepad-picker.$DEVICE_ARCH "Label 1|command 1" "Label 2|command 2"
...` — each argument is a label and a full command line, split on the first `|` (an argument with
no `|` is used as both). On confirm, prints the *chosen command line* to stdout and exits 0; on
cancel, exits 1 with no output. Input via `SDL_GameControllerOpen` directly (not gptokeyb — no
gptokeyb involvement for the picker step itself), genuinely cross-device via
`$sdl_controllerconfig`: D-pad or left-stick Y to move, A confirms, B cancels (keyboard
up/down/enter/space/esc also work, for testing). Rendering via `SDL_RENDERER_SOFTWARE`, no GL/GLES — fully independent of
whatever graphics stack the actual game needs. Text via an embedded 8x8 monochrome bitmap font
(public domain, `font8x8_basic.h` from `dhepper/font8x8`), compiled directly in; `GLYPH_SCALE = 3`
(24px glyphs). It covers ASCII 0-127 only; accented Latin needs `font8x8_latin.h` from the same
source. Rejected alternatives: SDL2_ttf + a bundled TTF (long dependency chain plus a 757KB font)
and one PNG per choice (per-port artwork).

**Result-capture gotcha**: don't use `LAUNCH_CMD=$(./gamepad-picker ...)` — unrelated stray stdout
(a graphics-library init banner, a CFW version string) can corrupt the captured value. Use
`GAMEPAD_PICKER_OUTPUT` set to a file path instead (truncated at startup, so a cancel leaves it
empty), and read the result from there. Keep the picker call and the game's env setup as two
contiguous blocks:

```bash
# ... standard controlfolder/control.txt/get_controls/GAMEDIR/BINARY/log-capture/cd, unchanged ...

export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"

export GAMEPAD_PICKER_OUTPUT="$GAMEDIR/.picker_result"
./gamepad-picker.${DEVICE_ARCH} "Deutsch|./$BINARY" "English|./$BINARY --language en" > /dev/null
LAUNCH_CMD=$(cat "$GAMEPAD_PICKER_OUTPUT")
LAUNCH_CMD="${LAUNCH_CMD:-./$BINARY}"

export LD_LIBRARY_PATH="$GAMEDIR/libs.${DEVICE_ARCH}:$LD_LIBRARY_PATH"

$GPTOKEYB2 "$BINARY" -c "./portname.ini" > /dev/null 2>&1 &
pm_platform_helper "$GAMEDIR/$BINARY"
$LAUNCH_CMD
pm_finish
```

Don't hardcode `$BINARY` as gptokeyb2's kill target if different picker choices could launch
genuinely different binaries — resolve the kill target from `$LAUNCH_CMD` instead in that case.
To pass a path containing spaces (e.g. Open Surge listing `games/*` folders and zips), make the
path itself the choice's "command" and build the real command line from it in the script, so
quoting survives. B (cancel) can simply quit the port.

## 1.10 OmniOSK — on-screen keyboard overlay

Use when a port needs real text entry (character names, save names, chat, server IP) and
gptokeyb2's own `TEXTINPUTINTERACTIVE`/`text_input` state (D-Pad letter-cycling, §1.8.1/§1.8.3)
isn't good enough UX — a full QWERTY grid instead of cycling one letter at a time. A
controller-navigable Dear ImGui overlay, loaded via `LD_PRELOAD` into the target game's process.

### 1.10.1 Two variants — pick by what SDL the target game actually runs on

- **`binarycounter/OmniOSK`** (original, real SDL2 rendering). Use for anything whose actual
  runtime SDL is real SDL2, **including a game reached through `sdl12-compat`/SDL1.2 emulation**
  (with the bridge below, kept on a `sdl12-compat-bridge` branch, not upstreamed).
- **`Cebion/OmniOSK_sdl3`** (fork, SDL3 rendering via the `sdl3-sdl2-backend` shim, §1.7.12). Use
  **only** for a game that is genuinely SDL3-native itself (e.g. `arcanumce`).
- **Neither works for a game that isn't on SDL at all** (Java/AWT, SFML, Allegro 4's X11 driver):
  OmniOSK hooks SDL2 via `LD_PRELOAD`. Use gptokeyb2's own text-input state there (§1.8.3).

Check with `readelf -d libomni_osk.so | grep NEEDED`: the original shows `libSDL2-2.0.so.0`, the
fork shows `libSDL3.so.0`. **Picking the SDL3 fork for an sdl12-compat game produced a confirmed
real `*** stack smashing detected ***` crash** (two incompatible SDL major versions loaded in one
process). Switching to the real-SDL2 original removes that crash, but getting the *original*
variant working against an sdl12-compat game needs the bridge below.

### 1.10.2 The sdl12-compat bridge — every fix confirmed on real hardware

Root cause behind every fix in this section: `sdl12-compat` resolves its own calls into real SDL2
via a private `RTLD_LOCAL` `dlopen`+`dlsym` (`LookupSDL20Sym`), never through the process's normal
global PLT/GOT table that `LD_PRELOAD` interposition depends on. Anything `sdl12-compat` does
internally to real SDL2 is invisible to a preloaded library. Needs `-DOMNI_SDL12_BRIDGE=ON`
(requires real `SDL/SDL.h` on disk; `OMNI_SDL12_INCLUDE_DIR`, default `/usr/include`; OFF by
default so the plain SDL2 build stays correct for SDL2-native games). The tell-tale symptom
before the fix: a `[TRACE]` print showing a KEYDOWN read back as `type=65538`, and SDL 1.2's
`SDLK_F12` being `293` versus SDL2's `1073741893`. Confirmed fixes, in order:

1. **Event struct layout mismatch**: SDL 1.2's `SDL_Event.type` is `Uint8`, SDL2's is `Uint32` —
   a whole-struct layout difference, not just different keysym numbers. Fixed via a translation
   unit (`sdl12_bridge.c`) compiled against real SDL 1.2 headers that decodes the raw buffer and,
   for KEYDOWN/KEYUP, round-trips through SDL 1.2's `SDL_GetKeyName()` → SDL2's
   `SDL_GetKeyFromName()` name strings — automatically correct for the whole keyspace without a
   hardcoded numeric table.
2. **No presentation-target discovery**: a game using old `SDL_SetVideoMode()` never calls the
   window/renderer creation functions OmniOSK normally hooks. Fixed by calling real SDL2's
   `SDL_GetKeyboardFocus()` directly to find the window, then `SDL_GetRenderer(window)` to reuse
   sdl12-compat's own renderer (falls back to a new software renderer only if none is found).
3. **No present-call hook fires**: `sdl12-compat` presents through its own invisible internal
   path. Final fix: hook `SDL_UpdateRect`/`SDL_UpdateRects`/`SDL_Flip` directly (real SDL 1.2-only
   function names, zero SDL2 name-collision risk, called by the game itself so ordinary
   interposition *does* reach them) — draw and present after calling through to the real
   implementation, guaranteeing OmniOSK is always the last thing drawn each real frame. A
   `real_present_hook_seen` flag disables the old timer-based draw (`present_overlay_fallback()`,
   kept only for a game that never presents) the moment a real hook fires.
4. **Flicker on an accelerated, vsync'd renderer**: every real frame got two competing presents on
   the same shared renderer. Several timing-based mitigations were tried and rejected
   (`SDL_RenderSetVSync(renderer, 0)` while open — improved but not clean and device-variable;
   `SDL_RENDER_DRIVER=software` — made it worse; quad-presenting — no difference). **Actual fix**: skip calling through to the real
   `SDL_UpdateRect`/`Flip` implementation entirely while the overlay is active (the game's own
   content simply stops reaching the screen, frozen on its last frame), resuming real forwarding
   the instant the overlay closes. Confirmed clean (no flicker) on two different devices.
5. **Input leaking through while the overlay is open**: two separate leaks. (a) Mouse events
   passed through unconditionally regardless of overlay state — fixed by adding mouse-event kinds
   to the bridge's own event classifier and explicitly suppressing them while active. (b)
   `SDL_GetKeyState()` (SDL 1.2's raw key-state poll, a *different function name* than SDL2's
   `SDL_GetKeyboardState()`, not just a rename — different indexing too) bypasses event-queue
   suppression entirely, since `sdl12-compat` updates that array as a side effect of its own
   internal event processing. Fixed with a dedicated hook, same shape as the present hooks: calls
   through to the real implementation first, then returns an all-zeroed shadow array while active.
6. **Display mis-scaling on non-native-resolution devices**: `SDL_RenderSetLogicalSize`
   letterboxing (set by sdl12-compat to match the game's requested video mode) isn't accounted for
   by OmniOSK's own layout math or by Dear ImGui's SDL2 backend, both of which read the window's
   raw physical size (seen on X55/ROCKNIX at 1280x720: the grid stretched and mostly off the
   right edge, while 640x480 devices looked right). Fix: query `SDL_RenderGetLogicalSize` and use
   that instead, in both places, when non-zero: OmniOSK's `output_size()`, and an override of
   `ImGui::GetIO().DisplaySize` placed **between** `ImGui_ImplSDL2_NewFrame()` (which sets it from
   the raw window) and `ImGui::NewFrame()` (which consumes it). **Not yet ported to the SDL3 fork**
   even though the same symptom was seen there.
7. **Text write-back**: submitted text needed two separate fixes — a real stack-buffer overflow
   (OmniOSK's synthesized events assumed an SDL2-shaped 56-byte event, but the real caller buffer
   for a bridge target is SDL 1.2's own 24-byte one), and the fact that most SDL 1.2-era games
   don't read text from the event queue at all (they poll `SDL_GetKeyState()` and edge-detect
   0→1 transitions into their own ASCII buffer). Fixed via a dedicated `SDL_GetKeyState()`
   combo-injection state machine that bypasses the event queue entirely for text delivery on a
   bridge build: submitted characters are grouped into combos (an uppercase letter is
   `LSHIFT-DOWN + LETTER-DOWN` presented together so the game's own shift lookup sees Shift held on
   the letter's press edge), each combo is reported pressed for exactly one poll and released on
   the next (one character per two polls), and SDL2 keysyms are translated to SDL 1.2 indices
   (only `SDLK_LSHIFT` actually differs: 304 in SDL 1.2) through the bridge's existing
   `omni_sdl12_equivalent()` table. The event-queue delivery path is deliberately disabled on a
   bridge build: the game drains `SDL_PollEvent` before polling key state, so it would steal
   characters first. Confirmed: a typed name reaches the game's field intact.

**Testing bed pattern**: iterate against a minimal app (`checkkeys`, SDL 1.2's own real
upstream keyboard-test tool, built against the same sdl12-compat build the port ships) rather
than the full game — much faster, and it caught a real
unrelated shell bug too (`$GPTOKEYB2` is a multi-word command line, never quote it — see §1.8.2).

### 1.10.3 Conventions and env vars

**Overlay toggle is always L2** — confirmed real precedent in two real shipped `.ini`s, mapped to
OmniOSK's toggle key (`f12` by default, `OMNI_TOGGLE_KEY` to override). Keep this consistent
across every OmniOSK-using port; players shouldn't have to relearn which button opens text
entry.

**Never `export LD_PRELOAD`** — same rule as §2.1. It leaks into
gptokeyb2's own subsequently-launched process, which links its own real SDL2 for joystick reading;
a second SDL pulled in via the preload breaks gptokeyb2's `SDL_Init()`. Set it as a bare,
unexported prefix only on the actual game binary's launch line, after gptokeyb2 is already running
in the background:
```bash
export OMNI_MODE=buffered
export OMNI_EVENT_MODE=auto
# ... gptokeyb2 launch, pm_platform_helper ...
LD_PRELOAD="$GAMEDIR/libs.${DEVICE_ARCH}/libomni_osk.so${LD_PRELOAD:+:$LD_PRELOAD}" ./$BINARY
```
`OMNI_*` vars are safe to `export` early — only `LD_PRELOAD` itself is dangerous. Also export
`SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"` before launching gptokeyb2 — needed for correct
L2/R2 mapping (often analog-trigger-shaped) so the OmniOSK toggle registers correctly.

**`OMNI_EMIT_RETURN`** (default `1`) auto-appends a synthesized Enter after submitted text — check
whether the target game's own Enter key does double duty (e.g. also "advance the dialog") before
leaving this on; set `OMNI_EMIT_RETURN=0` if so.

**`OMNI_EVENT_MODE`**: if the game polls raw key state/scancodes every frame (most SDL 1.2-era
games), `auto`/`key` mode is correct — and note that a scancode-polling game's *ordinary* gameplay
input was never actually at risk from any of the bridge bugs above (sdl12-compat updates its own
key-state array before OmniOSK's hook even runs); only OmniOSK's own toggle/nav recognition was at
risk. `text` mode for SDL text-input-API-driven fields is unconfirmed, not yet needed on a real
port.

**`OMNI_BACKSPACE_KEY`/`OMNI_CHARSET_KEY`** default to literal BACKSPACE/TAB. The physical button
sending that key keeps sending it regardless of overlay state — only decode/consumption is
overlay-gated, not the binding itself. Check whether the target game's own keybinds (including
hardcoded ones, not just configurable ones) give that raw key a real in-game meaning the player
doesn't want triggered by accident while the overlay is closed; only remap
(`OMNI_BACKSPACE_KEY`/`OMNI_CHARSET_KEY` to different letters) if so, or if the port's own gptokeyb2
state machine already needs those keys for something else. If the in-game meaning is something the
player *wants* while the overlay is closed, there's nothing to fix — the overlay's own suppression
already keeps it from reaching the game while open. Real example (`amuletsarmor`): `R1 = "tab"`
(OmniOSK's charset key) also toggled the game's relative mouselook while the overlay was closed,
an unwanted leak; R1 was later mapped to `space`, which is both OmniOSK's charset key and the
game's own Jump, so nothing needed fixing. `arcanumce` remaps the two keys to `W`/`K` because its
gptokeyb2 state machine needs BACKSPACE/TAB for other things.

**Dependency bundling** (`libs.$DEVICE_ARCH`): original variant is just `libomni_osk.so`
(`NEEDED`s `libSDL2-2.0.so.0`, `libstdc++.so.6`, `libgcc_s.so.1` — nothing else to bundle). SDL3
fork variant ships two files: `libomni_osk.so` (`NEEDED`s `libSDL3.so.0`, must be the shim) plus
the shim `libSDL3.so.0` itself (dlopens system SDL2 at runtime, doesn't link it, so bundling it
doesn't trigger the never-bundle-SDL2-alongside-a-shim gotcha). Licenses: OmniOSK's (and
Dear ImGui's) go in `licenses/`; none for gptokeyb2, which PortMaster provides.

---

# PART 2 — Real-World Gotchas Not Covered by the Official Site

## 2.1 Input handling

**The double-input trap covered in full above (§1.8.5) is the single most important classic-
gptokeyb-specific gotcha in this whole document.** It does not apply to gptokeyb2 at all (§1.8.1).

**`SDL_JoystickOpen` vs `SDL_GameControllerOpen`.** Games using the low-level joystick API often
hand-roll button mapping instead of using `gamecontrollerdb.txt`, which commonly shows up as
swapped or wrong buttons. Fixes, in order of preference: patch the game to `SDL_GameControllerOpen`
if that's clean; otherwise fully disable its native joystick code (remove/guard `SDL_JoystickOpen`,
`SDL_JoystickEventState`, `SDL_NumJoysticks` checks, the `SDL_JOY*` event handling and
`SDL_JoystickClose`) and drive all input through gptokeyb2; a custom `gamecontrollerdb.txt` via
`SDL_GAMECONTROLLERCONFIG_FILE` is a last resort. Check which API a game actually uses before
assuming a mapping bug is a config-file problem — some engines (mkxp-z, raylib via its high-level
API, Allegro 5's SDL backend, GameMaker's runner) are already the "known good" case and need zero
remapping at all. Code that reads fixed joystick button numbers is the usual culprit.

**Don't ship a `gamecontrollerdb.txt` the engine would load itself** (e.g. Allegro's
`al_set_joystick_mappings()`): it overrides the CFW's own `SDL_GAMECONTROLLERCONFIG` for the
built-in pad. Leave the CFW's mapping in charge.

**`SDL_GAMECONTROLLERCONFIG` is needed by gptokeyb2 itself**, whatever the game uses: gptokeyb2
reads the controller with its own real SDL2 (`SDL_GameControllerOpen`). Before removing or
justifying any env var, check it against every process the script runs (game, gptokeyb2,
OmniOSK, box64...). (Exception: exporting it crashed FRT 2's Godot, §1.7.6.)

**Touchscreen devices** (some Retroid and Anbernic models, RP5): SDL2 synthesizes a mouse event
from every touch by default, so a touch overrides gptokeyb2's synthetic mouse position (the
cursor snaps to the finger). First check how touch reaches the game (grep the engine/compat layer
for `SDL_FINGER` handling):
- If touch only arrives as SDL's synthesized mouse events (sdl12-compat drops `SDL_FINGER`
  events; raylib keeps finger events separate), set `SDL_TOUCH_MOUSE_EVENTS=0` on the game's
  command line. Nothing else is needed.
- If the game reads finger/touch events itself, or input doesn't go through SDL2's touch-to-mouse
  path, ship the standard ROCKNIX block (after the hi-res deadzone bump, before `$GPTOKEYB2`):
  ```bash
  if [ "$CFW_NAME" = "ROCKNIX" ]; then
    export SDL_TOUCH_MOUSE_EVENTS=0
    swaymsg input type:touch events disabled 2>/dev/null
  fi
  ```
- Never patch the game itself for touch.

**ROCKNIX: stick-to-mouse gets no input on some controllers** (confirmed on RP5, GUID
`0300fd574c050000e60c000011810000`, the InputPlumber "DualSense" identity of its built-in pad).
ROCKNIX's `map_input_control()` (`/etc/profile.d/100-gamecontroller-functions`) only knows
`leftanalog*`/`rightanalog*` names, but ES's `es_input.cfg` records `joystick1left`/`joystick1up`/
`joystick2left`/`joystick2up`, so `leftx`/`lefty`/`rightx`/`righty` never reach
`SDL_GAMECONTROLLERCONFIG`. Any SDL_GameController tool is affected; the D-pad still works. The
ROCKNIX maintainer declined device-specific fixes, so **don't ship a GUID-sniffing workaround**:
accept D-pad-only analog input there. (Proof of cause: unsetting `SDL_GAMECONTROLLERCONFIG` and
`SDL_GAMECONTROLLERCONFIG_FILE` for one gptokeyb run made the stick work, but loses the CFW's
Nintendo-layout button mapping.)

**ROCKNIX: a relative-mouse game's cursor snaps to a fixed point every 1-3.5 s** (SDL2/raylib
`SDL_SetRelativeMouseMode` + Wayland pointer lock, any input source). Cause: sway's
`seat * hide_cursor 1000` in `/storage/.config/sway/config` makes the pointer leave and re-enter
the surface, and each re-enter delivers a stale absolute position that SDL/raylib turns into one
huge delta. Confirmed by commenting the line out and `swaymsg reload`. A CFW-gated (not GUID)
`swaymsg seat seat0 hide_cursor 0` before launch and `1000` after is the candidate port-side fix;
it hasn't been shipped yet.

**Westonpack double input** (a menu opens and instantly closes on each press): Crusty's
`CONTROLLER_HOOK` reads the physical pad in Weston's own process. Fix with `CRUSTY_BLOCK_INPUT=1`
(§1.7.4), not gptokeyb2's `exclusive = true`.

**`SDL_JOYSTICK_DISABLE` isn't read by SDL**; disable joystick code in the game instead.

**A low-resolution game stretched to a native-resolution fullscreen window by the engine without
its own scaling can let the mouse leave the game area** (BennuGD). Clamp/scale the mouse to the
game's logical area in the engine.

**Quit-button placement.** Don't bind quit to a face button sitting right next to a primary,
frequently-mashed action button (B next to A, when A is fire/jump/throttle) — real risk of
accidental quits mid-game. If the CFW's own dedicated Back button already quits, don't also
duplicate that onto a face button "for convenience."

**Never `export LD_PRELOAD` before launching gptokeyb2** — it leaks into gptokeyb2's own process,
which PortMaster already starts with its own `LD_PRELOAD` (`libinterpose`) and which links its own
real SDL2 for joystick reading; if it also inherits a preloaded library that itself pulls in
another SDL (e.g. an SDL3-via-SDL2-backend shim's `libSDL3.so.0`), gptokeyb2 ends up with two
incompatible SDLs loaded at once and its `SDL_Init()` can get silently rerouted through the wrong
one and fail outright (`undefined symbol: _udev_device_get_action`). On-device symptom: total,
silent controller failure ("no controls working") with no visible connection to the actual cause
unless gptokeyb2's own log output is read. Fix: set the var as a bare prefix on the one command
line that actually needs it, placed after gptokeyb2 is already launched, never as an `export`
earlier in the script. See §1.10.3 for the full OmniOSK-specific pattern.

**Choosing which button gets which action**: see §1.8.4's full decision framework (Tier 1/Tier 2
accessibility tiers, the Nintendo-vs-Xbox physical-layout caveat, shoulder-button cycling
conventions) — read that before writing any control-mapping file for a keyboard-only/non-native-
gamepad game. Mouse-driven games use §1.8.1's fixed mouse standard.

## 2.2 Display / graphics

**Never let an engine use its own native DRM backend**, even when it builds cleanly and looks
architecturally cleaner (no X11, no SDL2 translation layer). Two independent confirmed real cases:
a bespoke "talk to KMS/GBM/EGL directly" mode that compiled fine and failed on real hardware with
`Failed to find a suitable DRM connector mode` / `Failed to initialize platform`, then crashed; and
raylib's own `PLATFORM_DRM` backend hitting the identical failure on a second, unrelated port
(§1.7.11). Every CFW patches SDL2's own DRM/KMS handling for its specific connector quirks; a
generic engine DRM backend has none of that device-specific handling. Always reach the display
through SDL2 (or a runtime built on it).

**The same reasoning applies to an engine that statically vendors its own old SDL2.** The Dry
engine (an Urho3D fork) always compiled its bundled SDL **2.0.10** (January 2020) into `libDry.a`,
and on RG351V/AmberELEC it failed with `Could not initialize OpenGL / GLES library` although the
device's Mali GLES library works for hundreds of other ports. Fix: drop the vendored SDL from the
engine build (for Dry, its entry in `Source/CMakeLists.txt`'s `foreach (TARGET ...)` list), stage
the system SDL2 headers where the engine expects them (Dry includes `<SDL/SDL.h>`, not
`<SDL2/SDL.h>`), and link the system `libSDL2-2.0.so.0` dynamically (never bundled). Side effects
to expect: SDL's CMakeLists had `include()`d check modules (`CheckCSourceCompiles` etc.) another
third-party lib relied on (one-time `unknown CMake command`; add the `include()`s to the parent);
and a few API gaps across that many versions (here: an engine-private second argument to
`SDL_CreateWindowFrom()`, the removed `SDL_RemoveDollarTemplate`/`SDL_RemoveAllDollarTemplates`,
and the internal `SDL_AddTouch` the engine reached via its own `extern "C"`). Find them by
iterating real compile/link errors, and check whether each call is reachable by the game before
writing a replacement; all three guarded dead code (editor embedding, gestures, touch emulation)
and became no-ops.

**NEVER set `SDL_VIDEODRIVER` (or force any other specific video/audio driver) in a port's own
launch script.** Each CFW sources its own SDL2 backend selection via
`control.txt`/`mod_${CFW_NAME}.txt` (ROCKNIX sets `SDL_VIDEODRIVER=wayland` in its
`/etc/profile.d/050-sway.conf`) *before* the port's own script logic runs — not every device
uses `kmsdrm` specifically. A port forcing `SDL_VIDEODRIVER=kmsdrm` "to be safe" can silently
break on any CFW/device that actually needs a different driver. Confirmed real incident: the
`amphetamine` port added `export SDL_VIDEODRIVER=kmsdrm` and it caused the game to fail silently on
a real device (Knulli/H700). Never add this or a similar env var unless a specific, confirmed
real-device symptom points at needing an override — and even then, prefer a CFW-specific
`mod_${CFW_NAME}.txt` override path over hardcoding it in the port. **The one sanctioned
exception is the SDL3 shim's forwarding pattern** (§1.7.12): the CFW's value is forwarded into
`SDL3SHIM_SDL2_VIDEODRIVER`, and `SDL_VIDEODRIVER=sdl2` (the shim's only driver) is set on the game
command line only. Never write a literal driver name into `SDL3SHIM_SDL2_*` either. `dummy`
drivers (`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`) are for headless chroot tests only, never
in a launch script.

**Don't hardcode CFW or device names in engine source either.** A merged OpenRA port patched
CFW-name branches (`ArkOS`, `AmberELEC`) into engine code, and missed a third CFW with the same
problem. Fix the behaviour generically (e.g. fall back after a failed probe, §1.7.11) or detect a
capability.

**Only disable an engine/library backend for a concrete reason tied to that backend.** The
distinction that matters is a hard `NEEDED` dependency versus a `dlopen`ed one. SDL2's X11/KMSDRM
backends (`X11_SHARED`/`KMSDRM_SHARED`) are `dlopen`ed and cost nothing when absent; disabling X11
in a vendored SDL "because the target is KMS/DRM" broke real-device testing (BlipNBlup) with zero
evidence X11 was a problem. SDL's Wayland backend, by contrast, added a real hard
`NEEDED libwayland-client.so.0`, a valid reason to disable it. Check with `readelf -d`, don't
assume.

**Make sure the game actually requests fullscreen.** Many windowing APIs default to windowed
(`pygame.display.set_mode(size)`, plain `SDL_CreateWindow`), and it only shows on a device whose
compositor doesn't fullscreen windows anyway (RP5/ROCKNIX showed a small window). Grep **every**
window/display-creation call (Alexandria had two) and add the flag (`pygame.FULLSCREEN`,
`SDL_WINDOW_FULLSCREEN`/`SDL_WINDOW_FULLSCREEN_DESKTOP`, the engine's own `-fullscreen`). Prefer
borderless/desktop fullscreen at native size: raylib's exclusive fullscreen on ROCKNIX/Wayland
fakes a mode change and squashed the image (1920x455). An engine that draws a fixed-size buffer
into the top-left corner needs GPU scaling added. This is a game-source fix, not an env var.

**Prefer a native GLES2/3 build path over gl4es whenever the engine actually has one.** gl4es is a
translation layer of last resort, not a default choice. Confirmed real cases where the native path
wins: raylib's `GRAPHICS_API_OPENGL_ES2`/`OPENGL_VERSION="ES 2.0"` (§1.7.11) worked cleanly across
two different real GPU vendors (Mali and Adreno), while routing OpenGL 2.1 through gl4es on the
same engine hit two real, confirmed bugs specific to that exact combination on GLES-only hardware:
an unsized depth-renderbuffer format GLES drivers reject, and a shader version string that didn't
convert correctly in one call path — net result, a black screen despite gl4es itself initializing
fine. mkxp-z's `-Dgfx_backend=gles` (§1.7.10), Allegro 5's `ALLEGRO_SDL` + `gles2+` (§1.7.16) and
the Qt6 eglfs runtime (§1.7.17) are further confirmed native-path cases. gl4es genuinely is the
right and only choice for engines that have **no** native GLES path at all — confirmed by reading
source: `MonoGame.Framework.DesktopGL` has no ES option anywhere in its actual SDL context-creation
code (§1.7.11), and neither does its KNI fork. But wherever an engine *can* request GLES natively
while still using SDL2 for windowing, try that first.

**…but a native GLES1.1 path can be worse than gl4es.** On ROCKNIX RK3566 Mali-G52 (`g24p0`
libmali), the driver's "ES-CM 1.1" fixed-function layer segfaults on every `glDrawArrays`
(identical with a 1×1 texture, no texture, explicit EGL attributes, or a VBO), while desktop GL
through gl4es (real GLES2 shaders) works. A native GLES1.1 port of WolfensteinRPG-RE worked on
RG351V and crashed there, so it shipped as desktop GL + gl4es. When a crash sits inside a closed
vendor driver, test minimal-diff variants of the same call until one axis changes the outcome,
instead of reasoning about GL state.

**Porting desktop GL 3.3 core to native GLES3** (Cortex Command, rlgl): rewrite `#version 330` to
`#version 300 es` at shader load time. `#version` must be the very first line (a leading comment
breaks it), precision statements go after any `#extension` lines, uniform initializers are invalid
(rlgl's default ES3 shader's `colDiffuse` then defaulted to 0: a black screen), no implicit
int/float comparisons, and single-channel textures use `GL_R8`/`GL_RED` with a swizzle.
**Panfrost differs from Mali on feedback loops**: sampling the currently bound FBO's own
attachment read the previous frame on Panfrost (Mali tolerated it); copy to a separate texture.
**Per-draw `glFlush()` cripples Panfrost**: old Irrlicht 1.2 flushed per mesh (2 → 45 FPS once
removed). GLSL from GLES-era engines usually only needs `#version 120` → `#version 100` plus
`precision mediump float;` in the fragment shader (OpenSoldat). Never assume `glGetString(GL_VERSION)`
starts with a digit (`"OpenGL ES 3.2 ..."`).

**Never link both `-lGLESv1_CM` and `-lGLESv2` on a GLES2/3 port.** They export the same names
(`glGenBuffers`, `glGenTextures`, `glGetString`...), and the dynamic linker resolves them by link
order, not by which context is current. Failure mode (BlipNBlup, RGB30/dArkOS Mali-G52; RG351V's
Mali-450 happened to tolerate it): `glGetError()` reports `GL_NO_ERROR`, but `glGenBuffers` writes
ID 0 and `glGetString(GL_VENDOR)` returns empty — all the signs of a broken context with none of
the causes. Found with a gdb breakpoint on `glGenBuffers` showing the call resolved into
`libGLESv1_CM.so.1`. Drop `-lGLESv1_CM` unless the code calls GLES1-only functions
(`glVertexPointer`, `glMatrixMode`; grep first); if it must stay, put `-lGLESv2` first. Engines
copy this pairing (Dry's `DryCommon.cmake` links both on ARM).

**`SDL_CreateTexture` can fail with "Texture format not supported"** on Mali-GPU/GLES2-backed
renderers, right after `SDL_CreateWindowAndRenderer` itself *succeeds* — specifically for pixel
formats used by manual/streaming textures (e.g. a hand-packed `SDL_PIXELFORMAT_RGBA8888` buffer),
even though identical code runs fine on desktop Linux. Confirmed on real devices (RG351V/
AmberELEC, twice). `SDL_CreateRenderer(..., SDL_RENDERER_ACCELERATED)` hits the same failure.
Under Mono/P/Invoke, the same root cause manifests as a **hard `SIGSEGV`** (§1.7.11). A game's own
logging wrapper may never print `SDL_GetError()`, so recognise the bug structurally (a streaming
texture on a GLES2 renderer, failing right after renderer creation), not by grepping the log for
the SDL text. Fix: don't use the combined `SDL_CreateWindowAndRenderer` call; split into
`SDL_CreateWindow` + `SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE)` — negligible perf cost
for a typical low-resolution game buffer — gated on a port define (`#ifdef PORTMASTER_BUILD`) so
desktop builds keep acceleration. Force software rendering preemptively for any game that creates
its own `SDL_Renderer` with streaming textures.

**SDL3 GLES2 renderer alpha bug**: an XRGB8888 texture drawn into an RGBA32 render target copies
X = 0 into alpha, so opaque images vanish when a game renders to a texture first. Workaround: draw
straight to the screen (nearest filtering).

**No hardware cursor on most of these devices.** SDL's KMSDRM cursor needs a hardware cursor
plane: it was invisible on RK3326/AmberELEC (one port), on H700/muOS (another), and
`SDL20_CreateCursor` failed outright on muOS. Draw a software cursor in the game (ZQuestClassic's
`[gui] software_cursor`, which also hashes cursor position into its frame-skip signature so idle
frames redraw; GameMaker's `cursor_sprite`; Love2D's draw-at-end-of-frame; ASC's software-cursor
patch). sdl12-compat cursor notes are in §1.1.

**A GUI library drawing nothing after the game's own rendering** (CEGUI invisible): the game left
`GL_DEPTH_TEST` on; CEGUI's `enableExtraStateSettings(true)` fixed it. **Present continuously**:
on dArkOS (Mali-G52) an app that only presented on change showed a black screen between presents;
re-present at least every 100 ms.

**An engine that forks a browser** (`Web.launchURL()` → `python -m webbrowser`) leaves fullscreen
and garbles the display; patch it out.

**`libmali` counts GPU memory in the process's RSS** (as `VmRSS`/RssFile, not visible in `smaps`
Rss); Panfrost doesn't. Don't compare RSS across drivers or resolutions (textures scale with screen
size).

**Never bundle a port's own `libSDL2-2.0.so.0`** — see §1.1 for the full rule and the confirmed
`amphetamine`/PulseAudio failure case. Applies equally to any `sdl12-compat` or `sdl3-sdl2-backend`
shim a port bundles: let the shim `dlopen()` the device's own system SDL2, never ship a paired one.

**gl4es standalone launch setup**: see Pattern B (§1.7.3) — source `libgl_${CFW_NAME}.txt` with the
default fallback, ship the `gl4es.$DEVICE_ARCH` folder, and only add the `LD_LIBRARY_PATH`-guarded
`SDL_VIDEO_GL_DRIVER`/`SDL_VIDEO_EGL_DRIVER` export when a confirmed symptom needs it (MonoGame);
forcing it broke OpenSoldat.

## 2.3 Audio

**`SDL_mixer` MIDI playback can silently do nothing.** PortMaster CFWs generally don't ship a
system `timidity.cfg` or default soundfont, so `Mix_PlayMusic`/`Mix_LoadMUSType_RW` on a `.mid`
file either produces no sound or fails, easy to miss if calling code doesn't check the return
value. Error meanings: `Couldn't open timidity.cfg` = no config found; `Unrecognized audio format`
= the config/patch path is wrong in a way SDL_mixer didn't report as missing (and non-`MThd` files
fall through to the MOD loader). Two proven fixes, both with real merged-PortMaster-port precedent:
1. **Classic Timidity (GUS patches) — copy the merged-port layout exactly** (`ports/freedink`,
   `ports/openclaw`): **one inline `timidity.cfg` in the game's working directory, starting with
   `dir ./<patchdir>`**, the patches in that subfolder, **no `source` directive, no
   `TIMIDITY_CFG` env var, no `Mix_SetTimidityCfg()`**. SDL_mixer's Timidity finds `./timidity.cfg`
   in the cwd by default. A variant that worked in the chroot (`timidity/timidity.cfg` with
   `dir timidity` + `source zc.cfg`, set via `Mix_SetTimidityCfg`) failed on device with
   `Unrecognized audio format`; the precedent layout fixed it (ZQuestClassic, confirmed). A full
   General MIDI "freepats" set is ~33MB (GPLv2); bundle it whole. ZQuestClassic ships upstream's
   own `zc.cfg` set (ultra + ppl160 + FreePats, 191 patches, 35MB).
2. **FluidSynth + a single `.sf2` soundfont**: set `SDL_SOUNDFONTS` to an absolute path pointing
   at a bundled `.sf2`. **Only works if the target's `libSDL2_mixer` was actually built with
   FluidSynth support** — check with `readelf -d` on the library (`NEEDED libfluidsynth`):
   ```bash
   readelf -d /usr/lib/aarch64-linux-gnu/libSDL2_mixer-2.0.so.0 | grep -i fluid
   ```
   Real example: `ports/swordofjade`, bundling the full `FluidR3_GM.sf2` (~140MB, split across
   five `.7z` volumes, extracted on first run). **A much lighter option**: `TimGM6mb.sf2`, only
   ~5.7MB, GPLv2, ships via the Debian/Ubuntu `timgm6mb-soundfont` package at
   `/usr/share/sounds/sf2/TimGM6mb.sf2` — for a small-scope port this is ~9x lighter than the
   freepats patch set, one file, one launch-script env var line:
   ```bash
   export SDL_SOUNDFONTS="$GAMEDIR/TimGM6mb.sf2"
   ```
   mkxp-z (§1.7.10) uses the same `TimGM6mb.sf2` file via its own `mkxp.json`
   `"midiSoundFont"` config field instead of this env var — same recommendation, different
   mechanism.

Check both options' actual footprint before committing to one. **Bundling an SDL_mixer build is
allowed when the port needs one** (it isn't core SDL2): ZQuestClassic ships its upstream's own
SDL_mixer fork (MIDI/Timidity only, 166KB, SONAME `libSDL2_mixer-2.0.so.0`) because it needs
`Mix_GetMusicBeat`/`Mix_SetMusicBeat`, and a second SDL audio device next to Allegro's. Verify MIDI
decoding headlessly in the chroot by linking a tiny test against the **same** SDL_mixer you ship
and rendering to SDL's `disk` (or `dummy`) audio driver; passing that proves decoding only, not how
it sounds on the device. **"Out of tune" quest MIDI has two separate causes**: a missing music pack
(the quest's enhanced-music references) and RPN pitch-bend range (CC101/100 = 0/0 then CC6) in
the MIDIs, which Allegro's DIGMID ignores (hardcoded ±2 semitones). Check what upstream itself does
on each platform before inventing your own MIDI path (no upstream ZC build used DIGMID).

**Engines using `miniaudio` for audio can fail to init on PipeWire-based CFWs** even when the
audio environment is genuinely healthy — miniaudio's PulseAudio backend probing doesn't always
get along with PipeWire's Pulse-compatibility shim on some CFW/version combinations. Confirmed
real case: a raylib port on ROCKNIX/Retroid Pocket 5 (PipeWire, `pactl info` and `aplay -l` both
healthy) hit `Failed to initialize playback device` outright. Fix: force miniaudio straight to
ALSA — `#define MA_NO_PULSEAUDIO` next to raylib's own existing `#define MA_NO_JACK` in
`raudio.c`, before `#include "external/miniaudio.h"` (one-line patch to the local vendored copy,
reapply on any fresh raylib checkout). A second miniaudio/PipeWire case: miniaudio's PulseAudio
backend with `MA_PA_STREAM_FIX_FORMAT` against PipeWire's `s24-32le` produced no sound; remove the
flag. Always triage with `pactl info` and `aplay -l` before declaring a device's audio broken.

**FMOD on Linux** autodetects PulseAudio with no fallback, and its ALSA output only enumerates
hinted devices, so on muOS there was no sound at all; add an SDL2 output plugin and select it.
`FMOD_CREATESAMPLE` decodes every sound to PCM up front, enough to OOM a 1GB device.

**One audio stream per sound effect through PipeWire kills ROCKNIX performance** (48 streams in
one port); mix into one stream.

**OpenAL Soft**: the distro (Ubuntu 22.04) `libopenal1` has no PipeWire/PulseAudio backend
(silent on a PipeWire-only device) and hard-links its sndio backend (`libsndio.so.7` + `libbsd` +
`libmd` must then be bundled). A from-source OpenAL Soft (gcc-12) with
`-DALSOFT_BACKEND_PIPEWIRE=ON -DALSOFT_BACKEND_PULSEAUDIO=ON -DALSOFT_BACKEND_ALSA=ON` adds the
backends as `dlopen`ed extras. At runtime `ALSOFT_DRIVERS="${ALSOFT_DRIVERS:-alsa}"` picks the
backend order and `ALSOFT_CONF="$GAMEDIR/alsoft.conf"` makes a bundled config actually load. Don't
build a closed-source audio library in (BASS opens its own audio device; `-DPOPLIB_WITH_BASS=OFF`).

**Allegro**: Allegro 4's `ALLEGRO_MODULES` is ignored as root, DIGMID needs `ULTRADIR`, Westonpack
breaks `XDG_RUNTIME_DIR` for PipeWire/Pulse, and crackling needs bigger ALSA fragments — all in
§1.7.16. Allegro 5's SDL audio driver needs the `buffer_size` patch (§1.7.16).

**`SDL_AUDIODRIVER` is a no-op for engines that never initialize SDL's audio subsystem at all** —
don't assume every port needs it set just because a reference/upstream script sets it. Confirmed
case: a PopLib/SDL3-based port's upstream script set `SDL_AUDIODRIVER=alsa` under a "both SDL and
OpenAL probe PulseAudio" theory, but the actual engine only ever calls
`SDL_Init(SDL_INIT_VIDEO)` — all audio goes through OpenAL directly (`alcOpenDevice`). Verify by
reading the actual `SDL_Init()` call's flags before trusting an upstream env var as load-bearing;
see §2.8's methodology note for the general lesson this exemplifies.

## 2.4 Filesystem / process assumptions

**Bulk game data ships as a `.tar.gz` extracted on first launch, by default, from the first
draft** *(project convention; loose files are valid too)*. Any port whose data is more than a handful of loose files (levels, patch sets, fonts,
themes, compiled assemblies, mod data) ships one archive (`gamedata.tar.gz`); leave the binary,
`libs.aarch64/`, `licenses/`, the control `.ini` (tuned often during testing), any folder that must
be visible right after install (a user's drop folder for their own game files, a bind-mount
target), and anything the script needs before extraction outside it. Reviewers flag hundreds of
loose files (382 on one port, 337 → 8 on another); SD cards with large clusters also make thousands
of small files expensive (8,500 files showed as 1.2GB with 128KB clusters). Count before calling a
package done: `find <gamefolder> -type f | wc -l`.

**Create the archive with ownership stripped and no symlinks**:
```bash
tar czhf gamedata.tar.gz --owner=0 --group=0 --numeric-owner <data dirs>
```
- `--owner=0 --group=0 --numeric-owner`: a plain `tar czf` bakes in the build machine's UIDs/GIDs;
  a CFW that runs the port unprivileged (Knulli/RGCubeXX) then fails to `chown` every file
  (`Cannot change ownership to uid N, gid N: Operation not permitted`), and BusyBox tar aborts the
  whole extraction. Invisible on any CFW that runs ports as root, so one good device test isn't
  proof.
- `h` (`--dereference`): BusyBox tar can't create (relative) symlinks (`tar: can't create
  symlink`), and not every CFW allows `ln` at all. Resolve symlinks, and run `find -type l` over
  the whole assembled package (loose files and archive contents) before calling it done.
- **Empty directories don't exist in git**: if the game needs an empty folder (e.g. `data/temp`),
  ship a `.gitkeep` in it (a missing one made every player render white in one port).

**Extract with the canonical block, never `tar -xzf`** (some BusyBox `tar` builds have no `-z`:
`tar: invalid option -- 'z'`, real failure on muOS; `gunzip`/`gzip` are required tools on every
CFW). `--no-same-owner` is a second, independent guard against the ownership failure above. No
per-CFW branching (`if muOS ...`): this form works everywhere.
```bash
ARCHIVE_FILE="gamedata.tar.gz"
if [[ -f "$ARCHIVE_FILE" ]]; then
    pm_message "Extracting game data, this can take a few minutes..." --title "Please wait"
    if ! gunzip -c "$ARCHIVE_FILE" | tar --no-same-owner -xf -; then
        pm_show_error "Could not extract $ARCHIVE_FILE. Check that there is enough free space, then launch again." --title "Extraction failed"
        exit 1
    fi
    $ESUDO rm -f "$ARCHIVE_FILE"
elif [ ! -f 'gamedata/<some-known-file>' ]; then
    pm_show_error "No game data found and $ARCHIVE_FILE is missing. Reinstall the port." --title "Game data missing"
    exit 1
fi
```
The `elif` checks one real file that's always present in a complete copy (not just the
directory), so an interrupted extraction is caught too.

**Archives must stay under 100MB each if the port lives in a git repo**: GitHub hard-rejects any
blob over 100MB on push (`GH001: Large files detected`), whatever the branch. Split along a real
content boundary (e.g. audio+images in one archive, video+gamedata in another), not `split -b`, so
each archive is independently valid and needs no reassembly, and extract them in sequence:
```bash
ARCHIVE_FILES=("data-part1.tar.gz" "data-part2.tar.gz")
if [[ -f "${ARCHIVE_FILES[0]}" || -f "${ARCHIVE_FILES[1]}" ]]; then
    pm_message "Extracting game data, this can take a few minutes..." --title "Please wait"
    [[ -d 'data/' ]] && $ESUDO rm -fR 'data/'
    if ! { gunzip -c "${ARCHIVE_FILES[0]}" | tar --no-same-owner -xf - && gunzip -c "${ARCHIVE_FILES[1]}" | tar --no-same-owner -xf -; }; then
        pm_show_error "Could not extract the game data. Check that there is enough free space, then launch again." --title "Extraction failed"
        exit 1
    fi
    $ESUDO rm -f "${ARCHIVE_FILES[@]}"
elif [ ! -d 'data/' ]; then
    pm_show_error "No data directory found and the archive files are missing. Reinstall the port." --title "Game data missing"
    exit 1
fi
```
A single opaque file over 100MB (a PhysFS `.smod`, a stored APK) can't be content-split: byte-split
it (`split -b 60000000 -d file file.part`) and `cat file.part* > file` once at first launch behind a
`pm_message`. Don't reach for Git LFS or a Release asset first. **If the oversized blob was already
committed, replacing it doesn't help** (the push still carries it in history); if the branch was
never successfully pushed, squash it to one clean commit from the current tree
(`git reset --soft $(git merge-base <default-branch> <branch>)`, recommit, plain
`--set-upstream` push).

**Ship what the game needs, in the form it expects.** Use the project's `make install
DESTDIR=...` output, not the raw source data tree (2000 files became two archives on one port).
Shareware data that was made to be redistributed ships pre-extracted (converted at packaging time),
not as an installer for the device to unpack; the player's full version in `gamedata/` overrides
it, and shareware content limits still apply. A nested `.zip` inside the data is fine if that's how
upstream ships it — but drop files the port doesn't need.

**Redirect saves with `bind_directories`/`bind_files`, never `export HOME=...`.**
`bind_directories <target> <source>` is for a directory the game creates under `$HOME`,
`bind_files <target> <source>` for a single dotfile. Both bind-mount (falling back to `ln -sfv` when
`PM_CAN_MOUNT=N`, e.g. RetroDECK, which can't mount without root; exFAT homes can't use symlinks,
hence the bind). **Both silently no-op unless the exact source path (`$2`) already exists**
(`echo "no directory/file found at $2"`, no error): `bind_directories` only `mkdir -p`s the target,
`bind_files` only `touch`es the target. Pre-create the exact source: `mkdir -p
"$GAMEDIR/conf/.gamename"` (not just `$GAMEDIR/conf` — the `dreamchess` port silently never mounted
because of this), or `mkdir -p "$GAMEDIR/conf" && touch "$GAMEDIR/conf/.gamename_prefs"`. A
harmless `umount: can't unmount ...: Invalid argument` line precedes a first successful mount.
`export HOME=` redirects everything resolved through `$HOME` for the whole process tree. Before
adding any redirect, grep the game for where it actually writes: many engines have a native option
instead (`-fs_userpath`, `-Djava.util.prefs.userRoot`, `XDG_CONFIG_HOME` used as-is, run-in-place
builds), and some games write only inside their own folder and need nothing. A library name
mismatch can be bridged the same way (`bind_files "$GAMEDIR/libs.${DEVICE_ARCH}/freetype6.so"
"$FREETYPE_LIB"`, §1.7.11).

**A bare-`fopen()`-only engine (common in older DOS-era codebases with a straight SDL2 bolt-on)
needs a guarded `chdir()` inside the binary's own `main()`**, not a launch-script `cd`, if its
assets live in a subfolder the code assumes is cwd:
```cpp
#include <filesystem>
std::error_code ec;
if( std::filesystem::is_directory( "assets", ec ) )
{
    std::filesystem::current_path( "assets", ec );
}
```
This is a no-op when `assets` doesn't exist relative to cwd (doesn't break existing IDE/dev
debug-directory setups), and it means the launch script can stay in the standard
`cd $GAMEDIR && ./$BINARY` form. Doing the `cd` in the launch script instead works but gets
fragile fast: any other file the binary needs to find via an *absolute* `$GAMEDIR` path (a bundled
soundfont, a control-mapping file) still needs to resolve correctly regardless of which folder the
script `cd`d into — handling it inside the binary keeps cwd-relative game assets and
`$GAMEDIR`-absolute launch-script-managed files from fighting each other. (Under Westonpack the cwd
is `/tmp/weston`, §1.7.4.)

**DOS/Windows-era code on a case-sensitive Linux filesystem** (three real crashes in one port,
`amuletsarmor`): grep every string literal used as a path for `\\` separators (`"AAMUSIC\\%s.MUS"`
just fails to open on Linux); add a case-insensitive retry (e.g. uppercase fallback) to **every**
independent low-level file-open path, not just the main wrapper (a separate `FileGetSize()` with its
own `fopen()` returned 0, a NULL load, then a crash); and don't assume `#ifndef NDEBUG` code is only
a debug convenience (a loose-file fallback the Release build needed on Unix was gated off). All of
this worked by accident on the exFAT ports partition of one CFW and failed on case-sensitive ext4
on another — so does a mod referencing `op2_art.bmp` for a shipped `OP2_ART.BMP`. Normalize
references to the shipped filenames; never ask players to rename their own files. A temporary Debug
build that turns on the engine's own call-stack tracking can turn a silent segfault into a
file/line report.

**Architecture assumptions in older code:**
- **`#ifdef __x86_64__` used to mean "64-bit pointers"**: aarch64 falls into the 32-bit branch
  (Newton physics' `dgMemory.h` crashed in `NewtonCreate`). Grep for it and use `__LP64__`; also
  look for x86 `cpuid` inline asm, SSE flags and intrinsics (give them scalar or NEON fallbacks),
  x86-only JIT backends, NVIDIA Cg.
- **Upstream `-march=native` in CMake must go**: under a QEMU chroot it can select CPU features
  the real cores lack. Same class as the shim's `-mcpu` SIGILL (§1.7.12): build generic
  `-march=armv8-a`.
- **Plain `char` is unsigned on aarch64** (signed on x86_64). `-fsigned-char` is only justified by
  a real symptom, never added pre-emptively. Real symptoms seen: a build error (`narrowing
  conversion of '-1' from 'int' to 'char'`, ZQuestClassic), heap corruption traced to signed-char
  assumptions (WolfensteinRPG-RE, where a two-spot fix was insufficient and the blanket flag was
  confirmed by A/B), and a serialization library dispatching on `std::is_unsigned<char>`: cereal's
  JSON archive (RapidJSON) calls `GetUint()` on negative `char` values in `mission.json` and asserts
  `rapidjson internal assertion failure: data_.f.flags & kUintFlag` only on ARM (raceintospace,
  RG351V). That signature — an unsigned-read assertion that only reproduces on ARM — is the cue.
- **64-bit type-size bugs in old bundled libraries**: an old Irrlicht 1.x's bundled libpng used an
  8-byte `png_uint_32` on aarch64, giving `Invalid image width` for every PNG; build against the
  system libpng instead.
- **Fixed-size or narrowing assumptions from MSVC**: GCC rejects `switch` case labels like
  `0xFFCC0000` against an `int` (narrowing); cast with `(int)`.
- `getpwuid(getpid())` (a PID passed as a UID) finds no home directory; use `getuid()`.
- An engine that `dlopen`s a bare unversioned name (`libvorbisfile.so`) needs exactly that filename
  bundled.
- Garbage-collected runtimes that rely on their own `SIGSEGV` handler (SBCL) break when the GPU
  driver or SDL installs another one.

**Global variable names can collide with libc/POSIX function declarations** when cross-compiling
an old Windows/DOS-era codebase for Linux — e.g. a global `unsigned char pause` compiles fine on
Windows and fails on Linux with `redeclared as different kind of entity`, because `<unistd.h>`'s
`pause()` function gets pulled in transitively. Pure naming collision; rename the variable. Worth
a quick grep (`pause`, `read`, `write`, `index`, `yield`, `y1`, `j0`, and similar common libc/POSIX
names) on any first Linux cross-compile of an older codebase hitting this error class.

**Windows/MinGW-only projects bundling their own SDL2 dev kit** (`defblade`): a bundled `-Iinclude`
always wins over `pkg_check_modules`'s `-isystem` dirs (GCC searches `-I` before `-isystem`
regardless of order), and CMake silently drops a redundant `-I/usr/include`, so you can't
out-prioritize the bundled headers. Copy the single-header dependencies the project needs into their
own include root instead. MinGW's headers also pull in `<cstring>` transitively where glibc doesn't
(a real missing `#include <cstring>`). Python helper scripts written on Windows may assume CRLF line
endings (fix the script, not the data) and call `python` (only `python3` exists: put a `python`
shim on `PATH` for the build).

## 2.5 Debugging (a completely separate skill from packaging, but worth having ready)

- **Always get a stack trace or thread dump before touching code.** `gdb -batch -ex run -ex bt
  -ex quit --args ./program` for a reproducible crash; `gdb -p <pid>` (e.g. `gdb -p $(pgrep -x
  program)`) then `thread apply all bt` for a hang; `gdb ./program core -ex bt -ex quit` for a
  core dump; `coredumpctl list` / `coredumpctl gdb <pid>` if systemd-coredump is active. Enable
  core dumps if needed: `ulimit -c unlimited` or `echo "core" > /proc/sys/kernel/core_pattern`.
  Reading a segfault: a NULL (or near-NULL) fault address means a NULL dereference; a PC in
  unmapped memory means a call through a bad pointer or an unloaded library (e.g. SDL2 already
  `dlclose`d, §1.7.12); a mangled frame chain means stack corruption. For intermittent crashes,
  loop the run: `while true; do gdb -batch -ex run -ex bt --args ./program 2>&1 | grep -A30
  "SIGSEGV\|SIGABRT\|SIGFPE" && break; done`.

- **On a PortMaster handheld, assume GDB is present and reach for it — don't fall back to
  log-only debugging out of caution** (present on AmberELEC and the other major CFWs). The proven
  pattern for getting a real backtrace out of a launch script (the crash only reproduces under the
  exact environment the script already built — `LD_LIBRARY_PATH`, `SDL_GAMECONTROLLERCONFIG`, gl4es
  sourcing, etc. — so GDB has to run as a temporary substitution for the script's own final launch
  line, not a bare separate invocation):
  1. Ship a small `gdb_commands.txt` alongside the binary:
     ```
     set pagination off
     run
     bt
     quit
     ```
     (`set pagination off` matters even under `-batch` — without it a long backtrace can stall on
     a `---Type <return> to continue---` prompt with no TTY to answer it.)
  2. Temporarily replace the launch script's final `./$BINARY` line with:
     ```bash
     gdb -batch -x "$GAMEDIR/gdb_commands.txt" --args "./$BINARY" > "$GAMEDIR/gdb_backtrace.txt" 2>&1
     ```
     Redirect to its own file, not the outer `tee "$GAMEDIR/log.txt"` capture — a per-command `>`
     takes over that command's stdout/stderr for its duration even inside an already-
     `exec > >(tee ...)`-redirected script.
  3. Have the tester re-run once, then read back `gdb_backtrace.txt`.
  4. **This is temporary debugging instrumentation, not something to ship.** Pull both the
     `gdb`-wrapped line and `gdb_commands.txt` back out once the crash site is identified and
     fixed — a real submission's launch script should read like a normal, unremarkable one.
  Under Westonpack the game runs inside westonwrap: see §1.7.5 for the wrapper-script trick.

- **GDB limits on these devices**: **no hardware watchpoints** ("Unable to determine the number of
  hardware watchpoints available"), so a `watch` silently falls back to software single-stepping
  and the game looks frozen for minutes. A `watch` on a local is deleted when its frame returns
  (watch a raw address saved in a convenience variable instead). What works: ordinary breakpoints
  at each suspect function's return with a `commands` block that prints the value of interest
  (full speed, narrows the culprit in one pass), then temporary `printf` instrumentation and a
  rebuild. Breakpoints inside a library that isn't loaded yet need `set breakpoint pending on`
  first (or they're silently dropped with no TTY) and the exact source path from a real backtrace
  (`../libweston/compositor.c:9749`, not `compositor.c`). Breakpoints inside an `LD_PRELOAD`
  library's constructors fail ("Function not defined"). A hung process's buffered stdout can be
  flushed with `gdb -p <pid> -batch -ex "call (int)fflush(0)"`.

- **Direct SSH access to the device settles in minutes what log-pasting can't.** When a bug
  survives several well-reasoned fixes, `strace`/`ltrace`/`gdb` on the actual hardware is the
  fastest way to tell a real lead from a coincidental correlation: on BlipNBlup two plausible
  theories (a wrong Mali driver build; a broken EGL read surface, after `eglGetCurrentSurface`
  returned `NULL`) were both disproven live before a breakpoint on the failing `glGenBuffers` found
  the real cause (§2.2). Device-session workflow facts:
  - **Launches over SSH differ from launches from the frontend**: no controller DB (Knulli's
    configgen writes `/tmp/gamecontrollerdb.txt` only for ES launches), different memory state,
    missing `XDG_RUNTIME_DIR`/`WAYLAND_DISPLAY`/`DISPLAY` (ROCKNIX: `/var/run/0-runtime-dir`,
    `wayland-1`, `:0.0` — copy them from a running process's `/proc/<pid>/environ`), which changed
    behaviour (texture IDs came back -1). Bugs seen only over SSH (gamepad=0 on Knulli, a dArkOS
    freeze) were artifacts; re-check from the frontend.
  - **Stop the frontend before an SSH test**, or both processes fight over the display (`ERROR:
    Could not queue pageflip: -16`, EBUSY): AmberELEC `systemctl stop emustation`, ArkOS/dArkOS
    `sudo systemctl stop emulationstation`, ROCKNIX `systemctl stop essway.service`, Knulli
    `/etc/init.d/S31emulationstation stop`. dArkOS SSH logs in as `ark` (needs `sudo`).
  - Password SSH from a chroot without a pty: `SSH_ASKPASS=<script that echoes the password>
    SSH_ASKPASS_REQUIRE=force ssh -o PreferredAuthentications=password ... < /dev/null`; for
    `scp`, export the two variables in a wrapper (inline prefixes fell back to a missing system
    askpass). `sshpass` doesn't work there.
  - **stdio is fully buffered through `ssh ... > file`**, so a crash loses the log's tail; wrap
    the remote command in `stdbuf -oL -eL`.
  - **ROCKNIX's `paste` uploads its stdin to dpaste.com and prints a public URL** (not coreutils
    `paste`); never pipe into it (doing so once published a device's input-device list). `pkill -f
    <pattern>` from SSH can match its own remote shell and kill the session (use a `[b]racket`
    pattern or a PID); `grep` over `/proc/*/cmdline` matches the SSH command itself (use `pidof`).
    AmberELEC's BusyBox lacks `setsid`, `script` and `cmp`, and its `pgrep -x` missed names.
  - **Screenshots**: ROCKNIX `XDG_RUNTIME_DIR=/run/0-runtime-dir WAYLAND_DISPLAY=wayland-1 grim
    out.png`, AmberELEC `fbgrab`, dArkOS neither. Look at the capture before claiming success.
    DRM debugfs (`/sys/kernel/debug/dri/0/state`, `.../summary`) shows which process owns the
    visible plane.
  - **Never overwrite a `.sh` while it's running on the device**: bash reads a running script by
    byte offset, so it resumes mid-file in the new content — relaunching the game without
    gptokeyb2 (looks like "Start+Select doesn't work") or failing with a fragment like `orm_helper:
    command not found`. Check `pgrep` first. A related trap: a hand-copied script crashes once on
    its first runtime download with a garbage fragment (`ntime_check: command not found`, then
    `syntax error near unexpected token 'fi'`): `runtime_check` makes harbourmaster insert a
    `# PORTMASTER: <zip>, <script>` signature at line 2 of every installed script lacking one,
    shifting the running script. A real install signs the script up front; when hand-copying, keep
    the device's existing line 2. Never "fix" this in the port.
  - Inject real gamepad presses for automated tests by writing `input_event`s
    (`struct.pack("llHHi", ...)`) to the pad's `/dev/input/eventN` (BTN_SOUTH = A on RG351V; take
    button ids from ES's `es_input.cfg`).
  - Exit code 137 during a test usually means someone pressed Start+Select (the kill switch).
  dArkOS's `perfmax` launch image can stay on the display plane until the next client presents.
- **Use device access for diagnosis; leave functional testing to the porter.** A chroot run or an
    agent's own launch proves nothing about whether the port "works" for players.

- **Prove the game presents frames**: `strace -tt` the game and count
  `DRM_IOCTL_MODE_PAGE_FLIP\|DRM_IOCTL_MODE_SETCRTC\|DRM_IOCTL_MODE_ATOMIC`. One hit over 30 s is
  a single modeset with nothing presented; a climbing count is real output. `strace` also showed a
  "black screen" client simply exiting normally (`exit_group(0)`).

- **Memory and OOM**: a silent mid-load death or a whole-device freeze on a 1GB device is usually
  the OOM killer: `dmesg | grep -i oom` (`Out of memory: Killed process ...`). Measure peak RSS in
  the chroot with a headless load-and-quit run where the engine has one (ZQuestClassic's
  `-headless -load-and-quit`), and find the big allocation with an `LD_PRELOAD` malloc logger
  (allocations above a threshold, `backtrace_symbols_fd`, resolved with `addr2line` against the
  unstripped binary): one 823MB `std::vector::resize` explained a 1GB-device freeze. Remember
  libmali counts GPU memory in RSS (§2.2). Cap JVM heaps (`-Xmx`).

- **Performance on weak GPUs: measure with a once-per-second timing log, never per frame** (per-frame
  logging of 250-300 lines/s itself dropped a device to 1-2 fps). Bracket one suspect stage at a
  time, fix only what the numbers show, re-measure. Real findings from DustRacing2D on RG351V: an
  unclamped variable physics timestep caused the "spiral of death" (cars flying, spinning; clamp the
  delta to ~3× the tick interval); shadow passes doubled draw calls; per-glyph text rendering with a
  default-on shadow doubled every HUD glyph; one decorative tree type spawned 20-40 child objects
  (draw calls) each. Split GPU from CPU time by bracketing a stage with `glFinish()` plus
  `SDL_GetTicks()` (the working fallback when GL tracing tools can't attach, §3.3).

- **glibc's fortified buffer-overflow checks (`*** buffer overflow detected ***`) are not caught
  by ASan.** A clean ASan run on a debug build is not proof the overflow doesn't exist in the
  Release build — this is glibc's own `_chk` function family (`__strncpy_chk`, `__memcpy_chk`,
  `__sprintf_chk`), a completely separate check. Investigate in order: (1) get the stack trace —
  the `__chk_fail` frame's caller names the exact function and file; (2) read the source at that
  call site; (3) look for a sub-object vs. parent-object `sizeof` mismatch — the destination
  pointer likely points into a struct member or array element, but the size/copy-length
  expression uses the parent object's size, which the compiler doesn't see. Valgrind is a good
  second opinion: `valgrind --tool=memcheck --num-callers=30 ./program`.

- **For a hang, dump every thread's backtrace, not just the one that looks frozen** — thread A
  being stuck is frequently caused by thread B holding a lock and never releasing it
  (`gdb -p <pid>`, then `thread apply all bt`). Per-thread state triage: `futex`/`__lll_lock_wait`
  = mutex wait (scroll up to see which mutex/caller); `pthread_cond_wait` = condvar wait;
  `clock_nanosleep`/`poll`/`read` = usually benign I/O wait, not the culprit; identical program
  counter across repeated `continue`+`bt` = confirmed spin loop, not a block. Near-zero CPU with
  threads parked in futex waits means deadlock; CPU pinned near 100% with no progress means
  livelock/infinite loop (`perf top` or `perf record`/`perf report` to see where cycles go — only
  where the kernel supports perf, §3.3).

- **Classify the deadlock once threads are stuck**: **Class A** (mutex contention, one holder) —
  most common root cause is a recursive-mutex assumption ported from Windows: `pthread_mutex_t` is
  non-recursive by default on Linux, but Windows mutexes are recursive by default, so code doing
  `lock(); helper(); unlock()` where `helper()` also locks the same mutex self-deadlocks only on
  Linux; fix with `std::recursive_mutex` or restructure lock boundaries. **Class B** (classic
  ABBA) — Thread A holds mutex 1 waits on mutex 2, Thread B holds mutex 2 waits on mutex 1, both
  seen in `__lll_lock_wait` on different futex words; fix by enforcing a single, consistent lock
  acquisition order across all threads. **Class C** (signal-induced hang) — SIGINT/SIGTERM
  delivered but a handler just sets a flag nothing polls (e.g. SDL installs its own SIGINT handler
  that just sets an internal flag).

- **Common mistakes**: fixing the wrong side (if Thread A can't acquire a lock Thread B holds, a
  timeout on A's wait just converts a hang into silent corruption — understand why B holds too
  long); "verifying" a fix under a different trigger than the original; blaming your own code
  before testing an unrelated, known-good consumer of the same shared dependency (hundreds of
  other ports working on the same driver rules the driver out); and missing a recent CFW/driver
  update as the cause (the dArkOS 08/27/2026 libmali update broke every `drm`-backend Westonpack
  port at once via a symbol-visibility change, §1.7.4).

- **Porting to a newer library major version (e.g. SDL2 to SDL3) that crashes/hangs**: the root
  cause is almost always a changed return-type convention (`bool` vs `int` success values) or a
  renamed/restructured struct field (SDL2's `event.key.keysym.scancode` became SDL3's
  `event.key.scancode`; `SDL_atomic_t` became `SDL_AtomicInt`; `char*` fields became `char[32]`),
  or an enum renamed/removed (grep the new headers) — diff the old and new header signatures for
  the exact failing call site, then check every call site actually handles the new convention
  correctly.

- **Tracing without rebuilding**: `strace -f -e trace=open,openat,read,write ./program` for
  file/device access, `strace -f -e trace=connect,send,recv ./program` for network,
  `ltrace` for library calls; CPU and GPU profiling tools are in §3.3 (check kernel support first).
  For Java, a `-javaagent` probe (§1.7.15); for Westonpack, `LD_DEBUG=bindings` through the
  `strace=` hook (§1.7.5).

- **When logging beats a debugger**: when you can't attach a debugger, or when the debugger itself
  is the bottleneck (no hardware watchpoints). Use sparingly (one well-placed log pair beats ten
  scattered guesses, since each log line costs a full edit/compile/run/wait cycle GDB skips
  entirely): `SDL_Log("[phase] entering render loop");` bracketing the suspected region.

- **Isolate multi-part fixes.** If two changes land in the same test round, you don't know which
  one mattered — OpenSoldat added an unneeded `SDL_VIDEO_GL_DRIVER` override alongside the real fix
  (shipping the missing gl4es folder), and the override later turned out to break GL loading. Change
  one variable per round when a symptom persists, and use a `git worktree` sibling checkout to A/B
  "does reverting this subsystem fix it" without disturbing uncommitted work.

- **Chroot-side checks that are legitimate**: image/audio *decode* needs no GPU/display/input, so a
  tiny headless C program linked against the exact `.so` being shipped (`IMG_Load`, `Mix_Init`,
  `Mix_LoadMUS` on the real asset files) catches real bugs (a TGA variant one SDL2_image build
  couldn't decode, a wrong `MIX_InitFlags` value). Running the actual game headless
  (`SDL_VIDEODRIVER=dummy`) to reproduce a reported crash is forensics, not testing — ask the user
  before doing it.

- **All chroot/dev-machine verification is build/package-only, never functional proof.** Neither
  a chroot nor "it compiled" proves a port works — real GPU/KMS/input access doesn't exist there.
  Every actual functional check (does the window open, does gptokeyb2 move the cursor, does audio
  play) happens on a real device in a separate pass. Never claim or imply "tested" in a PR or
  README based on build-only work — the most likely gap for an AI specifically, since an AI has
  no device to test on at all. Report what was actually exercised ("reached the main menu"), not
  "works"; if testers keep finding crashes in untried modes, automate the testing (§1.7.8).

## 2.6 Packaging gaps beyond what Part 1 already covers

**Don't trust a NuGet/packaging layer's bundled license file as automatically correct** for the
library it's shipping — go to the actual upstream project's repo for the real license. A real
case: a package's included `LICENSE` file only covered a small BSD-licensed sub-component, while
the actual library being shipped is LGPL upstream. For distro libraries, use the Debian-format
`/usr/share/doc/<package>/copyright`. If a dependency's upstream has vanished, say so rather than
guessing a license.

**Bundled `.so` files need to be flattened to one real file, not a symlink chain.** A dev
machine's install often has `libfoo.so -> libfoo.so.2 -> libfoo.so.2.0.6`; copying that chain
into a port can silently break across zip/scp to the device (and ships two copies of one library).
Resolve it and ship one real file, named to match the exact SONAME the binary's own dynamic
section actually requests (`readelf -d`), not whatever name the dev machine happened to use. The
same goes for every other file in the package: no symlinks anywhere (`find <package> -type l` must
come back empty, archives included).

**A screenshot must always be a real capture from the actual device or build.** Never generate,
crop, or fabricate one, and never substitute existing game art as a stand-in. Leave it for whoever
has the device.

**`port.json`'s `store` field is a list of objects, not bare URL strings** — see §1.2 for the real
schema (`name`/`gameurl`/`developerurl`); this was flagged directly on a live PR review.

**Sanity-check the package size against upstream's own release** (a 400MB+ port of a game whose
Windows release is 265MB means something is duplicated or unstripped).

**Keep `README.md` and `testing_thread.txt` in sync with the `.ini`.** Whenever button assignments
change, re-check both controls tables against the actual `.ini` values, not memory. Write
`testing_thread.txt` from the template (§1.5), not from another port's copy.

**When modelling a file on real merged ports, check enough of them to spot the outlier.** One
example can be old, non-conformant or a special case (a stray `<players>` tag in `gameinfo.xml`; the
mono runtime key being arch-suffixed while ~30 others aren't; a reference script using a wrong
Godot pack flag). The field lists in §1.2-§1.3 are authoritative; reference ports aren't.

**Building a new runtime squashfs** (e.g. the Qt6 runtime, §1.7.17):
- **While testing on devices, ship the runtime as a plain folder** inside the port and
  `mount --bind` it to the exact path the squashfs will later mount at, so nothing else in the
  script changes. Rebuild-and-redeploy of a squashfs for every added `.so` is real friction.
- Build the final image with `mksquashfs <dir> <file>.squashfs -comp gzip -no-xattrs` (many
  device kernels lack XZ and/or `CONFIG_SQUASHFS_XATTR`; confirm with `unsquashfs -stat` showing
  "Xattrs are not stored").
- **`mount: ... failed: Invalid argument` has at least four unrelated causes**: no XZ support, an
  xattr table the kernel rejects, a type-less `mount` probing FAT/exFAT and never reaching squashfs
  (`dmesg`: `exFAT-fs (loopN): invalid boot record signature`), and — the one that actually
  mattered — **a stale mount-point directory** that had absorbed many mount/umount cycles of
  different builds during testing. Read `dmesg` right after the failure and test-mount to a brand
  new directory first. (The stale-directory case can't happen for players.) Real ports' scripts use
  plain `mkdir -p` / `umount "$file" || true` / `mount "$file" "$dir"`, no `-t`.
- Submitting it: squashfs files plus a `runtimes.json` entry in `PortsMaster/PortMaster-New/runtimes/`
  with a **generic** key (`"frt_3.3.4.squashfs": {"name": ..., "default": "aarch64", "arch":
  {"aarch64": "frt_3.3.4.aarch64.squashfs", ...}}`). harbourmaster has no mount logic: every port
  mounts its own runtime. A shared runtime may bundle more generously than a port (it's downloaded
  once): favour features (e.g. keep ICU) over size, but still never GPU/display-stack libraries.

**Exclude libraries per device class**: libraries the device's GPU/display stack links (§1.1),
`libpulse.so.0` (its `libpulsecommon` hard-needs X11), and anything a `readelf -d` walk shows is
only reachable from dead code (eliminate it at the source, §1.1).

## 2.7 CFW shell / runtime environment contract

Every launch script relies on a real environment the CFW guarantees — worth knowing what's
actually load-bearing vs. merely convenient.

**Sourcing chain**: `control.txt` sources `device_info.txt`, then `funcs.txt` (which sources
`PortMasterDialog.txt`), so everything below exists once `source $controlfolder/control.txt`
returns. (`PM_FUNCS_VERSION=3`, `DEVICE_INFO_VERSION=0.1.15` as of 2026-10.)

**Environment variable contract**:

| Variable | Content |
|----------|---------|
| `$DEVICE_ARCH` | `aarch64`, `armhf`, or `x86_64` |
| `$DEVICE_CPU` | SoC identifier (`rk3326`, `rk3566`, `h700`, etc.) |
| `$DEVICE_NAME` | Human-readable device name |
| `$DEVICE_RAM` | RAM in GB (integer) |
| `$DISPLAY_WIDTH` / `$DISPLAY_HEIGHT` | Real current screen resolution in pixels (always set) |
| `$DISPLAY_ORIENTATION`, `$ASPECT_X` / `$ASPECT_Y` | Orientation and aspect ratio |
| `$ANALOG_STICKS` | Number of analog sticks (branch on it for stickless devices, §1.8.1) |
| `$CFW_NAME` / `$CFW_VERSION` | CFW identifier (matched by `mod_${CFW_NAME}.txt`, `libgl_${CFW_NAME}.txt`) and version |
| `$CFW_GLIBC` | Detected glibc as digits (e.g. `238` = 2.38 on AmberELEC, `241` on ROCKNIX) |
| `$PM_VERSION` | PortMaster version |
| `$DEVICE_HAS_ARMHF` / `_AARCH64` / `_X86` / `_X86_64` | Which userlands exist |
| `$ESUDO` | `""` without sudo, else `sudo --preserve-env=<allowlist of SDL/controller vars>` (or `doas`) |
| `$ESUDOKILL` / `$ESUDOKILL2` | CFW-specific kill flags baked into `$GPTOKEYB`/`$GPTOKEYB2`; never used directly |
| `$GPTOKEYB` / `$GPTOKEYB2` | Multi-word command lines (`$ESUDO env LD_PRELOAD=.../libinterpose.$DEVICE_ARCH.so .../gptokeyb2 $ESUDOKILL2`); never quote them |
| `$sdl_controllerconfig` | The single-line SDL mapping `get_controls` built for this device |
| `$directory` | Base path for ports storage |
| `$PM_CAN_MOUNT` | `Y` or `N` — squashfs/bind mounting support |
| `$TASKSET` | `taskset` command for CPU affinity (or empty) |

`get_controls` detects the pad by `/dev/input/by-path/` entries, applies device-specific quirk
`sed`s to a temp copy of the controller DB, and builds `$sdl_controllerconfig` (plus
`$ANALOGSTICKS`/`$LOWRES`). Ports never touch `$DEVICE`/`$param_device` themselves.

**Helper functions (`funcs.txt`)**: `bind_directories`/`bind_files` (§2.4), `pm_message`/
`pm_show_error`/`pm_message_close` (§1.7.13), `pm_platform_helper "$GAMEDIR/$BINARY"` (closes any
message card; a CFW's `mod_*.txt` can override it, e.g. ROCKNIX's sway fullscreen helper; otherwise
a placeholder), and `pm_finish` (the last line of every script: kills gptokeyb/gptokeyb2 with
`pkill -9 -f`, closes dialogs, restarts `oga_events` in the background, clears the TTY with
`printf "\033c"`; never kill gptokeyb2 yourself). `PortMasterDialog.txt` drives pugwash over named
pipes (`/dev/shm/portmaster/pm_input`/`pm_done`) and saves/restores an allowlist of SDL env vars
around it (`SAVE_CLEAN_ENV`/`SAVE_LD_LIBRARY_PATH`) — which is why logs can show `$ESUDO env
$SAVE_CLEAN_ENV ... $controlfolder/pugwash` lines the port never wrote. Ports don't call it
directly. A local clone of `PortsMaster/PortMaster-GUI` (`PortMaster/funcs.txt`, `control.txt`,
`device_info.txt`, `libgl_*.txt`, `harbourmaster/harbour.py`) is the ground truth for every helper;
read it rather than inferring a function's name or behaviour from another port's call site (a
guessed `bind_file` — singular — doesn't exist).

**Architecture detection**: PortMaster probes the dynamic linker (`/lib/ld-linux-aarch64.so.1` →
aarch64, `/lib/ld-linux-armhf.so.3` → armhf, `/lib/ld-linux-x86-64.so.2` → x86_64).

**Where ports live per CFW** (for SSH work): ROCKNIX/AmberELEC `/storage/roms/ports`, muOS
`/mnt/mmc/ROMS/Ports` (+ `/mnt/mmc/ports`), Knulli `/userdata/roms/ports`. PortMaster's control
folder is the first of `/opt/system/Tools/PortMaster/`, `/opt/tools/PortMaster/`,
`$XDG_DATA_HOME/PortMaster/`, `/roms/ports/PortMaster`.

**Shell baseline**: GNU Bash 4.x+ (`[[ ]]`, `${var,,}`, process substitution, arrays, `trap`) is a
hard CFW requirement — BusyBox ash/dash would break hundreds of ports. **Don't assume full GNU
userland beyond that, though**: PortMaster's guide asks CFWs for GNU coreutils, but real devices
ship BusyBox pieces (BusyBox `tar` without `-z` on muOS; AmberELEC's BusyBox has no `setsid`,
`script` or `cmp`, and its `pgrep -x` misbehaves; `nm`/`readelf`/`objdump` are absent on some CFWs —
grep a binary for a symbol instead; ROCKNIX's `paste` is a pastebin uploader). Write scripts with
the canonical patterns in this document. **Required tools** every CFW provides: `tar`, `unzip`,
`gunzip`/`gzip`, `mount`/`umount`, `sudo` or `doas`, `systemctl` (it must tolerate a missing
`oga_events`). Present but not universal: `dos2unix`, `xdelta3` (binary delta patching), `dialog`
(TUI menu selection), `rsync`, `7z`/`7za` (PortMaster bundles `7zzs` as primary, these are
fallback), `swaymsg` (ROCKNIX), `pw-metadata` (PipeWire tuning), `getconf`. Assume absent unless
bundled: `innoextract`, `ffmpeg`, `ar`. Python 3 with `lzma` is required by harbourmaster itself.

**`/dev/uinput` is required** — gptokeyb(2) needs it, used by 99%+ of ports. Some scripts
explicitly `$ESUDO chmod 666 /dev/uinput`; worth knowing if a gptokeyb2 invocation silently fails
to inject input. `/tmp` and `/dev/shm` are tmpfs. `/dev/tty0`/`/dev/tty1` are writable.

**Graphics/audio baseline**: GLES2 is the minimum GPU feature. **`/dev/dri/card0` is not
universal** (most H700 devices are fbdev-only, no DRM/KMS; `libgl_default.txt` falls back to
`LIBGL_FB=2`, Qt needs `QT_QPA_EGLFS_INTEGRATION=none`). Panfrost is present on some CFWs alongside
libmali (ROCKNIX lets the player choose; test both). ALSA is required; PulseAudio and PipeWire are
common (ROCKNIX, Knulli use PipeWire); never strip ALSA support from a build to "save a dependency"
(mkxp-z lost all audio that way). glibc on CFWs is at least 2.29 (PortMaster's own tools target
2.17-2.29); `libstdc++.so.6` with `GLIBCXX_3.4.21`+ (§3.2 for keeping a binary under these floors).

**Squashfs + loop devices are the single most impactful kernel requirement** — this is *why* every
runtime pattern in this document (Pattern D/F/G/H, Westonpack, Java, Qt) works at all. CFWs
guarantee `CONFIG_SQUASHFS` (zlib/lzo/xz/zstd per PortMaster's guide, though real kernels vary —
build runtimes with gzip and no xattrs, §2.6) + `CONFIG_BLK_DEV_LOOP` with `loop.max_loop=16`+
(some ports mount multiple runtimes simultaneously).

**zram/swap pattern** for memory-hungry ports:
```bash
zramctl --reset /dev/zram0 && mkswap /dev/zram0 && swapon /dev/zram0
# fallback:
dd if=/dev/zero of=/swapfile bs=1M count=512 && mkswap /swapfile && swapon /swapfile
```

**Never set a system-wide `LD_PRELOAD`** — it breaks the CFW's own library-override mechanism
(the same one ports rely on for their `libs.$DEVICE_ARCH`/`LD_LIBRARY_PATH` overrides). Westonpack's
`WRAPPED_PRELOAD`/`WRAPPED_LIBRARY_PATH` (§1.7.5) and OmniOSK's never-export rule (§1.10.3) are the
scoped, port-safe versions of this same principle.

**exFAT/FUSE caveat**: exFAT is the standard target filesystem (cross-platform drag-and-drop), and
it's case-insensitive — which hides case bugs that fail on CFWs using ext4 for ports (§2.4).
FUSE-based exFAT has known deadlock issues under heavy I/O on older BSP kernels — a mysterious I/O
hang on an older device may be a documented CFW-level issue, not necessarily the port's own bug.

**Other CFW facts**: some CFWs run the port unprivileged (Knulli), so anything needing root goes
through `$ESUDO` and archives must not carry owners (§2.4); a game refusing to run as root needs an
option for it (OpenSoldat's `-allowroot`) because others run as root. ROCKNIX runs sway: Westonpack
bypasses Weston on Panfrost, `pm_platform_helper` fullscreens windows after creation (so engines get
a resize event, §1.7.16), and `swaymsg` is available. A CFW's Python/pugwash/SDL2_image bugs can
break PortMaster's own dialogs (§1.7.13). Smoke-test ports per runtime for a new CFW (all Ready To
Run): DevilutionX/VVVVVV (native), Spelunky Classic HD (GameMaker), Mr. Rescue (Love2D), Cats on
Mars (FRT 3), Slime 3K Demake (Godot 4 + Weston), Mindustry (Java 17), Unciv (JDK + Weston),
Megaball (Pyxel), Shards of God (AGS).

## 2.8 Methodology: re-derive requirements from source, don't trust upstream's own launch script

A real, generalizable lesson from a completed port (Insaniquarium Deluxe, a PopLib/SDL3 fork):
every env var and file requirement was independently re-derived by reading the actual engine
source and the repo's own asset-verification tooling, not by trimming upstream's shipped `.sh`.
This caught two real, concrete mistakes upstream's own script would have carried forward:

- Upstream set `SDL_AUDIODRIVER=alsa` under a "both SDL and OpenAL probe PulseAudio" theory;
  reading the actual engine source showed `SDL_Init(SDL_INIT_VIDEO)` only — SDL's audio subsystem
  is never initialized, all audio goes through OpenAL directly, so the env var was a pure no-op
  and got dropped (see §2.3).
- Upstream had a post-crash diagnostic retry block that set `SDL_VIDEODRIVER=kmsdrm`/`mali`
  explicitly to narrow down driver failures — this directly conflicts with the hard
  never-hardcode-`SDL_VIDEODRIVER` rule (§2.2), so it wasn't carried over in any form, not even
  scoped to a failure-only retry path.

**When converting an existing port's classic `.gptk` tuning to gptokeyb2's `.ini`, don't invent
new numbers by guessing at a conversion formula** — `mouse_scale` and `deadzone_scale` are
described as "aliases" (§1.8.2) but classic gptokeyb's old two-field split (`deadzone_scale` for
curve shaping, `mouse_scale` for movement-delta divisor) doesn't carry over numerically once
gptokeyb2 merges them into one field. With no way to verify new numbers without a real device,
reuse the proven standard (§1.8.1: `deadzone_scale = 6` baseline, the `deadzone_scale = 18`
high-resolution bump) rather than converting upstream's old `mouse_scale`/`mouse_delay`/
`dpad_mouse_step` values.

More lessons from the same period, each from a real mistake:
- **Real-device evidence beats a plausible static-analysis theory.** OpenRA's `freetype6` name
  mismatch was real and fixed; the identical-looking `SDL2` concern never showed on any device, so
  no fix was added. Don't fix a symptom nobody has observed.
- **Don't guess: verify on source, then on the device.** A chain of plausible guesses (a `chmod +x`
  on the device's Mali driver after an `ldd` permission warning; a driver swap) was flatly wrong
  ("1000 ports work fine with libmali on this device") — the driver was used unmodified by hundreds
  of ports.
- **Check what upstream does on each platform before inventing your own approach** (ZQuestClassic's
  MIDI: no upstream build used DIGMID; following the web build's Timidity path, then the
  merged-port Timidity layout, fixed it).
- **Look for an actively maintained community fork before porting raw upstream**, especially when
  upstream says Linux is unfinished.
- **Use the engine's own data as the source of truth**: take default key bindings from the game's
  config/hotkey files, asset lists from its own verification tooling, save paths from its source.
- **Docs must track the latest verified truth.** When a later device test overturns an earlier
  conclusion, replace the old text instead of appending; a stale "confirmed" line misleads the next
  port (two Allegro ports were built on a wrong earlier claim).
- **Label inferred causes as unverified** when a patch works but the mechanism is a theory,
  especially in a bug report to the code's author (a confident wrong explanation of a Crusty fix
  cost its author time; the real cause was an SFML constructor race).
- **SDL 1.2 games don't need Westonpack**: sdl12-compat runs them on SDL2's own KMSDRM driver.
- **Check the released runtime, not just your test device.** A workaround that an unreleased
  Westonpack build makes redundant is still needed by players on the released one (§1.7.4).

---

# PART 3 — Building in the aarch64 Chroot: Toolchain, glibc Floor, Profiling Tools

Ports are built natively in an aarch64 Ubuntu 22.04 chroot (QEMU user emulation on an x86 host),
everything as root. Build there, link-check there (`readelf -d`, `nm -D`, `file`), and test only on
real devices.

## 3.1 Toolchain notes

- **Native aarch64, not a cross-compile**: no toolchain files or `ARCH=` for aarch64 targets.
  armhf targets (box86, its gl4es/sdl12-compat) use `gcc-arm-linux-gnueabihf` with a toolchain file
  (§1.7.14).
- **QEMU makes some steps slow, not hung**: LTO links (Ruby for mkxp-z took over an hour; gatord's
  LTO), one huge generated source file in box64 (10+ minutes), Igor/gm-cli audio conversion. Check
  for forward progress (`ps aux | grep lto1`) before killing anything. Disable LTO where the build
  allows it (`-l off`). A `libc-bin`/`ldconfig` trigger segfaulting under QEMU is a host-side
  qemu-user-static problem, not the chroot's.
- **Never tune to one CPU**: no `-mcpu=<core>` and remove upstream `-march=native`; build
  `-march=armv8-a` so GCC uses outline atomics (runtime LSE check) instead of inlining LSE
  instructions that SIGILL on Cortex-A35 (RK3326) (§1.7.12).
- **gcc-12 for C++20** (`<ranges>`: OpenAL Soft HEAD, SDL3, ZQuestClassic): install `gcc-12 g++-12`
  next to the default GCC 11 and select it per build (`-DCMAKE_C_COMPILER=gcc-12
  -DCMAKE_CXX_COMPILER=g++-12`), never system-wide. GCC 12 has its own traps: `-static-libgcc` pulls
  in `_dl_find_object` (glibc 2.35, §3.2), `std::condition_variable::wait` binds to `GLIBCXX_3.4.30`,
  and new `-Warray-bounds` false positives (don't let a project's `-Werror` options block the build;
  ZC: `-DWANT_ERROR_CHECKING=FALSE`).
- **CMake 4.x** rejects `cmake_minimum_required` below 3.5 in vendored subprojects: pass
  `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` (SurgeScript, OpenSoldat's stb, RenderDoc). For builds that
  run a nested CMake (vcpkg bootstraps in gatord), it must be an **environment variable**
  (`export CMAKE_POLICY_VERSION_MINIMUM=3.5`); a `-D` doesn't reach the nested run. vcpkg on arm also
  needs `VCPKG_FORCE_SYSTEM_BINARIES=1`.
- **Always set `-DCMAKE_BUILD_TYPE=Release`** when a project's default is empty/Debug.
- **SDL2 to build against**: replace Ubuntu's stock SDL2 2.0.20 with a from-source 2.26.2 (closer
  to what CFWs ship). Purge the packages first, not just the files, and hold them, or a later
  `apt-get install` silently reinstalls 2.0.20 over the custom build:
  ```bash
  apt-get remove --purge -y libsdl2-2.0-0 libsdl2-dev
  rm -f /usr/lib/aarch64-linux-gnu/libSDL2.* /usr/lib/aarch64-linux-gnu/libSDL2-2.0.so*
  wget https://github.com/libsdl-org/SDL/archive/refs/tags/release-2.26.2.tar.gz
  tar xf release-2.26.2.tar.gz && cd SDL-release-2.26.2/
  ./configure --prefix=/usr && make -j8 && make install && /sbin/ldconfig
  apt-mark hold libsdl2-2.0-0 libsdl2-dev
  sdl2-config --version; pkg-config --modversion sdl2   # both 2.26.2
  ```
  Never install `libsdl2-dev` afterwards. This build is for compiling against only, **never for
  shipping** (§1.1).
- **One chroot-wide SDL3** (no Jammy package exists): tag `release-3.2.30`, gcc-12, shared and
  static, installed to `/usr`; consumers use `find_package(SDL3 REQUIRED CONFIG)` and link
  `SDL3::SDL3` (shared, so the shim can be swapped in, §1.7.12). A port whose CMake still
  `add_subdirectory`s its own SDL3 copy has to be switched to `find_package` to use it.
  SDL3_ttf/image/mixer stay per-port.
  ```bash
  git clone --branch release-3.2.30 --single-branch https://github.com/libsdl-org/SDL.git SDL3
  mkdir -p SDL3/build && cd SDL3/build
  cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_C_COMPILER=gcc-12 -DCMAKE_CXX_COMPILER=g++-12 -DSDL_SHARED=ON -DSDL_STATIC=ON
  cmake --build . --parallel $(nproc) && cmake --install . && /sbin/ldconfig
  pkg-config --modversion sdl3   # 3.2.30
  ```
- **Java**: the chroot's JDK is OpenJDK 17 with no `ant`; target the device's JDK 11 runtime with
  `javac --release 11` (§1.7.15).
- **Other toolchains used**: Free Pascal 3.2.2 (distro), Node.js 24 + `@gamemaker/gm-cli` (official
  linux-arm64 tarball), a static FFmpeg ≥ 5.1 (BtbN linuxarm64 builds) first on `PATH` for GameMaker
  audio conversion, Go from go.dev (the distro's is too old for current projects; a shallow clone can
  break `git describe`-based version scripts). Only `python3` exists (no `python`).
- **Old autotools tarballs**: replace `config.guess`/`config.sub` with current copies before
  `./configure` (they predate aarch64). Missing `freetype-config`: a two-line shim around
  `pkg-config freetype2` (§1.7.20).
- **Detecting accidental dependencies**: CMake `find_package` calls pick up whatever `-dev` packages
  happen to be installed (an installed `libtbb-dev` silently added `libtbb.so.12`; curl, websockets
  added `libssl`). Disable optional finds explicitly
  (`-DCMAKE_DISABLE_FIND_PACKAGE_TBB=ON`, `-DCMAKE_DISABLE_FIND_PACKAGE_CURL=ON`) and re-check
  `readelf -d` after every rebuild.

## 3.2 Keeping binaries under the device glibc floor

A plain build in an Ubuntu 22.04 chroot (glibc 2.35, GCC 11/12) can require `GLIBC_2.34`/`2.35` and
`GLIBCXX_3.4.29`/`3.4.30`. PortMaster's own tools stay at 2.17-2.29, CFWs guarantee 2.29+, and
older/other CFWs report lower `$CFW_GLIBC` values, so check every shipped ELF — the main binary
**and every bundled `.so`** (an earlier check that skipped some libraries missed a 2.35 symbol):
```bash
for f in portexecutable.aarch64 libs.aarch64/*.so*; do echo "$f"; objdump -T "$f" | grep -o 'GLIBC_[0-9.]*\|GLIBCXX_[0-9.]*' | sort -Vu | tail -2; done
```
Techniques, cheapest first:
- **Pin individual symbols with `.symver`** in a header force-included into the C and C++ flags
  (`-include glibc-compat.h`). It must `#include <features.h>` first, or `__GLIBC__` isn't defined
  yet at `-include` time and the guard silently skips everything:
  ```c
  #include <features.h>
  #if defined(__aarch64__) && defined(__GLIBC__)
  __asm__(".symver hypot,hypot@GLIBC_2.17");
  __asm__(".symver hypotf,hypotf@GLIBC_2.17");
  #ifdef __cplusplus
  __asm__(".symver _ZNSt18condition_variable4waitERSt11unique_lockISt5mutexE,_ZNSt18condition_variable4waitERSt11unique_lockISt5mutexE@GLIBCXX_3.4.11");
  #endif
  #endif
  ```
  (`hypot`/`hypotf` got new versions in glibc 2.35 on aarch64; `condition_variable::wait`'s
  `GLIBCXX_3.4.30` entry is a stub, the `3.4.11` one is still exported.) Where a header can't be
  injected, `-Wl,--wrap=hypot` plus a tiny wrapper calling the old version works too.
- **Don't link `-static-libgcc` with GCC 12** (its unwinder calls glibc 2.35's `_dl_find_object`);
  link `libgcc_s.so.1` dynamically. Meson projects can drop libstdc++ assertion symbols with
  `-Db_ndebug=true` (`__glibcxx_assert_fail`).
- **`__libc_start_main@GLIBC_2.34` comes from the new `crt1.o`**: for a small C program with no
  constructors, link a minimal `_start` (`start_aarch64.S` binding
  `.symver __libc_start_main,__libc_start_main@GLIBC_2.17`) with `-nostartfiles` (portmsg does this
  to stay at 2.17; check `.init_array` is empty and verify with `objdump -T`).
- **Build in an older root** when symbols are bound by generated code (gmloader-next's thunk
  tables): a Debian bullseye root (`debootstrap --variant=minbase bullseye`, glibc 2.27 /
  `GLIBCXX_3.4.26` max) or an Ubuntu 18.04 sysroot (used for an armhf build).

## 3.3 Profiling and GPU tracing tools

Check the kernel before deploying any of these: perf and gatord need `CONFIG_PERF_EVENTS`.
```bash
uname -r
zcat /proc/config.gz | grep -E 'CONFIG_(PROFILING|PERF_EVENTS|HW_PERF_EVENTS|HIGH_RES_TIMERS|TRACING|CONTEXT_SWITCH_TRACER)='
ls /sys/bus/event_source/devices/      # want an armv8_*/cpu PMU entry
cat /proc/sys/kernel/perf_event_paranoid   # <= 1, or run as root
ls -l /dev/mali*                       # Mali GPU counters need the vendor kbase driver
```
**RG351V/AmberELEC (kernel 4.4.189) has no `CONFIG_PERF_EVENTS`**: `perf_event_open` returns errno
38 (`ENOSYS`, "No CONFIG_PERF_EVENTS=y kernel support configured?"). Nothing a port can fix.

- **perf**: a prebuilt aarch64 `perf_4.9.170` (built for the muOS BSP kernel 4.9.170; circulated on
  the PortMaster Discord) needs `libaudit.so.1`, `libcap-ng.so.0`, `libslang.so.2` beside it (and
  `liblzma.so.5`, missing on AmberELEC). Treat output from a different kernel version with
  suspicion. `perf record -g -p <pid>`, `perf report`. Code without an on-disk ELF (JIT, a custom
  loader) can be symbolized by writing `/tmp/perf-<pid>.map` lines `<start> <size> <symbol>`.
- **gatord / Arm Streamline**: CPU PMU and Mali GPU counters in one timeline. Build from
  `ARM-software/gator` (tag 9.6.0): `export CMAKE_POLICY_VERSION_MINIMUM=3.5;
  ./build-linux.sh -p native-gcc -l off -s`, then in `build-native-gcc-rel`
  `export VCPKG_FORCE_SYSTEM_BINARIES=1 VCPKG_DISABLE_METRICS=1; cmake
  -DGATORD_BUILD_STATIC:BOOLEAN=ON . && cmake --build .` (a static glibc `gatord`; the dynamic one
  needs GLIBC_2.34; static glibc may misbehave in `getpwnam`/`getaddrinfo`, so try the dynamic one
  or Arm's own prebuilt musl `gatord` if user lookup or TCP fails). GPU counters need `/dev/mali*`
  (vendor kbase); Panfrost gives CPU data only. Run as root. Interactive: `./gatord &` ("Gator
  ready", TCP 8080) and connect Arm Performance Studio's Streamline. Headless:
  `./gatord -o /tmp/game.apc -C workflow_all -Q <binary-name> -t 30 -L` (`-A <cmd>` to launch
  instead, `-i <pid>` to attach, `-r low|normal|high` sample rate), then on the host
  `streamline-cli -pa --type=json:report.json game.apc`. Reported working on RG40XXH/muOS by another
  porter; not yet run by this document's authors.
- **apitrace** (which GL/EGL calls, how many, per frame): build with
  `git clone --recurse-submodules https://github.com/apitrace/apitrace` and
  `cmake .. -DCMAKE_BUILD_TYPE=Release -DENABLE_X11=OFF -DENABLE_EGL=ON -DENABLE_GUI=OFF`. Ship
  `wrappers/egltrace.so` (needs only libc) and run
  `LD_PRELOAD="$GAMEDIR/egltrace.so" TRACE_FILE="$GAMEDIR/capture.trace" ./$BINARY` as a bare
  prefix after gptokeyb2 has started. Analyze with `apitrace dump capture.trace`,
  `apitrace dump --calls=frame`, `apitrace info`. If the driver lacks a function apitrace has no
  `fail=` value for (Mali has no `eglGetPlatformDisplay`), the trace aborts (`error: unavailable
  function eglGetPlatformDisplay`): add `fail='EGL_NO_DISPLAY'` in `specs/eglapi.py`, delete the
  generated `dispatch/glproc.cpp` and `wrappers/egltrace.cpp`, rebuild. **Through gl4es it doesn't
  work**: pointing gl4es at it (`LIBGL_EGL=`/`LIBGL_GLES=egltrace.so`) recurses (both are named
  `libEGL.so.1`; strip `gl4es.$DEVICE_ARCH` from `LD_LIBRARY_PATH` for the traced run), and then
  egltrace exporting every entry point defeats gl4es's own `LOAD_EGL_EXT` capability probing, so
  `eglInitialize` fails with `EGL_BAD_DISPLAY`. Use it on native GLES ports.
- **RenderDoc** (one frame's full pipeline state): upstream has no GBM support; JohnnyonFlame's fork
  (`github.com/JohnnyonFlame/renderdoc`, branch `v1.x`) builds with `cmake .. -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DENABLE_GL=ON -DENABLE_GLES=ON -DENABLE_EGL=ON -DENABLE_GBM=ON
  -DENABLE_VULKAN=OFF -DENABLE_XLIB=OFF -DENABLE_XCB=OFF -DENABLE_WAYLAND=OFF -DENABLE_GGP=OFF
  -DENABLE_RENDERDOCCMD=OFF -DENABLE_QRENDERDOC=OFF -DENABLE_PYRENDERDOC=OFF` into
  `lib/librenderdoc.so` (needs `libgbm`/`libstdc++` on the device). It hardcodes `/dev/dri/card0`.
  `RENDERDOC_HOOK_GL=0` disables GL hooking, but disabling GLES/EGL hooking needs
  `RENDERDOC_HOOK_GLES=1` (inverted logic in `egl_hooks.cpp`). On a gl4es+GBM+Mali port it crashed
  in `SDL_CreateWindow`, and still in `SDL_GL_CreateContext` with both hooks off (its `dlopen` hook
  alone breaks gl4es); under gdb it fails earlier (`linux_check_ptrace_features`). Untested on a
  native GLES port.
- **What actually worked for "CPU- or GPU-bound?" through gl4es**: temporary `SDL_GetTicks()`
  brackets around a `glFinish()` (§2.5), plus once-per-second stage timing.

---

# Bottom Line

If only a few things from this whole document get absorbed, make it these:

1. **gptokeyb2/`.ini` for every new port (§1.8.1), not classic gptokeyb/`.gptk` (§1.8.5,
   legacy-only).** Ship the standard mouse block and hi-res `sed` bump on every mouse port
   (A/B clicks, X slow), `deadzone = 12000` on every stick-to-keys mapping, no `.ini` at all for a
   kill-switch-only port, and the kill target as the real process name (≤15 characters).
2. **PM handhelds are physically Nintendo-style, not Xbox-style, and gptokeyb2's logical
   `a`/`b`/`x`/`y` keys don't auto-remap to compensate (§1.8.4).** Get the real physical layout
   from whoever's testing on-device before assigning bindings.
3. **Never hardcode drivers or devices.** No `SDL_VIDEODRIVER` in a launch script (§2.2; the SDL3
   shim's forwarding pattern is the one scoped exception, §1.7.12), no CFW-name branches in fixes,
   no bundled SDL2 or GPU/display-stack libraries, and source `libgl_${CFW_NAME}.txt` with the
   default fallback.
4. **Use the current script conventions** (some are this project's own choices, marked in the
   text): the standard header with the `mod_${CFW_NAME}.txt` line,
   `pm_message`/`pm_show_error` with the message first (§1.7.13), `pm_platform_helper` before the
   game, bulk data in a `gamedata.tar.gz` built with `--owner=0 --group=0 --numeric-owner` and
   extracted with `gunzip -c | tar --no-same-owner -xf -` (§2.4), and the `weston_prefix` +
   `CRUSTY_BLOCK_INPUT` lines on every `drm`-backend Westonpack script (§1.7.4).
5. **Nothing is "tested" until it ran on real devices across CFWs** (§2.5), and a report says
   only what was actually tried. The PR template's Authorship & Testing checkbox (§1.6)
   genuinely needs to be true, not just checked.

Everything else here is real, drawn from actual on-device debugging and actual PortMaster PR
review feedback across many real ports, but those five are the ones most likely to matter on the
very first port someone tries to ship with AI help.
