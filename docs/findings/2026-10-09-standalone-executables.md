# Standalone executables: how to build them, and what they cost (2026-10-09)

The owner asked to "work through the standalone executables" (roadmap item 23 and the
"Standalone executables" row). This page records the research and the measurements behind
[ADR-0047](../adr/0047-standalone-executables.md). Research by a subagent from primary sources
(a-scie/jump at b09928e, a-scie/lift, pex-tool/pex, ofek/pyapp, python-build-standalone releases);
the bundleup executable measured afterwards on the committed implementation.

## Setup

- This Mac: macOS 26, arm64. Project `gauntlet/skill` (python-pptx, lxml, Pillow; pywin32 on
  Windows), CPython 3.12. Test: `import pptx, lxml, PIL`.
- pex 2.103.4 (`uvx`), which used science 0.21.0, scie-jump 1.13.0 and python-build-standalone
  (PBS) 20261009.
- Each first run with a fresh `HOME` and launcher cache (`SCIE_BASE`) and bundleup cache; first
  run the median of 3, warm the median of 5 to 7.

## Results

| | `pex --scie eager` (defaults) | `pex --venv --scie eager`, stripped Python | bundleup `--format exe` | bundleup `.pyz` on an installed Python |
|---|---|---|---|---|
| File size | 42.3 MB | 42.2 MB | 49.1 MB | 15.9 MB (needs Python) |
| Build, cold | 165 s | 101 s | as the `.pyz`, plus 7 s once (downloads, stdlib compile) | 50 s (cold uv cache) |
| Build, warm | 3.3-3.5 s | n/a | 0.8 s (the executable step: 32 ms) | 0.8 s |
| First run | 4.73 s | 4.69 s | 4.5 s | 3.09 s |
| Warm run | 142 ms | 62 ms | 61 ms | 58 ms |
| Warm, `PYTHONDONTWRITEBYTECODE=1` | 235 ms | 141 ms | 61 ms | 65 ms |
| Disk after first run | 138 MB | 138 MB | ~130 MB | 41 MB |

From the same Mac, bundleup also built the Windows x86_64 (50 MB, PE32+ console) and Linux
x86_64 (57 MB) executables; CI runs each on its OS with no Python on `PATH` (`skill-run`).
pex could build for Windows, and for Linux only with `manylinux_2_28` (Pillow 12 has no
manylinux2014 wheel).

## What we learned

- **A scie is concatenation plus a JSON trailer.** `[scie-jump][file 1]...[file N]\n{json}\n`.
  The launcher finds the JSON after the zip end record of the last file, so the last file must be
  a zip (a `.pyz` is one) and the JSON well under 64 KB. File *i* starts at the launcher's size
  plus the sizes before it; each file has `size`, `hash` (sha256) and `type`; the manifest's
  `jump` object takes the launcher's size and version from its own last 9 bytes (version length,
  size, magic `0x4A532520`). This is documented ("cat assembly") and needs nothing from the
  build machine, so building for another OS is downloading that OS's launcher and Python.
- **At run time** the launcher unpacks each file once to `<cache>/nce/<sha256>/<name>` (checking
  the hash then, under a lock, renamed into place), replaces itself with the command on Unix
  (`execve`; on Windows it waits for it), and costs about 2 ms. `SCIE_BASE` moves the cache and
  must be absolute.
- **python-build-standalone ships no stdlib bytecode for macOS and Linux** (3 of 1,090 modules;
  Windows 563). Python then compiles the stdlib on first use, and with
  `PYTHONDONTWRITEBYTECODE=1` (common in Docker images) or a read-only cache, on every run:
  181 ms warm instead of 62 ms. Compiling it at build time fixes this (61 ms either way).
  Bytecode depends only on the Python version, so the build machine's interpreter compiles it for
  any OS.
- **Unpacking Linux's Python on a Mac fails**: its `share/terminfo` has names differing only in
  case, which collide on a case-insensitive disk ("Too many levels of symbolic links"). Copy the
  archive entry by entry and unpack only the `.py` files to compile.
- **Reproducible**: compiled files record their source path, so compile with the temporary
  folder stripped (`compileall -s`), and write gzip with no time or name in its header.
- **uv fetches another platform's Python** (`uv python install cpython-3.12-windows-x86_64-none`,
  hash-checked) but extracts it; with `UV_PYTHON_CACHE_DIR` it also keeps the archive, which is
  what an executable needs. Afterwards `uv python find` in that folder fails trying to run the
  foreign interpreters, so it's a throwaway folder.
- **Signing.** A scie can't be signed on macOS: `codesign -v` fails on the bare release launcher
  already ("main executable failed strict validation"), because data after the Mach-O isn't
  covered. So no Developer ID signing or notarization. Files from `git clone` carry no
  quarantine attribute and ran; browser downloads are quarantined and Gatekeeper asks
  (pex#2621). Windows: one open report of Defender flagging a scie (lift#170, intermittent);
  Authenticode signing untested (the certificate would land after the JSON). Node SEA, Deno and
  PyInstaller can sign because they put the payload inside the executable format; that's the
  route if notarized macOS binaries are ever needed.
- **pex was not the way to do it here**: it resolves again from requirements (no `uv.lock`, none
  of bundleup's checks), keeps its own runtime cache, and is slower to build; its fastest
  setting only ties our warm start.

## Prior art, briefly

PyApp compiles its configuration into a Rust launcher (a toolchain per target; downloads the
interpreter on first run by default). PyInstaller onefile unpacks to a new temp folder on every
run and can't cross-build. Node SEA injects the blob into a named section (so it can be signed),
Deno and Bun `compile` cross-build by downloading a runtime per target, the same shape as
downloading a launcher.

## What it means

bundleup builds executables itself, from pinned, hash-checked parts, for any of six OS/CPU pairs
from any machine ([ADR-0047](../adr/0047-standalone-executables.md)). Fit: machines without
Python (Windows above all) receiving files through git or a package manager. Not a fit, yet:
software downloaded in a browser on macOS, where an unsigned executable meets Gatekeeper.
