# How Developer Tools Replaced Each Other in JavaScript and Python — and What Python's Next Tools (Especially a Bundler) Should Learn

**Bottom line:** In both ecosystems, new tools won when they were dramatically faster *and* kept the old tool's interfaces: config formats, plugin APIs, registries and standards. Usually one launch post put a number on the speedup ("10–100x"). A Python esbuild-style bundler should therefore start from the deployment complaint uv users are already filing ("give me one artifact I can copy to Lambda or a server"). It should output standard formats (zipapp/PEX, plus an optional bundled interpreter via python-build-standalone). It should not promise source-level inlining, the trap stickytape fell into.

## TL;DR
- **The winning pattern is speed plus compatibility, not novelty.** esbuild, Yarn, Ruff, uv, Biome, Rolldown and Pyrefly all led with a headline speedup measured against the incumbent. They also kept the incumbent's surface: the npm registry, Flake8 rule codes, Prettier output, the Rollup plugin API, pip's CLI and PEP-standard metadata. Tools that changed the user's mental model without a large speed win either stalled (Yarn PnP, Pipenv) or lost their maintainer (PyOxidizer).
- **Python's transitions were gated by PEPs; JavaScript's were gated by de facto APIs.** Wheels (PEP 427), PEP 517/518 build isolation, PEP 621 metadata, PEP 723 inline scripts and PEP 751 lock files each unlocked a new generation of tools. Brett Cannon dates the lock-file effort from 2021-01-31 to PEP 751's acceptance on 2025-03-31, and even then uv treats `pylock.toml` as an export format rather than a replacement for `uv.lock`. Executable bundling, task runners and GPU-aware wheels are still waiting for standards or for a tool to win.
- **For the bundler:** lead with "one reproducible deployable artifact from a uv/pyproject project, in under a second." Consume `pyproject.toml`, `uv.lock`/`pylock.toml`, PEP 723 headers and wheels, and emit zipapp/PEX-compatible or scie-style outputs. Avoid three earlier mistakes: stickytape's regex-based source inlining, PyOxidizer's bespoke Starlark config and custom importer that broke `__file__`, and Pipenv's overclaimed "official" status paired with an unstable release cadence.

## Key Findings

**Documented history (sourced):**
1. esbuild's README states its goal directly: "Our current build tools for the web are 10-100x slower than they could be."\[1\] Evan Wallace told InfoQ in 2020 he was not trying to "create an extremely flexible build system that can build anything," only to "reset the expectations of the community for what it means for a JavaScript build tool to be fast."\[2\]
2. Vite 8 went stable on March 12, 2026. It replaced its esbuild (dev) plus Rollup (prod) split with Rolldown, which "supports the same plugin API as Rollup and Vite." The rollout went through a separate `rolldown-vite` preview package and a December 2025 beta.\[3\] VoidZero's "Announcing Rolldown 1.0" post says Rolldown reached 1.0 stable on May 7, 2026, and that "the ^1.0.0 API is now locked."
3. Facebook launched Yarn in October 2016 because of "problems with consistency, security, and performance" in the npm client, while "remaining compatible with the npm registry." The announcement said Yarn cut some installs "from several minutes to just seconds."\[4\]
4. Node's type stripping shipped in v22.6.0 (August 2024), was unflagged in v23.6.0 (January 2025), was backported unflagged to v22.18.0 LTS (July 31, 2025), and was marked Stable in v25.2.0/v24.12.0 (November 2025). Its author says the initial consensus took "about twenty days."\[5\]\[6\]
5. Charlie Marsh launched Ruff as a proof of concept that "Python tooling could be much, much faster." Its initial goal was "feature-parity with Flake8 when used (1) without any plugins, (2) alongside Black." Ruff now advertises "drop-in parity with Flake8, isort, and Black."\[7\]\[8\]\[9\]
6. Astral's ty reached beta on December 16, 2025, claiming it is "between 10x and 60x faster than mypy and Pyright" without caching.\[10\] Meta's Pyrefly (alpha May 15, 2025) was written to replace the OCaml-based Pyre and checks Instagram's codebase in 13.4 seconds, versus 100+ seconds for Pyre.\[11\]\[12\]
7. PEP 751 (`pylock.toml`) was accepted on March 31, 2025, ending work Brett Cannon says "started on a lock file specification for Python in earnest on 2021-01-31." pip 25.1, PDM 2.24.0 and uv 0.6.15 could all export it within weeks. Charlie Marsh, however, wrote that "pylock.toml files are not sufficient to replace uv.lock."
8. OpenAI announced an agreement to acquire Astral (uv, Ruff, ty) on March 19, 2026, with the team joining Codex.\[13\] Anthropic had announced its acquisition of Bun on December 2, 2025. Astral described the deal as "an agreement to join OpenAI," and CNBC and Bloomberg reportedly said it was subject to "customary closing conditions, including regulatory approval"; I found no announcement that it has closed.
9. Gregory Szorc wrote in March 2024 that PyOxidizer's future is "uncertain, possibly dead."\[14\]\[15\] Its most durable output, python-build-standalone, moved to Astral in December 2024\[16\] and now underpins both uv and PEX's `--scie` mode.\[17\]\[18\]
10. In the PSF+JetBrains 2024 Python Developers Survey (published August 2025), dependency-management usage was pip 74%, Poetry 20%, Conda 18% and uv 12% in uv's first year.\[19\]\[20\] In the 2025 Stack Overflow survey, uv was the most admired tag technology at 74%.\[21\]

**Interpretation (mine):** Python's tooling consolidation (Ruff, then uv, then ty, all from one vendor now inside OpenAI) closely mirrors the JS "Rust/Go rewrite" wave of Biome/oxc/Rolldown/Rspack. Python has one structural difference: it lacks a dominant runtime vendor (like Node, Deno or Bun) that can absorb tools into the runtime. CPython absorbs slowly, through PEPs. That leaves room for third-party tools to own whole categories, bundling included.

---

## Part 1: How JavaScript Tool Categories Evolved

### Bundlers

| Transition | Complaint | Approach | Compatibility kept | Speed / accelerant | Fate of old tool |
|---|---|---|---|---|---|
| Browserify → webpack | Browserify only bundled CommonJS. CSS, assets, code splitting and HMR needed bolt-ons. | Everything is a module via loaders; code splitting; dev server with HMR. | CommonJS and AMD; npm packages unchanged. | Adoption followed React-era SPA growth and framework CLIs such as create-react-app that embedded webpack (interpretation; no adoption data found). | Browserify survives in maintenance mode, mostly in legacy builds. |
| webpack → Rollup (libraries) | webpack's output was bloated with runtime wrappers, bad for publishing libraries. | ES-module-first, scope hoisting, tree shaking. | npm; it later became the de facto *plugin API* that Vite and Rolldown adopted. | Library authors adopted it because the output was smaller. | webpack kept apps; Rollup took libraries. They split the niches. |
| → Parcel | webpack config fatigue. | Zero config. | Existing source trees. | Fast early buzz; it never displaced webpack (no data). | Still maintained; niche. |
| → esbuild | "10–100x slower than they could be."\[1\] | Go native binary, parallel parse/print, few AST passes, deliberately limited scope.\[22\]\[23\] | ESM + CJS, TS/JSX out of the box; a simple plugin API but *not* webpack's. | Became infrastructure inside Vite and other tools rather than a direct app bundler; Wallace said he didn't "personally want to run a large open-source project."\[24\] | Very much alive as an engine, but Vite 8 replaced it with Oxc/Rolldown.\[25\] |
| → Vite | Even fast bundlers re-bundle on every edit in dev. | Native ESM dev server (esbuild pre-bundling deps), Rollup for prod. | The Rollup plugin API; framework-agnostic. | Framework templates switched defaults (interpretation). | Two-engine design, later replaced by Rolldown in Vite 8.\[25\] |
| → Rspack / Rolldown / Turbopack | Vite's dev/prod engine split caused parity bugs; webpack shops wanted speed without migrating. | Rust rewrites. Rolldown is a single engine for dev and prod; Rspack reimplements webpack; Turbopack is Next.js-specific. | Rolldown: Rollup plugin API; Rspack: webpack config/loaders (from my knowledge of the project; not separately sourced here). | Vite 8 stable March 12, 2026. The Vite team cites Linear going "from 46 seconds to 6 seconds." The rollout used an opt-in preview package, then a beta, then the default.\[3\]\[26\] | Rollup and esbuild remain standalone projects, thanked in the Vite 8 post.\[3\] |

**Lesson from bundlers:** The most successful move was *becoming the engine inside someone else's tool* (esbuild in Vite) or *reimplementing someone's plugin API in a faster language* (Rolldown for Rollup). Vite 8's staged rollout (separate package, then beta, then default, with deprecation aliases for `rollupOptions`) is the template for replacing an engine without breaking users.\[3\]\[26\]

### Package managers

- **npm → Yarn (2016).** *Complaint:* Facebook "ran into problems with consistency, security, and performance," including non-deterministic installs and install-time code execution.\[4\] *Approach:* lockfile, deterministic install algorithm, parallel fetches, offline cache. *Compatibility:* same registry, same `package.json`, same `node_modules` layout.\[27\] *Speed of change:* Facebook reported installs dropping by "an order of magnitude."\[4\] *Survival:* npm absorbed the ideas: `package-lock.json` arrived in npm 5 in 2017, per secondary sources.\[28\] Yarn then split into Classic and Berry (2020),\[29\] and Berry's Plug'n'Play broke the `node_modules` assumption. Even in 2026, Vite 8's migration notes list Yarn PnP incompatibility with Rolldown's resolver as a failure mode.\[30\] A tool that breaks the filesystem contract pays for it for years.
- **→ pnpm.** *Complaint:* duplicated disk use and phantom dependencies from hoisting.\[31\] *Approach:* content-addressable store, hard links, strict symlinked `node_modules`.\[27\] *Compatibility:* it kept a `node_modules` directory, so most tools keep working, unlike PnP.
- **→ Bun.** *Approach:* runtime, package manager, bundler and test runner in one binary, with `bun build --compile` for single executables (shipped in 0.6.0 in response to a 2022 issue).\[32\] *Survival so far:* npm, pnpm and Yarn are all still in use. Anthropic announced on December 2, 2025 that it was acquiring Bun, which remains MIT-licensed.

### Runners: ts-node → tsx → Node built-in type stripping

- *Complaint about ts-node:* slow (it ran the TypeScript compiler) and fragile ESM support. *tsx* swapped in esbuild transforms: fast, no type checking.
- *Node built-in:* Marco Ippolito's PR introduced type stripping in v22.6.0. It replaces types with whitespace so source maps are unnecessary, ignores `tsconfig.json`, and rejects non-erasable syntax. TypeScript 5.8 added `erasableSyntaxOnly` in cooperation. Unflagged in 22.18.0; Stable in 25.2.0.\[5\]\[6\]
- *Survival:* tsx and ts-node keep the niches type stripping doesn't cover: enums, path aliases, and anything under `node_modules` (`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`).\[33\] **Lesson:** the runtime absorbed the 80% case by defining a *restricted subset* and getting the language team to bless it. The PEP 723 + `uv run` path is Python's closest analogue.

### Linters/formatters: JSHint → ESLint → Prettier → Biome/oxc

- JSHint → ESLint: the complaint was a fixed rule set. ESLint's answer was pluggable rules over an AST, and its plugin ecosystem became its moat.
- Prettier: ended style arguments by being opinionated, with minimal options.
- Biome (a 2023 fork of the abandoned Rome) won by targeting *Prettier output compatibility* as a metric. It passed 95% (the "Prettier challenge") and then over 97% compatibility, while also shipping a linter. Biome 2.0 (June 2025) added type-aware linting without the TypeScript compiler, plus plugins.\[34\]\[35\] oxc/oxlint augments ESLint rather than replacing it.
- *Survival:* ESLint and Prettier remain dominant where custom plugins matter. Rust tools lack the plugin breadth. Biome's own v2.1 post says its type inference catches about 85% of the cases its noFloatingPromises rule should detect, up from about 75% at 2.0; that figure covers one rule, not typescript-eslint as a whole.

---

## Part 2: How Python Tool Categories Evolved

### Installers and environments

| Transition | Complaint | Approach | Compatibility | Enabling standard | Fate |
|---|---|---|---|---|---|
| easy_install → pip (2008) | No uninstall, eggs, opaque installs. | Requirements files, uninstall, source installs. | PyPI, setuptools. | Later: PEP 427 wheels (2012), PEP 440 versions, PEP 508 markers. | easy_install was removed from setuptools. |
| → virtualenv / venv | Global site-packages collisions. | Per-project environments. | Python stays unchanged. | PEP 405 (venv in stdlib, 3.3). | Both live; venv is the default. |
| → pip-tools | No lock files. | `pip-compile` pins the full tree. | requirements.txt format. | none | Still at 9% in the 2024 survey.\[19\] |
| → Pipenv (2017) | Juggling pip + virtualenv + requirements files. | Pipfile + Pipfile.lock + venv in one CLI. | pip underneath. | none; Pipfile was never standardized into pip. | Its README called it "the officially recommended Python packaging tool from Python.org" from 2017-08-31 until 2018-05-19. No release from November 2018 to May 2020.\[36\] 8% in the 2024 survey.\[19\] |
| → Poetry | Pipenv couldn't build/publish libraries; slow resolution; instability. | Resolver + lock + build + publish; `pyproject.toml`. | Own `[tool.poetry]` metadata at first. | PEP 517/518; PEP 621 support came later in Poetry 2.x. | 20% in the 2024 survey.\[19\] |
| → PDM / Hatch | Poetry's non-standard metadata. | PEP 621-native; Hatch adds env matrices; PDM briefly backed PEP 582. | Standard metadata. | PEP 621, PEP 660 (editable installs). | Active, niche. PDM was first to offer opt-in `pylock.toml`.\[37\] |
| → uv (Feb 2024) | Slowness, plus the need for five tools (pip, pip-tools, virtualenv, pyenv, pipx/Poetry). | Rust; `uv pip` as a pip-compatible interface first, then projects, Python installs via python-build-standalone, `uv run` with PEP 723. | pip CLI, requirements.txt, PEP 621, PEP 735, PEP 723. | PEP 723 (final January 8, 2024), PEP 735 (accepted October 10, 2024),\[38\]\[39\] PEP 751 (March 31, 2025).\[37\] | uv hit 12% dependency-management share in its first survey year; the report calls it "a notable achievement".\[19\] |

**Stalled transitions:**
- *Lock files.* PEP 665 (2021) failed. PEP 751 needed three drafts "to get consensus among uv, Poetry, and PDM."\[37\] In uv it remains an export/install format; Poetry had not shipped support as of April 2026 (per pydevtools).\[40\]
- *`__pypackages__`.* PEP 582 was rejected by the Steering Council in March 2023.\[41\] stevapple's comment on the uv bundling issue notes that a non-self-contained bundle "is basically re-implementing PEP-582."\[42\]

### Build systems: distutils → setuptools → PEP 517 backends
- *Complaint:* `setup.py` is arbitrary code, and setuptools was implicitly required to even read metadata.
- *Approach:* PEP 518 (`[build-system]` requires) and PEP 517 (the backend hook API) decoupled frontends from backends. This made flit, hatchling, pdm-backend, poetry-core, maturin, scikit-build-core and `uv_build` possible. PEP 621 standardized metadata; PEP 660 standardized editable installs.
- *Survival:* setuptools absorbed distutils. distutils itself was removed from the stdlib in 3.12 (PEP 632). setuptools is still the default for C-extension-heavy legacy projects.
- *Live friction:* uv's own backend lacks single-file modules (#16766, #17205)\[43\]\[44\] and scm-based dynamic versions (#14037, labelled `needs-decision`; it cites "setuptools-scm – 20k+ references").\[45\] PEP 517 made new backends *possible*. It did not make them *complete*.

### Freezers: py2exe → cx_Freeze → PyInstaller → PyOxidizer → PyApp/scie
- py2exe was Windows-only. cx_Freeze and PyInstaller went cross-platform with import-graph analysis plus hooks for packages that do dynamic imports. PyInstaller's hook library is its moat. `--onefile` works by extracting to a temp dir at runtime.\[46\]
- **PyOxidizer (2019).** *Complaint:* Szorc built it partly because of "the poor experience I had with Python application packaging and distribution through the Mercurial Project."\[47\] *Approach:* static-linked interpreter, in-memory imports via `oxidized_importer`, Starlark config. *Problems:* in-memory loading breaks code that relies on `__file__`, so it later had to add a "files mode" "for maximum compatibility." Version 0.8 made breaking Starlark config changes.\[48\]\[49\] Cross-compiling and numpy-class packages remained gaps.\[50\]\[51\] *Fate:* neglected from January 2023; "possibly dead" (March 2024).\[14\]\[15\]
- **What survived:** python-build-standalone (now Astral's) became the portable-interpreter substrate.\[16\] Its successors are PyApp (a Rust launcher that bootstraps an interpreter and installs a wheel) and scie/science, which PEX uses for `--scie eager|lazy`.\[18\]\[52\] **Interpretation:** the durable idea was *ship a relocatable CPython plus standard wheels*, not *a custom importer*.

### Bundlers: pex → zipapp/PEP 441 → shiv → ?
- pex (Twitter, later Pants) = a zip with `__main__.py` bootstrap that builds an isolated environment. PEP 441 (Python 3.5) put `zipapp` in the stdlib but provides no dependency handling. shiv (LinkedIn) = zipapp plus site-packages extracted to a cache on first run, to fix pex's start-up cost and native-extension issues.
- **What came after:** (1) *PEX with scie*: "a native executable that contains both a Python interpreter and your PEX'd code," using python-build-standalone.\[53\] (2) *PEP 723 + `uv run`*, which removed the need to bundle dependencies for single-file scripts: the artifact is the script, and dependencies resolve at run time. (3) *Docker images* as the default deployment unit (interpretation). No esbuild-style *source-level* bundler has won. stickytape's own author called its approach "all one big hack" that "writes out all of its dependencies to temporary files." Its README now steers users to zipapp or PyInstaller.\[54\]\[55\]\[56\]
- **Demand evidence:** uv issue #12035 asks for `uv bundle handler.py -o bundled.py`, a "tree-shaken" single file for AWS Lambda, explicitly modelled on TypeScript bundlers.\[42\] #5802 (`uv bundle` à la PyInstaller) is labelled "wish – Not on the immediate roadmap."\[57\] #13503 (PyInstaller output) was "closed as not planned."\[58\] **The incumbent package manager has declined this category, which is the opening.**

### Linters/formatters: pylint/flake8/Black → Ruff
- *Complaint:* speed, plus orchestrating Flake8 + dozens of plugins + isort + pyupgrade + Black. *Approach:* Rust; plugins reimplemented natively rather than loaded. *Compatibility:* Flake8 rule codes and `noqa`, Black-compatible formatting. *Cost:* "Unlike Flake8 and others, Ruff doesn't support plugins," a trade-off Marsh acknowledged at launch.\[7\] *Fate:* Flake8, pylint and Black persist where custom plugins or pylint's deeper inference matter (interpretation; no share data found).

### Type checkers
- mypy (reference implementation, Python/mypyc) → pyright (Microsoft, TypeScript, LSP-first via Pylance) → pytype (Google) and Pyre (Meta, OCaml) as company-scale checkers.
- **New wave (Rust):** Pyrefly (Meta, alpha May 2025, beta November 2025) replaces Pyre because "the need for an extensible type checker that can bring code navigation, checking at scale, and exporting types to other services drove us to start over."\[11\]\[12\]\[59\] ty (Astral, beta December 2025) is built around incrementality and claims a 4.7 ms re-check after editing a PyTorch file (80x faster than Pyright).\[10\]\[60\] Both added migration helpers (`pyrefly init` reads `mypy.ini`).\[61\]
- *Enabling standard:* the shared typing spec, PEP 484 and successors (Pyrefly cites it explicitly).\[11\] *Caveat:* ty is still on 0.0.x versioning with "no stable API." Reviewers note its inference is less sophisticated than Pyright's.\[62\]\[63\] Speed has arrived before conformance.

---

## Part 3: What Python Users Are Still Unhappy With (2025–2026)

| Complaint | Who has it | Evidence | Fix in progress? |
|---|---|---|---|
| **Fragmentation / too many tools** | Everyone. The PSF packaging survey found "most users found the landscape too complex to navigate… An overwhelming majority of users recommended a more unified experience."\[64\] | PSF Packaging Strategy discussion (2023) | Partly de facto via uv; no PyPA "one tool." |
| **No standard task runner** | Rye refugees, Node/Poetry users | uv #5903 "Using `uv run` as a task runner" is open and on uv's popular-requests list; duplicates #8519, #7203, #10211; discuss.python.org "standardize project development scripts" thread\[65\]\[66\]\[67\]\[68\]\[69\]\[70\] | PR #9955 proposed; no PEP. A Poe the Poet maintainer doubts a single schema could work.\[71\]\[72\] |
| **Deployment / single-artifact bundling** | Serverless and CLI authors | uv #12035, #5802 ("wish"), #13503 ("not planned")\[57\]\[58\] | Not in uv. PEX `--scie`, PyApp and PyInstaller fill parts of it.\[18\]\[46\] |
| **GPU / hardware-specific wheels** | ML users (PyTorch, CUDA) | Custom index URLs and package-name suffixes\[73\] | PEP 817 (draft, December 2025) and PEP 825; experimental variant-enabled uv build (August 2025)\[74\]\[75\] |
| **Conda interop** | Scientific users | uv #1703: "will always have to sit alongside conda" ("wish")\[76\] | No |
| **Dynamic/scm versions in uv_build; lock churn** | Library maintainers | #14037, #9233 ("closed as not planned"), #20123 (June 2026)\[45\]\[77\]\[78\] | Undecided |
| **Lock-file portability** | Teams mixing tools | uv keeps `uv.lock` primary; Poetry lacks `pylock.toml`\[40\]\[79\] | Slowly |
| **Vendor concentration** | Risk-averse orgs | OpenAI–Astral deal (March 2026); commentary flags "supply chain concentration"\[80\] | The tools are MIT/Apache and forkable; no governance plan published\[80\] |
| **Type checker speed vs. accuracy** | Large codebases | ty and Pyrefly are both pre-stable\[62\]\[81\] | Active development |

Data caveat: I could not retrieve uv issues sorted by reaction count, so the table cites uv's own popular-requests list rather than exact counts. I found no published 2025 PSF/JetBrains survey results.

---

## Part 4: What Other Ecosystems Do Best

| Ecosystem | Best-in-class idea | Mechanism | Python feasibility / obstacle | Tried in Python? |
|---|---|---|---|---|
| **Go** | Static single binary; trivial cross-compilation | Compiler links everything; `GOOS/GOARCH` | Hard: CPython plus C extensions plus dynamic imports. The partial answer is a bundled interpreter. | PyOxidizer (stalled), Nuitka, PEX scie, PyApp |
| **Rust/Cargo** | One tool for build/test/run/publish; lockfile; workspaces | Single manifest, single vendor | Largely achieved by uv (interpretation) | uv, Rye (absorbed into uv) |
| **Zig** | Cross-compiling C toolchain shipped with the compiler | Bundled libc headers and clang | Could ease sdist builds for cross-targets; cultural/infra obstacles | No mainstream adoption found |
| **Julia** | BinaryBuilder/JLL: binary deps as versioned packages | Cross-compiled artifacts in the registry | Analogous to wheels plus the PEP 817 variants gap | conda-forge (partially); WheelNext |
| **Elixir** | Mix releases: self-contained runtime plus app | ERTS bundled, config at boot | Feasible with python-build-standalone | PEX scie, PyApp |
| **Java** | Fat JARs/Shade; JBang single-file scripts with deps; GraalVM native-image | Classpath zip; relocation; closed-world AOT | Fat JAR ≈ PEX/shiv; Shade-style *relocation* (renaming vendored packages) is unsolved in Python; GraalVM needs a closed world Python lacks | pex/shiv; pip's manual vendoring |
| **.NET** | `dotnet watch`; trimming; file-based apps (`dotnet run app.cs` with `#:package` directives)\[82\] | IL analysis for trimming; virtual project per file\[83\] | File-based apps ≈ PEP 723 + `uv run` (done). Trimming conflicts with Python's dynamism. | PEP 723 |
| **Deno** | `deno compile`; URL imports; permissions | Runtime embeds code | Runtime-level sandboxing unlikely in CPython | No |
| **Bun** | One binary for runtime + pm + bundler + test; `bun build --compile`\[32\] | Runtime vendor owns the toolchain | Python has no comparable runtime vendor | uv is the closest |
| **Dart / Swift PM** | Toolchain-integrated package resolution and AOT | Official SDK ships the tools | Requires CPython to bless a tool | No |

Notes: The Go, Zig, Julia, Elixir, Java, Deno, Dart and Swift entries rest on general knowledge of those toolchains rather than sources fetched for this report. Treat them as interpretation.

---

## Part 5: Lessons

### 1. Patterns in how new tools win
1. **Make the speedup big enough to quote in a headline.** "10–100x" (esbuild, Ruff), "minutes to seconds" (Yarn), "46s to 6s" (Rolldown at Linear), "10–60x" (ty).\[1\]\[4\]\[10\]\[26\] Every winner put a number in its launch post.
2. **Keep the incumbent's interface.** Same registry (Yarn), same plugin API (Rolldown), same output (Biome's 97% Prettier compatibility), same rule codes (Ruff), same CLI (`uv pip`), same metadata standard (PDM, Hatch, uv).
3. **Bundle adjacent tools.** Ruff replaced Flake8 plus about ten other tools;\[84\] uv replaced pip, pip-tools, virtualenv, pyenv and pipx; Bun and Biome did the same in JS.
4. **Ride a standard, or get absorbed into one.** Type stripping needed TypeScript's `erasableSyntaxOnly`. uv's script mode needed PEP 723.
5. **Roll out in stages.** Vite: `rolldown-vite` preview, then beta, then default, with deprecation aliases.\[3\]\[26\]

**How tools lost:** they broke the filesystem/runtime contract (Yarn PnP; PyOxidizer's in-memory imports breaking `__file__`), overclaimed authority and then went quiet (Pipenv), depended on a single maintainer (PyOxidizer, Rome), or demanded a new config language without matching value (PyOxidizer's Starlark).

### 2. Ranked ideas worth bringing to Python

| Rank | Idea | Value | Feasibility | Main obstacle |
|---|---|---|---|---|
| 1 | Single deployable artifact from a uv project (PEX/zipapp + optional embedded interpreter) | High | High (python-build-standalone exists) | uv has declined it; C-extension platform matrix |
| 2 | Standard task runner in pyproject | High | Medium | No consensus schema |
| 3 | Hardware-aware wheels (PEP 817/825) | Very high for ML | Medium | Draft PEPs; provider-plugin security |
| 4 | Shade-style dependency relocation for vendoring | Medium | Low–medium | Absolute imports, C extensions |
| 5 | Zig-style cross-compiling toolchain for sdists | Medium | Low | C toolchain politics |
| 6 | Tree-shaking/trimming | Low–medium | Low | Dynamic imports, `importlib`, entry points |

### 3. Implications for a Python esbuild-style bundler

**Lead with this complaint:** "I have a uv project and want one artifact I can copy to Lambda, a container or a server, built in under a second, reproducibly from my lock file." That is the #12035 use case, which uv's maintainers have not taken on.

**Be compatible with:**
- Inputs: `pyproject.toml` (PEP 621), `uv.lock` and `pylock.toml` (PEP 751), PEP 723 script headers, PEP 735 dependency groups, and wheels as the unit of third-party code (never re-parse site-packages source).
- Outputs: PEP 441 zipapp/PEX-compatible archives first, then an optional scie-style embedded python-build-standalone interpreter, plus a Lambda-zip layout.
- Ecosystem: PyInstaller's hook knowledge for dynamic imports, so you don't rebuild that library yourself.

**Design choices:**
- Do a fast Rust/Go import-graph scan only to *prune* or *warn*. Do not inline. stevapple's circular-lazy-import example in #12035 shows why inlining is unsound in Python.\[42\]
- Keep real files on disk or in a cache (shiv-style extraction) by default, so `__file__`, `importlib.resources` and native `.so` files keep working.
- Make reproducibility (hash-pinned from the lock) and a quotable cold-build benchmark the headline features.

**Mistakes to avoid:**
- *stickytape:* regex-based import detection plus temp-file unpacking.\[55\]\[85\] Don't rewrite source.
- *PyOxidizer:* a custom importer, a bespoke config language (Starlark) with breaking changes, and a single maintainer. Use TOML in `[tool.yourtool]`, stay zero-config by default, and plan governance early.
- *Pipenv:* don't claim official status; ship a steady release cadence; keep an escape hatch to standard formats.
- *esbuild's caution:* stay narrow (the sweet spot is deployable backend/CLI artifacts) and let others embed you as an engine.

## Caveats
- I found no adoption numbers beyond the PSF/JetBrains and Stack Overflow surveys. Statements about why particular transitions sped up are my interpretation.
- I could not verify uv issue reaction counts or the closing status of the OpenAI–Astral deal.
- The webpack/Rollup/Parcel, Rspack/Turbopack, Go/Zig/Julia/Elixir/Java/Deno/Dart/Swift and distutils/PEP-numbering details rest partly on background knowledge rather than sources fetched for this report.
- Where I could, I replaced secondary-source figures with primary ones: the Rolldown 1.0 date comes from VoidZero's announcement, and Biome's type-inference coverage comes from Biome's v2.1 post.

## Sources

1. [GitHub - evanw/esbuild: An extremely fast bundler for the web · GitHub](https://github.com/evanw/esbuild)
2. [esbuild faster go js bundler](https://www.infoq.com/news/2020/06/esbuild-faster-go-js-bundler/)
3. [Vite Release Notes - April 2026 Latest Updates - Releasebot](https://releasebot.io/updates/vite)
4. [Yarn: A new package manager for JavaScript - Engineering at Meta](https://engineering.fb.com/2016/10/11/web/yarn-a-new-package-manager-for-javascript/)
5. [Modules: TypeScript](https://nodejs.org/api/typescript.html)
6. [How a Summer in Abruzzo Helped Bring Type Stripping to Node.js](https://satanacchio.hashnode.dev/the-summer-i-shipped-type-stripping)
7. [Python tooling could be much, much faster](https://notes.crmarsh.com/python-tooling-could-be-much-much-faster)
8. [pypi.org](https://pypi.org/project/ruff/0.0.39/)
9. [pypi.org](https://pypi.org/project/ruff/0.6.5/)
10. [ty: An extremely fast Python type checker and LSP](https://simonwillison.net/2025/Dec/16/ty/)
11. [Introducing Pyrefly: A new type checker and IDE experience for Python - Engineering at Meta](https://engineering.fb.com/2025/05/15/developer-tools/introducing-pyrefly-a-new-type-checker-and-ide-experience-for-python/)
12. [meta pyrefly python typechecker](https://www.infoq.com/news/2025/05/meta-pyrefly-python-typechecker)
13. [OpenAI Just Acquired Astral? What It Means for uv, Ruff, and Python](https://www.itechguides.com/openai-just-acquired-astral-what-the-deal-means-for-uv-ruff-and-every-python-developer/)
14. [Project status update · Issue #741 · indygreg/PyOxidizer](https://github.com/indygreg/PyOxidizer/issues/741)
15. [Pex: A tool for generating .pex (Python EXecutable) files, lock files and venvs](https://news.ycombinator.com/item?id=42148220)
16. [A new home for python-build-standalone - Astral](https://astral.sh/blog/python-build-standalone)
17. [pex\_binary](https://www.pantsbuild.org/dev/reference/targets/pex_binary)
18. [PEX with included Python interpreter - Pex Docs (v2.102.0)](https://docs.pex-tool.org/scie.html)
19. [Python Developers Survey 2024 Results](https://lp.jetbrains.com/python-developers-survey-2024/)
20. [Python Software Foundation News: The 2024 Python Developer Survey Results are here!](https://pyfound.blogspot.com/2025/08/the-2024-python-developer-survey.html)
21. [2025 Stack Overflow Developer Survey](https://survey.stackoverflow.co/2025/)
22. [A Deep Dive into esbuild’s Architecture and Speed](https://codedamn.com/news/javascript/a-deep-dive-into-esbuild-s-architecture-and-speed)
23. [esbuild Architecture: How is it So Fast?](https://feature-sliced.design/blog/esbuild-performance-explained)
24. [DEV Community](https://dev.to/bnevilleoneill/fast-javascript-bundling-with-esbuild-f53)
25. [Vite 8 Swapped Your Bundler: Three Config Keys That Break Silently](https://medium.com/@ahmadfiazjan/vite-8-swapped-your-bundler-three-config-keys-that-break-silently-46ebf2b7b99f)
26. [Migrating to Vite 8 + Rolldown - Certificates.dev](https://certificates.dev/blog/migrating-to-vite-8-rolldown)
27. [NPM & Yarn: The Complete Package Management Guide for 2026](https://devtoolbox.dedyn.io/blog/npm-yarn-complete-guide)
28. [Yarn vs npm 2026: 3.7x Faster, 85% Less Disk - Tech Insider](https://tech-insider.org/yarn-vs-npm-2026/)
29. [Yarn (package manager)](<https://en.wikipedia.org/wiki/Yarn_(package_manager)>)
30. [Vite 8 + Rolldown Migration Guide: Cut Build Times by 87% in 2026](https://www.nexgismo.com/blog/vite-8-rolldown-migration-guide-2026)
31. [JavaScript package managers compared: npm, Yarn, or pnpm? - LogRocket Blog](https://blog.logrocket.com/javascript-package-managers-compared/)
32. [github.com](https://github.com/oven-sh/bun/issues/441)
33. [Marco Ippolito on X: "Node.js v22.18.0 is out 🎉 Type stripping is enabled by default 🔥🔥🔥🔥 You can just run \`node file.ts\` without \`--experimental-strip-types\` flag. https://t.co/jQkpHrr2Xw" / X](https://x.com/satanacchio/status/1951146917766803461)
34. [Emanuele Stoppa](https://biomejs.dev/blog/authors/emanuele-stoppa/)
35. [Biome: Replace ESLint + Prettier With One Tool - DEV Community](https://dev.to/vishdevwork/biome-replace-eslint-prettier-with-one-tool-3gaa)
36. [Pipenv: promises a lot, delivers very little](https://chriswarrick.com/blog/2018/07/17/pipenv-promises-a-lot-delivers-very-little/)
37. [Why it took 4 years to get a lock files specification](https://snarky.ca/why-it-took-4-years-to-get-a-lock-files-specification/)
38. [peps/peps/pep-0723.rst at main · python/peps](https://github.com/python/peps/blob/main/peps/pep-0723.rst)
39. [PEP 735: Dependency Groups in pyproject.toml](https://discuss.python.org/t/pep-735-dependency-groups-in-pyproject-toml/39233/312)
40. [What is PEP 751?](https://pydevtools.com/handbook/explanation/what-is-pep-751/)
41. [steering-council/updates/2023-03-steering-council-update.md at main · python/steering-council](https://github.com/python/steering-council/blob/main/updates/2023-03-steering-council-update.md)
42. [Feature Request: Production Bundling for Python – A Single File Deployment Approach](https://github.com/astral-sh/uv/issues/12035)
43. [Please add support for single-file packages · Issue #17205 · astral-sh/uv](https://github.com/astral-sh/uv/issues/17205)
44. [uv build-backend does not allow building a single-module package (module-only, no package directory) · Issue #16766 · astral-sh/uv](https://github.com/astral-sh/uv/issues/16766)
45. [Support Git scm-based versioning in \`uv\` build backend · Issue #14037 · astral-sh/uv](https://github.com/astral-sh/uv/issues/14037)
46. [github.com](https://github.com/jabbalaci/pythonexe)
47. [Python, PyOxidizer - Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/page/4/)
48. [categories: Personal, PyOxidizer - Gregory Szorc's](https://gregoryszorc.com/blog/category/pyoxidizer/)
49. [Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/2020/10/18/announcing-the-0.9-release-of-pyoxidizer/)
50. [Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/2020/10/12/announcing-the-0.8-release-of-pyoxidizer/)
51. [Project Status — PyOxidizer 0.19.0 documentation](https://gregoryszorc.com/docs/pyoxidizer/0.19.0/pyoxidizer_status.html)
52. [GitHub - edaniels/uv-pex-example · GitHub](https://github.com/edaniels/uv-pex-example)
53. [Version 2.97 - Pex](https://docs.pex-tool.org/_static/pex.pdf)
54. [GitHub - mwilliamson/stickytape: Convert Python packages into a single script](https://github.com/mwilliamson/stickytape)
55. [Convert Python packages to single-file Python scripts with stickytape](https://mike.zwobble.org/2012/10/convert-python-packages-to-single-file-python-scripts-with-stickytape/)
56. [pypi.org](https://pypi.org/project/stickytape/)
57. [Suggestion: \`uv bundle\`, \`uv build --release\` or similar to create a contained executable a la pyinstaller, py2exe · Issue #5802 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5802)
58. [Support PyInstaller binary packaging output to dist/ directory · Issue #13503 · astral-sh/uv](https://github.com/astral-sh/uv/issues/13503)
59. [Meta Open Sources Pyrefly Beta With 95% Faster Python Type-Checking - Open Source For You](https://www.opensourceforu.com/2025/11/meta-open-sources-pyrefly-beta-with-95-faster-python-type-checking/)
60. [Python type checker ty now in beta](https://www.infoworld.com/article/4108979/python-type-checker-ty-now-in-beta.html)
61. [Why You NEED This New Python Tool](https://daily.dev/posts/why-you-need-this-new-python-tool-slaxyym9p)
62. [GitHub - astral-sh/ty: An extremely fast Python type checker and language server, written in Rust. · GitHub](https://github.com/astral-sh/ty)
63. [Astral ty Python Type Checker: 60x Faster Than Mypy](https://byteiota.com/astral-ty-python-type-checker-60x-faster-than-mypy/)
64. [Python Software Foundation News: Python Packaging Strategy Discussion Summary - Part 1](https://pyfound.blogspot.com/2023/02/python-packaging-strategy-discussion.html)
65. [uv run support for \`tool.uv.scripts\` · Issue #8519 · astral-sh/uv](https://github.com/astral-sh/uv/issues/8519)
66. [Idea: Introduce/standardize project development scripts - Standards - Discussions on Python.org](https://discuss.python.org/t/idea-introduce-standardize-project-development-scripts/67194)
67. [Using \`uv run\` as a task runner · Issue #5903 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5903)
68. [Before posting in the issue tracker · Issue #9452 · astral-sh/uv](https://github.com/astral-sh/uv/issues/9452)
69. [Task runner plugin system · Issue #10211 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10211)
70. [Custom task runner · Issue #7203 · astral-sh/uv](https://github.com/astral-sh/uv/issues/7203)
71. [A new PEP to specify dev scripts and/or dev scripts providers in pyproject.toml - #7 by natn - Packaging - Discussions on Python.org](https://discuss.python.org/t/a-new-pep-to-specify-dev-scripts-and-or-dev-scripts-providers-in-pyproject-toml/11457/7)
72. [Add minimal Python API and task runner (#5903) by chrisrodrigue · Pull Request #9955 · astral-sh/uv](https://github.com/astral-sh/uv/pull/9955/files)
73. [Wheel: Python Binary Distribution Format](https://pydevtools.com/handbook/reference/wheel/)
74. [An experimental, variant-enabled build of uv - Astral](https://astral.sh/blog/wheel-variants)
75. [Why Installing GPU Python Packages Is So Complicated](https://pydevtools.com/handbook/explanation/installing-cuda-python-packages/)
76. [Add support for managing Conda environments and packages · Issue #1703 · astral-sh/uv](https://github.com/astral-sh/uv/issues/1703)
77. [uv lock --locked and dynamic versioning collide. · Issue #9233 · astral-sh/uv](https://github.com/astral-sh/uv/issues/9233)
78. [Allow \`uv version --bump\` to handle dynamic versions · Issue #20123 · astral-sh/uv](https://github.com/astral-sh/uv/issues/20123)
79. [How to create a pylock.toml lockfile](https://pydevtools.com/handbook/how-to/how-to-create-a-pylock-toml-lockfile/)
80. [OpenAI Acquires Astral: Is uv Still Worth Using? · Technical news about AI, coding and all](https://dasroot.net/posts/2026/06/openai-acquires-astral-uv-vendor-lock-in-supply-chain-risk/)
81. [ty: Astral's New Python Type Checker Released](https://pydevtools.com/blog/ty-beta/)
82. [Announcing dotnet run app.cs - A simpler way to start with C# and .NET 10 - .NET Blog](https://devblogs.microsoft.com/dotnet/announcing-dotnet-run-app/)
83. [Exploring C# File-based Apps in .NET 10](https://milanjovanovic.tech/blog/exploring-csharp-file-based-apps-in-dotnet-10)
84. [github.com](https://github.com/csko/ruff)
85. [pypi.org](https://pypi.org/project/stickytape/0.1.11/)
