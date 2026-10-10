# ADR-0047: `--format exe`: a standalone executable that brings its own Python

- **Status:** Accepted (the owner, 2026-10-09: "let's also work through the standalone
  executables"; the design not yet reviewed by the owner)
- **Date:** 2026-10-09
- **Deciders:** the owner (the direction), an agent (the design)
- **Supersedes:** [ADR-0002](0002-target-the-runtime-only-tier.md)'s exclusion of standalone
  executables (the rest of it stands)

## Context

A `.pyz` needs a Python 3 on the machine. Many Windows machines have none (`python` may be the
Store placeholder), which is the biggest audience a `.pyz` can't reach (round 4; the founding
skill's Windows users). ADR-0002 ruled executables out because of code signing and notarization,
the problem that started the project. Since then: delivery through git and agent package managers
doesn't quarantine files, uv can fetch any platform's interpreter, and an existing launcher
(scie-jump, behind `pex --scie`) makes an executable a matter of concatenation
([findings](../findings/2026-10-09-standalone-executables.md)).

## Decision

- `--format exe` (`format = "exe"`) writes one executable for one OS/CPU and one Python version:
  `dist/<name>` (`dist/<name>.exe` for Windows). Several `--python`/`--python-platform` values
  are an error: the file carries that one interpreter. `--split` is for `.pyz` only.
- The file is a scie: scie-jump 1.13.0 for the target (macOS, Linux and Windows on x86_64 and
  arm64; Linux uses the static build), then python-build-standalone's stripped interpreter of the
  target's Python version, then the bundle's `.pyz`, then the manifest. Running it unpacks the
  interpreter and the `.pyz` once into the launcher's cache (`nce` in the user cache folder,
  `SCIE_BASE` moves it) and runs `python app.pyz ARGS` with `PYTHONHOME` and `PYTHONPATH`
  removed; from there the bundle behaves as any `.pyz` (its own cache, checks, `--entry python`).
- bundleup writes the file itself; it doesn't run pex, science or the launcher's packer. The
  launcher is downloaded from its GitHub release once and checked against a sha256 pinned in
  bundleup; the interpreter comes from `uv python install` (uv checks its hash) and its archive is
  kept. Both live in bundleup's build cache (`exe/`, cleared by `cache clean --build`); each
  download is announced, and `UV_PYTHON_DOWNLOADS=never` stops the interpreter's.
- The interpreter's standard library is compiled to bytecode at build time (the archives for
  macOS and Linux ship none), reproducibly, so a warm start doesn't depend on a writable cache or
  `PYTHONDONTWRITEBYTECODE`.
- Unsigned. `--smoke` runs the executable itself; `bundleup verify` checks the `.pyz` inside it.

## Consequences

- One file that runs on a machine with no Python, built for any of the six platforms from any
  machine: 49-57 MB for the skill fixture against 16 MB as a `.pyz`; warm starts equal the
  `.pyz`'s (61 ms against 58), first runs are slower (4.5 s against 3.1) and it uses about three
  times the disk (the interpreter, the `.pyz` and the unpacked bundle).
- **Not signed, and on macOS it can't be:** data appended to a Mach-O isn't covered by its
  signature. Fine for files delivered by git or a package manager (no quarantine); a browser
  download on macOS meets Gatekeeper's warnings. Windows antivirus may flag an unknown
  executable (one report for scies). Recommend the `.pyz` wherever Python exists.
- A dependency on scie-jump's format and releases (one maintainer). Pinned by hash; the format is
  small enough to replace with our own launcher if needed, which is also the route to signing
  (put the payload inside the executable format, as Node SEA does).
- Revisit when someone needs a signed or notarized executable, or when uv ships its own.

## Alternatives considered

- **`pex --scie`** (ADR-0002's "hand off to pex"): resolves again without `uv.lock` or bundleup's
  checks, its own runtime layer, 165 s cold builds; its fastest setting only ties ours.
- **scie-jump's packer (boot-pack)** instead of writing the file: it's a native binary, so the
  build machine would need its own launcher too, for no gain over ~60 lines of Python.
- **Our own launcher** (Rust or C): the only way to signing, but a toolchain per target and a
  binary to maintain; not before someone needs signing.
- **A launcher that downloads Python on first run** (PyApp's default): needs the network on the
  user's machine, which bundleup promises not to.

## Evidence

- [Findings 2026-10-09](../findings/2026-10-09-standalone-executables.md): layout rules,
  measurements, signing and quarantine.
- [tests/test_exe.py](../../tests/test_exe.py): runs with no `PATH`, `--smoke`, verify, builds
  Windows and Linux executables from any OS.
- CI `skill` / `skill-run`: the skill built on macOS as three executables, each run on its OS
  with no Python on `PATH`, `--entry python` and a child process included.
