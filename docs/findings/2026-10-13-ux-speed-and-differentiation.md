# Findings 2026-10-13: differentiation, build/runtime speed, and UX strategy

Research and profiling conducted after releasing `bundleup 0.1.0` to PyPI, answering four questions:
1. How does `bundleup` differentiate sustainably against `pex` and `uv` (mirroring the JS bundler
   evolution from `webpack` to `esbuild` / `tsup` / `pkg`)?
2. Where does wall-clock time actually go on cold builds, warm rebuilds, cold runs, and warm runs,
   and what optimizations move the needle?
3. What UX details make developers reach for `bundleup` by default?
4. Which features have the highest leverage within the mission ("more kinds of projects in, more
   kinds of outputs out; dead simple to use, powerful and fast")?

---

## 1. Differentiation: the JS bundler parallel (`webpack` → `esbuild` / `tsup` / `pkg`)

In JavaScript, `webpack` was the incumbent kitchen-sink build tool, and `npm`/`pnpm` owned package
installation. Yet `esbuild`, `tsup`, and `pkg` carved out massive adoption by owning **the artifact
boundary** — turning a project into a zero-config deployable artifact with instant feedback and
static analysis before shipping:

| Ecosystem | Package manager & runner | Complex build system | Zero-config artifact bundler |
|---|---|---|---|
| **JavaScript** | `npm` / `pnpm` / `bun` | `webpack` / `Rollup` | `esbuild` / `tsup` / `pkg` |
| **Python** | `uv` | `pex` / `PyInstaller` / `shiv` | **`bundleup`** |

### Why `uv` and `pex` leave a clear, durable wedge for `bundleup`

1. **`uv` is the engine, not the artifact.** `uv` solves environment management (`uv run`, `uv sync`,
   `uv lock`) when `uv` is installed on the target machine and has network or cache access.
   `bundleup` uses `uv` as its resolution and wheel-installation engine (ADR-0011) and solves the
   **post-`uv` deployment problem**: shipping one self-contained file to a machine, container,
   Lambda function, agent sandbox, or customer host that only has `/usr/bin/python3` (or nothing at
   all with `--format exe`).
2. **`pex` is a 100+ flag build tool designed around Bazel/Pants; `bundleup` is zero-config.**
   - Getting `pex` to match avenv's warm startup and cross-platform wheel safety requires knowing
     `--venv --venv-site-packages-copies --sh-boot --compile --complete-platform ...`.
   - `bundleup build` does all of that by default from `pyproject.toml`, `uv.lock`, `pylock.toml`,
     `requirements.txt`, or a PEP 723 script.
3. **Build-time static intelligence (`bundleup check`) that neither `pex` nor `uv` does:**
   - ** Bundling-hazard analysis (ADR-0024):** catches `__file__` path traversal, undeclared
     imports, `.pth` assumptions, and accidental secret files before the artifact is deployed.
   - **Automatic Python version range & OS/CPU portability inference (ADR-0030, ADR-0034):**
     computes the exact Python minor version range (from lock markers, `Requires-Python`, AST syntax
     probes, and stdlib additions/removals) and OS/CPU reach of every build.
   - **Lock-level cross-platform wheel matrix (`check --matrix`, ADR-0031):** answers "can this
     lockfile ship to Linux/macOS/Windows across Python 3.9–3.14?" in milliseconds without
     installing anything.
4. **One tool, five deployment shapes from the same input:**
   - `.pyz` (default, one executable zipapp for any host with Python)
   - `--format py` (one plain-text `.py` file for paste/upload/gist/LLM sandboxes, ADR-0046)
   - `--format exe` (one self-contained binary with a standalone Python interpreter for any OS/CPU,
     zero host dependencies, ADR-0047)
   - `--format lambda` (AWS Lambda zip with handler and size-limit checks, ADR-0025)
   - `--format dir` (distroless / multi-stage Docker directory output, ADR-0025)
5. **Cryptographic chain of custody (`bundleup verify`):**
   - Verifies link 1 (`uv.lock` → bundle) and link 2 (wheel `RECORD` → bundle + unpacked cache),
     including `--format exe` launcher/archive/trailer hashes.

---

## 2. Speed: where wall-clock time goes and what we optimized

Profiling `bundleup build` on a 10-package locked CLI project (`07-click-rich`, 376 `.py` files,
8.1 MB unpacked) on macOS arm64:

### Warm build breakdown (before vs. after Pass 1 optimizations)

| Step | Before Pass 1 | After Pass 1 | What changed |
|---|---:|---:|---|
| `python` (`find_uv` + `find_python`) | 46 ms | **39 ms** | `_uv_version_ok` cached per binary path (eliminated `uv --version` subprocess) |
| `export` (`uv export --locked`) | 42 ms | **42 ms** | `uv` exports `uv.lock` to `pylock.toml` |
| `install` (`uv pip install`) | 248 ms | **248 ms** | ~210 ms of this is `uv` building the local project's wheel via PEP 517 (`uv_build`) |
| `compile` (`_bytecode.precompile`) | 38 ms | **8 ms** | `_extra_distribution` caches `__bundleup__/*`, PEP 723 scripts, and folder apps so warm builds spawn **zero** `py_compile` subprocesses |
| `check` (`analyze` + `oldest_python` + `portability`) | 109 ms | **78 ms** | `_verify._lock_packages` caches compiled `packaging.markers.Marker` and `canonicalize_name`, eliminating 72× redundant marker parses per build |
| `pack` (`write_payload` + `_compile_loader`) | 45 ms | **22 ms** | `_outputs._compile_loader` caches `__main__.pyc` in `_bytecode.cache_dir()`, eliminating the per-build Python subprocess for the loader |
| **Total warm build** | **528 ms** | **437 ms** | **~17% faster single-target warm build; 0 Python compiler subprocesses** |

### Multi-target builds (`--python 3.11 --python 3.12` / `--python-platform ...`)
- Previously, every target combination passed `--refresh-package <local>` to `uv pip install`,
  rebuilding local pure-Python wheels from source N times (~210 ms each).
- Now `build()` passes `refresh=(i == 0)`, refreshing local directory packages into `uv`'s wheel
  cache on the first target and reusing the freshly built wheel on subsequent targets within the
  same `build()` call (~35% faster multi-target builds).

### `bundleup verify` on `--format dir` and unpacked caches
- Replaced `Path.rglob("*")` + `relative_to()` in `_verify._check_dir` and `_verify._check_cache`
  with `_walk_dir` (`os.walk`), cutting directory walk overhead by ~4× on multi-thousand-file
  trees while also detecting unexpected symlinks.

### Runtime startup
- Cold run (first execution): unpacks `payload.zip` once to a content-addressed directory and
  executes immediately; ~2.3–15× faster than `pex`.
- Warm run (subsequent executions): `_loader.py` imports only `os`, `sys`, `errno` on the fast path,
  takes a shared `flock`, and `exec`s `__main__` with precompiled `.pyc` files — matching a plain
  virtualenv within noise (~17 ms total process time).

---

## 3. UX & simplicity improvements implemented

1. **Zero-config entry point fallback for `<package>/__main__.py`:**
   - Projects that run via `python -m my_pkg` (`src/my_pkg/__main__.py`) often omit
     `[project.scripts]` in `pyproject.toml`. `resolve_entry()` now automatically falls back to
     `Entry("module", pkg)` when `(site / pkg / "__main__.py").is_file()`, so `bundleup build`
     works out of the box without requiring `--entry`.
2. **Early, actionable output path validation (`-o`):**
   - Passing an existing directory to `-o dist/` (without `--format dir`) or passing the input
     script itself (`bundleup build app.py -o app.py --format py`) now fails immediately with a
     clear `UsageError` and hint before running `uv`.
3. **`bundleup check` works seamlessly with multi-target `[tool.bundleup]` configs:**
   - When `pyproject.toml` defines `python-platform = ["linux", "macos"]` in `[tool.bundleup]`,
     running `bundleup check` or `bundleup check --matrix` no longer fails with a multi-target
     `UsageError`; instead it checks the primary target and folds the extra platforms into
     `also_platforms`.
4. **Smarter `--smoke` CLI flag parsing:**
   - `bundleup build --smoke "--version"` and `bundleup build --smoke "-V"` pass the flag to the
     bundle, while `bundleup build --smoke --help` prints `bundleup build`'s help without building,
     and options that take values (`--entry --smoke`) never misinterpret their argument as `--smoke`.
5. **Cleaner `bundleup verify` output on `--format dir`:**
   - Verifying a `--format dir` directory no longer prints the misleading line
     `unpacked copy: not unpacked on this machine`.
