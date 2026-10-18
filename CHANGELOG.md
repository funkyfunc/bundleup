# Changelog

Versions follow uv's scheme until 1.0: a minor version may break things
([style guide](docs/cli-style-guide.md) rule 37).

## 0.2.1 (2026-10-18)

Hardening across virtual projects, `--external`, ZIP64 verification, `--format exe`, `--smoke`, and
cache concurrency:

- Virtual / wrapper projects (`[tool.uv] package = false` and `[tool.poetry] package-mode = false`)
  install only their locked or declared dependencies without attempting to build the root directory
  as a wheel; stage-isolated `pylock.install.toml` keeps `with_project()` from mutating the lock
  path passed to `uv pip install`.
- `--external` strips excluded packages before `uv pip compile` on unlocked `pyproject.toml` and
  `requirements.txt` inputs (preserving line continuations and dropping invalidated `--hash` flags)
  and prunes them from `uv export`, preventing transitive dependency resolution of host-provided
  packages.
- `uv` commands (`export`, `pip compile`, `pip install`, `python find`) automatically retry with
  `--offline` when a transient DNS or network failure occurs and wheels are already cached locally.
- `bundleup verify` and `_zipwriter` validate ZIP64 end-of-central-directory records, 64-bit sizes
  and offsets, and trailer boundaries across `.pyz`, `--format py`, `--format zip`, and `--format
  exe`; `--split` accounts for ZIP64 header overhead so split parts never exceed the byte budget.
- `--format exe` builds isolate `SCIE_BASE` inside `--smoke` and runtime caches, handle read-only
  and hardlinked entries in `python-build-standalone` tarballs, and verify downloaded archive size
  and SHA-256 atomically.
- `--smoke` assigns spawned bundles to a Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`)
  and terminates process trees so background grandchildren cannot hold locks on temporary working
  directories, and falls back to `<build-cache>/smoke` when `TMPDIR` is mounted `noexec`.
- Runtime `.pth` processing normalizes Windows drive/path casing like `site.py` and backslashes in
  relative `.pth` entries, while nested bundle invocations cleanly replace parent bundle `sys.path`
  and `sys.modules` entries without leaking into host tools.
- `bundleup cache clean` respects active locks on `.tmp-*-pruned` directories, handles read-only
  cached trees on Windows without recursion errors, and ignores NTFS `st_mtime` skew when `--all`
  is passed.

## 0.2.0 (2026-10-16)

Smaller CLI surface, `--external`, undeclared-import detection, inline code frames, and why-included
dependency chains (ADR-0049, ADR-0050, ADR-0051):

- `--external PKG` (and `external = [...]` in `[tool.bundleup]` or `BUNDLEUP_EXTERNAL`): leave a
  package out of the bundle (`uv export --no-emit-package`) and let the bundle inherit the host
  Python's `site-packages` after its own packages at runtime, for host-provided packages (`bpy`,
  `maya`, `nuke`, system `torch` / CUDA).
- `undeclared-import` warning: AST-scans the project's own Python files for top-level imports that
  are neither in the standard library, the project itself, the installed wheels' `RECORD`s, nor
  `--external`, with a `pip install` / `uv add` mapping for common import-to-PyPI aliases (`yaml` →
  `PyYAML`, `cv2` → `opencv-python`, `PIL` → `Pillow`, `sklearn` → `scikit-learn`, ...).
- Diagnostics with `file` and `line` (`syntax-error`, `undeclared-import`, `[tool.bundleup]` line
  errors) render a 2-line source code frame with a `^` pointer on stderr.
- `PackageSize.required_by` (`required_by` in `--json` and `(<- pkg)` on the top-5 packages in
  `bundleup check` and `bundleup build -v`) shows the shortest dependency chain from a direct
  dependency to each transitive package, respecting target platform and Python markers.
- `uv export` outputs are cached under `<cache>/build/exports/` keyed by `uv` version, `uv.lock`
  hash, `pyproject.toml` hash and export flags, speeding up repeated and multi-target builds;
  `bundleup cache clean --build` clears the build cache.
- Breaking CLI cleanups:
  - `--format lambda` is now `--format zip` (generic flat `.zip` of code, packages and `.pyc`
    without AWS-specific size ceilings; pair with `--max-size` when deploying to Lambda; ADR-0049).
  - `--also-platform` and `--also-python` are consolidated into repeatable and comma-separated
    `--python-platform` (`--platform`) and `--python` (`bundleup build --python-platform
    linux,macos,windows`; ADR-0050).
  - Removed `--against` and `check --audit` from the core CLI in favor of explicit flags and
    `pip-audit` / `uvx pip-audit` (ADR-0050).
- Entry points (`--entry` and `[project.scripts]`) are validated at build time so missing modules or
  callables fail with `EntryPointError` before shipping.

## 0.1.0 (2026-10-13)

The first working release. From a project with `uv.lock` or `pylock.toml`, or a PEP 723 script:

- `bundleup build`: one `.pyz` that runs on plain Python with no install step. A pure-Python one
  runs on every Python version its lock allows and, when the lock picks the same packages
  everywhere, on any OS and CPU; one with compiled code on the version and platform it was built
  for, or, with several `--python`/`--python-platform`, one file with a payload for each. Started
  with the wrong Python, a bundle runs itself again with a matching installed one. Also `--format
  py` (the same as one plain-text `.py` file), `--format exe` (an executable that brings its own
  Python, for machines without one), `--format dir` (a plain directory for host
  applications) and `--format lambda` (an AWS Lambda zip),
  builds for other platforms (`--python-platform`), `--max-size` (refuse an output that's too
  big) and `--split` (no file over a size: a small `.pyz` and a folder of parts). Destinations such as Lambda and Claude API Skills are tested
  [recipes](docs/recipes.md), not named targets.
- `--entry python`: a `.pyz` that runs the scripts it's given (`python deps.pyz tool.py`), so
  one bundle serves every script of a skill. A bundle for several platforms stores each file
  once. Over 100 MB (GitHub's file limit), a build warns (`large-bundle`).
- `--against FILE` builds or checks for a destination described in a TOML file (its Python,
  platform, size limit, network and installs, with source and date); the Claude API sandbox and
  AWS Lambda are in docs/targets/ (ADR-0044).
- `check --audit` asks PyPI about the locked packages: known vulnerabilities, yanked versions,
  brand-new projects (ADR-0043). Bundles with compiled code skip cache folders on noexec
  filesystems.
- `--smoke [ARGS]` runs the finished bundle once in a fresh home folder with the network blocked
  (macOS, Linux), failing the build if it fails (ADR-0042).
- Projects without a lock build too (ADR-0041): a `pyproject.toml` installed with pip, a
  `setup.py` project, a folder of modules with `requirements.txt`, a script with a
  `requirements.txt` beside it or none at all. Versions are resolved at build time, with an
  `unlocked` warning unless every one is pinned; nothing is written into the project.
- Packages are installed from the lock's own files and index, with their hashes: a project
  locked against a company index builds from it, never from a same-named package on PyPI.
- `bundleup check`: what won't survive bundling, before shipping: code that doesn't compile on
  the target Python, packages without a wheel for a platform (from the lock alone, for any number
  of platforms with `--also-platform`, or as a grid with `--matrix`), data files outside packages,
  Lambda's size limits; package sizes. Every build runs the same checks; `--strict` makes warnings fail.
- `bundleup verify`: checks a bundle (`.pyz`, `.py`, `exe`, `dir` or `lambda`) and its unpacked
  copy against its manifest of file hashes.
- `bundleup cache list|clean`.
- Every build is checked against the lock and every wheel's `RECORD`, and is reproducible.
- Bundles unpack once to a cache, start as fast as an installed venv, check the Python version,
  platform, CPU, C library and macOS version first, ignore the machine's own packages, and let
  child processes that run the bundle's code see its packages (no other Python or tool). `cache
  clean` never removes a copy a running program uses, and a new version prunes older copies of
  the same bundle unused for 30 days (POSIX).
- A lock is checked against `pyproject.toml` by default (`--frozen` to skip); bundleup never
  writes or rewrites a project's lockfile.
- `--json` output with JSON Schemas, stable exit codes and diagnostic codes, `[tool.bundleup]`
  configuration, and a typed library API (`bundleup.build()`, `check()`, ...).
