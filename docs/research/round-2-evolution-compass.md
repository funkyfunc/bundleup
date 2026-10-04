# How Developer Tools Replaced Each Other in JavaScript and Python, and What Python's Next Bundler Should Learn

New developer tools have won mainly by being much faster while staying compatible with what users already had (the old registry, config formats, plugin APIs and command-line habits), and the next big gap in Python is turning a locked project into one runnable artifact. The past 18 months add evidence: Vite 8 replaced esbuild and Rollup with Rolldown while keeping the Rollup plugin API. Node absorbed ts-node and tsx's job through built-in type stripping. uv absorbed most of pip, pip-tools, virtualenv, pyenv and pipx. Yet uv's own tracker still lists "`uv bundle`… to create a contained executable" as "Not on the immediate roadmap."

## TL;DR

- **Why tools win:** In both ecosystems, winners delivered roughly a 10–100× speedup and could be dropped in on day one. Yarn kept the npm registry. esbuild and Rolldown kept the familiar CLI and plugin shapes. Ruff copied flake8 rule codes and Black's output. uv shipped a `uv pip` interface first. Winners then combined several tools into one. Tools lost when they broke compatibility on purpose (Yarn 2 Plug'n'Play by default), when they were slow and unreliable (Pipenv), or when one maintainer could not keep up (PyOxidizer).
- **What still hurts in Python:** The biggest open complaints are no standard way to ship an app as one file (uv #5802, PEP 711 stalled in Draft since April 2023), no task runner (uv #5903), no `uv upgrade` (uv #6794), non-Python and GPU dependencies (PEP 817/825 still Draft), and governance worries now that OpenAI has announced it is acquiring Astral (19 March 2026; secondary coverage reports the deal as pending regulatory approval, with the Astral team joining Codex once it closes).
- **What a bundler should do:** Lead with "one locked project in, one artifact out per target, and it starts fast." Read `pyproject.toml`, `uv.lock`/`pylock.toml` and PEP 723 scripts. Bundle python-build-standalone interpreters. Use only prebuilt wheels so you can build for other targets. Keep the import system standard; PyOxidizer's custom importer, stickytape's guessing at imports, and Pipenv's slowness and single point of failure are the three traps to avoid.

*Note on scope: the attached snapshot report was not accessible in this environment, so current tools are described only as much as each transition requires. "Documented" marks sourced history; "Interpretation" marks my analysis.*

---

## Key Findings

1. **Compatibility came before novelty in every successful switch.** Yarn (2016) was "a drop-in replacement for the npm client" on the same registry. uv (Feb 2024) was "optimized for adoption" around "the pip and pip-tools APIs… usable by existing projects with zero configuration." Rolldown "supports the same plugin API as Rollup and Vite." Ruff aimed for "drop-in parity with Flake8, isort, and Black." Biome's formatter won adoption by passing more than 95% of Prettier's own test suite.
2. **Speed got people to try a tool; combining tools kept them.** esbuild set out to "reset the expectations of the community for what it means for a JavaScript build tool to be fast." Ruff showed a 150× speedup over Flake8 on CPython. But Ruff's creator explicitly called the lack of plugins a feature, because the value was "the unification of multiple tools," and uv's second launch (Aug 2024) positioned it as "Cargo, for Python."
3. **Python switches mostly waited on standards; JavaScript switches mostly did not.** PEP 517/518/621 made the build-backend market possible. PEP 723 made `uv run script.py` possible. PEP 751 (accepted 31 Mar 2025) finally standardized a lockfile after PEP 665 failed. The categories still stuck (interpreter distribution via PEP 711, hardware-specific wheels via PEP 817/825, app bundles with no PEP at all) are the ones where no standard exists.
4. **Old tools usually find a niche rather than disappear.** webpack lives on through Rspack's compatibility layer. Rollup's API lives on inside Rolldown. npm adopted Yarn's lockfile idea. pip added `pip lock`. Prettier used the Biome bounty to fix its own performance. Pipenv and PyInstaller are still maintained. Clean deaths are rare (easy_install, distutils, PyOxidizer in practice).
5. **Python's bundler/freezer category has never produced a clear winner.** Each generation fixed one problem (PEX: isolation; shiv: startup cost; PyOxidizer: in-memory loading; PyApp: avoid "build sorcery") and paid for it somewhere else. No one has combined lockfile-driven, cross-target, standard-import, single-artifact output. uv has explicitly deferred it.

---

## Part 1: How JavaScript Tools Evolved

### 1.1 Bundlers

| Transition | Complaint (documented) | Approach | Compatibility kept | Speed of change | Fate of the old tool |
|---|---|---|---|---|---|
| Browserify → webpack | Browserify brought `require()` to the browser but treated everything else (CSS, images, code splitting) as add-ons | One dependency graph for every asset type, loaders, code splitting, hot module replacement (HMR) | CommonJS and AMD module formats | Gradual, then won through React-era starter templates | Browserify became a niche tool |
| webpack → Rollup (libraries) | Bundled output was bulky, with a wrapper around every module | Native ES modules and "tree-shaking" (dropping unused code) | npm packages, CommonJS through a plugin | Became the default for library authors | Coexisted with webpack; Rollup's plugin API later became the shared standard |
| → Parcel | webpack configuration was heavy | Zero config, multi-core | Standard entry points such as HTML | Strong interest, smaller share | Still exists, Rust-based core |
| → esbuild (2020) | JavaScript bundlers took 30s to over a minute on big codebases | Go, native code, "fully saturate all available CPU cores," everything "written from scratch," only "three" passes over the code tree | Familiar CLI, a minimal plugin API | Used fast as an *inner engine* (esbuild-loader inside webpack, Vite's dev-time pre-bundling) | esbuild's own ecosystem stayed smaller; its speed spread mostly inside other tools |
| → Vite | Even fast bundlers re-bundled everything in development | Unbundled ES-module dev server plus esbuild for dev and Rollup for production | Rollup plugin API | Took over new projects | — |
| → Rolldown / Vite 8 (Mar 2026) | Vite's two bundlers caused "subtle dev-versus-prod differences" | One Rust bundler on the Oxc compiler, "10–30× faster builds" | "Same plugin API as Rollup and Vite"; a migration step through the `rolldown-vite` package | Default for all Vite users on release, with no opt-in. Rolldown 1.0 stable on 7 May 2026 (secondary sources) | Rollup's *API* survives inside Rolldown; esbuild and Rollup leave Vite's default path |
| Rspack / Turbopack | webpack-scale apps too slow | Rust rewrites | Rspack: webpack's configuration and loaders. Turbopack: Next.js integration | Turbopack spread because Next.js adopted it (secondary source) | webpack lives on as the API Rspack implements |

**Documented details.** The esbuild FAQ explains why JavaScript bundlers are slow: "a command-line application is a worst-case performance situation for a JIT-compiled language… While esbuild is busy parsing your JavaScript, node is busy parsing your bundler's JavaScript."\[1\] InfoQ's 2020 coverage quotes Evan Wallace's goal: "works well for a given sweet spot of use cases… and resets the expectations of the community."\[2\] Vite 8's announcement says it is "maintaining full plugin compatibility" and that most "existing Vite plugins work out of the box."\[3\] It also admits the costs: the install is about 15 MB larger, the team recommends a two-step migration for complex apps, and the package is ESM-only.\[4\]\[5\] Vite's own benchmark shows 19,000 modules building in 1.61s versus 40.10s with Rollup. The Linear case went from 46s to 6s.\[6\]\[7\]

**Interpretation.** esbuild is the closest model for the user's plan. It won as a *component* more than as a standalone tool. Its biggest effect was making every other tool pursue native speed. A Python esbuild should expect the same: success may look like uv or Hatch calling it, not users invoking it directly.

### 1.2 Package managers

- **npm → Yarn (Oct 2016).** *Complaint:* Facebook "ran into problems with consistency, security, and performance". React Native's 68 dependencies became 121,358 files, and npm was "by design, nondeterministic" and slowed CI.\[8\]\[9\] *Approach:* deterministic lockfile, offline cache, parallel installs.\[10\] *Compatibility:* "remaining compatible with the npm registry"; built with Google, Exponent and Tilde.\[9\]\[11\] *Speed:* installs went from "several minutes to seconds" on Facebook projects. Hacker News reaction was "mostly positive."\[12\]\[13\] *Survival:* npm adopted lockfiles and parallelism, and its 2025 performance is "far removed from the sluggish installs developers complained about in 2016" (secondary source).\[14\] The incumbent absorbed the challenger's ideas.
- **Yarn 1 → Yarn 2 (Berry).** Yarn broke its own compatibility: Plug'n'Play was "used by default… which led to many prominent developers openly criticizing Yarn 2 for not making it opt-in."\[15\] *Interpretation:* this is the clearest JavaScript case of a technically better design losing users because it forced migration.
- **→ pnpm.** *Complaint:* "redundant storage of dependencies… across projects," and hoisting into a flat `node_modules` that let code import packages it never declared.\[15\] *Approach:* a content-addressed global store plus symlinks, giving strict but still `node_modules`-shaped layouts. *Compatibility:* same registry, the layout tools expect. *Interpretation:* pnpm succeeded where PnP struggled because it kept the folder layout tools rely on.
- **→ Bun.** An all-in-one runtime, package manager, bundler and test runner. It reads `package.json` and the npm registry. Its speed "raised the bar" (secondary source). Jarred Sumner's 2 December 2025 post "Bun is joining Anthropic" confirms that "Bun has been acquired by Anthropic," with Bun staying "open-source & MIT-licensed." This is directly relevant to Astral's later acquisition by OpenAI.

### 1.3 TypeScript runners

- **ts-node → tsx.** ts-node ran the TypeScript compiler (`tsc`) in-process and was slow. tsx swapped in esbuild's transform-only mode: no type checking, near-instant start. *Interpretation:* the same "drop the expensive correctness step from the hot path" move that esbuild made.
- **tsx → Node's built-in type stripping.** *Documented timeline:* `--experimental-strip-types` arrived in Node 22.6 (July 2024). It was enabled by default in v23.6.0 (January 2025) and backported to v22.18.0 (July 2025). Warnings were removed in v24.3.0/v22.18.0, and it was marked stable in v25.2.0 (11 November 2025). Node v26 removed `--experimental-transform-types`.\[16\]\[17\]\[18\] *Approach:* Node "will replace TypeScript syntax with whitespace, and no type checking is performed," so no source maps are needed. It "does not read `tsconfig.json`."\[17\] *Compatibility:* worked out with the TypeScript team, which shipped `erasableSyntaxOnly` in TS 5.8. Implementer Marco Ippolito did not embed SWC directly "after hearing the TypeScript team's concerns about tight-coupling," and shipped the separate Amaro package instead.\[18\] *Survival:* tsx and ts-node remain for features type stripping won't support (enums, namespaces, path aliases).
- **Interpretation for Python:** the platform absorbed the runner once the language team agreed on a deliberately limited subset. The parallel is PEP 723 plus `uv run`, where a standard made the "runner" a feature of the package manager.

### 1.4 Linters and formatters

- **JSLint → JSHint → ESLint.** JSHint forked JSLint to escape its author's fixed opinions. ESLint (2013) made every rule a plugin. Pluggability won, and the ESLint plugin ecosystem is now the moat that later tools struggle to cross.
- **→ Prettier (2017).** An opinionated formatter with almost no options, which ended style arguments and pushed formatting out of linters.
- **→ Biome / Oxc.** *Documented:* on 9 November 2023 Prettier's creator offered a $10k bounty for a Rust formatter passing 95% of Prettier's tests. Prettier's 27 November 2023 post "$20k Bounty was Claimed!" says "Guillermo Rauch, CEO of Vercel, matched it to bring it to $20k and napi.rs added another $2.5k." The same post says Biome claimed it, shipping in Biome v1.4.0, after "a dozen people come together to improve compatibility in only a short 3 weeks." Prettier's reasoning: "as a result of a lack of competition, there has been little incentive to push on performance," and the challenge led a contributor to find "many extreme inefficiencies in Prettier's CLI". Biome now advertises "97% compatibility with Prettier" and 500+ lint rules.\[19\] *Limits:* a Biome maintainer says plainly that "Biome linter isn't a drop-in replacement of ESLint," and users complain about renamed options (`trailingComma` → `trailingCommas`).\[20\] *Interpretation:* compatibility of *output* (formatter) is easy to measure and transfer. Compatibility of an *ecosystem* (ESLint plugins) is not. Ruff faced the same split.

---

## Part 2: How Python Tools Evolved

### 2.1 Installers and environments

| Transition | Complaint | Approach | Compatibility | Speed of change and accelerants | Survival | Enabling standards |
|---|---|---|---|---|---|---|
| easy_install → pip (2008) | No uninstall, eggs, poor errors | Install from source/sdist, requirements files, uninstall | Same PyPI | Years. Accelerated by the wheel format (PEP 427) and bundling pip with Python (PEP 453/`ensurepip`) | easy_install deprecated, then removed from setuptools | PEP 427, 453 |
| virtualenv → venv | Isolation needed a third-party tool | `venv` in the stdlib (3.3) | Same directory layout | Slow; virtualenv still used for speed and features | virtualenv survives (built on venv) | PEP 405 |
| pip → pip-tools | pip had no lock, and pins drifted | `pip-compile` to a pinned `requirements.txt` | Plain requirements files | Organic, CI-driven | Still used; uv copied its interface | none |
| → Pipenv (2017) | Juggling pip plus virtualenv plus requirements | Pipfile and Pipfile.lock, automatic venv | New file formats | Fast *endorsement*: Kenneth Reitz in Jan 2018: "officially recommended packaging tool… from Python.org" | Survives as a minority tool | none; Pipfile never standardized |
| → Poetry | Pipenv slow/buggy, no library publishing | Resolver, `pyproject.toml`, build plus publish | Early PEP 518 user, but its own `[tool.poetry]` metadata until later | Steady growth | Major tool | PEP 517/518 |
| → PDM / Hatch | Wanted standards-first (PEP 621) tools | PEP 621 metadata, pluggable backends (Hatchling) | Standards first | Moderate | Both alive; Hatchling widely used as a backend | PEP 621, 660 |
| → uv (2024) | Everything slow; many separate tools | Rust; `uv pip` drop-in first, then projects, Python install, scripts, tools | pip/pip-tools CLI, `requirements.txt`, PEP 621, PEP 723 | 11% for environment isolation in the PSF/JetBrains 2024 survey, which noted "uv hitting 11% in its first year of release (the first release was in February 2024) is a notable achievement." "Most admired" (74%) in the 2025 Stack Overflow survey | Rye absorbed; pip-tools, pipx and pyenv sidelined but alive | PEP 621, 723, 735, 751 |

**Documented details.**
- *Pipenv's decline.* Reitz's own one-year post was "a Call for Help": "too many incoming issues and reported bugs," and "no progress on getting Pipfile added to pip proper."\[21\] The long-running issue "Lock updating is very slow" (#1914) collected reports such as "This took 38 minutes on my machine to create the lock file." The maintainer reply was "That's just the reality, it's a bit slow."\[22\] A production user review cites fast commits straight to master with releases that broke CI.\[23\] *Interpretation:* Pipenv was endorsed before it was dependable, used a format no standard backed, and depended on one maintainer. All three are avoidable.
- *uv's two-stage launch.* Feb 2024: "a drop-in replacement for pip and pip-tools workflows… we're also taking stewardship of Rye."\[24\] Aug 2024: "an end-to-end solution for managing Python projects, command-line tools, single-file scripts, and even Python itself… Cargo, for Python," including `uv python install` and PEP 723 scripts run with `uv run`.\[25\] Charlie Marsh has said speed is "not just about being written in Rust," and that uv "has gotten faster and faster over time" through allocator, concurrency and zero-copy work.\[26\]
- *The interpreter piece.* uv's Python installs depend on python-build-standalone. Astral took it over on 17 Dec 2024. Gregory Szorc reported 70M+ downloads, "50 million of those since uv's initial release."\[27\] Charlie Marsh's summary of the problem it solves: "you can't 'download a Python binary' from… anywhere." Its approach is "statically linking Python against its dependencies" and "patching the CPython build system to operate on relative… paths."\[28\]
- *Corporate ownership.* On 19 March 2026 OpenAI announced an agreement to acquire Astral (uv, Ruff, ty), with the team joining Codex. Secondary coverage reports the deal as pending regulatory approval at an undisclosed price. The tools remain MIT-licensed. Sources disagree on whether the deal has *closed*: one review of official material through 18 Aug 2026 found no closing confirmation.\[29\]

### 2.2 Build systems

- **distutils → setuptools.** *Complaint:* distutils could not declare dependencies or entry points. *Approach:* setuptools monkeypatched and extended distutils. *Compatibility:* the same `setup.py` interface. *Survival:* distutils was deprecated (PEP 632) and removed from the stdlib in Python 3.12. setuptools absorbed it, vendoring its own copy.
- **setuptools monopoly → PEP 517 backends.** *Complaint:* `setup.py` was executable, imperative and tied to one tool, and you couldn't declare build dependencies. *Standards:* PEP 518 (`[build-system]` in `pyproject.toml`) and PEP 517 (a backend hook interface), then PEP 621 (declarative `[project]` metadata) and PEP 660 (editable installs). *Result:* flit-core, Hatchling, PDM-backend, poetry-core, maturin, scikit-build-core, meson-python and uv_build compete behind one interface. *Interpretation:* this is Python's strongest example of a standard creating a market. No single tool "replaced" setuptools; the interface let many tools share the job.

### 2.3 Freezers (an interpreter plus your app in one executable)

| Generation | Approach | Documented trade-off |
|---|---|---|
| py2exe → cx_Freeze → PyInstaller | Static import analysis plus a bundled interpreter, either "onedir" or "onefile" (extracted to a temp folder at run time) | Hidden-import "hooks" as a permanent maintenance burden; slow start for onefile; no building for other platforms |
| PyOxidizer (2019) | A Rust binary embedding a statically linked CPython, modules imported *from memory* via `oxidized_importer`, Starlark config | Custom importer: `importlib.metadata` "does not implement the full Distribution interface," which broke Poetry's dependencies. Szorc: "By early 2023… PyOxidizer and PyOxy fell into a state of neglect." Its by-product, python-build-standalone, outlived it\[30\]\[31\] |
| PyApp (Dec 2023) | A Rust launcher; on first run it downloads python-build-standalone and installs the project with pip/uv, or can embed both | Ofek Lev: "it does no build sorcery… your code is running on a real installation on disk," so extension modules don't break. Costs: network access and a delay on first run unless embedded; configured through build-time environment variables\[32\]\[33\] |
| scie / science (Pants) | A self-extracting launcher plus interpreter plus PEX | Same "real files on disk" philosophy |

**Interpretation.** The arc runs from *clever* (PyInstaller's analysis, PyOxidizer's in-memory imports) to *boring* (PyApp: install it normally, then cache). Boring won on reliability. Clever approaches failed at the edges: hidden imports, `__file__`, `importlib.resources`, native extensions.

### 2.4 Bundlers (a single artifact that needs an existing Python)

- **PEX (Twitter).** A zip of dependencies plus a bootstrap, run on a host Python. It solved isolated deployment.\[34\]\[35\]
- **PEP 441 / `zipapp` (Python 3.5).** Made the zip-plus-`__main__.py` format official and added the stdlib tool. But zipapps cannot hold native extensions in importable form, and the tool doesn't handle dependencies at all.\[36\]\[37\]
- **shiv (LinkedIn, 2018).** *Complaint:* PEX's reliance on `pkg_resources` meant a forced choice: give up neat packaging for invocation speed, or "impose a few second performance penalty." *Approach:* "completely avoids the use of pkg_resources"; it packs "an entire site-packages directory, as installed by pip," extracts it to `~/.shiv` on first run, and adds it with `site.addsitedir`.\[35\] *Compatibility:* uses pip as is and stdlib `zipapp` code.\[38\]\[39\]
- **stickytape.** Turns "a Python script and any Python modules it depends on into a single-file Python script."\[40\] Its author describes it as "all one big hack — the single-file script writes out all of its dependencies to temporary files."\[41\] The README warns that "many normal uses of Python imports are not properly supported," that it "cannot automatically detect dynamic imports," that non-imported files "won't be included," and that `from __future__` imports break it. It even recommends zipapp or PyInstaller instead.\[40\]\[42\]\[43\]
- **"→ ?"** No successor exists. Interest is clear: uv #12035 asks for exactly "stickytape in uv" (`uv bundle handler.py -o bundled.py`) for Lambda-style deployment, and uv #5802 asks for a PyInstaller-like bundle.\[44\]\[45\]

### 2.5 Linters and formatters: pylint/flake8/isort/Black → Ruff

- *Complaint:* slow, and spread across many tools and configs (flake8 plus a dozen plugins, isort, pyupgrade, Black).
- *Approach:* announced in August 2022 as "an extremely fast Python linter, written in Rust," 150× faster than Flake8 on CPython.\[46\] Every rule is re-implemented in Rust as "a first-party feature," with no plugin API. Marsh treats "the unification of multiple tools into Ruff as a feature, not a bug." It now has 900+ rules and a formatter.\[46\]\[47\]\[48\]
- *Compatibility:* flake8 rule codes and `noqa` comments, `pyproject.toml` config, Black-compatible formatting with a published list of known differences.\[48\]\[49\]\[50\]
- *Survival:* pylint keeps a niche for deep inference checks Ruff lacks. flake8 survives where teams depend on custom plugins. Black survives as the reference style.
- *Interpretation:* Ruff ran the playbook Biome later ran against Prettier. It copied the *output contract* exactly, skipped the *plugin ecosystem*, and bet that combining tools would make up for missing plugins. It worked because Python's important flake8 plugins were few enough to re-implement.

### 2.6 Type checkers

- **History.** PEP 484 (2014) defined the annotation semantics, and mypy is the reference implementation. Pyright (Microsoft) won the editor experience through speed and Pylance. Meta's Pyre and Google's pytype stayed mostly in-house. In 2025 a Rust generation arrived: Astral's ty and Meta's Pyrefly.
- **Difference from other categories.** No checker can be "drop-in." PEP 484 leaves a lot of inference behaviour unspecified, so checkers disagree on the same code. The typing spec/conformance work tries to narrow that.
- *Interpretation:* type checkers are the one category where switching is blocked by *behaviour* compatibility, not speed. It looks like ESLint plugins, not like Prettier output. ty and Pyrefly will likely win editors (the speed-sensitive part) before they win CI gates.

### 2.7 Standards that enabled switches, and ones that stalled

| Enabled | What it unlocked |
|---|---|
| PEP 427 (wheel), 453 (ensurepip) | pip's victory over easy_install |
| PEP 405 (venv) | stdlib isolation |
| PEP 517/518/621/660 | the build-backend market; tool-agnostic project metadata, which uv relies on |
| PEP 441 (zipapp) | shiv/PEX legitimacy |
| PEP 723 (inline script metadata) | `uv run script.py`; the .NET/JBang-style "one-file app" |
| PEP 751 (pylock.toml, accepted 31 Mar 2025) | `pip lock` in pip 25.1; experimental `pip install -r pylock.toml` in pip 26.1 (Apr 2026); uv supports it as an *export* format, while uv.lock stays primary\[51\] |

| Stalled or slow | Status | Consequence |
|---|---|---|
| Pipfile into pip | never happened | Pipenv stuck with its own format |
| PEP 665 (lockfiles, 2021) | rejected | 4 more years of incompatible lockfiles until PEP 751 |
| PEP 711 (PyBI interpreter format) | "Draft", "PEP-Delegate: TODO", only post on 06-Apr-2023\[52\] | python-build-standalone became the *de facto* standard through uv instead. Armin Ronacher on HN: the "discussions around lockfiles, dynamic metadata or PyBI… are good examples of how hard it is to cause change in that space"\[53\] |
| PEP 817 / 825 (wheel variants for GPU/CPU builds) | Draft (Dec 2025 / Feb 2026)\[54\] | PyTorch still needs separate per-CUDA index URLs; uv shipped an experimental variant-enabled build in Aug 2025 with PyTorch, NVIDIA and Quansight\[55\] |
| PEP 725 (external/non-Python dependencies metadata) | Draft | conda and pixi keep that territory |
| App bundle format | no PEP exists | each freezer and bundler has its own format |

---

## Part 3: What Python Users Are Still Unhappy With (2025–2026)

*Caveat: I couldn't get reaction counts for uv issues, so the order below reflects how prominent and long-running each issue is, not verified 👍 totals.*

| # | Complaint | Who has it | Evidence | Is anyone fixing it? |
|---|---|---|---|---|
| 1 | **No way to ship an app as one artifact** | CLI/app authors, internal tooling teams, serverless deployers | uv #5802 ("`uv bundle`… contained executable a la pyinstaller") is labelled "wish – Not on the immediate roadmap." uv #12035 asks for single-`.py` bundling for Lambda. A commenter notes `uv run --with pyinstaller` fails because "dependencies will not be installed by uv." PyInstaller's slow start on Windows is raised in the same thread\[44\]\[45\] | Not uv in the near term. PyApp, PEX/scie, PyInstaller, Nuitka, cosmofy cover parts. **This is the gap the user's bundler fits** |
| 2 | **No task runner** | Rye/Poetry/npm migrants | uv #5903 "Using `uv run` as a task runner" (open since Aug 2024; #8122, #10928, #10211 closed as duplicates; #7203 "not planned")\[56\]\[57\]\[58\]\[59\]\[60\] | Under design discussion (alias proposal, `[tool.uv.tasks]`); third-party: poethepoet, taskipy, uv-tasks\[60\] |
| 3 | **No `uv upgrade` for `pyproject.toml` bounds** | app maintainers | uv #6794; "this feature should be top priority"; at least six third-party workaround tools (uv-upx, uppd, uvrepin, uvbump…)\[61\] | Partial: `uv tree --outdated` (0.5.0); a related PR (#19738) reportedly merged, unverified\[61\]\[62\] |
| 4 | **Non-Python dependencies (C libraries, CLI tools, CUDA)** | scientific/bioinformatics/ML users | uv #12258;\[63\] on HN: "if you think uv solved python dependency issues then you probably never had those issues… Conda… with external binary dependencies, now we're talking"\[64\] | PEP 725 (Draft); pixi as "a uv for the Conda ecosystem"\[64\] |
| 5 | **GPU/CPU-specific wheels** | ML users | PEP 817: PyTorch "publishes 7 different variants… users must manually select" via `--index-url`; PEP 817 is "the longest PEP ever written"\[65\]\[66\] | PEP 817/825 Draft; uv's experimental variant build; WheelNext\[54\] |
| 6 | **Shared/named environments (conda-style activate)** | data scientists, educators | uv #13457 closed as duplicate of #1495\[67\] | Open; Simon Willison counters that uv's real win was removing the need for environment bookkeeping ("hundreds of venv folders")\[64\] |
| 7 | **Lockfile fragmentation persists** | security/compliance teams, multi-tool shops | uv keeps `uv.lock` as its primary format and exports pylock.toml; pip's pylock install is experimental | Slow convergence; Poetry/PDM have said they'll adopt to varying degrees |
| 8 | **Governance and concentration risk** | the whole community, especially organizations | OpenAI's announced acquisition of Astral; HN and New Stack coverage note "details are still fuzzy"; tools are MIT so "anyone can fork them"\[68\]\[69\] | Nothing structural; the forkability safety valve is the only mitigation |
| 9 | **Upgrade lag** | ops teams | In the 2024 PSF/JetBrains survey, as summarised in JetBrains' "The State of Python 2025," 15% run the latest Python while 83% use "a version a year old or older" | uv's Python management helps; no standard fix |

**On survey data.** The 2024 PSF/JetBrains survey (30,000+ took part, 25,000+ responses after filtering, collected Oct–Nov 2024, published 18 Aug 2025) put uv at 11% for environment isolation in its first year. LWN commenters question its representativeness (no error bars, promoted through JetBrains channels).\[70\] I found no published 2025–2026 survey with a newer uv share, and download figures ("126M+ monthly") are community-reported. Treat both as directional.

---

## Part 4: What Other Ecosystems Do Best

*These mechanisms are well-established ecosystem features; this pass did not re-verify each one against primary docs. The Python-attempt notes are sourced where marked above.*

| Ecosystem | Best in class | Mechanism | Could Python adopt it? What stands in the way | Python attempts |
|---|---|---|---|---|
| **Go** | Static single binaries; building for other platforms by setting environment variables (`GOOS/GOARCH`); checksum database (`go.sum`) | The compiler links the runtime and all code into one file; pure-Go code needs no C toolchain | **Partly.** CPython plus C extensions need per-platform native code. But if every dependency ships prebuilt wheels, building for another target is just *downloading that target's wheels* plus that target's python-build-standalone build. Obstacle: dependencies that only ship source (sdists) | PyOxidizer (dormant), PyApp (no cross-compile: "one binary for every platform/architecture pair")\[33\] |
| **Rust/Cargo** | One tool for build, test, run, publish and workspaces; lockfile by default; features | One manifest plus lockfile; the compiler and build tool designed together | **Largely done**: uv explicitly aims to be "Cargo for Python."\[24\] Remaining gaps: tasks (#5903), bundling (#5802) | uv, Rye |
| **Zig** | `zig cc`: cross-compiling C with bundled libc headers for every target | Ships libc sources and headers and builds them for the target on demand | **Yes, as a component.** The `ziglang` PyPI package already serves as a C cross-compiler for maturin/cargo-zigbuild. Obstacle: CPython's own build isn't set up for it | Used in the Rust-extension toolchain |
| **Julia** | BinaryBuilder plus JLL packages: cross-compiled native libraries shipped as ordinary packages; content-addressed "artifacts" | Yggdrasil builds recipes for every platform; packages declare binary artifacts by hash | **Hard, culturally.** The mechanism is wheel-like, but Python has no shared build farm for C libraries and PEP 725 is still Draft. conda-forge is the closest | conda-forge; PEP 725/817 |
| **Elixir** | Mix releases: a self-contained folder with the Erlang runtime, compiled code and a runtime config hook | Built into Mix as a first-class build target | **Yes.** This is basically "PyApp embedded mode, standardized." Obstacle: no PEP, and Python's runtime config story is ad hoc | PyApp, scie |
| **Java** | Fat JARs plus Shade *relocation* (rewriting package names to avoid conflicts); JBang `//DEPS` one-file scripts; GraalVM native-image | JVM classpath; bytecode rewriting; GraalVM's whole-program ahead-of-time compilation under a closed-world assumption | Fat JAR ≈ zipapp/shiv (done). Relocation is possible through import rewriting (pip vendors this way) but fragile with dynamic imports. JBang ≈ PEP 723 (done). GraalVM-style trimming is blocked by Python's dynamic imports and `__import__` | shiv, PEX; PEP 723; Nuitka (compiles, but not closed-world) |
| **.NET** | File-based apps (`dotnet run app.cs`, `#:package`, `dotnet project convert`); `dotnet watch` hot reload; trimming | Directives compile into a hidden project; `dotnet pack app.cs` makes an installable tool; IL trimming with annotations\[71\] | File-based apps: **done** via PEP 723 plus `uv run`; the "graduate to a project" step (`uv init --script` and similar) is partial. Hot reload: hard; CPython has no supported in-place code replacement. Trimming: blocked by dynamic imports | PEP 723; jurigged-style reloaders |
| **Deno** | `deno compile` to one binary, including for other targets; permissions sandbox; built-in tools (fmt, lint, test) | Runtime binary plus an embedded file system for your code | Compile: **yes**, through standalone CPython plus an embedded archive. Permissions: **no.** CPython has no capability model; PEP 578 audit hooks are observe-only | PyOxidizer, PyApp |
| **Bun** | All-in-one with an extremely fast install; `bun build --compile` | Native runtime, a single binary that does everything | uv covers install/run; the compile step is the gap | — |
| **Dart** | `dart compile exe` with tree-shaking ahead-of-time compilation; a fast hot-reload dev loop | A sound type system makes whole-program analysis safe | Tree-shaking: **no**, for the same reasons as GraalVM | — |
| **Swift PM** | Manifest written in Swift; sandboxed package plugins | Manifest is code, but plugins run sandboxed | Python went the other way (declarative TOML after `setup.py`'s problems), which is correct for metadata | — |

---

## Part 5: Lessons

### 5.1 Patterns in how new tools win and lose

**Documented patterns (with examples):**

1. **A big speedup on the slowest step.** esbuild (30s → under 1s), Yarn (minutes → seconds), Ruff (150×), uv (10–100×), Rolldown (10–30×). Every winner advertised a multiplier, not a percentage.
2. **Day-one compatibility with *someone else's* contract.** The npm registry (Yarn, pnpm, Bun), Rollup's plugin API (Vite, Rolldown), webpack's config (Rspack), flake8 codes and Black output (Ruff), Prettier's test suite (Biome), the pip/pip-tools CLI (uv).
3. **Combining tools once trusted.** uv's second launch, Ruff's lint-plus-format, Vite 8's one bundler, Bun. Combining tools works as *stage two*, after compatibility has earned the right to replace a whole workflow.
4. **Riding a standard.** uv rode PEP 621/723/735; Hatchling rode PEP 517/621; Node type stripping rode TypeScript 5.8's `erasableSyntaxOnly`.
5. **Being embedded in someone else's tool.** esbuild in Vite and webpack loaders; python-build-standalone in uv; Turbopack in Next.js.

**How tools lost:**

- **Forced breaking changes:** Yarn 2's PnP default.
- **Endorsed before reliable:** Pipenv (official recommendation, 38-minute locks, "call for help").
- **Too few maintainers:** PyOxidizer ("fell into a state of neglect"), Pipenv's small team.
- **Clever runtime tricks that break the long tail:** PyOxidizer's incomplete `importlib.metadata`; stickytape's import analysis; PEX's `pkg_resources` startup cost.
- **A missing standard leaves every tool on its own format:** Pipfile, the many lockfiles before PEP 751, every freezer format.
- **Incumbents absorbing the idea:** npm absorbing lockfiles, pip adding `pip lock`, Prettier getting faster. The challenger still "wins" the idea but may not win the users.

**Interpretation.** In Python, standards matter more than in JavaScript. JavaScript switches happened through de facto contracts (npm registry, Rollup API) set by tools. Python switches needed PEPs because so many tools touch the same files. The upside is that a standard, once accepted, enables a new tool generation within about two years (PEP 621 in 2020 → Hatch/PDM → uv; PEP 723 in 2023–24 → `uv run`).

### 5.2 Ranked ideas worth bringing to Python

| Rank | Idea (source ecosystem) | Value | Feasibility | Main obstacle |
|---|---|---|---|---|
| 1 | **One artifact per target from a lockfile** (Go, Deno, Bun `--compile`, Mix releases) | Very high; top open uv wish | High: python-build-standalone plus wheels already exist | Native extensions must be on real disk; manylinux/glibc portability; no bundle-format PEP |
| 2 | **Building for other targets by resolving wheels for each target** (Go `GOOS/GOARCH`) | High for CI and release work | High where every dependency has a wheel | Source-only dependencies; platform markers |
| 3 | **Built-in task runner** (npm scripts, Cargo aliases) | Medium-high; a long-running uv thread | High | Shell semantics; whether it needs a standard (`[tool.uv.tasks]` vs. a PEP) |
| 4 | **Upgrade command for declared ranges** (`cargo upgrade`, `npm-check-updates`) | Medium | High | Design choices (how to rewrite version bounds) |
| 5 | **Hardware-aware binary selection** (Julia JLL, conda) | Very high for ML | Medium | PEP 817/825 approval; trusting installer plugins |
| 6 | **Standard way to declare non-Python dependencies** (JLL, conda) | High for science | Low-medium | PEP 725; no shared build farm |
| 7 | **"Script → project" step** (.NET `dotnet project convert`) | Medium | High | Mostly UX |
| 8 | **Package-name relocation for vendoring** (Java Shade) | Medium for bundlers and plugins | Low-medium | Dynamic imports, `importlib.metadata` names |
| 9 | **Hot reload** (.NET watch, Dart) | Medium | Low | No supported way to swap code in CPython |
| 10 | **Tree-shaking/trimming** (GraalVM, .NET, Dart) | Medium (size) | Low | Dynamic imports; only "file-level" pruning is safe |
| 11 | **Permission sandbox** (Deno) | Medium | Very low | No capability model in CPython |

### 5.3 What this means for a Python bundler

**Lead with this complaint:** *"I have a locked uv/Poetry/PEP 723 project. Give me one artifact per target that starts fast and runs on a clean machine, without me writing hidden-import hooks."* That is uv #5802 and #12035 in users' own words. Maintainers have publicly put it off the immediate roadmap.\[44\] That leaves an opening, with a risk: Astral (now with OpenAI's resources) can close it whenever it chooses. **Interpretation:** design to be the engine uv could call (the esbuild-inside-Vite path), not a competitor to uv.

**Be compatible with:**
- **Inputs:** `pyproject.toml` (PEP 621 `[project]`, `[project.scripts]` entry points), `uv.lock` *and* `pylock.toml` (PEP 751), PEP 723 inline scripts, `requirements.txt` for legacy users.
- **Resolution:** delegate to uv/pip rather than writing a resolver. Install from wheels only by default, which makes building for other targets possible.
- **Runtime:** python-build-standalone interpreters (the de facto PyBI).
- **Import semantics:** the *standard* importer, with real files for native extensions. `importlib.metadata`, `importlib.resources`, `__file__` and entry points must behave exactly as in a venv.
- **Migration paths:** read PyInstaller hook data for hidden imports, and offer shiv/PEX-like zipapp output as one target.

**Output modes, esbuild-style (one tool, several targets):**
1. A single `.pyz`/zipapp for hosts that already have Python (shiv's approach, but faster, with extraction cached by content hash).
2. A self-contained executable: launcher plus embedded standalone CPython plus a pre-installed site-packages, extracted once to a content-addressed cache (PyApp embedded mode, without the first-run download).
3. Optional: a "single `.py`" mode for pure-Python Lambda-style use. Inline only modules you can resolve, and refuse loudly on dynamic imports or C extensions rather than guessing.

**Mistakes to avoid:**
- **stickytape:** guessing at imports by static analysis and silently dropping data files. Instead, take the dependency set from the lockfile/installed environment, not from import scanning, and treat files that aren't imported as part of the package.
- **PyOxidizer:** (a) a custom in-memory importer that breaks `importlib.metadata` and C extensions; (b) a bespoke config language (Starlark) instead of `pyproject.toml`; (c) one maintainer. Keep configuration in `[tool.<name>]`, keep imports standard, and plan for co-maintainers from day one.
- **Pipenv:** (a) slow core operations, so make the warm-cache rebuild path finish in under a second, the way esbuild did; (b) a new file format with no standard behind it; (c) seeking official endorsement before reliability. Earn adoption the way uv did: with a drop-in mode first.
- **Yarn 2:** never make a breaking design the default. Opt-in only.

**Interpretation of the opportunity.** Python's bundler category is where JavaScript bundling stood before esbuild: tools that work, but slow, fragile, and each with its own format. The parts a winner needs (python-build-standalone, PEP 751, PEP 723, uv's resolver, Rust/Go toolchains) all became available in 2024–2025. A tool that puts them together, with compatibility as the pitch and speed as the proof, fits the pattern that produced Yarn, esbuild, Ruff and uv.

---

## Caveats

- **Primary versus secondary sources.** Launch posts and maintainer writing were used for Yarn, esbuild, Vite 8, Node type stripping, Prettier/Biome, uv, Ruff, Pipenv, shiv, PyApp, PyOxidizer, python-build-standalone, PEPs 711/751/817 and .NET file-based apps. Rolldown 1.0's date, Turbopack's default status and npm's current performance come from secondary write-ups; Bun's acquisition is confirmed by Bun's own 2 December 2025 post "Bun is joining Anthropic." Older JavaScript history (Browserify/webpack/Rollup/Parcel, JSHint/ESLint, ts-node/tsx) and the Part 4 mechanisms are presented from established background knowledge and were not re-verified against primary sources in this pass.
- **No made-up adoption numbers.** The only usage figures given are the PSF/JetBrains 2024 survey (uv 11%), the Stack Overflow 2025 "admired" figure (74%), python-build-standalone download counts (Szorc) and Vite's benchmarks. uv's monthly downloads are community-reported. No uv issue reaction counts could be retrieved.
- **OpenAI/Astral:** announced 19 March 2026. Whether it has closed is unconfirmed in the sources reviewed.
- **Draft PEPs** (711, 725, 817, 825) can change or be withdrawn. Anything described as "would" or "could" in them is a proposal, not shipped behaviour.

## Sources

1. [esbuild - FAQ](https://esbuild.github.io/faq/)
2. [esbuild faster go js bundler](https://www.infoq.com/news/2020/06/esbuild-faster-go-js-bundler/)
3. [Vite 8.0 is out!](https://vite.dev/blog/announcing-vite8)
4. [JavaScript build tool: Vite 8.0 speeds up with Rust-based bundler Rolldown](https://www.heise.de/en/news/JavaScript-build-tool-Vite-8-0-speeds-up-with-Rust-based-bundler-Rolldown-11210695.html)
5. [Migrating to Vite 8 + Rolldown - Certificates.dev](https://certificates.dev/blog/migrating-to-vite-8-rolldown)
6. [Vite 8 and Rolldown: Is the Migration Worth It? — CODERCOPS](https://blog.codercops.com/blog/vite-8-rolldown-migration-guide-2026)
7. [Vite 8.0 Rolldown Migration Guide: 10-30x Faster Builds](https://byteiota.com/vite-8-0-rolldown-migration-guide-10-30x-faster-builds/)
8. [Facebook partners with Google, others to launch a new JavaScript package manager](https://techcrunch.com/2016/10/11/facebook-partners-with-google-others-to-launch-a-new-javascript-package-manager/)
9. [Yarn: A new package manager for JavaScript - Engineering at Meta](https://engineering.fb.com/2016/10/11/web/yarn-a-new-package-manager-for-javascript/)
10. [Facebook launches Yarn, a JavaScript package manager built for speed](https://thenextweb.com/dd/2016/10/12/facebook-launches-yarn-a-faster-npm-client/)
11. [Facebook Yarn Unravels Dependency Management Issues for JavaScript Packages](https://test.thenewstack.io/facebooks-yarn-unraveled/)
12. [Facebook spins Yarn to replace NPM packager](https://www.infoworld.com/article/2249957/facebook-spins-yarn-to-replace-npm-packager-2.html)
13. [Facebook Yarn's for your JavaScript package](https://www.theregister.com/software/2016/10/12/facebook-yarns-for-your-javascript-package/937990)
14. [Choosing the Right JavaScript Package Manager in 2025: npm vs. Yarn vs. pnpm vs. Bun](https://developersvoice.com/blog/js/npm-yarn-pnpm-bun-comparison/)
15. [JavaScript package managers compared: npm, Yarn, or pnpm? - LogRocket Blog](https://blog.logrocket.com/javascript-package-managers-compared/)
16. [Node.js Native TypeScript: The Complete Guide to Running .ts Files Without a Compiler - DEV Community](https://dev.to/pockit_tools/nodejs-native-typescript-the-complete-guide-to-running-ts-files-without-a-compiler-mpa)
17. [Modules: TypeScript](https://nodejs.org/api/typescript.html)
18. [How a Summer in Abruzzo Helped Bring Type Stripping to Node.js](https://satanacchio.hashnode.dev/the-summer-i-shipped-type-stripping)
19. [GitHub - biomejs/biome: A toolchain for web projects, aimed to provide functionalities to maintain them. Biome offers formatter and linter, usable via CLI and LSP. · GitHub](https://github.com/biomejs/biome)
20. [Is there a cheat sheet for the biome.json config? · biomejs/biome · Discussion #3568](https://github.com/biomejs/biome/discussions/3568)
21. [Pipenv: One Year Later & a Call for Help - Kenneth Reitz](https://kennethreitz.org/essays/2018-01-pipenv_one_year_later_amp_a_call_for_help)
22. [github.com](https://github.com/pypa/pipenv/issues/1914)
23. [Pipenv review, after using it in production](https://medium.com/@DJetelina/pipenv-review-after-using-in-production-a05e7176f3f0)
24. [uv: Python packaging in Rust - Astral](https://astral.sh/blog/uv)
25. [uv: Unified Python packaging - Astral](https://astral.sh/blog/uv-unified-python-packaging)
26. [uv: An extremely Fast Python Package Manager :: Jane Street](https://www.janestreet.com/tech-talks/uv-an-extremely-fast-python-package-manager/)
27. [Transferring Python Build Standalone Stewardship to Astral](https://simonwillison.net/2024/Dec/3/python-build-standalone-astral/)
28. [A New Home for Python-Build-Standalone](https://www.pelayoarbues.com/literature-notes/Articles/A-New-Home-for-Python-Build-Standalone)
29. [OpenAI Just Acquired Astral? What It Means for uv, Ruff, and Python](https://www.itechguides.com/openai-just-acquired-astral-what-the-deal-means-for-uv-ruff-and-every-python-developer/)
30. [Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/2024/03/17/my-shifting-open-source-priorities/)
31. [DEV Community](https://dev.to/gi0baro/how-i-made-a-binary-version-of-poetry-package-manager-5246)
32. [How do I ship a Python application to end users?](https://pydevtools.com/handbook/explanation/how-do-i-ship-a-python-application-to-end-users/)
33. [Show HN: PyApp](https://news.ycombinator.com/item?id=38629539)
34. [Introducing and Open Sourcing Shiv](https://engineering.linkedin.com/blog/2018/05/introducing-and-open-sourcing-shiv)
35. [Motivation & Comparisons — shiv documentation](https://shiv.readthedocs.io/en/latest/history.html)
36. [Python's zipapp: Build Executable Zip Applications](https://realpython.com/python-zipapp/)
37. [Python zip applications and static includes - Micah R Ledbetter](https://me.micahrl.com/blog/python-zipapp-staticincludes/)
38. [shiv May 02, 2018](https://app.readthedocs.org/projects/shiv/downloads/pdf/docs/)
39. [Shiv API — shiv documentation - Read the Docs](https://shiv.readthedocs.io/en/latest/api.html)
40. [GitHub - mwilliamson/stickytape: Convert Python packages into a single script](https://github.com/mwilliamson/stickytape)
41. [Convert Python packages to single-file Python scripts with stickytape](https://mike.zwobble.org/2012/10/convert-python-packages-to-single-file-python-scripts-with-stickytape/)
42. [GitHub - minhtuan221/stickytape: Convert Python packages into a single script](https://github.com/minhtuan221/stickytape)
43. [github.com](https://github.com/dmgolembiowski/stickytape)
44. [Suggestion: \`uv bundle\`, \`uv build --release\` or similar to create a contained executable a la pyinstaller, py2exe · Issue #5802 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5802)
45. [Feature Request: Production Bundling for Python](https://github.com/astral-sh/uv/issues/12035)
46. [Ruff: a fast Python linter \[LWN.net\]](https://lwn.net/Articles/930487/)
47. [GitHub - sthagen/charliermarsh-ruff: An extremely fast Python linter, written in Rust. · GitHub](https://github.com/sthagen/charliermarsh-ruff)
48. [GitHub - astral-sh/ruff: An extremely fast Python linter and code formatter, written in Rust. · GitHub](https://github.com/astral-sh/ruff)
49. [Ruff Python Linter 2026: Replace flake8, isort, and black with One Tool](https://tutorials.technology/tutorials/ruff-python-linter-tutorial-2026.html)
50. [pypi.org](https://pypi.org/project/ruff/0.0.47/)
51. [What is PEP 751?](https://pydevtools.com/handbook/explanation/what-is-pep-751/)
52. [PEP 711](https://peps.python.org/pep-0711/)
53. [A new home for Python-build-standalone](https://news.ycombinator.com/item?id=42312277)
54. [Why Installing GPU Python Packages Is So Complicated](https://pydevtools.com/handbook/explanation/installing-cuda-python-packages/)
55. [Blog](https://astral.sh/blog)
56. [Custom task runner · Issue #7203 · astral-sh/uv](https://github.com/astral-sh/uv/issues/7203)
57. [Task runner plugin system · Issue #10211 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10211)
58. [support scripts defined in \`pyproject.toml\` · Issue #8122 · astral-sh/uv](https://github.com/astral-sh/uv/issues/8122)
59. [npm style script support · Issue #10928 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10928)
60. [Using \`uv run\` as a task runner · Issue #5903 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5903)
61. [(🎁) add an \`upgrade\` command](https://github.com/astral-sh/uv/issues/6794)
62. [github.com](https://github.com/containerbase/base/issues/3575)
63. [Consider supporting non-python packages and tools for dev toolchains · Issue #12258 · astral-sh/uv](https://github.com/astral-sh/uv/issues/12258)
64. [Thoughts on OpenAI acquiring Astral and uv/ruff/ty](https://news.ycombinator.com/item?id=47443675)
65. [PEP 817 - Wheel Variants: Beyond Platform Tags - Packaging - Discussions on Python.org](https://discuss.python.org/t/pep-817-wheel-variants-beyond-platform-tags/105860)
66. [Episode #544 - Wheel Next + Packaging PEPs](https://talkpython.fm/episodes/show/544/wheel-next-packaging-peps)
67. [Support shared environment like conda · Issue #13457 · astral-sh/uv](https://github.com/astral-sh/uv/issues/13457)
68. [OpenAI acquires Astral to bring open source Python developer tools to Codex — but details are still fuzzy - The New Stack](https://thenewstack.io/openai-astral-acquisition/)
69. [OpenAI Acquires Astral: What It Means for uv, Ruff, and the Future of Python Development](https://renovateqr.com/blog/openai-acquires-astral)
70. [The State of Python 2025 \[LWN.net\]](https://lwn.net/Articles/1034313/)
71. [How to run a file-based C# app with \`dotnet run app.cs\` in .NET 11 - Start Debugging](https://startdebugging.net/2026/08/how-to-run-a-file-based-csharp-app-with-dotnet-run-in-dotnet-11/)
