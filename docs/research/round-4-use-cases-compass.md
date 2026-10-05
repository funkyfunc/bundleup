# Self-contained Python programs: who needs them, what each situation requires, and which formats bundleup should offer

Advertise `.pyz` now to every audience where the target machine already has a matching CPython and a writable cache directory: internal CLIs, CI and automation scripts, push-and-run ops scripts, offline HPC nodes, air-gapped servers, single-board computers and course tools. After that, add exactly two more outputs: a **vendored directory** (to embed in host applications such as Blender, QGIS and Splunk) and an **AWS Lambda zip/layer**. Leave standalone executables, container images, conda environments, Pyodide/WebAssembly and Excel to other tools. The most important engineering work is not a new format. It is making the `.pyz` honest about its target: a pinned Python minor version/ABI, a platform tag, a cache location you can override, and a clear error when the host doesn't match.

## TL;DR

- **Strong fit today (plain `.pyz`):** internal tools and CLIs, CI scripts, scripts pushed to remote hosts (like Ansible's AnsiballZ), HPC compute nodes without internet, air-gapped or regulated servers, Raspberry Pi and appliances that have Python, education, and agent sandboxes. They all have Python available but no network or no install rights. That is exactly bundleup's promise.
- **Worth supporting soon:**
  - cross-platform builds (`--platform`, `--python`). These unblock Linux servers, Pi/aarch64 and Splunk.
  - a `dir` output (unpacked site-packages plus code) for host applications and plugins.
  - a `lambda` preset that writes a Lambda-native zip or layer. Lambda unzips for you, its only writable path is `/tmp`, and every cold start would otherwise pay for extraction.
- **Out of scope or poor fit:**
  - desktop apps for non-technical users (these need an embedded interpreter, which the roadmap rules out).
  - Cloudflare Python Workers and other Pyodide targets.
  - Python in Excel (runs in Microsoft's cloud, with no custom packages).
  - conda-style environments with system libraries or CUDA.
  - container image building, and Vercel. Vercel already builds natively from `uv.lock`, so bundleup adds little there.

## Key Findings

1. **The `.pyz` + extract-to-cache design is proven by prior tools, but they also show its sharp edges.** shiv extracts dependencies to `~/.shiv` (overridable with `SHIV_ROOT`) "because of limitations of third-party and binary dependencies. Shared objects loaded via the dlopen syscall require a regular filesystem."\[1\]\[2\] Shiv users have hit lock-file collisions between versions of the same app (linkedin/shiv#203).\[3\] Others note first-run latency and cache build-up that has to be cleaned periodically.\[4\] bundleup inherits all three problems and should design for them up front.
2. **The biggest practical blocker is where the cache goes, not the format.** On Lambda, the home directory is read-only and only `/tmp` is writable. Libraries that write to `$HOME` fail with `[Errno 30] Read-only file system: '/home/sbx_user1051'`, as seen in crewAI#502/#1275.\[5\]\[6\]\[7\] Azure Functions mounts run-from-package deployments as a read-only `wwwroot`.\[8\]\[9\] Cloud Run (2nd gen) has a writable filesystem, but it is in memory and counts against instance memory.\[10\]
3. **The ABI is the second blocker.** A bundle containing `cp313` extension wheels only runs on CPython 3.13 with a matching platform tag. Every environment that controls its own Python (Lambda, Azure, Blender, Splunk, QGIS, HPC modules) needs bundleup to build for *their* Python rather than the developer's.
4. **Platforms are moving toward building from the lockfile themselves.** Vercel "installs Python dependencies with uv by default" and reads `uv.lock` natively.\[11\] Cloud Run's Python buildpack uses uv as the default installer from Python 3.14.\[12\] Cloudflare's `pywrangler` resolves `pyproject.toml` with uv.\[13\] Where the platform already builds from the lock, a bundler adds little, except offline or vendored builds (Cloud Run's `GOOGLE_VENDOR_PIP_DEPENDENCIES`).\[14\]
5. **Host applications have converged on "ship wheels or a vendored directory, not a zipapp".** Blender extensions bundle unmodified PyPI wheels per platform in `blender_manifest.toml`.\[15\]\[16\] Splunk tells developers to install dependencies into `bin/lib/` with `pip install --target ... --platform manylinux2014_aarch64 --only-binary=:all:`.\[17\] QGIS plugin tooling vendors runtime dependencies into the plugin zip.\[18\] A `dir` output covers all three.
6. **Data platforms already use PEX and packed environments.** PySpark's official packaging guide documents conda-pack, venv-pack and PEX (`PYSPARK_PYTHON=./env.pex`).\[19\]\[20\] Dagster+ Serverless deploys PEX files by default; Dagster's blog says that "using pex, Serverless Dagster Cloud now deploys 4 to 5 times faster by avoiding the overhead of building and launching Docker images." A `.pyz` cannot serve as `PYSPARK_PYTHON` the way a PEX can, so the data-platform fit is only partial.

## 1. Input shapes (Part 1)

| Shape | How common | What breaks when bundled | How existing tools cope |
|---|---|---|---|
| **A. Stdlib-only script** | Very common for ops, CI and teaching (no adoption data found) | Almost nothing. The only issue is the Python version floor (`requires-python`). | Plain `python -m zipapp` or just a `.py` file. A bundler adds little beyond metadata and a version check. |
| **B. Code + pure-Python deps** | Common | Packages that read data files via `__file__` or `open()` relative to their own module fail inside a zip. `importlib.resources.files()` works from zips, and `as_file()` supports directories since 3.12.\[21\] Namespace-package edge cases in zipimport (cpython#121111).\[22\] Entry-point and plugin discovery through `importlib.metadata` needs `.dist-info` kept. | shiv and pex extract to disk or a venv to sidestep the problem. zipapps optionally keeps pure code in the zip.\[23\] |
| **C. Compiled extensions** | Very common (numpy, pydantic-core, cryptography, orjson…) | zipimport cannot load `.so`/`.pyd`, so extraction is mandatory.\[23\]\[24\] Wheels are tied to the CPython minor version (unless abi3), OS, CPU and libc (manylinux glibc floor vs musllinux). | shiv/pex extract. PyInstaller/Nuitka freeze. Blender/Splunk require per-platform wheels. |
| **D. Non-Python deps** (libpq, libGL, OpenSSL, ffmpeg, Playwright browsers, Node, models, CUDA) | Common in data/ML, scraping, media | Wheels that bundle their `.so` files (via auditwheel/delocate) work. Anything expected from the OS (libGL for opencv-python, a system ffmpeg, a browser downloaded by `playwright install`) does not. CUDA wheels run to gigabytes and depend on the driver. | Containers, conda-pack/pixi-pack, Lambda container images (10 GB).\[25\] No zipapp tool solves this well. |
| **E. Multiple entry points** | Common (CLI subcommands, web app + worker + cron, host-loaded plugins) | Single `__main__` vs several console scripts. Web servers want `module:app`. Host apps import a package rather than executing anything. | PEX's `-c`/`-e` and `--scie-busybox`, shiv's `-c`/`-e`. Lambda wants `module.function`. Hosts want a package directory. |

**Interpretation:** A–C are bundleup's home ground. For C, the work is target selection and extraction hygiene. For D, bundleup should *detect and warn*, not solve. For example, scan extension modules for undeclared `DT_NEEDED` libraries and flag known post-install downloaders like Playwright. Promising D would mean becoming conda or Docker. E needs a small multi-entry-point design (a busybox-style `app.pyz <command>` dispatch plus an `--entry` override).

## 2. Output formats (Part 2)

| Format | Target needs | Offline | Compiled / non-Python deps | Size & start-up | Signing / security | Produced today by |
|---|---|---|---|---|---|---|
| **PEP 723 script** (+ `uv lock --script`) | uv or pipx **and network** on first run | No (unless a uv cache/index is pre-seeded) | Resolved at run time from an index. Non-Python deps not handled. | Tiny file. First run resolves and installs. | Code is readable. Supply chain is decided at run time unless locked. | uv, pipx, hatch. `uv lock --script` added in uv 0.6.3.\[26\] |
| **`.pyz`, single platform** | Matching CPython | Yes | Extracted to a cache on first run. Non-Python deps only if inside wheels. | Moderate. First-run extraction, warm afterwards. | One file to hash or sign (detached signature, e.g. Sigstore/GPG). No OS-level code signing. | shiv, zipapps, **bundleup** |
| **`.pyz`, multi-platform** | Matching CPython | Yes | Per-platform wheel sets, choosing the right one at boot | Larger (N× the extension payload) | Same as above | pex (multi-platform), shiv (manual) |
| **PEX** | Matching CPython (or none with `--scie eager`) | Yes (eager) | Extracts to `PEX_ROOT` or a venv | Similar to `.pyz`. venv mode is faster when warm. | Same as above | pex, Pants |
| **Lambda zip / layer** | Lambda managed runtime | Yes | Platform-tagged wheels, unpacked. No extraction step. | 50 MB zipped (direct upload) / 250 MB unzipped incl. layers\[27\] | IAM / code signing for Lambda | SAM, CDK, Serverless Framework, hand-built `pip install -t` |
| **Cloud Run functions / Azure Functions source** | Platform builder | Builds pull from an index unless vendored | Platform installs Linux wheels | Platform-dependent | Platform | gcloud, func core tools |
| **Vercel function** | Vercel builder (uv) | Build-time network | Linux wheels, 500 MB uncompressed\[28\] | — | — | Vercel itself from `uv.lock` |
| **Cloudflare Python Worker** | Pyodide in workerd | — | Only pure-Python, PyEmscripten wheels, or packages in Pyodide\[29\] | 128 MB memory per isolate\[30\] | — | pywrangler |
| **OCI image without Dockerfile** | Container runtime | Yes | Anything on the base image | Large but cached by layer | Image signing (cosign) | ko/jib equivalents for Python are rare. Usually a Dockerfile plus uv. |
| **Standalone executable** | Nothing | Yes | Embedded interpreter. PyInstaller onefile re-extracts to a temp dir. | Largest. Slowest first start (onefile). | Authenticode / notarization possible and often needed | PyInstaller, Nuitka, PyApp, pex `--scie eager` |
| **Vendored directory** | Host app's Python | Yes | Platform wheels unpacked, no zip. Host-controlled ABI. | Unpacked size. Fastest import. | Host app's review (e.g. Splunk AppInspect) | `pip install --target`, extbpy, qgis-plugin-dev-tools |
| **Wheelhouse** | pip/uv + Python | Yes | Platform wheels | Install step required | Hashes in the lock | `pip download`, `uv export` + `pip wheel` |
| **conda-pack / pixi-pack** | Nothing but the OS (includes the interpreter) | Yes | Handles system libs and CUDA via conda | Large | — | conda-pack, pixi-pack |
| **PySpark `--py-files` zip** | Spark's Python | Yes | **Pure Python only** (no `.so` from zip) | Small | — | `zip -r` |
| **Pyodide / WebAssembly bundle** | Browser or Wasm host | Depends | Wasm wheels only | — | — | Pyodide, PyScript, pywrangler |

**Can one artifact serve several modes?** It partly works today. A zip file tolerates arbitrary bytes in front of it, so a `.pyz` can carry a shebang plus a PEP 723 block. But uv currently "chokes in trying to read the metadata section, since it tries to read the whole file and errors out on the *non-unicode* parts of it" (uv#18662, an open wishlist item).\[31\] One commenter suggested putting a `pyproject.toml` inside the zip, but reported "I can't get it to work so far."\[31\] **Recommendation:** offer an opt-in `--uv-header` that writes the PEP 723 block. Document it as forward-looking, and don't make any feature depend on it until uv supports it. The "use uv if available, else embedded deps" hybrid is technically easy. It is a bootstrap branch, and bundleup controls the bootstrap. But it creates two code paths whose dependency sets can drift, which undermines the "locked, no network" promise. I would not ship it as a default.

## 3. Use cases (Part 3)

### Serverless

**AWS Lambda (zip, layers, container images).** *Who:* The large volume of "Unzipped size must be smaller than 262144000 bytes" threads on AWS re:Post, and the read-only-filesystem bug reports, show this is a widespread need. *Constraints (AWS docs, checked October 2026):*
- Zip packages are capped at 50 MB zipped for direct upload and 250 MB unzipped, "including layers and custom runtimes". Up to five layers. Container images up to 10 GB. `/tmp` is configurable from 512 MB to 10,240 MB.\[25\]\[32\]\[33\]
- Only `/tmp` is writable.\[34\]\[35\]
- Runtime list: python3.14 runs on Amazon Linux 2023 with deprecation projected for June 30, 2029. AWS's "Building Lambda functions with Python" page lists python3.10 (Amazon Linux 2) for deprecation on Oct 31, 2026. python3.9 was deprecated December 15, 2025.
- All supported runtimes run on x86_64 and arm64.\[36\]
- The handler must be `module.function` inside the package.

*Today:* `pip install --target` with `--platform manylinux2014_*` and `--only-binary`, SAM/CDK, or container images. *What goes wrong:* building on macOS ships Mac wheels, the size cap, and `$HOME` writes. *Fit for `.pyz`:* **partial**. A `.pyz` can't be the handler directly. It needs a stub `handler.py` that extracts into `/tmp` on every cold start, because each new execution environment starts with an empty `/tmp`.\[34\] That adds latency for no benefit, since Lambda already unzips the deployment package. *What bundleup should do:* a `--target lambda` preset that emits a Lambda-native zip (code plus unpacked site-packages at the root) or a layer (`python/` prefix). It should take `--python 3.13|3.14` and `--platform manylinux_2_28_x86_64|aarch64`, report the unzipped size against the 250 MB limit, and set the cache to `/tmp` if a `.pyz` is used anyway. Input shapes A–C. D only via a container image (leave to Docker).

**Google Cloud Run functions.** *Constraints (Google docs, October 2026):*
- Runtimes include python314 (Ubuntu 24.04, deprecation 2030-10-10), python313 and python312. python39 was decommissioned 2026-04-05.\[37\]\[38\]
- Dependencies come from `requirements.txt` or `pyproject.toml`. From Python 3.14 the buildpack uses uv by default.\[12\]\[39\]
- Offline or restricted builds can ship pre-downloaded wheels via `GOOGLE_VENDOR_PIP_DEPENDENCIES`.\[14\]
- Google's quota table gives 100 MB compressed / 500 MB uncompressed for 1st gen and lists "N/A" for current functions.\[40\]
- The container filesystem "is writable … an in-memory file system".\[10\]

*Fit:* **partial and low priority.** The platform builds from source. bundleup's useful contribution is a vendored wheel directory for restricted builds, which is a wheelhouse, not a `.pyz`.

**Azure Functions.** *Constraints (Microsoft docs, September 2026):*
- Python 3.10–3.14 are GA on Linux only. 3.10 support ends October 2026.\[41\]
- "Python 3.12 is the last Python version supported for Linux Consumption plan apps."\[41\]
- Remote build is the recommended path and installs into `.python_packages/lib/site-packages`.\[42\]
- Flex Consumption runs from a package by default. "When you run from a package, files in wwwroot are read-only." The maximum package size is 1 GB.\[8\]\[43\]

*Fit:* **partial.** A local build is possible if the package "runs on Linux based systems",\[42\] i.e. a vendored dir with Linux wheels at `.python_packages/lib/site-packages`. That is a `dir` output with an Azure path preset. `.pyz` extraction would have to target a temp path, since `wwwroot` is read-only.

**Vercel Python functions.** *Constraints (Vercel docs, 2026):* 500 MB uncompressed for Python, up to 5 GB with Large Functions (public beta, Fluid compute).\[28\]\[44\] Vercel installs with uv by default and reads `uv.lock`.\[11\] *Fit:* **poor/unnecessary.** Vercel already turns a locked uv project into a function. Document "you don't need bundleup here".

**Cloudflare Python Workers.** *Constraints:* code runs on Pyodide (CPython compiled to WebAssembly) in V8 isolates. pywrangler supports pure-Python packages, PyEmscripten wheels and packages shipped with Pyodide. Memory is 128 MB per isolate.\[29\]\[30\] Cloudflare's Workers limits page sets "Worker size (uncompressed) 64 MiB" with no compressed size limit; a September 2026 GA is cited by third-party summaries only. *Fit:* **out of scope.** There is no CPython, no `.so` loading, and the tooling is already uv-based.

### Data and batch

**PySpark / Databricks / EMR.** The official PySpark guide ships environments via conda-pack (`--archives env.tar.gz#environment`) or venv-pack. venv-pack "requires all nodes in a cluster to have the same Python interpreter installed because venv-pack packs Python interpreter as a symbolic link". PEX files can be shipped with `--files` and used as `PYSPARK_PYTHON`.\[20\]\[45\] `--py-files` cannot carry native code. *Fit:* **partial.* A `.pyz` works for the *driver* script, or as a `--py-files`-style addition for pure-Python code, but executors need an interpreter-like artifact. *Bundler needs:* either a mode where the `.pyz` behaves as a Python interpreter (re-exec `python` with the extracted `sys.path` when invoked as `PYSPARK_PYTHON`), or a pure-Python `--py-files` zip output. I'd document the PEX/venv-pack paths instead of competing in v1.

**Airflow / Dagster tasks.** Dagster+ Serverless packages code as PEX by default. Dagster reports roughly 40 s deploys versus 3+ minutes with Docker.\[46\]\[47\] Dagster's 1.13.23 changelog says fast deploys "now build a Docker image instead of a Python executable when the target environment cannot run one: Serverless on Kubernetes, or a Harbor image registry." *Fit:* **partial.** A `.pyz` invoked by a `BashOperator`/`subprocess` task on workers that have Python works today. Platform-native integration is the platform's job. Airflow's own guidance was not checked in this research.

**Ray.** Not verified in this research. Ray's `runtime_env` (pip, `py_modules`, `working_dir`) is the native mechanism. Treat as **poor fit**: Ray workers need importable modules, not an executable.

**HPC clusters with offline compute nodes.** No primary source fetched in this research, but the pattern (login node has internet, compute nodes don't, Python comes from environment modules) is widely documented by university HPC centres. *Fit:* **strong.** Build on the login node against the module's Python and run `python app.pyz` in the job script. *Needs:* `--python` matching the module, a cache override pointing at node-local scratch (home on NFS/Lustre is slow and shared), a concurrency-safe extraction lock when 1,000 array tasks start at once, and an optional `app.pyz --extract-only` pre-warm step.

### CI and automation

**CI scripts, GitHub Actions in Python, pre-commit hooks.** CI runners have Python. The point of a `.pyz` is no `pip install` step and no network flakiness. *Fit:* **strong** for scripts run with `python tool.pyz`. GitHub Actions natively run JavaScript, Docker or composite actions, so a Python action is a composite action that runs `python ${{ github.action_path }}/tool.pyz`. pre-commit has its own Python environment management. A `.pyz` fits a `language: system`/`script` hook. Neither was verified against current docs in this research.

**Ansible / configuration management.** AnsiballZ is the precedent: Ansible zips the module "and all its dependencies, embed[s] the (Base64-encoded) zipped code in a Python script", sets `PYTHONPATH` to the zip and imports the module as `__main__`. Ansible issue #76941 notes that "even for very simple modules, that zipped data is usually at least 120KB." *Fit:* **strong** for "copy one file to a host and run it with the host's `python3`" (push-and-run ops scripts, agents, incident response). Pure-Python dependencies should stay in-zip, with no extraction, to keep it fast and leave no trace.

### Applications that embed Python

**Blender.** Extensions must be self-contained. Wheels "must be bundled unmodified from Python's package index" and "must include their dependencies", listed in `blender_manifest.toml` with a `platforms` list. `blender --command extension build --split-platforms` produces per-platform builds.\[15\]\[16\] extbpy already builds Blender extensions from `uv.lock`.\[48\] *Fit:* **partial.** The host wants wheels, not a `.pyz`. bundleup could output "the resolved wheel set for Python X on platforms P1…Pn". That is cheap if cross-platform resolution exists, but extbpy is ahead.

**QGIS / ArcGIS.** QGIS plugins share one interpreter. QEP #202 proposes `pip_dependencies` in metadata.\[49\] Plugin publishing rules require stating external dependencies, and qgis-plugin-dev-tools vendors runtime dependencies into the plugin zip.\[18\]\[50\] *Fit:* **partial.* The `dir` output with namespace isolation (vendoring under the plugin package) is the need. Shared-interpreter conflicts (two plugins vendoring different numpy builds) are a real risk, so bundleup must warn on compiled dependencies the host already ships.\[49\] ArcGIS was not checked.

**Splunk apps.** The official SDK README says to install dependencies to `bin/lib/` with `--platform manylinux2014_aarch64 --only-binary=:all:` matching "the platform Splunk is built and ran on, NOT the one you're writing your App on".\[17\] A Splunk staff answer says "Do not modify the version of Python shipped with Splunk… do not attempt to establish virtualization environments."\[51\] *Fit:* **partial, high value.** A `dir` output with `--platform` and `--python` set to Splunk's bundled Python is exactly what's asked for.

**Maya / Houdini / KNIME.** Not researched in this pass. The pattern is a host-controlled CPython on Windows/Linux/macOS loading plugins from a path, so it is the same as Splunk/QGIS: `dir` output, **partial**.

**Python in Excel.** Code runs "in the Microsoft Cloud" in an isolated Azure container with Anaconda's packages.\[52\] Users report you "can't install custom packages".\[53\] The separate Anaconda Code add-in (Pyodide-based) lets you add packages from PyPI or wheel URLs.\[54\] *Fit:* **out of scope.**

### People-facing tools

**Internal tools and CLIs for colleagues or customers.** This is the core case, and shiv's adoption (Django single-file deploys at Lincoln Loop, etc.) is evidence. *Constraints:* the recipient's Python version and OS vary. *Fit:* **strong** once multi-platform builds land. Today it is strong within a homogeneous fleet (e.g. "everyone has macOS arm64 + Python 3.13"). *Needs:* `requires-python` check with a human-readable error, `--platform` multiples, and a `cache clean` subcommand.

**Desktop tools for non-technical users.** They don't have Python, or don't know what it is. They need double-click, an icon and code signing. *Fit:* **poor/out of scope**, because it needs an embedded interpreter, which the roadmap rules out. Point to PyApp, pex `--scie eager`, PyInstaller or Briefcase.

**Edge and embedded (Raspberry Pi, appliances, offline devices).** Raspberry Pi OS ships Python, and many appliances ship an older one. *Fit:* **strong** if you build on the device today, and strong generally after cross-building to `linux-aarch64`/`armv7l`. Watch for old glibc on appliances (manylinux floor), musl on Alpine-based images (musllinux), small flash/eMMC (cache size), and read-only root filesystems (cache override to `/var` or `/run`).

**Air-gapped and regulated environments; incident response.** The Cloud Foundry buildpack docs say that in disconnected environments "your application must vendor its dependencies".\[55\] *Fit:* **strong.** One hashable file, no network, a lockfile-derived SBOM. *Needs:* reproducible builds (identical bytes from the same lock), an embedded SBOM, detached signature guidance, a mode that leaves no trace (temporary cache deleted on exit) for incident responders, and refusal to follow `PYTHONPATH`/user site by default (run isolated, as pex does with `-sE`).\[56\]

**Agent sandboxes and skills (already researched by you).** In brief: these sandboxes usually have Python but restricted or no network, a writable workspace, and ephemeral disks. A `.pyz` lets a skill carry its dependencies. The cache must point into the writable workspace, and first-run extraction counts against per-call time limits. **Strong fit.**

**Education.** Instructors hand out graders and starter tools. Students have assorted Pythons. *Fit:* **strong** for A/B shapes (pure Python works on any OS with one artifact). Compiled dependencies need multi-platform bundles. No primary-source evidence gathered here.

**Notebooks to programs.** You convert with `jupyter nbconvert --to script`, then lock as a PEP 723 script, then bundle. *Fit:* **partial.** bundleup could accept `.ipynb` input, but magics and display calls break. Document the recipe rather than building it.

### Summary table

| Use case | Input shapes needed | Best output | Fit |
|---|---|---|---|
| Internal CLIs / tools | A–C, E | `.pyz` (multi-platform) | Strong |
| CI scripts / Actions / hooks | A–C | `.pyz` | Strong |
| Push-and-run ops (Ansible-style), IR | A–B (C) | `.pyz` | Strong |
| HPC offline nodes | A–C | `.pyz` with cache override | Strong |
| Air-gapped / regulated | A–C | `.pyz` + SBOM + signature | Strong |
| Edge / Pi / appliances | A–C | `.pyz` (aarch64/armv7) | Strong (after cross-build) |
| Education | A–B (C) | `.pyz` | Strong |
| Agent sandboxes / skills | A–C | `.pyz` | Strong |
| AWS Lambda | A–C | Lambda zip / layer | Partial → strong with preset |
| Azure Functions | A–C | `dir` (`.python_packages`) | Partial |
| Cloud Run functions | A–C | vendored wheels | Partial, low priority |
| Splunk / QGIS / Maya / Houdini plugins | B–C | `dir` (vendored) | Partial |
| Blender extensions | B–C | wheel set | Partial (extbpy exists) |
| PySpark / EMR / Databricks | B–C | PEX / conda-pack (driver: `.pyz`) | Partial |
| Airflow / Dagster | B–C, E | `.pyz` via subprocess; PEX native | Partial |
| Notebooks | A–C | `.pyz` via recipe | Partial |
| Ray | B–C | runtime_env | Poor |
| Vercel | B–C | Vercel's native build | Poor (unneeded) |
| Desktop for non-technical users | A–D | standalone exe | Out of scope |
| Cloudflare Workers / Pyodide | A–B | Pyodide bundle | Out of scope |
| Python in Excel | — | — | Out of scope |
| D-heavy (CUDA, ffmpeg, browsers) | D | container / conda-pack | Out of scope |

## 4. Output strategy (Part 4)

**What other tools teach.** esbuild keeps two independent axes, `--format` (esm/cjs/iife) and `--platform` (browser/node/neutral), with platform setting sensible format defaults. Bun splits "bundle" (`bun build`) from "make an executable" (`bun build --compile`, with `--target=bun-linux-x64` style cross-targets). Deno uses a separate verb (`deno compile --target`). Go uses only environment variables (`GOOS`/`GOARCH`), and users find that easy because there is exactly one output type. .NET's `dotnet publish` combines `-r <rid>`, `--self-contained` and `-p:PublishSingleFile=true`, and the property combinations are a common source of confusion. PyInstaller's onedir vs onefile is a single switch, but onefile's re-extraction to a temp dir on every start is a recurring complaint. pex layers `--scie eager|lazy` onto one core format.\[57\] (These CLI descriptions come from the tools' public docs and weren't re-fetched for this report.)

**Lessons:** (1) keep *what format* and *what target* as separate axes. (2) A preset should be a named, printable expansion of ordinary flags, not a hidden mode. (3) Every format that extracts at run time needs a visible cache policy.

**Recommended CLI shape:**

```
bundleup build                                  # .pyz for this host (today's behaviour)
bundleup build --python 3.13 --platform linux-x86_64 --platform linux-aarch64
bundleup build --format dir  --python 3.11 --platform manylinux_2_17_aarch64   # Splunk / QGIS / Azure
bundleup build --target lambda --python 3.14 --arch arm64                     # preset → --format lambda-zip ...
bundleup build --target lambda-layer
bundleup targets            # list presets and print what each expands to
app.pyz --bundleup-info     # embedded metadata: target python/ABI/platforms, lock hash, SBOM
BUNDLEUP_CACHE=/tmp/x python app.pyz            # cache override; also --extract-only / --clean
```

One verb, two orthogonal axes (`--format`, `--python/--platform`), and `--target` presets that expand to them and print the expansion. No separate commands per format.

**Order of work:**
1. Cross-target `.pyz` (`--python`, `--platform`, multi-platform). This unlocks most "strong" rows.
2. Runtime hardening: cache resolution order (explicit env, then XDG cache, then `~/.cache`, then a temp dir if home is unwritable), atomic extraction with per-build-hash locks, a stale-cache cleaner, ABI/platform self-check with a clear message, isolated `sys.path`.
3. `--format dir`.
4. `--target lambda`/`lambda-layer`.
5. Optional `--uv-header` once uv#18662 is resolved.

Leave to others: standalone executables (PyApp, pex scie, PyInstaller), OCI images (Dockerfile + uv; document a 3-line recipe that copies `app.pyz` into `python:3.x-slim`), conda environments, Pyodide, wheelhouses (`uv export` + `pip download` already does this).

**Steelman: ".pyz only, done extremely well."** One format means one runtime, one test matrix, one mental model, and docs that say "`python app.pyz`, everywhere". Most of the use cases in the strong rows need nothing else. Every extra format (Lambda zip, `dir`) duplicates work that SAM, extbpy or `pip install --target` already do. Feature creep is how PyInstaller and PyOxidizer became hard to maintain (its author Gregory Szorc wrote in March 2024 that "PyOxidizer and all the projects under its umbrella are effectively in a zombie state").

**Steelman: several formats.** The hard part (resolving a locked project for a *foreign* Python/platform, choosing wheels, checking ABI) is shared by all outputs. Once bundleup can do it for `.pyz`, writing the same file set as a directory or a Lambda zip is roughly a different archive writer. And the two biggest audiences that can't use a `.pyz` well (Lambda, host-app plugins) are exactly where people currently fail with hand-rolled `pip install --target --platform` commands.

**Verdict:** make `.pyz` the product and add `dir` and `lambda` as thin writers over the same resolved file set. Refuse anything that needs an interpreter, a container runtime or a non-CPython ABI.

## 5. Three lists

**Advertise now (works today with host-platform `.pyz`, given a matching Python):**
- Internal CLIs within a homogeneous fleet
- CI scripts and composite GitHub Actions
- Push-and-run ops / config-management scripts
- Incident-response scripts (pure Python best)
- HPC jobs (build on the login node)
- Air-gapped servers (build on a matching machine)
- Raspberry Pi (build on the Pi)
- Course tools and graders (pure Python)
- Agent sandboxes and skills
- Docker images via a 3-line Dockerfile copying `app.pyz`

**Support soon (needs a feature or format):**
- Cross-platform `.pyz` (customers' laptops, mixed fleets, aarch64 edge devices)
- Cache override and hardening (Lambda, read-only roots, HPC scratch)
- AWS Lambda zip/layer preset
- `dir` output for Splunk, QGIS, Maya/Houdini and Azure Functions
- Wheel-set export for Blender
- `.pyz`-as-interpreter or a `--py-files` zip for PySpark
- `--uv-header` dual-mode (blocked on uv#18662)

**Out of scope:**
- Desktop apps for non-technical users (needs an embedded interpreter; roadmap rules it out)
- Cloudflare Workers and Pyodide/browser
- Python in Excel
- Vercel (already native)
- Cloud Run functions builds beyond vendored wheels
- Ray
- conda-style system libraries and CUDA (shape D)
- Container image building
- Wheelhouses (use uv/pip)

## 6. Doc invitations

- **Internal tools:** "Hand a colleague one file. If they have Python 3.12, `python mytool.pyz` just works: no virtualenv, no pip, no network."
- **CI:** "Stop installing your CI helpers on every run. Commit or cache `ci-tool.pyz` and call it with the runner's Python."
- **Push-and-run ops / Ansible-style:** "Like AnsiballZ, but for your own tools: `scp tool.pyz host: && ssh host python3 tool.pyz`."
- **Incident response:** "One hashable, signable file that runs with the system Python, never touches the network, and can clean up its cache on exit."
- **HPC:** "Compute nodes have no internet? Build on the login node against your module's Python and point `BUNDLEUP_CACHE` at node-local scratch."
- **Air-gapped / regulated:** "Locked inputs, reproducible output, an embedded SBOM: carry one file across the gap and run it with the Python already approved there."
- **Raspberry Pi / edge:** "Run your project on a Pi with the Python it ships. Build on the device today, cross-build for aarch64 soon."
- **Education:** "Give students one file that runs on Windows, macOS and Linux. They never have to `pip install` anything."
- **Agent sandboxes and skills:** "Ship a skill with its dependencies inside it. Works in sandboxes without network access."
- **Containers:** "No need for a multi-stage uv build: `COPY app.pyz /app.pyz` onto `python:3.13-slim` and set `CMD [\"python\", \"/app.pyz\"]`."
- **AWS Lambda (soon):** "`bundleup build --target lambda --python 3.14 --arch arm64` gives you a Lambda-ready zip built for Lambda's Linux, not your Mac, and warns you before you hit the 250 MB unzipped limit."
- **Splunk / QGIS / Maya plugins (soon):** "Vendor your locked dependencies for the host application's own Python and platform with `--format dir`. No more hand-written `pip install --target --platform`."
- **Azure Functions (soon):** "Build `.python_packages` locally for Linux and deploy without remote build. Works with read-only run-from-package."
- **Blender (soon):** "Export the exact wheels your extension needs for every platform Blender supports, straight from `uv.lock`."
- **PySpark (soon):** "Use the same locked bundle for your driver and executors."

## Caveats

- **Not verified in this pass:** HPC centre docs, GitHub Actions/pre-commit docs, Ray, Airflow, Maya/Houdini/KNIME/ArcGIS, Raspberry Pi OS Python versions, and CLI behaviour of esbuild/Bun/Deno/.NET/Go/PyInstaller. These judgments rest on general knowledge and should be checked before they appear in docs.
- **Cloudflare details:** the 64 MiB uncompressed Worker size comes from Cloudflare's Workers limits page; the September 2026 GA date comes from third-party summaries only.
- **Cloud Run python310** was deprecated on 2026-10-04 (decommission 2027-04-04) according to Google's runtime-support table.
- **Roadmap gaps:** I don't have the roadmap. Whether `dir`/Lambda outputs or a `.pyz`-as-interpreter mode fit its stated non-goals is your call. The analysis assumes only "no embedded interpreter".
- **No adoption or market-size data** was found for any use case. "Common" means frequent in docs and issue trackers, not measured.
- **Limits change.** Every platform limit and runtime above is as of September–October 2026 and should be re-checked at publication.

## Sources

1. [shiv · PyPI](https://pypi.org/project/shiv/)
2. [shiv May 02, 2018](https://app.readthedocs.org/projects/shiv/downloads/pdf/docs/)
3. [different zipapps sharing the same .lock file during extraction due to dots in the filename · Issue #203 · linkedin/shiv](https://github.com/linkedin/shiv/issues/203)
4. [Single-file Python/Django Deployments](https://lincolnloop.com/blog/single-file-python-django-deployments/)
5. [\[BUG\] \[Errno 30\] Read-only file system error when using AWS Lambda · Issue #1275 · crewAIInc/crewAI](https://github.com/crewAIInc/crewAI/issues/1275)
6. [how to work around directory permissions in aws lambda?](https://repost.aws/questions/QUoCCNNS59RryAKeEBezXFcg/how-to-work-around-directory-permissions-in-aws-lambda)
7. [\[Errno 30\] Read-only file system error when using AWS Lambda · Issue #502 · crewAIInc/crewAI](https://github.com/crewAIInc/crewAI/issues/502)
8. [Package-based deployment for Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/deployment-zip-push)
9. [Run your Functions from a Package File in Azure](https://docs.azure.cn/en-us/azure-functions/run-functions-from-deployment-package)
10. [Container runtime contract](https://docs.cloud.google.com/run/docs/container-contract)
11. [How to deploy a uv project to Vercel](https://pydevtools.com/handbook/how-to/how-to-deploy-a-uv-project-to-vercel/)
12. [Specify dependencies in Python](https://cloud.google.com/run/docs/runtimes/python-dependencies?authuser=0)
13. [How to deploy a uv project to Cloudflare Workers](https://pydevtools.com/handbook/how-to/how-to-deploy-a-uv-project-to-cloudflare-workers/)
14. [Specify dependencies in Python](https://cloud.google.com/run/docs/runtimes/python-dependencies)
15. [Python Wheels - Blender 5.2 LTS Manual](https://docs.blender.org/manual/en/latest/advanced/extensions/python_wheels.html)
16. [1.0.0 - Blender Developer Documentation](https://developer.blender.org/docs/features/extensions/schema/1.0.0/)
17. [GitHub - splunk/splunk-sdk-python: Splunk Software Development Kit for Python · GitHub](https://github.com/splunk/splunk-sdk-python)
18. [pypi.org](https://pypi.org/project/qgis-plugin-dev-tools/0.4.0)
19. [Python Package Management — PySpark 4.2.0 documentation](https://spark.apache.org/docs/latest/api/python/tutorial/python_packaging.html)
20. [python packaging](https://github.com/apache/spark/blob/v3.5.0-rc5/python/docs/source/user_guide/python_packaging.rst)
21. [github.com](https://github.com/python/cpython/pull/107734.diff)
22. [zipimport cannot do a namespace import when a directory has no python files, but it contains nested directories with python files inside of a zip file. · Issue #121111 · python/cpython](https://github.com/python/cpython/issues/121111)
23. [pypi.org](https://pypi.org/project/zipapps/2020.11.16/)
24. [github.com](https://github.com/lepy/pydzipimport)
25. [Unzipped size must be smaller than 262144000 bytes](https://repost.aws/articles/ARuWbuBaFETwihsWkPZXCpQQ/unzipped-size-must-be-smaller-than-262144000-bytes)
26. [Initialize PEP 723 script in \`uv lock --script\` by charliermarsh · Pull Request #11717 · astral-sh/uv](https://github.com/astral-sh/uv/pull/11717)
27. [Optimizing AWS Lambda Layers: Overcoming the 250MB Deployment Limit 🚀](https://medium.com/@r.bhavesh2002/optimizing-aws-lambda-layers-overcoming-the-250mb-deployment-limit-09c9eedbfa4e)
28. [Vercel Functions Limits](https://vercel.com/docs/functions/limitations)
29. [Cloudflare Python Workers GA: Fit and Limits](https://dmarketertayeeb.com/blog/cloudflare-python-workers-ga-compatibility-guide/)
30. [Cloudflare Python Workers GA: FastAPI and Django at the edge](https://creuto.com/cloudflare-python-workers-ga-fastapi-django)
31. [Wishlist: make \`uv run --script\` shebang also work for zipapp \`.pyz\` files · Issue #18662 · astral-sh/uv](https://github.com/astral-sh/uv/issues/18662)
32. [AWS Lambda Limits: Complete Guide to Quotas and Workarounds](https://middleware.io/blog/aws-lambda-limits/)
33. [Adding layers to functions - AWS Lambda](https://docs.aws.amazon.com/lambda/latest/dg/adding-layers.html)
34. [Read-only file system AWS Lambda](https://repost.aws/questions/QUyYQzTTPnRY6_2w71qscojA/read-only-file-system-aws-lambda)
35. [Lambda gives error when trying to modify S3 files](https://repost.aws/questions/QU5DE77drrRd21PHXRj_r9Ug/lambda-gives-error-when-trying-to-modify-s3-files)
36. [Lambda runtimes - AWS Lambda](https://docs.aws.amazon.com/en_us/lambda/latest/dg/lambda-runtimes.html)
37. [Runtime support](https://docs.cloud.google.com/functions/docs/runtime-support)
38. [Cloud Functions execution environment | Cloud Run functions (1st gen) | Google Cloud Documentation](https://docs.cloud.google.com/functions/1stgendocs/concepts/execution-environment?authuser=1)
39. [The Python runtime](https://docs.cloud.google.com/run/docs/runtimes/python)
40. [Quotas | Cloud Run functions | Google Cloud Documentation](https://docs.cloud.google.com/functions/quotas)
41. [Supported Languages in Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/supported-languages)
42. [python build options](https://learn.microsoft.com/en-ca/Azure/azure-functions/python-build-options)
43. [run functions from deployment package](https://learn.microsoft.com/he-il/azure/azure-functions/run-functions-from-deployment-package)
44. [Using the Python Runtime with Vercel Functions](https://vercel.com/docs/functions/runtimes/python)
45. [how to manage python dependencies in pyspark](https://databricks.com/blog/2020/12/22/how-to-manage-python-dependencies-in-pyspark.html)
46. [Dagster Cloud: 5X Faster Deployments](https://dagster.io/blog/fast-deploys-with-pex-and-docker)
47. [Serverless runtime environment](https://docs.dagster.io/dagster-plus/deployment/deployment-types/serverless/runtime-environment)
48. [extbpy · PyPI](https://pypi.org/project/extbpy/0.3.1/)
49. [PIP dependencies for Python plugins · Issue #202 · qgis/QGIS-Enhancement-Proposals](https://github.com/qgis/QGIS-Enhancement-Proposals/issues/202)
50. [github.com](https://github.com/specklesystems/speckle-qgis/issues/139)
51. [Solved: Can I add python modules to the Splunk environment... - Splunk Community](https://community.splunk.com/t5/Building-for-the-Splunk-Platform/Can-I-add-python-modules-to-the-Splunk-environment/m-p/9064)
52. [python in excel](https://github.com/microsoft/python-in-excel)
53. [Excel Python formulad - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5453405/excel-python-formulad)
54. [Configuring excel and python - How-To - Anaconda Forum](https://forum.anaconda.com/t/configuring-excel-and-python/91346)
55. [Python buildpack](https://docs.cloudfoundry.org/buildpacks/python/)
56. [pex\_binary](https://www.pantsbuild.org/stable/reference/targets/pex_binary)
57. [PEX with included Python interpreter - Pex Docs (v2.102.0)](https://docs.pex-tool.org/scie.html)
