# Python Build & Packaging Tooling vs. Other Ecosystems: Where the Real Gaps Are (October 2026)

Python has no maintained esbuild equivalent: no tool starts at an entry point, follows imports into installed packages, and writes one artifact for a bare interpreter.\[1\] `uv run` plus PEP 723 already covers most of tsx except watch mode. The best opportunity is therefore an import-aware, multi-platform zipapp bundler. It is a crowded and risky one, though, because uv has an open "uv zipapp" request (astral-sh/uv#7419, opened September 16, 2024 and labeled "wish: Not on the immediate roadmap") and OpenAI has agreed to acquire it.

## TL;DR
- **esbuild equivalent: largely missing.** stickytape, the closest match, last shipped in January 2021 and finds imports with a regex. shiv, pex and zipapps bundle from declared requirements rather than by following imports. Nothing does module pruning or `--target`-style downleveling. Astral called bundling something it is "interested in doing someday", not a current focus.
- **tsx equivalent: about 80% solved.** `uv run script.py` with PEP 723 inline metadata gives you a zero-setup run with dependencies. What's missing is a built-in watch mode (astral-sh/uv#9652, labeled "help wanted"), smooth handling of files inside packages (relative imports), and PEP 723 for multi-file `.pyz` (uv#18662). The watch-mode gap is small enough that a single PR to uv could close it, so it isn't a product.
- **Top 3 opportunities:** (1) an import-graph-aware bundler built on uv's resolver that emits multi-platform `.pyz`/scie artifacts with runtime guards; (2) a deploy-artifact size analyzer and pruner (Lambda/containers); (3) a dev-loop runner (watch, restart, `-m` auto-detection), best shipped as a uv contribution or a thin uv wrapper. Freezers (PyInstaller, Nuitka, pex `--scie`) and lockfiles are solved. Don't rebuild them.

---

## 1. Executive summary

**Biggest gaps, ranked (detailed in §6):**
1. **An import-following bundler that only needs the interpreter** (the esbuild analogue). It exists only in abandoned or partial form.
2. **Artifact size analysis and module-level pruning** for zipapps, containers and serverless. No tool does this.
3. **A built-in dev-loop and watch runner.** It exists as glue (`watchfiles 'uv run app.py'`), with rough edges such as SIGINT propagation (uv#8654).
4. **Target-version checking and downleveling for bundled code.** Checking exists (vermin 1.8.0, November 2025). Downleveling is essentially missing, since py-backwards is dead and strip-python3 is a one-person project.
5. **Native-code matrix pain.** This is standards work (abi3t in 3.15; wheel variants still in draft), not something a small team can fix.
6. **A task runner and polish for uv workspaces.** Third-party tools exist; it's a modest gap.

**Does an esbuild equivalent exist?** No, not in the import-following sense. If you only need "one file containing my code and its deps, runnable by `python`", the honest answer is that **pex** does it (2.103.2, released September 18, 2026, several releases a week).\[2\] zipapps (ClericPy, released April 25, 2026) also does it.\[3\] **shiv** works but is in maintenance mode, with its last release on November 1, 2024.\[4\] All three resolve declared requirements, not the import graph. None prunes, minifies, or checks the target version.

**Does a tsx equivalent exist?** Mostly. `uv run` with PEP 723 is the tsx/`bun run`/`dotnet run app.cs` analogue. Watch mode is the visible gap, but it is tracked upstream and is cheap for Astral to close.

**Context you must factor in:** OpenAI announced on March 19, 2026 that it would acquire Astral (uv, Ruff, ty), with the team joining Codex. OpenAI said that until closing the two "will remain separate and independent companies", and secondary reports through August 2026 found no confirmation that the deal has closed. JetBrains' PyCharm blog (March 2026) puts uv at "around 124 million monthly downloads"; other outlets citing PyPI Stats give 126 million. Any gap squarely in uv's lane carries "uv ships it" risk. The acquisition also adds uncertainty about uv's roadmap, which could cut either way.\[5\]

---

## 2. How Python works, for tool builders (Part 1)

### 2.1 Imports
- **`sys.path` / `sys.modules`.** Import looks in the `sys.modules` cache first. On a miss, it asks each finder on `sys.meta_path` (by default BuiltinImporter, FrozenImporter, then PathFinder). PathFinder walks `sys.path` entries through `sys.path_hooks`, so zip files get a `zipimporter`. Unlike Node, there is no per-file resolution relative to the importer. There is no `node_modules` walk-up, and only one copy of a package can exist per process. That kills npm-style nested duplicate versions, and with it any easy fix for dependency conflicts inside a bundle.
- **Import hooks.** A custom finder or loader on `sys.meta_path` is the Python equivalent of a Node loader hook (`--import`/`module.register`). Bundlers like stickytape, pinliner and PyOxidizer's `oxidized_importer` all work this way.\[6\] The catch is that third-party code calling `__file__`, `pkgutil`, or `importlib.metadata` assumes a real filesystem.
- **Packages vs namespace packages.** A directory with `__init__.py` is a regular package. Without one it is a PEP 420 namespace package, which can be split across several `sys.path` entries (e.g. `google.*`, `azure.*`). A bundler must merge these portions rather than pick one.
- **Relative imports, `python -m`, and "attempted relative import with no known parent package".** Relative imports resolve against `__package__`/`__spec__.parent`. `python path/to/mod.py` runs the file as `__main__` with no parent package, and it puts the script's directory, not the project root, on `sys.path[0]`. Any `from . import x` then fails. `python -m pkg.mod` sets the package context correctly. Node has no such distinction, which is why tsx can "just run a file". A tsx-like Python runner has to work out the package root and rewrite `file.py` into `-m pkg.mod`.

### 2.2 Bytecode and zip import
- `.pyc` files are cached in `__pycache__/` and keyed by interpreter version (`cpython-313`). They can be validated by mtime or hash (PEP 552). Bytecode is **not** portable across minor versions, so shipping only `.pyc` locks you to one exact minor version.
- `zipimport` loads `.py` and `.pyc` from zips but **never writes** a bytecode cache. Shipping only `.py` in a zipapp means every cold start recompiles it, so bundlers should precompile for the target interpreter. More importantly, `zipimport` **cannot load extension modules**. That is the root reason shiv extracts to `~/.shiv` and pex unpacks into a cache or venv on first run.\[4\]

### 2.3 Native extensions
- **Build and load.** C, C++, Cython, Rust (PyO3/maturin) and mypyc all produce a shared library (`.so`/`.pyd`) exposing `PyInit_<name>`. `ExtensionFileLoader` calls `dlopen`/`LoadLibrary`, which needs a real file path. Linux `memfd_create` can technically get around this. Windows has custom in-memory loaders, which PyOxidizer used. Neither is portable, and both break libraries that locate sibling `.so` files via `$ORIGIN`/rpath.
- **The ABI matrix.** Each binary wheel is keyed by OS × CPU × libc (glibc version via manylinux, or musllinux) × Python minor version × GIL vs free-threaded (`cp313` vs `cp313t`). Since 3.14 there is also a further split for free-threaded builds.
- **abi3 / Limited API** removes the Python-version axis: one `cp3X-abi3` wheel runs on 3.X and later, though only on GIL builds until now. **PEP 803 ("abi3t")** is accepted and ships in Python 3.15. Extensions can now target a stable ABI that works on free-threaded builds, but only from cp315 onward. The 3.15 docs note that, at the time of writing, setuptools, meson-python, scikit-build-core and maturin do **not** yet support abi3t, and maturin's tracking issue (#3064) is still exploratory.\[7\]\[8\]\[9\]
- **Compared with Node-API.** Node-API has been ABI-stable across Node majors for years, and prebuilt binaries are distributed as per-platform npm packages (`@esbuild/linux-x64`-style `optionalDependencies` with `os`/`cpu`/`libc` fields). Python's equivalent is the wheel tag system: multiple files per release, chosen by the installer. The tag system can't express GPU/CUDA, CPU-microarchitecture or BLAS variants. **PEP 817 (Wheel Variants)** was merged as a draft on January 23, 2026 and later split into PEP 825 and others. A September 30, 2026 PR turns PEP 817 into an Informational umbrella document. It is not landing soon. PyTorch publishes 7 variants that users must pick by index URL.\[10\]\[11\]\[12\]\[13\]

### 2.4 How packages find their own data and version
- `__file__`-relative paths (`os.path.dirname(__file__)`) are still common. They break inside zips and in-memory importers.
- `importlib.resources.files()` returns a Traversable that works through zip loaders. `as_file()` extracts to a temporary file when a real path is needed.
- `importlib.metadata.version()/entry_points()` reads `*.dist-info` directories found on `sys.path`. It works inside a zip **only if the bundler keeps the dist-info directories**. Stripping them, as naive "copy the modules" bundlers do, silently breaks version lookups and plugin discovery (pytest plugins, OpenTelemetry instrumentations, CLI entry points).
- **What this means for bundling:** an esbuild-style bundler must be **distribution-aware**, not just module-aware. It has to carry dist-info, data files and entry-point metadata, not only `.py` files.

### 2.5 How dynamic Python is in practice
`importlib.import_module(name)` with computed names, `__import__`, `try: import x except ImportError` optional dependencies, entry-point plugins, Django's `INSTALLED_APPS` strings, pickle and `getattr`-driven dispatch are everywhere. The best evidence that static analysis isn't enough is that **PyInstaller needs a large community hooks repository** (pyinstaller-hooks-contrib) to declare hidden imports and data files. GraalVM native-image has the same problem with "reachability metadata". stickytape states plainly that it "cannot automatically detect dynamic imports" and needs `--add-python-module`.\[14\]
- **Function-level tree-shaking:** not realistic. Module top-level code runs at import time, and attribute access is dynamic.
- **Module-level pruning:** feasible if it combines a static graph (modulegraph2 2.3, maintained, released November 2025)\[15\] with runtime tracing (`sys.modules` snapshots or `-X importtime` from tests) and hook files for escape hatches. Python 3.15's **lazy imports** make "imported" and "used" diverge further, which helps tracing but not static guarantees.

### 2.6 How Python reaches users' machines
- **macOS:** `/usr/bin/python3` is a shim that prompts you to install the Xcode Command Line Tools. Don't build on it.
- **Windows:** `python.exe` in a fresh install is often the Microsoft Store app-execution-alias stub. The python.org installers and the new Python install manager (PEP 773) are the official paths.
- **Linux:** distro Pythons are marked **externally managed (PEP 668)**, so `pip install` into the system interpreter is refused. Users are pushed to venvs, pipx/uv tool, or distro packages. Interpreter versions vary widely by distro.
- **pyenv** compiles from source, which is slow and needs a toolchain. **conda** ships its own interpreter and non-Python libraries. **python-build-standalone** provides relocatable prebuilt CPython (now maintained under Astral) and underpins `uv python install`, pex `--scie`, PyApp and others.
- **What this means for tool builders:** "needs only the runtime" means a different runtime on every machine. For anything aimed at end users, the realistic target is "carry or fetch a python-build-standalone interpreter" (scie, PyApp, PyCrucible), not "use whatever `python3` exists".

---

## 3. Community and governance (Part 2)

### 3.1 What developers value and complain about
- The **PSF/JetBrains Python Developers Survey** (8th edition, 30,000+ respondents, data collected late 2024, published August 2025) found that uv reached **11%** for environment isolation in its first year. It also found that **83%** of respondents don't use the latest Python.\[16\]\[17\] Treat these numbers with care: LWN commenters pointed out that there are no error bars, the sample is self-selected, and PyCharm usage looks suspiciously high.\[18\]
- The **Stack Overflow 2025 survey** (49,000+ responses from 177 countries) named uv the **most-admired "SO tag" technology (74%)**.
- Recurring complaints: too many tools ("which one do I use?"), slow resolvers, painful environments, CUDA/PyTorch installs, and distribution to non-developers. User comments on uv's bundling issues are blunt: "I've used a few packaging tools: zipapp, shiv, pex. none of them are very good" (uv#10019).\[19\]

### 3.2 How decisions get made
- The **Steering Council** (five people, elected by core developers) approves PEPs or delegates them. The PSF handles funding, PyPI and legal matters, not technical direction. **PyPA** is a loose group of projects (pip, setuptools, build, packaging, twine, cibuildwheel, etc.). Packaging PEPs are decided by a delegated PEP-Delegate on discuss.python.org's Packaging category.
- **How adoption actually happens:** a tool ships something good, a standard follows, and other tools adopt it. Examples are PEP 723, which grew out of pipx/hatch/uv script runners, and PEP 751. PEP 751 was accepted in March 2025, and pip added experimental `pip lock` in 25.1\[20\] and experimental `pip install -r pylock.toml` in 26.1 (April 2026). uv can export it, and PDM supports it. As of mid-2026, Poetry had not shipped it, and Dependabot and Bazel rules_python had open requests.\[21\]\[22\]\[23\]\[24\]
- **Where proposals stall:** big cross-cutting designs. Lockfiles took years, and PEP 665 was rejected before 751. Wheel variants grew too big to approve, were split up in 2026, and still have unresolved lockfile interactions. Distribution of non-Python dependencies (PEP 725) is in a similar position. Anything that needs both index and installer changes moves slowly.\[25\]

### 3.3 Feelings about uv, Astral and "Rust-ification"
- Adoption has been overwhelming, and Rye's author openly argued that the community should rally around one dominant tool ("Domination is a goal…").\[26\]
- Concern about a VC-backed company owning core tools turned into concern about a large AI company owning them once OpenAI announced the acquisition. Both sides say uv, Ruff and ty stay MIT-licensed and open.\[27\] Simon Willison noted that a "product+talent acquisition can turn into a talent-only acquisition later on", and that Astral's pyx registry was missing from both announcements.\[28\] The forkability argument (MIT, Rust) is real, but few people could maintain a fork.
- **Implication for you:** a tool that sits *on top of* uv's primitives inherits uv's adoption but also its roadmap risk. Being uv-agnostic, for example by consuming pylock.toml or wheels directly, is a hedge.

### 3.4 Groups with different needs
| Group | What they need | Tooling reality |
|---|---|---|
| Web/backend | Locked deps, Docker images, fast CI | uv solves most of this; image size and cold start remain pain points |
| Data science/ML | CUDA/BLAS binaries, non-Python libs | conda/pixi world; wheel variants unresolved; bundling barely applies |
| Scripting/DevOps | One-file scripts on random hosts | PEP 723 + uv solves this *if uv is installed*; otherwise you need zipapps or a single binary |
| Library authors | Build backends, wheel matrix, CI | cibuildwheel/maturin/scikit-build-core mature; abi3t adoption pending |
| App distributors | Installers and executables for end users | PyInstaller/Nuitka/Briefcase; signing and notarization pain |
| Education | No-setup runs | uv + PEP 723 helps; system-Python traps (macOS shim, Store stub, PEP 668) remain |

---

## 4. Toolchain map (Part 3), as of October 2026

Status key: **Active** = release in the last ~6 months; **Maint.** = occasional fixes; **Dead** = no development.

### 4.1 Getting an interpreter
| Tool | Status | Notes |
|---|---|---|
| uv python | Active | Downloads python-build-standalone builds; the de facto default |
| python-build-standalone | Active (Astral) | Relocatable CPython; foundation for uv, pex scie, PyApp |
| pyenv | Maint./active | Builds from source; slow; still common |
| conda/mamba/pixi | Active | Interpreter plus native libraries; the ML world |
| Rye | **Dead** | "No longer developed as of February 2025"; no security updates; replaced by uv\[29\] |

### 4.2 Environments, dependencies, lockfiles
| Tool | Status | Lockfile | Notes |
|---|---|---|---|
| uv | Active | uv.lock (universal); exports pylock.toml | Replaces pip/pip-tools/pipx/pyenv/virtualenv |
| pip | Active | Experimental `pip lock` (25.1), `install -r pylock.toml` (26.1) | Baseline installer\[22\] |
| pip-tools | Maint. | requirements.txt; `pip-lock` PR for PEP 751 | Being replaced by uv\[30\] |
| Poetry | Active | poetry.lock; no pylock.toml yet (mid-2026) | Large installed base |
| PDM | Active | pdm.lock + PEP 751 export | Standards-forward |
| Hatch | Active | Environments; locking via plugins | Build backend hatchling is popular |
| Pipenv | Maint. (declined) | Pipfile.lock + pylock.toml (2026.7.1)\[31\] | Lost the mindshare race to Poetry, then uv, over years of slow resolution\[32\] |
| pixi | Active | pixi.lock (conda + PyPI) | conda-world answer to uv |
Standards: PEP 621 (`[project]` metadata), PEP 735 (dependency groups), PEP 751 (pylock.toml), PEP 668.

### 4.3 Build backends and native builds
| Tool | Purpose |
|---|---|
| setuptools | Legacy default; C extensions |
| hatchling, flit-core, pdm-backend, uv_build | Pure-Python backends (uv_build is Astral's) |
| maturin | Rust/PyO3 extensions; abi3; abi3t support exploratory (#3064) |
| scikit-build-core | CMake-based extensions |
| meson-python | Meson (NumPy, SciPy) |
| cibuildwheel | CI matrix builder for manylinux/musllinux/macOS/Windows wheels |
Standards: PEP 517/518 (build interface), PEP 660 (editable installs), wheel format, manylinux (PEP 600), musllinux (PEP 656), abi3, PEP 803 abi3t (3.15).

### 4.4 Publishing
PyPI supports **Trusted Publishing** (OIDC from GitHub, GitLab and others, no long-lived tokens) and **PEP 740 attestations**. Private indexes: devpi, Artifactory, CodeArtifact, GitLab, and Astral's pyx (a commercial registry, whose future after the acquisition is unclear). What's missing compared with npm: namespaces/scopes. Typosquatting remains an operational problem.

### 4.5 Running scripts and dev loops
| Tool | Status | Notes |
|---|---|---|
| `python -m` | stdlib | Correct package context |
| `uv run` / `uv run --script`, `uvx` | Active | PEP 723 inline deps; shebang `#!/usr/bin/env -S uv run --script` |
| pipx run | Active | PEP 723 support; slower |
| watchfiles (CLI) | Active | Rust `notify`-based; `watchfiles "python main.py" src`;\[33\] used by uvicorn `--reload` |
| hupper, watchdog, pytest-watcher, entr | Various | Generic restarters |
Gap: there is no first-party `--watch` (uv#9652, "help wanted"), and signal handling through `uv run` under watchers has been buggy (uv#8654).\[34\]\[35\]

### 4.6 Bundling into one file that only needs the runtime
| Tool | Status (Oct 2026) | Approach | Limits |
|---|---|---|---|
| zipapp (stdlib) | stdlib | Zips a directory | No dependency handling |
| shiv | **Maint.** (1.0.8, Nov 1, 2024; classifiers ≤3.11) | Requirements → `.pyz`, extracts to `~/.shiv`\[4\] | Platform-specific if native; no pruning |
| pex | **Very active** (2.103.2, Sep 18, 2026) | Requirements/lock → `.pex`; multi-platform via `--platform`/`--complete-platform`; venv mode | No import-graph pruning; no target checks |
| zipapps (ClericPy) | Active (Apr 25, 2026) | `.pyz` with deps; lazy install option\[36\] | Single maintainer |
| stickytape | **Dormant** (0.2.1, Jan 29, 2021) | Follows imports → one `.py`\[37\]\[38\] | Regex import detection; writes to temp dir; breaks `__file__`/data\[38\]\[39\]\[40\] |
| pinliner | **Dead** (~2016–17; uses removed `imp`) | Inlines named packages\[41\]\[42\] | Does not follow imports; Python 2-era |
| tinyBundle | **Dead** (archived Oct 22, 2024) | Rollup-like file concatenation\[43\] | Never released on PyPI |
| pip's `vendoring` / `get-pip.py` | Internal-purpose | Vendors deps with import rewriting / embeds a base85 zip | Purpose-built, not general |

### 4.7 Freezing and standalone executables
| Tool | Status | Notes |
|---|---|---|
| PyInstaller | Active (6.22.3, Sep 12, 2026) | Most used; hooks ecosystem; no cross-compiling\[44\] |
| Nuitka | Active | Compiles to C; standalone/onefile; commercial tier |
| cx_Freeze | Active | Classic freezer |
| Briefcase (BeeWare) | Active | Native installers, mobile |
| pex `--scie eager/lazy` | Active | Embeds or lazily fetches python-build-standalone; native binary; Python ≥3.8\[45\] |
| PyApp (Ofek) | Active | Rust bootstrapper; installs the project on first run |
| PyCrucible | Active (0.4.6, Mar 22, 2026) | Rust + embedded uv; ~2 MB binary; bootstraps at runtime\[46\]\[47\] |
| pyfuze | Active-ish (2.7.1, Jul 7, 2025) | Cosmopolitan APE + uv; portable mode embeds Python 3.12.3\[48\]\[49\] |
| PyOxidizer | **Dead** (0.24.0, Dec 30, 2022) | Author: "PyOxidizer and PyOxy fell into a state of neglect" by early 2023; python-build-standalone spun out and survived\[50\]\[51\] |

### 4.8 Lint, format, type-check, test (the Rust trend only)
Ruff replaced flake8, isort and Black for many teams. ty (Astral) and Rust-based checkers are going after mypy and pyright. pytest is unchallenged. Rust rewrites succeed when the tool is a pure function over source files or metadata (lint, format, resolve). They are much harder for anything that has to *execute* Python, which is why no one has a Rust pytest. A bundler sits in between: graphing and zipping are Rust-friendly, but discovering dynamic imports needs Python running.

### 4.9 Monorepos
Pants (uses pex internally; fine-grained dependency inference from imports), Bazel rules_python (pylock.toml support still requested in #3088), and uv workspaces (shared lockfile; no built-in task runner). Pants' import-based dependency inference is the closest existing "follow the imports" engine. It is tied to Pants, though, which shows the technique works at scale.

---

## 5. Comparison matrix across ecosystems (Part 4)

Python cells are marked **S** (solved), **P** (partial) or **M** (missing).

| Ecosystem | Runtime/versions | Deps & lockfile | Single file + inline deps | Dev loop / watch | One-file bundle (runtime only) | Tree-shake / minify / `--target` | Native code | Standalone exe | Workspaces | Registry & supply chain | Tool speed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Python** | **S**: uv python + python-build-standalone; system Pythons are traps | **S** (uv.lock); standard pylock.toml **P** (experimental in pip) | **S**: PEP 723 + `uv run` | **P**: external watchfiles; uv#9652 open | **P**: pex/shiv/zipapps, requirement-driven, extract native code to disk | **M**: no pruning, no downleveling; vermin checks only | **P**: wheels + manylinux + abi3 good; abi3t only from 3.15; GPU variants in draft | **P→S**: PyInstaller, Nuitka, pex scie, PyApp; no first-party; weak cross-building | **P**: uv workspaces, no task runner; Pants/Bazel | **P/S**: Trusted Publishing + PEP 740; no namespaces | **S**: uv, Ruff |
| JS/TS | nvm/fnm/volta/corepack | npm/pnpm/yarn lockfiles | tsx/Bun/Deno run; Deno `npm:` specifiers inline | `node --watch`, `tsx watch`, `bun --watch` | esbuild/Rollup/Bun build | Full: tree-shaking, minify, `--target` | Node-API ABI-stable; per-platform optionalDependencies | Node SEA, `bun build --compile`, `deno compile` | npm/pnpm workspaces, Nx/Turbo | npm provenance, scopes | esbuild/Bun/oxc very fast |
| Rust | rustup | Cargo.lock | cargo script (frontmatter); stabilization in FCP as of Feb 2026 | cargo-watch/bacon (third-party) | n/a (compiled) | Compiler DCE; MSRV via `rust-version` | Static linking default | Native by default | Cargo workspaces | crates.io trusted publishing | Fast tooling, slow compile |
| Go | Toolchain directive auto-downloads | go.mod/go.sum + checksum DB | `go run file.go` (no inline deps beyond module) | Third-party (air) | n/a | Linker DCE | cgo breaks cross-compile | Static binaries, trivial cross-compile | go.work | sumdb transparency log | Fast |
| Java/JVM | SDKMAN, toolchains | Maven/Gradle (locking optional) | JBang (`//DEPS`) | Gradle continuous, devtools | Fat/uber JAR; Shade relocation | ProGuard/R8 shrinking | Native libs inside JARs, extracted to temp at runtime (like shiv) | jlink, GraalVM native-image (needs reachability metadata) | Multi-module builds | Maven Central signing | Medium |
| .NET | SDK installers, global.json | NuGet + packages.lock.json | `dotnet run app.cs` with `#:package` (.NET 10); multi-file `#:include` in .NET 11\[52\]\[53\] | `dotnet watch` (first-party, hot reload) | Single-file publish | Trimming (IL linker) | RID-specific packages | Single-file / Native AOT | Solutions | NuGet signing | Good |
| Ruby | rbenv/rv | Gemfile.lock | `bundler/inline` | guard, rerun | Weak | None | Platform gems | Weak (Traveling Ruby, stale) | Monorepo via Bundler paths | RubyGems trusted publishing | Medium |
| PHP | Distro/phpenv | composer.lock | Weak | n/a | phar (Box) | None | Extensions are system-level | static-php-cli/FrankenPHP | Composer path repos | Packagist | Medium |
| Perl | perlbrew/plenv | cpanfile.snapshot (Carton) | Weak | n/a | App::FatPacker (pure-Perl only) | None | XS needs compile | PAR::Packer | n/a | CPAN | Medium |

**How to read this:** the columns where Python is clearly behind at least one other ecosystem are **watch mode** (behind Node and .NET), **one-file bundling** (behind esbuild, Shade and phar), **tree-shaking and target** (behind esbuild, R8 and .NET trimming) and **cross-building executables** (behind Go and `bun build --compile`). Python is roughly level on single-file scripts (PEP 723 came before .NET's `#:package` and cargo script), lockfiles and tool speed. Java's experience is the most useful precedent. Fat JARs with native libraries extracted to temp at runtime are exactly how shiv and pex work, and nobody calls that unsolved in Java. The difference is that Java ships *one* JAR per OS family less often, because JNI usage is rarer than C extensions are in Python.

---

## 6. Ranked gap analysis (Part 5)

Scores are out of 5. Defensibility means how hard it would be for uv, PyPA or an incumbent to replace you.

### Gap A: an import-aware, multi-platform "esbuild for Python" bundler
- **What's missing.** *Before:* `uv export --no-dev > req.txt && shiv -r req.txt -e app:main -o app.pyz`. This gives a platform-specific `.pyz` if any dependency has C code, and Windows-built bundles fail on Linux (as described in uv#7419).\[36\] There's no Python-version guard, no size report, dev dependencies leak unless you are careful, and a broken `__file__` usage only shows up at runtime. *After:* `pybundle app/main.py --target cp311-cp313 --platform linux-x86_64,macos-arm64 -o app.pyz`. This follows imports, maps modules to distributions, pulls the matching wheels for each platform from the lockfile, keeps dist-info and entry points, precompiles bytecode, embeds a startup guard ("needs CPython ≥3.11 on linux-x86_64; you have 3.10 on macOS"), and prints a per-distribution size breakdown plus warnings about dynamic imports and `__file__` usage.
- **Evidence it hurts:**
  - uv#7419 (opened September 2024): "building a zipapp is currently too complicated for the average user".\[36\]
  - uv#10019: "zipapp, shiv, pex. none of them are very good".\[19\]
  - uv#13263: a wheelhouse of runtime-only dependencies for shiv.\[54\]
  - uv#2752: `--target` as a zipapp recipe.\[55\]
  - uv#18662: PEP 723 for `.pyz`.\[56\]
  - The *volume* of requests (several distinct uv issues) is stronger evidence than any single thread. I did not measure Stack Overflow volume, so treat it as anecdotal.
- **Who it affects.** DevOps and script authors shipping internal CLIs, people deploying to hosts without uv or container builds, and Lambda/serverless users. That is perhaps hundreds of thousands of developers, but the survey data doesn't break this down, so the estimate is low-confidence.
- **Existing attempts.** pex covers most of the "after" except import-following, pruning, the size report and target guards. Its UX is aimed at Pants users. stickytape is dormant and uses a regex. shiv is in maintenance mode. zipapps has a single maintainer.
- **Obstacles.** Technical: dynamic imports (you need hooks like PyInstaller's), native code (extraction to disk is unavoidable), namespace packages, data files, and `__file__`. Cultural: Python users think in requirements, not imports, so "follow imports" must stay an optimization layered on a correct requirement-based bundle.
- **Risk someone ships it soon: medium-high.** Astral said in uv#7419 that bundling is "definitely something we're interested in doing someday… not sure zipapp is the ideal format for us".\[36\] uv#5802 (`uv bundle`) is labeled "wish / Not on the immediate roadmap".\[1\] The acquisition might speed this up or kill it. pex could also add a friendlier front end.
- **Feasibility for one developer: good.** Use uv or pex for resolution and wheel fetching, modulegraph2 or Python's `ast` for the graph, and tracing for confirmation.
- **Scores:** Pain 4, Reach 3, Feasibility 4, Defensibility 2. **Total 13.** Real pain, and doable, but uv could absorb it. The defensible parts are the dynamic-import intelligence (a hooks database) and the diagnostics, not the zipping.

### Gap B: deploy-artifact size analysis and module-level pruning
- **What's missing.** *Before:* a 900 MB container or a Lambda zip over AWS's documented 250 MB unzipped limit (which counts all uploaded files, including layers), with no idea which distributions or modules matter. People hand-delete `tests/`, `*.pyi` and unused botocore data. *After:* `pyprune analyze .venv --entry app:main --trace pytest` produces a treemap per distribution and module, marks what was "never imported in traced runs", and writes a prune manifest with an allowlist for dynamic imports. It can also output a slimmed site-packages, zipapp or layer.
- **Evidence it hurts:** I found no first-party tool and no dedicated thread in this research. The evidence is indirect: the PyInstaller hooks ecosystem exists to fight this exact dynamic-discovery problem, and native/data payloads dominate ML wheels. **Evidence is thin; validate it with user interviews before building.**
- **Who it affects:** serverless and container users, and app distributors (frozen app size).
- **Existing attempts:** PyInstaller excludes (manual), Nuitka's follow-import controls, Pants dependency inference (build-graph only), ad-hoc cleanup scripts.
- **Obstacles:** dynamic imports make pruning probabilistic. It needs tracing plus allowlists, and it has to fail safely with a clear error naming the pruned module.
- **Risk someone ships it soon: low-medium.** It's not on any uv issue I found.
- **Feasibility: good.** Analysis is read-only and low-risk. Pruning can be opt-in.
- **Scores:** Pain 3, Reach 3, Feasibility 4, Defensibility 3. **Total 13.** Less exposed to uv. It can be sold as a standalone product or folded into Gap A.

### Gap C: a dev-loop runner (the remaining tsx gap)
- **What's missing.** *Before:* `uvx watchfiles 'uv run app.py' src`. Ctrl-C and SIGINT propagation have broken through `uv run` (uv#8654). `python pkg/sub/mod.py` raises "attempted relative import with no known parent package", and the user has to know to rewrite it as `-m pkg.sub.mod` from the right directory. *After:* `uv run --watch pkg/sub/mod.py` (or `pyx-dev`) detects the package root, runs it as a module, restarts on changes to `.py` and config files, clears the screen, debounces, forwards signals, and optionally runs tests related to the change.
- **Evidence it hurts:** uv#9652 ("Essentially Bun watch mode but with uv") is labeled *help wanted*.\[34\] Downstream projects ask for watch modes (e.g. ethereum/execution-spec-tests#2156).\[57\] uvicorn has long-running reload bugs (watch limits, ignore patterns).\[58\]
- **Who it affects:** almost everyone writing Python, but the pain per person is low.
- **Existing attempts:** watchfiles, hupper, pytest-watcher, framework reloaders. All are good, but you have to assemble them yourself.
- **Obstacles:** a full process restart is the only safe way to reload in Python. `importlib.reload` hot-reload is unsound because module state and object identity persist. That caps how "magic" this can be.
- **Risk someone ships it soon: high.** It's "help wanted" upstream, so a contributor's PR can close it.
- **Feasibility: very high.**
- **Scores:** Pain 3, Reach 5, Feasibility 5, Defensibility 1. **Total 14.** It has the highest reach, but almost no moat. Do it as a uv contribution to build credibility, or as part of a broader dev-loop product, not as a standalone business.

### Gap D: target-version checking and syntax downleveling for bundles
- **What's missing.** An equivalent of esbuild's `--target cp38`: fail the build if bundled code, *including dependencies*, uses syntax or stdlib APIs newer than the target, and optionally rewrite simple syntax (walrus, match statements are not feasible, PEP 604 unions in annotations, f-string nesting).
- **Existing attempts:** **vermin** 1.8.0 (November 20, 2025; release notes: "Python 3.14 support and 200 new rules"; its README cites 4140 rules covering v2.0–2.7 and v3.0–3.14) checks syntax and stdlib but not dependency metadata,\[59\] and no bundler integrates it. **py-backwards** is dead.\[60\] **strip-python3** (2025, one person) downgrades syntax and strips hints.\[60\]\[61\] No "reverse pyupgrade" exists. Wheels already declare `Requires-Python`, which covers dependencies at install time but not vendored or bundled source.
- **Why demand is lower than in JS:** in Python you usually *choose the interpreter* (uv python, scie). The browser-compatibility problem that made `--target` essential in JS mostly doesn't exist here. Downleveling also can't handle stdlib API differences.
- **Risk:** low. **Feasibility:** checking is easy (wrap vermin plus `Requires-Python` across the bundle). Downleveling is hard to do correctly and has little value.
- **Scores:** Pain 2, Reach 2, Feasibility 3, Defensibility 3. **Total 10.** Build this as a *feature* of Gap A (the "target guard"), not as a product.

### Gap E: native-code matrix and variant selection
- **What's missing:** one wheel per platform that works for both GIL and free-threaded builds before 3.15, plus GPU/CPU-variant selection.
- **Status:** abi3t is accepted for 3.15, but build tools don't support it yet. Wheel variants (PEP 817 → 825 and others) are still in draft and being restructured as of September 2026.\[8\]\[9\]\[13\]
- **Feasibility for a small team:** low. This is standards and installer work, dominated by NVIDIA, Quansight, Astral and the PyTorch maintainers. Contributing abi3t support to maturin or scikit-build-core is a useful, credible contribution but not a product.
- **Scores:** Pain 4, Reach 3, Feasibility 1, Defensibility 1. **Total 9.**

### Gap F: cross-building standalone executables and monorepo task running
- **Executables:** pex `--scie` already builds per-platform native executables, with an embedded or lazily fetched interpreter. PyInstaller can't cross-build. **This is mostly solved: use pex `--scie eager` or PyApp.** The remaining pain is code signing and notarization, and that is a service business, not a tool.\[62\]
- **Task runner for uv workspaces:** poethepoet, just and nox exist. Pain is moderate and uv could add `[tool.uv.scripts]` at any time. **Scores:** Pain 2, Reach 3, Feasibility 5, Defensibility 1. **Total 11.**

### Ranking
| Rank | Gap | Pain | Reach | Feas. | Defens. | Total |
|---|---|---|---|---|---|---|
| 1 | A: Import-aware multi-platform bundler | 4 | 3 | 4 | 2 | 13 |
| 2 | B: Size analyzer/pruner | 3 | 3 | 4 | 3 | 13 |
| 3 | C: Dev-loop/watch runner | 3 | 5 | 5 | 1 | 14 (low moat) |
| 4 | F: Task runner / exe cross-build | 2 | 3 | 5 | 1 | 11 |
| 5 | D: Target check/downlevel | 2 | 2 | 3 | 3 | 10 (fold into A) |
| 6 | E: Native matrix / variants | 4 | 3 | 1 | 1 | 9 (standards work) |

I rank C below A and B despite its higher raw total, because a moat score of 1 means uv can close it with one PR.

### Top 3 opportunities and MVP outlines

**1. `pybundle`, an esbuild-style bundler (combines A and D)**
- Input: an entry module or script (PEP 723 aware) plus a uv.lock or pylock.toml.
- Static import graph (`ast` walk or modulegraph2) → module-to-distribution map using `RECORD` files → include only reachable distributions. The default is safe mode, which includes every locked runtime distribution and *reports* the ones it considers unreachable.
- Multi-platform: fetch wheels for each `--platform`/`--python` from the lock, and build either one "fat" `.pyz` with per-platform native subtrees picked at startup, or one artifact per platform. Pure-Python projects produce a single universal `.pyz`.
- Runtime bootstrap: an import hook that serves pure code from the zip, extracts native code and data to a content-addressed cache (as shiv and pex do), keeps dist-info so `importlib.metadata` and entry points work, and runs a startup guard checking interpreter version, platform and free-threaded build.
- Build-time diagnostics: dynamic `import_module` calls, `__file__` usage, and `pkg_resources` usage. A hooks file format (borrow PyInstaller's hooks-contrib knowledge, checking its license) and a vermin-based `--target` check.
- Optional `--exe`: hand off to pex `--scie`/science or PyApp. Don't write your own launcher.
- Differentiator to state openly: "pex's correctness, esbuild's ergonomics and diagnostics". Write it in Rust or Python. Python is fine, since the speed bottleneck is downloads.

**2. `pyprune`, a size analyzer for deploy artifacts (B)**
- `pyprune analyze <venv|image|zip>` produces an HTML treemap by distribution, module, file type (`.so`, tests, `.pyi`, data) and duplicates.
- `--trace "pytest -x"` or `--trace "python -m app --selftest"` records `sys.modules` and file opens, then marks what was never touched.
- `pyprune apply --manifest` writes a slimmed copy, with a safety shim that raises a clear error naming any pruned module that gets imported.
- Lambda- and Docker-specific presets. This can be monetized (CI reports), and it stands apart from uv's core focus.

**3. Dev-loop runner (C): ship it upstream first**
- Implement `uv run --watch` (uv#9652): Rust `notify`, debouncing, process-group signal handling (the uv#8654 class of bugs), restarts on changes to `pyproject.toml`/lock with re-sync, and auto-conversion of `pkg/x.py` to `-m pkg.x` when it is inside a package.
- If Astral declines it, ship a 1-binary wrapper (`uvw`) instead. Either way, the main payoff is credibility and distribution for opportunities 1 and 2, not revenue.

---

## 7. Verdicts on the hypotheses

1. **"Python has no esbuild equivalent." Confirmed, with nuance.** No *maintained* tool follows imports from an entry point into installed packages and emits one interpreter-runnable artifact. stickytape is the only real attempt: its last release was January 2021 and it uses regex detection.\[37\]\[38\] pinliner and tinyBundle are dead. modulegraph2 analyzes but doesn't bundle.\[63\] However, requirement-driven bundlers (pex, which is very active; zipapps; shiv, in maintenance) already produce "code + deps in one file for the runtime". For most users, the missing pieces are ergonomics, multi-platform defaults, diagnostics and pruning, not the ability to bundle at all.
2. **"`uv run` + PEP 723 covers most of tsx; what's left is watch mode and files inside packages." Mostly confirmed.** Add two more: PEP 723 doesn't cover multi-file or `.pyz` programs (uv#18662), and signal-forwarding and watcher integration has had bugs (uv#8654). Python needs no transpile step, so tsx's TypeScript stripping doesn't apply. .NET 10's `dotnet run app.cs` with `#:package` and Rust's cargo script (stabilization FCP, February 2026) are converging on the same model that PEP 723 shipped first.\[64\]\[65\]\[66\]
3. **"Native extensions are the biggest technical obstacle; multi-platform wheels (pex-style) are the most promising answer." First half confirmed; second half partly.** `zipimport` can't load extensions, and `dlopen` needs a real file, so extracting to disk can't be avoided. Multi-platform wheel selection is *necessary*, and pex already does it, so it isn't new. It doesn't solve GPU/CPU variants (PEP 817/825 still in draft) or free-threaded builds before 3.15 (abi3t is cp315+ only, with no build-tool support yet). The most practical answer is per-target artifacts that bring their own interpreter (scie/python-build-standalone), with a fat multi-platform `.pyz` only for small native footprints.
4. **"Function-level tree-shaking is impractical; module-level pruning is feasible." Confirmed.** Import-time side effects and dynamic attribute access rule out function-level shaking. Module- and distribution-level pruning works if you combine static graphs, runtime tracing and hook allowlists. The PyInstaller hooks ecosystem and GraalVM's reachability metadata show this is workable but always needs upkeep. The size gains are mostly at *distribution and data* level (tests, `.pyi`, unused botocore/ML data), not in pure-Python modules.
5. **"Python lacks syntax downleveling and minimum-version checking for bundled code." Half true.** *Checking* exists: vermin 1.8.0 (November 2025) is maintained,\[67\] though no bundler integrates it. *Downleveling* is effectively missing: py-backwards is dead, strip-python3 is a small one-person project, and no reverse pyupgrade exists. Demand is far lower than in JS, because Python deployments pick their interpreter. Build target *checking* as a bundler feature and skip downleveling.

---

## 8. Sources and evidence quality

- **Strong primary sources:** the astral-sh/uv issues (#7419, #5802, #9652, #8654, #10019, #18662, #13263, #2752); PEP 803, PEP 817 and the PEP 825 discussions on discuss.python.org; the CPython 3.15 "What's New"; PyPI release histories (pex, shiv, PyInstaller, pycrucible, pyfuze, stickytape, modulegraph2, vermin); the Rye site; Gregory Szorc's blog; Astral's and Armin Ronacher's posts; the Rust cargo PR #16569 and the Inside Rust update; Microsoft's file-based-apps docs; and JetBrains' survey pages.
- **Secondary or weaker sources, flagged:** the acquisition's HN comment counts and some commentary come from aggregator blogs. Survey representativeness is disputed (LWN). Some release dates for zipapps, strip-python3 and pinliner come from libraries.io, piwheels or profile pages rather than release pages. pinliner's exact last release date is unconfirmed.
- **Not verified in this research, and stated from established background knowledge:** the specifics of Node SEA, `bun build --compile`, JBang, Shade, PAR::Packer and static-php-cli. The claim that python-build-standalone moved to Astral is also unverified here. Check these before quoting them externally.
- **Changing fast; recheck before you build:** whether cargo script has shipped in a stable Rust release, Astral's post-acquisition roadmap for bundling, abi3t support in build backends, and the PEP 825 series.

## Sources

1. [Suggestion: \`uv bundle\`, \`uv build --release\` or similar to create a contained executable a la pyinstaller, py2exe · Issue #5802 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5802)
2. [pex · PyPI](https://pypi.org/project/pex/)
3. [Profile of pythonld · PyPI](https://pypi.org/user/pythonld/)
4. [shiv · PyPI](https://pypi.org/project/shiv/)
5. [OpenAI Just Acquired Astral: What It Means for uv, Ruff, and Every Python Developer - DEV Community](https://dev.to/max_quimby/openai-just-acquired-astral-what-it-means-for-uv-ruff-and-every-python-developer-41ah)
6. [Hacking python's import system for single file packages - Christopher Prohm](https://cprohm.de/blog/python-packages-in-a-single-file/)
7. [PEP 803](https://peps.python.org/pep-0803/)
8. [Implement PEP 803 -- abi3t · Issue #146636 · python/cpython](https://github.com/python/cpython/issues/146636)
9. [What's new in Python 3.15 — Python 3.15.0rc3 documentation](https://docs.python.org/3.15/whatsnew/3.15.html)
10. [PEP 817 - Wheel Variants: Beyond Platform Tags - Packaging - Discussions on Python.org](https://discuss.python.org/t/pep-817-wheel-variants-beyond-platform-tags/105860)
11. [peps/peps/pep-0817.rst at main · python/peps](https://github.com/python/peps/blob/main/peps/pep-0817.rst)
12. [PEP 817: Wheel Variants: Beyond Platform Tags by DEKHTIARJonathan · Pull Request #4740 · python/peps](https://github.com/python/peps/pull/4740)
13. [PEP 817: Wheel Variants: switch to Informational, major update by rgommers · Pull Request #5149 · python/peps](https://github.com/python/peps/pull/5149)
14. [github.com](https://github.com/dmgolembiowski/stickytape)
15. [modulegraph2 · PyPI](https://pypi.org/project/modulegraph2/)
16. [The State of Python 2025: Trends and Survey Insights - The JetBrains Blog](https://blog.jetbrains.com/pycharm/2025/08/the-state-of-python-2025/)
17. [Python survey 2025: key trends, tools, and takeaways](https://www.frameworktraining.co.uk/news-insights/what-eighth-python-developer-survey-means)
18. [The State of Python 2025 \[LWN.net\]](https://lwn.net/Articles/1034313/)
19. [build tool · Issue #10019 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10019)
20. [Python Tools Are Quickly Adopting the New pylock.toml Standard](https://socket.dev/blog/pylock-toml-standard-adoption)
21. [Tool-Agnostic Python Lock Files With PEP 751 and pylock.toml](https://realpython.com/python-lock-file-pylock-toml/)
22. [What is PEP 751?](https://pydevtools.com/handbook/explanation/what-is-pep-751/)
23. [Support pylock.toml / PEP 751 requirements files · Issue #3088 · bazel-contrib/rules\_python](https://github.com/bazel-contrib/rules_python/issues/3088)
24. [PEP 751 pylock.toml support · Issue #12094 · dependabot/dependabot-core](https://github.com/dependabot/dependabot-core/issues/12094)
25. [PEP 817 - Wheel Variants: Beyond Platform Tags - Page 11 - Packaging - Discussions on Python.org](https://discuss.python.org/t/pep-817-wheel-variants-beyond-platform-tags/105860?page=11)
26. [Rye and uv: August is Harvest Season for Python Packaging](https://lucumr.pocoo.org/2024/8/21/harvest-season/)
27. [OpenAI Bought the Company Behind Python's Fastest Tools](https://kkm-mako.com/en/blog/articles/openai-acquires-astral-ruff-uv/)
28. [Thoughts on OpenAI acquiring Astral and uv/ruff](https://simonw.substack.com/p/thoughts-on-openai-acquiring-astral)
29. [Rye](https://rye.astral.sh/)
30. [✨ feat(lock): add pip-lock command for PEP 751 pylock.toml by gaborbernat · Pull Request #2380 · jazzband/pip-tools](https://github.com/jazzband/pip-tools/pull/2380)
31. [PEP 751 pylock.toml Support — pipenv 2026.7.1 documentation](https://pipenv.pypa.io/en/latest/pylock.html)
32. [pylock.toml and PEP 751](https://deepwiki.com/pypa/pipenv/3.4-pylock.toml-and-pep-751)
33. [watchfiles](https://pydevtools.com/handbook/reference/watchfiles/)
34. [Add \`uv run --watch script.py\` command to rerun \`uv run\` on \`.py\` file changes · Issue #9652 · astral-sh/uv](https://github.com/astral-sh/uv/issues/9652)
35. [uv run and SIGINT propagation · Issue #8654 · astral-sh/uv](https://github.com/astral-sh/uv/issues/8654)
36. [Provide uv zipapp](https://github.com/astral-sh/uv/issues/7419)
37. [stickytape 0.2.1 on PyPI - Libraries.io - security & maintenance data for open source software](https://libraries.io/pypi/stickytape)
38. [pypi.org](https://pypi.org/project/stickytape/0.1.3/)
39. [Convert Python packages to single-file Python scripts with stickytape](https://mike.zwobble.org/2012/10/convert-python-packages-to-single-file-python-scripts-with-stickytape/)
40. [pypi.org](https://pypi.org/project/stickytape/0.1.11/)
41. [GitHub - Akrog/pinliner: Python Inliner merges in a single file all files from a Python package. · GitHub](https://github.com/Akrog/pinliner)
42. [pinliner/pinliner/importer.template at master · Akrog/pinliner](https://github.com/Akrog/pinliner/blob/master/pinliner/importer.template)
43. [github.com](https://github.com/jakewdr/tinyBundle)
44. [PyInstaller Manual — PyInstaller 6.22.3 documentation](https://www.pyinstaller.org/)
45. [pex\_binary](https://www.pantsbuild.org/dev/reference/targets/pex_binary)
46. [pycrucible · PyPI](https://pypi.org/project/pycrucible/)
47. [razorblade23/PyCrucible](https://deepwiki.com/razorblade23/PyCrucible)
48. [pyfuze · PyPI](https://pypi.org/project/pyfuze/)
49. [Python Packaging Tool Revolution: Eliminate Environment Issues with pyfuze](https://www.xugj520.cn/en/archives/python-packaging-tool-pyfuze-2.html)
50. [categories: Personal, PyOxidizer - Gregory Szorc's](https://gregoryszorc.com/blog/category/pyoxidizer/)
51. [pyoxidizer · PyPI](https://pypi.org/project/pyoxidizer/)
52. [File-based apps - .NET](https://learn.microsoft.com/en-us/dotnet/core/sdk/file-based-apps)
53. [Run C# Scripts With dotnet run app.cs (No Project Files Needed)](https://milanjovanovic.tech/blog/run-csharp-scripts-with-dotnet-run-app-no-project-files-needed)
54. [Create a wheelhouse with only runtime wheels · Issue #13263 · astral-sh/uv](https://github.com/astral-sh/uv/issues/13263)
55. [Support pip's --target · Issue #2752 · astral-sh/uv](https://github.com/astral-sh/uv/issues/2752)
56. [Wishlist: make \`uv run --script\` shebang also work for zipapp \`.pyz\` files · Issue #18662 · astral-sh/uv](https://github.com/astral-sh/uv/issues/18662)
57. [feat(fill): watch mode with re-run for \`uv run fill\` · Issue #2156 · ethereum/execution-spec-tests](https://github.com/ethereum/execution-spec-tests/issues/2156)
58. [Ignore patterns not passed to \`watchfiles\`, leading to “file watch limit reached” · Kludex/uvicorn · Discussion #1978](https://github.com/Kludex/uvicorn/discussions/1978)
59. [Vermin - python boilerplate](https://python-boilerplate.github.io/uv-template/features/code_quality/vermin/)
60. [GitHub - gdraheim/strip\_python3: easy way to remove python3 typehints and to transform sources to older python compatibility using ast.unparse](https://github.com/gdraheim/strip_python3)
61. [piwheels - strip-python3](https://www.piwheels.org/project/strip-python3/)
62. [PEX with included Python interpreter - Pex Docs (v2.102.0)](https://docs.pex-tool.org/scie.html)
63. [GitHub - ronaldoussoren/modulegraph2: Modulegraph2 is a library for creating and introspecting the dependency graph between Python modules.](https://github.com/ronaldoussoren/modulegraph2)
64. [Exploring C# File-based Apps in .NET 10](https://milanjovanovic.tech/blog/exploring-csharp-file-based-apps-in-dotnet-10)
65. [Program management update — January 2026](https://blog.rust-lang.org/inside-rust/2026/02/11/program-management-update-2026-01/)
66. [Stabilize cargo script by epage · Pull Request #16569 · rust-lang/cargo](https://github.com/rust-lang/cargo/pull/16569)
67. [Releases · netromdk/vermin](https://github.com/netromdk/vermin/releases)
