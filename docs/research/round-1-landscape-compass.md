# Python Build & Packaging vs. Other Ecosystems: Where the Real Tooling Gaps Are (as of October 2026)

**Bottom line: Python has no true esbuild equivalent and no complete tsx equivalent. The parts that matter most are mostly solved, though: `uv run` + PEP 723 handles "run a file with inline deps", and pex handles "one artifact runnable by a bare interpreter, including native wheels for several platforms". What's left is a narrow but real gap in ergonomics and correctness, not a missing capability.** The best opportunity for a small team is a uv-native bundler in the esbuild mold. It would start from an entry point, check zip-safety and resource access statically, build multi-platform `.pyz` files from `uv.lock`, and guard the minimum Python version. Watch mode is real pain but has almost no moat. uv has an open, "help wanted" issue for it.

## TL;DR
- **esbuild equivalent: partially exists, not in esbuild's form.** pex (very active; 2.103.2 released Sep 18, 2026) and shiv/zipapps already bundle code plus dependencies into a zipapp, and pex can target several platforms. None of them starts from an entry point and follows imports the way esbuild does, none checks zip-safety or resource access, and none emits a version guard. uv has had an open "Provide uv zipapp" request (astral-sh/uv#7419) since September 2024. A maintainer replied that bundling is "something we're interested in doing someday", but nothing had shipped as of October 2026.
- **tsx equivalent: mostly solved by `uv run` + PEP 723.** The remaining gaps are watch mode (astral-sh/uv#9652, labelled "help wanted"; the MVP PR astral-sh/uv#12847, "Add uv run --watch for scripts", is still unmerged) and running a file that sits inside a package without `python -m`. Both are small. The first is easy for uv to absorb.
- **Biggest structural obstacles are native code and runtime file access, not syntax.** Extension modules can't load from a zip or from memory. The ABI matrix is being widened by free-threading: PEP 803 "abi3t" was accepted for Python 3.15, but build tools didn't support it yet as of the 3.15 RC docs. Wheel variants (PEP 817/825) are still drafts. Astral, which owns uv, Ruff and ty, agreed on March 19, 2026 to be acquired by OpenAI. That makes "will uv ship this?" both more likely and harder to predict.

## 1. Executive summary

**What exists and what doesn't (as of Oct 2026):**

| Want | Status | Use today |
|---|---|---|
| tsx (`tsx file.ts`) | **Solved, with watch mode the missing piece** | `uv run script.py`, PEP 723 inline deps, `#!/usr/bin/env -S uv run --script` |
| tsx watch | **Partial**: third-party only | `watchfiles 'python app.py' .`. uv#9652 is open, and #8654 reports SIGINT-propagation problems when wrapping `uv run`\[1\] |
| esbuild-style bundle (one artifact, bare interpreter) | **Partial**: exists, but not entry-point-driven | pex (multi-platform), shiv (dormant since Nov 2024), zipapps (active)\[2\] |
| Standalone executable | **Solved (several mature options)** | PyInstaller 6.22.3 (Sep 2026),\[3\] Nuitka 4.2 (Aug 2026),\[4\] cx_Freeze 8.7.1 (Sep 2026),\[5\] pex `--scie`, PyApp, PyCrucible |
| esbuild `--target` (downlevel syntax) | **Missing** (checking is possible, transforming isn't) | vermin detects the minimum version. No maintained downleveler was found\[6\]\[7\] |
| Tree-shaking/minification | **Missing, and mostly not worth building** | Module-level pruning happens implicitly in PyInstaller/Nuitka import analysis |
| Lockfile standard | **Solved on paper, partial in practice** | PEP 751 `pylock.toml`, accepted March 31, 2025 (the PEP header lists Status: Final, Replaces: 665). pip reads it experimentally (26.1, Apr 2026); uv exports it but keeps `uv.lock` |

**The ranked gaps** (detailed in §6):
1. **Bundle correctness and ergonomics:** an esbuild-like `.pyz` builder on top of uv's lock and resolver, with static zip-safety and resource checks, multi-platform wheel selection, and a runtime version/platform guard. Highest overall score, but the risk that uv ships it is real.
2. **Bundle/deploy readiness analysis** (an import graph plus checks for `__file__`, `importlib.metadata`, native-extension and minimum-version problems). It's a good wedge product and less likely to be absorbed.
3. **A tsx-grade dev runner:** run any file, infer package context, restart on change, forward signals. Easy to build and genuinely wanted, but it has almost no moat.

## 2. How Python works, for tool builders (Part 1)

### 2.1 Imports
- **Search and cache.** `import x` first checks `sys.modules`, a process-wide cache keyed by dotted name. If `x` isn't there, Python asks each *finder* on `sys.meta_path` in turn. The default finders are BuiltinImporter, FrozenImporter and PathFinder. PathFinder walks `sys.path` and uses `sys.path_hooks` to get a path-entry finder for each entry; that is how directories and zip files become importable.
- **Contrast with Node.** Resolution is global and name-based. There is no per-file `node_modules` lookup and no `exports` map, so two versions of one distribution can't coexist in one process. This is the main reason bundling Python needs vendoring with *relocation* (rewriting import names, the way pip's `vendoring` tool does) whenever you want to isolate dependencies. JVM users know the same trick as Shade.
- **Import hooks.** Adding a finder/loader to `sys.meta_path` is the supported way to import from anywhere: memory, a single-file archive, a database. Tsutsumu, PyOxidizer's `oxidized_importer` and pex's runtime all work this way.\[8\] A hook can serve pure-Python modules from memory. It can't do the same for C extensions (see §2.3).
- **Packages vs. namespace packages.** A directory with `__init__.py` is a regular package. Without one, it's a PEP 420 namespace package that can be spread across several `sys.path` entries. Namespace packages are a known trap for bundlers and static tracers, because "is this directory a package?" depends on everything else on `sys.path`.
- **Relative imports and `python -m`.** A relative import resolves against `__package__`. Running `python path/to/pkg/mod.py` sets `__name__ == "__main__"` and `__package__` to `None`/empty, and puts the *script's directory* on `sys.path[0]` instead of the project root. A `from . import x` then fails with "attempted relative import with no known parent package". `python -m pkg.mod` sets `__package__` correctly and puts the CWD on `sys.path`. That gap, a file-path workflow versus a module-name workflow, is the "run a file inside a package" problem a tsx clone has to solve: map a path to the nearest package root and run it with `-m`.

### 2.2 Bytecode and zip imports
- `.pyc` files are cached in `__pycache__/` and checked against the source's mtime/size or (PEP 552) a hash. They are version-specific (a magic number per minor release), so a bundle that ships only `.pyc` files is tied to one CPython minor version. Bundlers should ship source, or source plus pyc for exactly one target.
- `zipimport` imports `.py`/`.pyc` from zip files. It can't write bytecode back into the archive, so it recompiles from source on every start unless the zip already contains pyc files. More importantly, **it can't load extension modules**. This is why shiv and pex extract to a cache directory on first run: the issue author of uv#7419 calls it "the shiv hack that unzip the project on the first run."\[9\]

### 2.3 Native extensions
- **How they're built.** C/C++ through setuptools, meson-python or scikit-build-core; Rust through PyO3 + maturin; Python-to-C through Cython or mypyc. The output is a shared library (`.so`/`.pyd`) loaded with `dlopen`/`LoadLibrary`.
- **Why they can't come from a zip or memory.** The OS loader needs a real file path (Linux `memfd` tricks exist, but they're fragile and don't work on all platforms). Dependent shared libraries are resolved by the OS loader, not by Python. That forces "extract to disk", or a fully static, custom-built interpreter, which is what PyOxidizer tried at a large cost in compatibility (see §4.7).
- **The ABI matrix.** Wheel tags encode Python tag × ABI tag × platform tag. In practice that means OS × CPU arch × libc (manylinux glibc baseline vs. musllinux) × CPython minor version × GIL vs. free-threaded (`cp313t`) build.
- **abi3 / the Limited API** lets one wheel cover "CPython ≥ 3.x" for GIL builds. Free-threading broke this: the stable ABI wasn't available for free-threaded builds. PEP 803 ("abi3t") was accepted to add a free-threaded stable ABI in Python 3.15.\[10\]\[11\] The 3.15 "What's New" (at RC3) still says build tools like setuptools, meson-python, scikit-build-core and maturin "do **not** support abi3t" at the time of writing.\[12\] maturin has an exploration issue (PyO3/maturin#3064).\[13\]
- **Contrast with Node-API.** Node-API has been ABI-stable across Node major versions since its introduction. One prebuilt `.node` per OS/arch/libc covers every Node version, and npm's `optionalDependencies` + `os`/`cpu` fields (the esbuild/swc model) select the right binary. Python's abi3 is the nearest analogue, but adoption is partial and it doesn't cover free-threaded builds before 3.15.
- **Beyond platform tags.** GPU/CPU-feature variants (CUDA version, x86-64-v3, BLAS choice) aren't expressible today.\[14\] WheelNext's PEP 817 ("Wheel Variants: Beyond Platform Tags", created Dec 10, 2025) is a Draft.\[15\] A Sept 30, 2026 PR turns it into an Informational umbrella PEP, with PEP 825 and follow-ups carrying the standards.\[16\] Prototype implementations exist for uv and pip.\[17\]

### 2.4 How packages find their data and version at runtime
- `__file__`-relative paths (`os.path.dirname(__file__)`) are the most common pattern, and they break inside zips. `importlib.resources.files()` works through loaders (including zipimport) and is the zip-safe API. Adoption is incomplete.
- `importlib.metadata.version("pkg")` and entry points (`importlib.metadata.entry_points()`) read `*.dist-info` directories. A bundler that copies only `.py` files loses them, so `version()` raises `PackageNotFoundError` and plugin discovery silently returns nothing. Any bundler has to carry the `dist-info` directories along (pex and shiv do, because they install wheels).
- **What this means for bundling.** Zip-safety is a property of the *whole dependency closure*, not of your own code. The uv#7419 author notes that "Web frameworks like django, flasks or fastapi actually assume they have access to the file system directly."\[9\] This is the single most important reason "just zip it" fails, and it's statically detectable to a useful degree.

### 2.5 How dynamic Python is in practice
- `importlib.import_module(name_from_config)`, `__import__`, try/except optional imports (`try: import ujson as json except ImportError: import json`), entry-point plugins, Django's `INSTALLED_APPS` strings, and `pkgutil.iter_modules` scans are all common in mainstream libraries.
- **Static analysis** of literal `import` statements is easy (stdlib `ast`, or PyInstaller's modulegraph). The long tail needs hooks. PyInstaller maintains a separate `pyinstaller-hooks-contrib` repository (at v2026.6 as of June 2026) for exactly this reason,\[18\] and Nuitka keeps per-package configuration as well. That's the evidence that whole-program import tracing *works*, but only with a curated knowledge base. That knowledge base is the real moat in this space.
- **Tree-shaking.** Module bodies run arbitrary code at import time (registration decorators, monkey-patching), and attribute access is dynamic (`getattr`, `__getattr__` on modules via PEP 562). Function-level elimination is unsound in general. Module-level pruning (don't ship modules that are never reachable) is feasible with hooks and a conservative fallback. Python 3.15's explicit lazy imports (PEP 810, a `lazy import x` soft keyword that Real Python reports the Steering Council accepted on November 3, 2025) make import-time side effects easier to defer, but they don't make pruning sound.

### 2.6 How Python reaches users' machines
- **macOS:** Apple's `/usr/bin/python3` is a shim that triggers the Command Line Tools install. It's an old-ish CPython that is "Apple's", not the user's.
- **Windows:** `python.exe` on a fresh install is an App Execution Alias that opens the Microsoft Store. The `py` launcher is the reliable entry point when python.org Python is installed.
- **Linux:** distro Pythons are marked "externally managed" (PEP 668), so `pip install` into the system interpreter errors out unless you pass `--break-system-packages`. Users are pushed to venvs/pipx/uv.
- **Developer installs:** python.org installers, pyenv (builds from source), conda/mamba/pixi (binary distributions including non-Python libraries), and **python-build-standalone**. python-build-standalone's relocatable builds are now the de-facto source for uv, Rye, mise, Bazel rules_python, pipx, Hatch and others.\[19\] Astral took over stewardship on Dec 17, 2024 and publishes releases continuously (release 20261003 on Oct 3, 2026).\[20\]\[21\]
- **Implication.** A "needs only the runtime" artifact can't assume *which* runtime. That's why a bundler needs a minimum-version and platform guard, and why "fetch a Python with uv if missing" (PyApp, PyCrucible, pex lazy scies) has become the dominant pattern for executables.

## 3. Community and governance (Part 2)

### 3.1 What Python developers value and complain about
- **PSF/JetBrains Python Developers Survey, 8th edition**, published Aug 2025 with data collected in late 2024, 30,000+ respondents.\[22\] 86% use Python as their main language, 51% do data exploration/processing,\[23\] and exactly 50% have under two years of professional coding experience (31% under one year). uv went "from 0% to 11% the year it was introduced". Rust's share for binary extensions grew from 27% to 33%. Only 15% were on 3.13, then the latest release (35% were on 3.12 and 21% on 3.11); JetBrains concludes 83% use a version a year old or older. LWN commenters question how representative the sample is (no error bars, PyCharm over-represented).\[24\] Treat the numbers as directional.
- **The recurring complaints** are packaging fragmentation (pip/Poetry/PDM/Hatch/conda), "it works on my machine" environment drift, slow installs, and distribution to end users. The 2023 packaging-strategy discussions on discuss.python.org circled back repeatedly to "one tool, like Cargo". uv's adoption is the market's answer.
- **Measuring Stack Overflow volume** for "attempted relative import" and "ModuleNotFoundError" would be useful evidence, but I didn't get reliable counts in this research. Treat that pain as anecdotal-but-pervasive rather than quantified.

### 3.2 How decisions get made
- The **Steering Council** (5 people elected by core devs) rules on PEPs, usually through delegates. **Packaging PEPs** go to a PEP-Delegate drawn from the PyPA community. **PyPA** is a loose umbrella of projects (pip, setuptools, packaging, build, twine, cibuildwheel…), not a company with a roadmap. The **PSF** funds infrastructure (PyPI) and staff such as the Deputy Developer-in-Residence who drove PEP 803.\[25\]
- **Pattern for adoption:** a tool ships a non-standard feature, users adopt it, and then a PEP standardizes it. Examples: Poetry's/PDM's lockfiles leading to PEP 751, pipx/pip-run leading to PEP 723, and uv implementing standards early. Standards *without* a dominant implementation stall. PEP 751 took about four years: Brett Cannon's snarky.ca account says research began in January 2021, PEP 665 was rejected in January 2022 (with PEP 650, the installer API, rejected alongside it), and PEP 751 was accepted on March 31, 2025. PEP 711 (PyBI, binary interpreter distributions) never progressed beyond draft, and python-build-standalone filled the gap de facto.\[20\] PEP 817's variant design keeps getting reworked over lockfile interaction; one reviewer wrote "I do *not* want to find myself in the position of having approved a new wheel format that can't be made to work with lockfiles."\[26\]
- **Implication for you:** you don't need a PEP to ship a bundler. The `.pyz` format (PEP 441) and wheels are enough. A PEP becomes relevant only if you want installers to understand a new artifact.

### 3.3 Sentiment on uv/Astral and Rust-ification
- uv is the fastest-adopted Python tool in recent memory.\[27\] It also absorbed Rye ("no longer developed as of February 2025") and python-build-standalone.\[20\]\[28\]
- **Corporate status:** on **March 19, 2026, OpenAI announced an agreement to acquire Astral**. The team is to join the Codex org, and both sides committed to keeping uv, Ruff and ty open source. At announcement, closing was subject to regulatory approval.\[29\] Sources disagree on whether it has closed: one August 2026 analysis said closing "cannot be independently verified",\[30\] while pydevtools now describes uv as "Built by Astral, now part of OpenAI".\[31\] **Treat this as unconfirmed.** Astral had no revenue model and reportedly was near the end of its runway (pydevtools; secondary).\[29\]
- **Reaction:** the Hacker News thread was large; secondary sources report 707 points/445 comments at one crawl and 1,223/757 at another.\[32\]\[33\] The worries are roadmap capture by an AI vendor ("uv now answers to a model company"),\[34\] competitive misuse against other AI coding agents (Simon Willison: "One bad version of this deal would be if OpenAI start using their ownership of uv as leverage in their competition with Anthropic"),\[35\] and bus factor, since forking a large Rust codebase is hard.\[36\] JetBrains' PyCharm blog called the risks "real, but manageable".\[37\] Releases haven't slowed: the astral-sh/uv releases page lists 0.12.20 (Sep 28), 0.12.21 (Sep 29) and 0.12.22 (Oct 2, 2026).
- **The Rust-ification trend** (Ruff → flake8/Black/isort, uv → pip/pip-tools/pyenv/pipx, ty/pyrefly → mypy/pyright, maturin/PyO3 for extensions) is broadly welcomed for speed. The pushback is about contributor accessibility (Python users can't easily patch Rust tools) and concentration, not technical quality.

### 3.4 Groups with different needs
| Group | Key need | Bundling relevance |
|---|---|---|
| Web/backend | Reproducible deploys, containers, fast CI | Medium. Docker usually wins, but `.pyz` deploys (pex at Twitter/Pants users) are a known pattern |
| Data science/ML | Native libs, CUDA, BLAS → conda/pixi | Low for zipapps (huge native wheels). High for variants (PEP 817) |
| Scripting/DevOps | Single file, no setup, runs on servers with "some Python" | **Highest** for zipapp/PEP 723 tools |
| Library authors | Build backends, wheels for every platform (cibuildwheel), abi3 | Indirect: the abi3/abi3t transition |
| App distributors (CLI/GUI) | Standalone executables, signing, installers | High. Served by PyInstaller/Nuitka/Briefcase/PyApp |
| Education | Zero-setup | `uv run`, though the Windows Store stub and macOS shim still confuse beginners |

## 4. Toolchain map (Part 3)

Status dates are as of Oct 2026 unless noted. "Active" means releases in the last ~6 months.

### 4.1 Getting an interpreter
| Tool | Status | Notes |
|---|---|---|
| `uv python` | Active (uv 0.12.x, Sep 2026) | Downloads python-build-standalone builds, including free-threaded and PyPy. Pin with `.python-version` |
| python-build-standalone | Very active (20261003, Oct 3 2026) | Astral-maintained since Dec 2024. The ecosystem's de-facto binary CPython\[19\]\[20\] |
| pyenv | Maintained (not verified in this research) | Compiles from source, so it's slow and needs build deps |
| conda/mamba/pixi | Active | Interpreter plus non-Python native libs |
| Rye | **Abandoned**: "no longer developed as of February 2025", final 0.44.0 | Absorbed into uv. "No further updates are planned, including security updates"\[28\]\[38\]\[39\] |
| PEP 711 PyBI | Stalled draft | Superseded in practice by python-build-standalone |

### 4.2 Environments, dependencies, lockfiles
| Tool | Status | Notes |
|---|---|---|
| uv | Very active | Universal (cross-platform) `uv.lock`, workspaces, `uv export --format pylock.toml`\[40\] |
| pip | Active | `pip lock` (experimental, 25.1, Apr 2025). `pip install -r pylock.toml` (experimental, 26.1, Apr 26 2026). Dependency cooldowns in 26.1\[41\] |
| Poetry | Active (latest release not verified here) | Own `poetry.lock`. No pylock.toml support shipped as of the pydevtools check\[40\] |
| PDM | Active | `pdm export -f pylock` (2.24.0+). Plans to replace `pdm.lock` with pylock.toml\[42\] |
| Hatch | Active (not verified here) | Env manager + hatchling backend. No native lockfile |
| pip-tools | Maintained | Discussing pylock support\[43\] |
| Pipenv | **Declined** | Lost mindshare after slow resolution and a long release gap (~2018–2020). Superseded by Poetry, then uv. Not abandoned (status not re-verified here) |
| pixi/conda | Active | conda-forge world. Lockfiles across conda + PyPI |
| PEP 751 `pylock.toml` | Accepted Mar 31, 2025 (Status: Final; Replaces: 665) | Producers: uv (stable export), pip (experimental), PDM (experimental). Pip's lock is valid only for the platform that generated it\[42\] |

### 4.3 Build backends and native builds
| Tool | Role | Notes |
|---|---|---|
| setuptools | Legacy default | Supports PEP 517/518/621/660 |
| hatchling, flit-core, pdm-backend | Pure-Python backends | Fine for pure-Python wheels |
| uv_build | Astral's pure-Python backend | Fast, strict layout |
| maturin | Rust/PyO3 extensions | Exploring abi3t (maturin#3064) |
| scikit-build-core | CMake | Experimental PEP 817 variant PR (#1284)\[44\] |
| meson-python | Meson (NumPy/SciPy) | — |
| cibuildwheel | CI matrix wheel builder | The standard way to produce manylinux/musllinux/macOS/Windows wheels |
Standards: PEP 517 (backend interface), 518 (`[build-system]`), 621 (`[project]` metadata), 660 (editable installs), the wheel format, manylinux (PEP 600) and musllinux (PEP 656) tags.

### 4.4 Publishing and registries
PyPI with **Trusted Publishing** (OIDC from GitHub/GitLab etc.) and **PEP 740 attestations** is the modern baseline. pyfuze's PyPI page, for example, shows "Uploaded using Trusted Publishing? Yes".\[45\] Astral's 2025 advisory on ZIP parser differentials (CVE-2025-54368) led PyPI to add upload checks.\[46\] pip 26.1 added dependency cooldowns against fresh-malware attacks.\[47\] Private indexes: devpi, Artifactory, AWS CodeArtifact, GitLab. Astral's commercial registry **pyx** was notably absent from the OpenAI announcement.\[35\] Its future is unclear.

### 4.5 Running scripts and dev loops
| Tool | Status | Gap |
|---|---|---|
| `python -m` | stdlib | Requires module names, not paths |
| `uv run` + PEP 723 | Solved | No `--watch` (uv#9652 open, "help wanted"; MVP PR #12847, "Add uv run --watch for scripts", still unmerged, and it kills the child with SIGKILL). Doesn't read PEP 723 from `.pyz` (uv#18662)\[48\] |
| `pipx run` | Active | Also supports PEP 723 |
| watchfiles (Rust-backed) / hupper | Active (versions not verified here) | Generic restart-on-change. `uvx watchfiles 'uv run x.py'` mostly works, but uv#8654 documents SIGINT not propagating through `uv run`\[1\] |
| uvicorn `--reload`, Django runserver, Flask debug | Framework-specific reload | Covers web dev, the biggest watch-mode audience |

### 4.6 Bundling into one file that needs only the runtime
| Tool | Status (Oct 2026) | What it does / doesn't do |
|---|---|---|
| stdlib `zipapp` | stdlib | Zips a directory with `__main__.py`. **No dependency handling**\[9\] |
| **pex** | **Very active** (2.103.2, Sep 18 2026; dozens of 2026 releases) | Resolves deps, **multi-platform** PEX (`--platform`/`--complete-platform`), lockfiles, venv mode, extracts to `~/.pex`. `--scie` embeds or lazily fetches an interpreter.\[49\]\[50\] Not entry-point-traced; it ships the whole resolved closure. Ergonomics are Pants-flavored |
| shiv (LinkedIn) | **Dormant**: 1.0.8, Nov 1 2024 | pip-installs into a zip, extracts on first run. Host-platform only by default\[2\]\[9\] |
| zipapps (ClericPy) | Active (2026.4.17) | Bundles deps or whole venvs, can lazily install on first run.\[9\]\[51\] Little known outside China/its niche |
| stickytape / pinliner | **Unmaintained** (not re-verified here; last activity years ago) | Concatenate pure-Python modules into one `.py`. Break on native code, resources and metadata\[52\] |
| Tsutsumu | Little known | Bundles modules + resources into one script with a custom importer\[8\] |
| pip's `vendoring` / `get-pip.py` | Niche, active within pip | `get-pip.py` embeds a base85 zip of pip. `vendoring` copies deps and rewrites imports (relocation). Proof that relocation works in Python, but tuned to pip's own needs |
| tinyBundle | Not found / no evidence | Couldn't verify this project exists in a maintained form |

### 4.7 Freezing and standalone executables
| Tool | Status | Model |
|---|---|---|
| PyInstaller | Very active: 6.22.3 (Sep 12 2026), 8 releases in 2026 | Bundles interpreter + modulegraph-traced modules. Onefile extracts to temp. Hooks repo (v2026.6)\[3\] |
| Nuitka | Very active: 4.2 (Aug 2026) | Compiles Python to C. Follows imports. Standalone/onefile\[53\] |
| cx_Freeze | Active: 8.7.1 (Sep 23 2026) | Classic freezer, Py 3.10–3.14\[5\]\[54\] |
| Briefcase (BeeWare) | Active (not re-verified here) | Native installers/app bundles incl. iOS/Android |
| PyApp (ofek) | Active (not re-verified here) | Rust launcher that installs your wheel into a managed Python on first run |
| pex `--scie` / science (a-scie) | Active | Native executable = scie-jump + PBS interpreter + PEX. Eager or lazy\[50\] |
| PyCrucible | Active | Rust launcher embedding uv + project. Deps fetched on first run, so **needs internet**\[55\]\[56\] |
| pyfuze | Last release 2.7.1, Jul 7 2025 | uv + Cosmopolitan "portable" mode for pure-Python only\[45\]\[57\] |
| **PyOxidizer** | **Abandoned**: no commits since Jan 2023. Mar 2024 owner post: future "uncertain, possibly dead"\[58\]\[59\] | In-memory import of everything incl. a static interpreter.\[60\] Szorc: single-file mode broke "compatibility with the larger pre-built Python package ecosystem… This ballooned into a hot mess." |

**Why the failures failed.** PyOxidizer fought Python's assumptions (`__file__`, extensions on disk). The cost in compatibility exceeded the benefit, and it had a single maintainer whose priorities changed.\[61\]\[62\] stickytape/pinliner were weekend projects that hit the native-code/metadata wall. Pipenv lost on speed and trust. Rye succeeded as a prototype and was deliberately absorbed into uv.\[63\]\[64\] The lesson: **cooperate with Python's file-based assumptions (extract to a cache) rather than fight them**, and don't be a single-maintainer project with an expansive scope.

### 4.8 Lint/format/type/test (only as it relates to the trend)
Ruff (Astral, Rust) replaced flake8/isort/pyupgrade and largely Black; Ruff 0.16.0 shipped July 2026.\[30\] ty (Astral, Rust; 0.0.x, still pre-1.0) and Meta's pyrefly challenge mypy/pyright. pytest remains dominant. The pattern is clear: **a fast Rust core with a Python-facing CLI wins adoption quickly when it's a drop-in replacement for an existing workflow.** That's a template for a bundler.

### 4.9 Monorepos and build systems
- **uv workspaces:** Cargo-style, with a single lock. Good for apps, but per-member publishing and per-member Python versions are limited.
- **Pants:** Python-first. Uses pex as its artifact format; dependency inference from imports. Active (release not re-verified here).
- **Bazel rules_python:** hermetic interpreters via python-build-standalone. Steep learning curve.

## 5. Comparison matrix across ecosystems (Part 4)

Legend for the Python row: ✅ solved / 🟡 partial / ❌ missing.

| Ecosystem | Runtime install & versions | Deps & lockfiles | Single file w/ inline deps | Dev runner & watch | One-file bundle (runtime only) | Tree-shake / minify / `--target` | Native code | Standalone exe | Workspaces | Registry & supply chain | Tool speed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Python** | ✅ uv python + PBS (but OS stubs confuse users) | ✅ uv.lock; 🟡 PEP 751 standard still settling | ✅ PEP 723 + `uv run` | 🟡 no built-in watch; watchfiles; framework reloaders | 🟡 pex/shiv/zipapps; no entry-point tracing or zip-safety checks | ❌ none; only version *detection* (vermin) | 🟡 wheels + manylinux; abi3 partial; abi3t in 3.15; variants draft | ✅ PyInstaller/Nuitka/pex scie/PyApp | 🟡 uv workspaces, Pants | ✅ Trusted Publishing, attestations, cooldowns (pip 26.1) | ✅ now fast (uv/Ruff) |
| JS/TS (Node/Bun/Deno) | nvm/fnm/volta; Bun/Deno single binary | package-lock/pnpm-lock/bun.lock | Deno `npm:` specifiers; Bun auto-install | `node --watch`, tsx watch, Bun `--watch`/`--hot`; Node type stripping stable (v24.12)\[65\] | esbuild/Rollup bundles → `node bundle.js`\[66\]\[67\] | ✅ tree-shaking, minify, `--target=es2017`\[67\] | Node-API ABI-stable; prebuilt per-platform optional deps | Node SEA, `bun build --compile`, `deno compile` | npm/pnpm/yarn workspaces | npm provenance, but chronic malware/typosquat | Fast (esbuild Go, Bun Zig, Rust tools) |
| Rust | rustup | Cargo.lock | cargo-script: stabilization FCP completed early 2026; frontmatter stabilized\[68\]\[69\] | `cargo watch`/bacon (third-party) | N/A (compiled) | Compiler does DCE | Native by nature | ✅ static binary | Cargo workspaces | crates.io trusted publishing | Compile is slow; tooling fast |
| Go | Toolchain directive auto-downloads | go.mod/go.sum + checksum DB | `go run file.go` (no inline deps outside a module) | third-party (air) | N/A | Linker DCE | cgo is the pain point | ✅ static binary, trivial cross-compile | go.work | sum.golang.org transparency log | Very fast |
| Java/JVM | SDKMAN, toolchains | Maven/Gradle; lockfiles optional | JEP 330 (single file, Java 11), JEP 458 (multi-file, Java 22); deps via JBang | Gradle continuous, devtools | ✅ fat/uber JAR (Shade with relocation) | ProGuard/R8 shrink | Native libs inside JARs, extracted at runtime (same as pex!) | jlink/jpackage, GraalVM native-image | Gradle/Maven multi-module | Maven Central signing | JVM startup slow |
| .NET | dotnet-install, global.json | NuGet, packages.lock.json | ✅ `dotnet run app.cs` + `#:package` (.NET 10, Nov 2025; multi-file planned for .NET 11)\[70\]\[71\]\[72\]\[73\] | `dotnet watch` built-in | Single-file publish (framework-dependent) | Trimming (IL linker) | RID-specific NuGet assets | Single-file self-contained, Native AOT | Solutions | NuGet signing | Good |
| Ruby | rbenv/asdf | Gemfile.lock | `bundler/inline` | guard/rerun | Limited (traveling ruby) | — | Native gems per platform | Weak | Rarely used | RubyGems trusted publishing | Moderate |
| PHP | Distro/phpbrew | composer.lock | — | — | ✅ phar (runtime only) | — | Extensions installed system-wide | Weak (static-php-cli) | — | Packagist | Moderate |
| Perl | perlbrew/plenv | cpanfile.snapshot (Carton) | — | — | App::FatPacker (pure-Perl only, inlines modules into one script) | — | XS can't be fatpacked | PAR::Packer | — | CPAN | — |

**What the matrix says.** On the "single-file run" and "speed" columns, Python has caught up with or passed Node and Ruby since 2024, and it's on par with .NET 10. Its weak columns are **bundling**, `--target`, and native-code ergonomics. The closest analogue to where Python should land is the **JVM uber-JAR**: one artifact, native libraries extracted at runtime, relocation for conflicts. Java solved this with Shade plus a 25-year culture of `getResourceAsStream`. Python has the format (pex/`.pyz`) but not the culture (`__file__` everywhere), and that's the gap a tool can paper over.

## 6. Ranked gap analysis, top 3 and MVPs (Part 5)

Scores are out of 5, where 5 is best for *you* as a builder. Higher defensibility means a lower chance of being absorbed.

### Gap A: esbuild-grade bundling (entry point → verified `.pyz`)
- **What's missing.** *Before:* `uv export --no-dev > req.txt && pex -r req.txt -c app -o app.pex --platform …`, then hand-debugging `FileNotFoundError` from `__file__` reads, missing `dist-info`, or a Windows-built zip failing on Linux (the platform-specific zipapp failure described in uv#7419).\[9\] *After:* `pybundle src/app/__main__.py --target py3.10 --platform linux-x86_64,macos-arm64 -o app.pyz`. It reads `uv.lock`, traces imports, includes dist-info and package data, picks per-platform wheels, writes a version/platform guard into `__main__`, and fails the build with an explanation if a dependency is not zip-safe.
- **Evidence it hurts:** uv#7419 (2024), uv#10019 ("zipapp, shiv, pex. none of them are very good"), uv#13263 (needs runtime-only wheelhouse for shiv), uv#18662 (PEP 723 for `.pyz`), uv#5802 (labelled "wish – not on the immediate roadmap").\[9\]\[48\]\[74\]\[75\]\[76\] Volume is moderate rather than massive.
- **Who it affects:** scripting/DevOps teams, internal CLI authors, and people deploying to locked-down servers. Probably low millions of developers touch this at some point; I couldn't find a direct metric, so this is an estimate.
- **Existing attempts:** pex is capable but is perceived as complex and Pants-centric. shiv is dormant. zipapps is little known. None does import tracing or zip-safety diagnosis.
- **Obstacles:** native extensions (must extract; multi-platform requires wheels to exist for each target), `__file__` culture, namespace packages, metadata, and sdist-only dependencies (which can't be built for foreign platforms).
- **Risk someone ships it:** **medium-high.** Astral said bundling interests them "someday", and uv has all the primitives.\[9\] The OpenAI acquisition could accelerate or deprioritize it. pex is active and could add ergonomics.
- **Feasibility for 1–3 people:** high if you build *on* uv (shell out to `uv export`/`uv pip install --target --python-platform`) rather than reimplementing resolution.
- **Scores:** pain 3, reach 3, feasibility 4, defensibility 2. The defensible part is the zip-safety knowledge base, the equivalent of PyInstaller hooks.

### Gap B: bundle/deploy-readiness analyzer
- **What's missing:** a `pyreadiness check` that, for an entry point and lockfile, reports the import graph, dynamic-import sites, `__file__`/`open(Path(__file__)…)` reads, `importlib.metadata` uses, native extensions per platform (missing wheels, sdist-only packages), abi3/abi3t coverage, and minimum Python version (embedding vermin-style rules). *Before:* you find out at runtime on the target machine. *After:* CI fails with "requests→certifi reads `__file__` (zip-unsafe; will work under extraction)".
- **Evidence:** indirect, from the size of PyInstaller's hooks repo and the long tail of "works in venv, fails frozen" issues across PyInstaller/Nuitka trackers. I didn't quantify this.
- **Who:** anyone bundling or freezing, plus library authors who want to be "bundle-friendly".
- **Existing attempts:** vermin (minimum version only, rules through 3.14), PyInstaller's `--debug=imports` (runtime only), and pydeps-style graphs.\[6\]\[77\] Nothing combines them.
- **Obstacles:** dynamic imports put a ceiling on accuracy. Results need to be framed as warnings with confidence levels.
- **Risk someone ships it:** low-medium. uv is unlikely to ship an analyzer; ty/Ruff could add individual lints.
- **Scores:** pain 3, reach 3, feasibility 5, defensibility 3.

### Gap C: tsx-grade dev runner (watch + run-any-file)
- **What's missing.** *Before:* `uvx watchfiles 'uv run python -m pkg.sub.mod' src` with SIGINT problems (uv#8654), or remembering `-m` and the module path.\[1\] *After:* `pyx watch src/pkg/sub/mod.py`: infers package root and `-m`, honours PEP 723, restarts with proper signal forwarding and process-group killing, clears the screen, debounces.
- **Evidence:** uv#9652 ("Essentially Bun watch mode but with uv"), labelled help-wanted. The MVP PR, #12847 ("Add uv run --watch for scripts", +255/−5), is still unmerged; its description says the child "is always killed via SIGKILL", and later comments on the issue ask about progress. Third-party projects ask the same (e.g. ethereum/execution-spec-tests#2156).\[78\]
- **Who:** very broad (every Python developer has hit the relative-import error), but per-user pain is low, because frameworks already have reloaders.
- **Existing attempts:** watchfiles, hupper, entr, framework reloaders.
- **Risk someone ships it:** **high**, because uv has a help-wanted issue and a draft implementation.
- **Scores:** pain 2, reach 4, feasibility 5, defensibility 1.

### Gap D: syntax downleveling / `--target`
- **What's missing:** compiling 3.12 syntax (PEP 695 generics, `match`, nested f-strings, `except*`) down to run on 3.9. Python developers accept "require a newer Python" more readily than JS developers accept "require a newer browser", because the *author* controls the runtime via uv/PBS.
- **Existing:** vermin for *detection*. Older transformers such as strip-hints and future-fstrings date from before 2023, and I didn't verify their current status, so treat them as likely unmaintained.
- **Obstacles:** `match` and `except*` have no clean lowering; stdlib API differences matter more than syntax.
- **Scores:** pain 2, reach 2, feasibility 3, defensibility 4. Better shipped as a *check* inside Gap A/B (`--target` = fail if the closure needs a newer Python) than as a transpiler.

### Gap E: tree-shaking/minification
Module-level pruning is feasible but saves little: dependency size is dominated by native wheels and data. Function-level shaking is unsound. **Scores:** pain 1, reach 2, feasibility 2, defensibility 3. Not recommended.

### Gap F: native-code variants and the ABI matrix
Real and severe for ML (CUDA/BLAS), but it's being handled by WheelNext/PEP 817/825 and needs installer, index and PyPI cooperation.\[14\] **Scores:** pain 4, reach 3, feasibility 1, defensibility 1. Not a small-team play. Track it.

### Gap G: cross-built standalone executables with signing
PyInstaller and Nuitka can't cross-compile. pex `--scie` and PyApp-style launchers *can* target foreign platforms because they ship wheels plus a downloaded PBS interpreter.\[79\] Code-signing/notarization remains manual. **Scores:** pain 3, reach 2, feasibility 3, defensibility 2 (pex scie already covers much of this).

### Ranking
1. **Gap A + B combined** (bundler with a built-in analyzer). Merging them turns low defensibility (A) into moderate defensibility (B's knowledge base).
2. **Gap B alone** as a CI linter. It's the cheapest path to users and survives even if uv ships `uv bundle`, because it would analyze uv's output too.
3. **Gap C** only as a weekend-sized wedge or a contribution upstream to uv#9652. Don't build a company on it.

### Top 3 MVP outlines
**1. `pybundle`: esbuild for Python, built on uv**
- Input: entry file or `module:function`, plus `uv.lock`/PEP 723 block. Uses `uv export` + `uv pip install --target --python-platform` for each requested platform.
- Traces imports with `ast` from the entry point to build a reachability report. Ships *all* installed files of reachable distributions (sound), and optionally prunes unreachable top-level packages behind a flag.
- Always includes `dist-info`. Rewrites nothing. Writes a `__main__.py` bootstrap that checks `sys.version_info` and platform tags against the build manifest, prints a clear error on mismatch, and extracts native/zip-unsafe distributions to a content-addressed cache (the pex/shiv approach). The rest stays zipped.
- Output: one `.pyz` per platform, or one fat multi-platform `.pyz` with a per-platform wheel directory chosen at boot. Optional `--scie` via the science project for an interpreter-included variant.
- Success metric: `pybundle` a FastAPI app, a Click CLI with `rich`, and a `numpy` script for linux-x86_64 and macOS-arm64 from a single machine.

**2. `pyready`: bundle-readiness analyzer**
- `pyready check app/__main__.py --lock uv.lock --target 3.10 --platform linux,macos,windows`.
- Rules: `__file__` file reads, `pkg_resources`, `importlib.metadata` without dist-info, `import_module` with non-literal args, namespace packages, native exts lacking wheels for a target, sdist-only deps, abi3/abi3t coverage, min-version via vermin-like rules.
- Ships a community "known issues" database (YAML, like PyInstaller hooks) keyed by package and version. That database is the moat.
- Outputs SARIF for GitHub code scanning. Ruff-style speed is optional at first, since Python is fine for an MVP.

**3. `pyx`/`runpy+`: tsx-style runner**
- `pyx path/to/file.py`: finds the nearest package root by walking up `__init__.py`/`pyproject.toml`, runs with `-m`, honours PEP 723 by delegating to `uv run --script`.
- `pyx watch`: watchfiles under the hood. Kills the process group, forwards SIGINT/SIGTERM, debounces, and has an ignore list for `.venv`/`__pycache__`.
- Ideally upstreamed into uv (#9652), which earns credibility for products 1–2.

## 7. Verdicts on the hypotheses

1. **"Python has no esbuild equivalent." Mostly true, with an important correction.** No tool starts from an entry point, follows imports, and emits a verified one-file artifact. But "bundle code + deps into one artifact runnable by the bare interpreter" **is solved by pex**, which is very active (2.103.2, Sep 2026), multi-platform and lock-aware.\[49\] shiv and zipapps do the same with less polish. The gap is tracing, diagnostics, ergonomics and uv integration, not capability.
2. **"`uv run` + PEP 723 covers most of what tsx does; remaining gaps are watch mode and running files inside packages." Confirmed.** Add two small items: signal propagation when wrapping `uv run` (uv#8654), and no PEP 723 support for `.pyz` (uv#18662).\[1\]\[48\] Python doesn't need tsx's main job, transpiling types, since annotations are native syntax. Node only reached parity on that with type stripping becoming stable in v24.12.0.\[65\]
3. **"Native extensions are the biggest technical obstacle; the multi-platform wheel approach (as in pex) is most promising." Half right.** Native extensions are the hardest *technical* constraint (no loading from zip or memory, ABI matrix, free-threading split until abi3t tooling lands). In practice, though, **`__file__`/filesystem assumptions and missing metadata cause more bundling breakage across typical apps**, and they're more tractable. Multi-platform wheels plus extract-to-cache is the right answer. JVM fat JARs with embedded native libraries do the same thing, and PyOxidizer's in-memory approach failed. It only works when wheels exist for every target platform (sdist-only dependencies break it).
4. **"Dynamic imports make function-level tree-shaking impractical, but module-level pruning is feasible." Confirmed, with low payoff.** PyInstaller and Nuitka already do module-level reachability with curated hooks. The savings are small next to native wheel sizes. Prune at the *distribution* level (drop unreachable packages) and treat finer pruning as optional.
5. **"Python lacks syntax downleveling and minimum-version checking for bundled code." Half right.** Downleveling is effectively missing; no maintained transpiler was found. **Minimum-version *checking* exists** (vermin, with rules covering 2.0–3.14), but it isn't integrated into any bundler, and it ignores dependency metadata (`Requires-Python`).\[6\]\[77\] Integrating version checks across the whole closure is the useful part. A transpiler isn't worth building.

## 8. Sources

Every factual claim above names its primary source inline: PEPs, GitHub issues/PRs, release pages, official docs, and maintainer blog posts. Links are attached in a separate citation pass and aren't duplicated as a list here.

### Caveats
- The Astral/OpenAI deal was announced on Mar 19, 2026. Whether it has closed is unconfirmed in the sources reviewed.\[30\]
- Several Part 3 rows (Poetry, Hatch, pyenv, Briefcase, PyApp, maturin, cibuildwheel, scikit-build-core, meson-python, watchfiles, hupper, Pants, stickytape, pinliner) were not re-verified for latest release date in this research. They're marked as such and should be checked before any decision.
- I couldn't confirm whether Rust's cargo-script reached the stable channel by Oct 2026. The stabilization FCP completed, but other documentation still listed it as unstable.\[69\]\[80\]
- Survey data (PSF/JetBrains 2025) is self-selected and was collected in late 2024.\[22\] It predates most of uv's growth.
- uv issue open/closed states were inferred from labels and changelogs, not from direct status reads.

## Sources

1. [uv run and SIGINT propagation · Issue #8654 · astral-sh/uv](https://github.com/astral-sh/uv/issues/8654)
2. [shiv · PyPI](https://pypi.org/project/shiv/)
3. [pyinstaller · PyPI](https://pypi.org/project/pyinstaller/)
4. [Posted in 2026 — Nuitka the Python Compiler](https://nuitka.net/blog/2026.html)
5. [cx-Freeze · PyPI](https://pypi.org/project/cx-Freeze/)
6. [GitHub - netromdk/vermin: Concurrently detect the minimum Python versions needed to run code · GitHub](https://github.com/netromdk/vermin)
7. [Best Tool to Determine the Minimum Python Version Required for Your Python Script: A Guide — ancisoft.com](https://www.ancisoft.com/blog/tool-to-determine-what-lowest-version-of-python-required/)
8. [pypi.org](https://pypi.org/project/tsutsumu)
9. [Provide uv zipapp](https://github.com/astral-sh/uv/issues/7419)
10. [PEP 803](https://peps.python.org/pep-0803/)
11. [Implement PEP 803 -- abi3t · Issue #146636 · python/cpython](https://github.com/python/cpython/issues/146636)
12. [What's new in Python 3.15 — Python 3.15.0rc3 documentation](https://docs.python.org/3.15/whatsnew/3.15.html)
13. [Explore support for abi3.abi3t wheels (PEP 803) · Issue #3064 · PyO3/maturin](https://github.com/PyO3/maturin/issues/3064)
14. [peps/peps/pep-0817.rst at main · python/peps](https://github.com/python/peps/blob/main/peps/pep-0817.rst)
15. [What Are Wheel Variants?](https://pydevtools.com/handbook/explanation/what-are-wheel-variants.md)
16. [PEP 817: Wheel Variants: switch to Informational, major update by rgommers · Pull Request #5149 · python/peps](https://github.com/python/peps/pull/5149)
17. [PEP 817 - Wheel Variants: Beyond Platform Tags - Page 2 - Packaging - Discussions on Python.org](https://discuss.python.org/t/pep-817-wheel-variants-beyond-platform-tags/105860?page=2)
18. [pyinstaller-hooks-contrib/CHANGELOG.rst at master · pyinstaller/pyinstaller-hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib/blob/master/CHANGELOG.rst)
19. [GitHub - astral-sh/python-build-standalone: Produce redistributable builds of Python · GitHub](https://github.com/astral-sh/python-build-standalone)
20. [A new home for python-build-standalone - Astral](https://astral.sh/blog/python-build-standalone)
21. [Release 20261003 · astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone/releases/tag/20261003)
22. [Python survey 2025: key trends, tools, and takeaways](https://www.frameworktraining.co.uk/news-insights/what-eighth-python-developer-survey-means)
23. [The State of Python 2025: Trends and Survey Insights - The JetBrains Blog](https://blog.jetbrains.com/pycharm/2025/08/the-state-of-python-2025/)
24. [The State of Python 2025 \[LWN.net\]](https://lwn.net/Articles/1034313/)
25. [What Every Python Developer Should Know About the CPython ABI](https://labs.quansight.org/blog/python-abi-abi3t)
26. [PEP 817 - Wheel Variants: Beyond Platform Tags - Page 11 - Packaging - Discussions on Python.org](https://discuss.python.org/t/pep-817-wheel-variants-beyond-platform-tags/105860?page=11)
27. [46 Python Statistics for 2026: Usage, Jobs & AI Trends - Pynions](https://pynions.com/python-statistics)
28. [Rye](https://rye.astral.sh/)
29. [OpenAI to Acquire Astral](https://pydevtools.com/blog/openai-acquires-astral/)
30. [OpenAI Just Acquired Astral? What It Means for uv, Ruff, and Python](https://www.itechguides.com/openai-just-acquired-astral-what-the-deal-means-for-uv-ruff-and-every-python-developer/)
31. [uv: A Complete Guide to Python's Fastest Package Manager](https://pydevtools.com/handbook/explanation/uv-complete-guide)
32. [OpenAI moves to acquire Astral, the company behind uv and Ruff - Insights](https://insights.marvin-42.com/articles/openai-moves-to-acquire-astral-the-company-behind-uv-and-ruff)
33. [OpenAI Just Acquired Astral: What It Means for uv, Ruff, and Every Python Developer](https://www.computeleap.com/blog/openai-astral-acquisition-python-developers-2026/)
34. [OpenAI buying Astral means uv now answers to a model company - DEV Community](https://dev.to/adioof/openai-buying-astral-means-uv-now-answers-to-a-model-company-20lc)
35. [Thoughts on OpenAI acquiring Astral and uv/ruff](https://simonw.substack.com/p/thoughts-on-openai-acquiring-astral)
36. [OpenAI Acquires Astral: What It Means for uv, Ruff, and Python's Future](https://toolhalla.ai/blog/openai-acquires-astral-uv-ruff-2026)
37. [OpenAI Acquires Astral: What It Means for PyCharm Users - The JetBrains Blog](https://blog.jetbrains.com/pycharm/2026/03/openai-acquires-astral-what-it-means-for-pycharm-users/)
38. [GitHub - astral-sh/rye: a Hassle-Free Python Experience · GitHub](https://github.com/astral-sh/rye)
39. [Rye is Archived: Use uv Instead · Mac Install Guide](https://mac.install.guide/python/use-rye)
40. [What is PEP 751?](https://pydevtools.com/handbook/explanation/what-is-pep-751/)
41. [pip Is Fighting Back: Lockfiles and Dependency Cooldowns Arrive in Version 26.1](https://modernpython.io/pip-lockfiles-dependency-cooldowns/)
42. [How to create a pylock.toml lockfile](https://pydevtools.com/handbook/how-to/how-to-create-a-pylock-toml-lockfile/)
43. [Python Tools Are Quickly Adopting the New pylock.toml Standard](https://socket.dev/blog/pylock-toml-standard-adoption)
44. [feat: add experimental PEP 817 variant support by henryiii · Pull Request #1284 · scikit-build/scikit-build-core](https://github.com/scikit-build/scikit-build-core/pull/1284)
45. [pyfuze · PyPI](https://pypi.org/project/pyfuze/)
46. [uv security advisory: ZIP payload obfuscation - Astral](https://astral.sh/blog/uv-security-advisory-cve-2025-54368)
47. [Pip 26.1 Ships Dependency Cooldowns and Experimental Lockfile Support to Combat Supply Chain Attacks - InfoQ](https://www.infoq.com/news/2026/05/pip-261-dependency-cooldowns/)
48. [Wishlist: make \`uv run --script\` shebang also work for zipapp \`.pyz\` files · Issue #18662 · astral-sh/uv](https://github.com/astral-sh/uv/issues/18662)
49. [pex · PyPI](https://pypi.org/project/pex/)
50. [PEX with included Python interpreter - Pex Docs (v2.102.0)](https://docs.pex-tool.org/scie.html)
51. [zipapps · PyPI](https://pypi.org/project/zipapps/)
52. [Create single file standalone Python scripts with builtin frozen file system](https://github.com/sourcesimian/pybake)
53. [Nuitka/Nuitka on GitHub](https://releasealert.dev/github/Nuitka/Nuitka)
54. [cx\_Freeze](https://marcelotduarte.github.io/cx_Freeze/)
55. [PyCrucible - python embedder and launcher built in Rust](https://app.daily.dev/posts/pycrucible---python-embedder-and-launcher-built-in-rust-tstaf9v5j)
56. [What is PyCrucible?](https://pycrucible.razorblade23.dev/latest/overview)
57. [GitHub - TanixLu/pyfuze: Package Python projects into executables](https://github.com/TanixLu/pyfuze)
58. [Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/)
59. [Project status update · Issue #741 · indygreg/PyOxidizer](https://github.com/indygreg/PyOxidizer/issues/741)
60. [Pex: A tool for generating .pex (Python EXecutable) files, lock files and venvs](https://news.ycombinator.com/item?id=42148220)
61. [categories: Personal, PyOxidizer - Gregory Szorc's](https://gregoryszorc.com/blog/category/pyoxidizer/)
62. [Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/2020/04/09/pyoxidizer-0.7/)
63. [So is Rye deprecated? The puzzling rye/uv relationship is what had stopped me fr...](https://news.ycombinator.com/item?id=41315476)
64. [uv: Python packaging in Rust - Astral](https://astral.sh/blog/uv)
65. [Modules: TypeScript](https://nodejs.org/docs/latest-v24.x/api/typescript.html)
66. [esbuild - API](https://esbuild.github.io/api/)
67. [An Introduction to the esbuild Bundler — SitePoint](https://www.sitepoint.com/esbuild-introduction/)
68. [Program management update — January 2026](https://blog.rust-lang.org/inside-rust/2026/02/11/program-management-update-2026-01/)
69. [Stabilize cargo script](https://github.com/rust-lang/cargo/pull/16569)
70. [.NET 10 File-Based Apps - Best Way to Script in C#](https://remigiuszzalewski.com/blog/dotnet10-file-based-apps)
71. [DEV Community](https://dev.to/mashrulhaque/dotnet-run-in-net-10-single-file-c-is-finally-here-1gdi)
72. [Exploring C# File-based Apps in .NET 10](https://milanjovanovic.tech/blog/exploring-csharp-file-based-apps-in-dotnet-10)
73. [dotnet run app.cs - Run C# Without a Project File in .NET 10](https://codewithmukesh.com/blog/file-based-apps-dotnet-10/)
74. [build tool · Issue #10019 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10019)
75. [Create a wheelhouse with only runtime wheels · Issue #13263 · astral-sh/uv](https://github.com/astral-sh/uv/issues/13263)
76. [Suggestion: \`uv bundle\`, \`uv build --release\` or similar to create a contained executable a la pyinstaller, py2exe · Issue #5802 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5802)
77. [Vermin - python boilerplate](https://python-boilerplate.github.io/uv-template/features/code_quality/vermin/)
78. [feat(fill): watch mode with re-run for \`uv run fill\` · Issue #2156 · ethereum/execution-spec-tests](https://github.com/ethereum/execution-spec-tests/issues/2156)
79. [pex 2.98.2 · pex-tool/pex · Discussion #3222](https://github.com/pex-tool/pex/discussions/3222)
80. [Unstable Features - The Cargo Book](https://doc.rust-lang.org/cargo/reference/unstable.html)
