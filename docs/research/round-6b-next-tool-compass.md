# What Comes Next for Shipping Python: Lessons from JavaScript Tooling, Evidence from 2024–2026

The empty seat in Python shipping is clear: no tool turns a uv-locked project into a single artifact that runs anywhere and can be built for any platform. The JavaScript analogue is `bun build --compile`, or esbuild for applications. The demand evidence for this job is the strongest in this report. The same evidence shows that Astral (which OpenAI agreed to acquire in March 2026; per Talk Python, Charlie Marsh "now continues to lead the Astral team from inside OpenAI") is the most likely builder, so an independent tool has to win on a job uv will not own, not on speed.

## TL;DR
- **Lesson from JS:** tools won when they gave a step change in speed (esbuild, SWC), had zero or familiar configuration (Parcel, Vite), or got embedded as the default inside someone else's tool (SWC in Next.js, esbuild in Vite, Turbopack in Next.js 16). Tools stalled when they were good but needed people to migrate (Yarn Berry Plug'n'Play, Parcel after v2) or tried to own everything before owning one job (Rome). uv is Python's Vite-plus-pnpm. Its weak spot is the "last mile": producing an artifact.
- **Biggest gap (well supported):** turning a uv-locked project into a standalone, cross-built, offline-capable artifact. uv issue #5802 ("`uv bundle` … a contained executable") has been open since August 2024 and is labelled "Not on the immediate roadmap".\[1\] Related issues ask for offline layouts (#11746) and air-gapped mirrors (#10203).\[2\]\[3\] PyInstaller, Nuitka and pex all release often, but each solves only part of the problem.
- **Top candidates:** (1) a uv-native "compile/bundle" layer built on python-build-standalone plus scie/PyApp-style launchers (high confidence on demand, high risk that Astral ships it); (2) offline/air-gapped "layout" artifacts for enterprise and regulated teams (medium-high confidence); (3) hardware-aware wheel selection via wheel variants (PEP 817/825) for ML (medium confidence; the standard is still in draft); (4) environment snapshots for agent sandboxes (speculative). Ideas the evidence argues against: another resolver or installer, a single-.py "tree-shaking" bundler, and betting on PEP 711 (PyBI).

## Part 1: The JavaScript lens

*Note on evidence:* release events from 2025–2026 (Vite 8, Turbopack, the Bun acquisition) were checked against primary sources for this report. Older history (Browserify through Yarn) comes from well-known project history and is not re-cited here. Treat it as background, not new evidence.

| Tool | Outcome | Specific reason | What it replaced and why |
|---|---|---|---|
| Browserify (2011) | Faded | First to bring `require()`/npm to the browser (a capability nobody else had) | Replaced hand-ordered script tags. Lost to webpack because it did one thing, with no code-splitting or asset loaders |
| webpack | Won, now being displaced | Loaders, code splitting, and HMR, plus being embedded in Create React App and Next.js | Replaced Browserify/Grunt. Now losing because it is slow and configuration-heavy |
| Rollup | Won a niche, then got embedded | Owned one job: ES-module libraries with tree-shaking. Then became Vite's production bundler | Replaced webpack for libraries |
| Parcel | Stalled | Zero configuration was a real insight, but it had no ecosystem anchor, and Vite copied the idea with more speed | Lost despite being good |
| esbuild | Won as a component | Speed step change (Go, 10–100×). Very few people use it directly; it is embedded in Vite and tsup | Replaced Babel/tsc for transforms |
| Vite | Won broadly | Workflow insight (native-ESM dev server) + esbuild + Rollup + framework-neutral plugins. Vite 8 (12 Mar 2026) replaced both with one Rust bundler, Rolldown; the Vite 8 announcement says "Vite is now being downloaded 65 million times a week", and the Vite 8.1 post says Vite 8 alone sees 41.6 million weekly downloads | Replaced CRA/webpack dev servers and Snowpack |
| SWC | Won as a component | Rust speed + embedding: Next.js made it its compiler | Replaced Babel inside frameworks |
| tsup → tsdown | Won a narrow job | Zero-config library bundling on top of esbuild; tsdown does the same on Rolldown | Replaced hand-written Rollup configs |
| Bun | Strong but partial | All-in-one runtime, package manager, bundler, and `--compile` single binaries. Anthropic acquired it on 2 Dec 2025; Jarred Sumner wrote that "Claude Code ships as a Bun executable to millions of users. If Bun breaks, Claude Code breaks." | Competes with Node+npm+esbuild. Adoption is limited by gaps in Node compatibility |
| Turbopack / Rspack | Turbopack won by being the default; Rspack won by compatibility | Turbopack became stable and the default in Next.js 16 (Oct 2025): "no configuration required".\[4\]\[5\] Rspack wins by being a webpack-API-compatible Rust drop-in | Both replace webpack |
| npm / Yarn / pnpm | npm persists; Yarn v1 won and then split; pnpm grew | Yarn (Facebook-backed) brought lockfiles and speed, and npm copied both. Yarn Berry's PnP broke tools and stalled. pnpm's content-addressed store and strictness won steadily | npm is the default that never dies |

**Rules**
1. **Tools win when they deliver an order-of-magnitude speed jump on a job people already do:** esbuild, SWC, Rolldown, and in Python, uv. **They stall when the speed gain is modest and the migration cost is real:** Rspack outside webpack shops, Parcel 2.
2. **Tools win when they get embedded as someone else's default:** esbuild/Rollup in Vite, SWC/Turbopack in Next.js, Bun inside Claude Code. **They stall as standalone products competing for direct users:** Parcel, and Rome (good, but it went all-in-one before owning one job).
3. **Tools win when they own one job completely:** Rollup for libraries, tsup for TS packages. **They stall when the job is half-owned:** Browserify, with no code splitting.
4. **Tools win with zero or familiar configuration:** Parcel's idea, Vite, Turbopack. **They stall when they demand new mental models:** Yarn PnP, webpack configuration fatigue.
5. **Incumbents copy the winning idea:** npm copied Yarn's lockfiles, Vite copied Parcel's zero-config. Tools that win only on one feature get absorbed.
6. **Company backing speeds things up but is not enough:** Vercel/Turbopack and Facebook/Yarn won; Rome Tools failed; VoidZero and Anthropic are now concentrating ownership.

## Part 2: Python today, through that lens

| Tool | Job it owns | Lesson | Activity (Oct 2025–Oct 2026) | Cannot do |
|---|---|---|---|---|
| **uv / uvx** | Resolve, lock, install, manage Python, run scripts (PEP 723), run tools | Rules 1+3+4: speed step change, one binary, pip-compatible interface. Stack Overflow's 2025 survey calls uv "the most admired (74%) SO tag technology this year" (the ranking covers Stack Overflow tags) | Very active: 0.12.23 released 3 Oct 2026; releases every few days.\[6\] OpenAI announced its acquisition of Astral on 19 Mar 2026. Talk Python #552 later reported that Charlie Marsh "now continues to lead the Astral team from inside OpenAI", so the deal appears to have closed (no formal closing date found) | Produce a standalone executable (#5802 open, "Not on the immediate roadmap"); offline layouts (#11746)\[1\]\[3\] |
| **pip / pipx** | The default installer that comes with Python | Rule 5: the default that never dies | pip 26.2.1 (4 Aug 2026);\[7\] `pip lock` is still experimental, single-platform only (#13953, Apr 2026).\[8\] pipx: not verified | Cross-platform locks, Python management |
| **Poetry** | Project management + publishing, from before uv | Like Yarn v1: pioneered lockfiles, now overtaken on speed | 2.3.0 (18 Jan 2026) added pylock.toml export via plugin; latest 2.4.3\[9\]\[10\] | Native pylock.toml as its lockfile;\[11\]\[12\] offline installs (#2184 long-running)\[13\] |
| **PDM** | Standards-first project manager | Rule 2 failure: good, but not embedded anywhere | Shipped pylock export in 2.24 (Apr 2025); later activity not verified\[14\] | Distinct value beyond uv |
| **Hatch** | Build backend (hatchling) + environments + `build -t binary` via PyApp | Rule 2 win for hatchling (embedded as a backend)\[15\] | 1.16.0–1.16.5 (Nov 2025–Feb 2026)\[16\] | Fully offline binaries (#2210, discussion #1717)\[17\]\[18\] |
| **conda / pixi** | Non-Python native dependencies (CUDA, GDAL, compilers) | Rule 3: owns one job PyPI can't do | pixi is active (pixi-pack self-extracting executables since pixi 0.44/0.47); conda release cadence not verified\[19\] | Plain-wheel world; pixi-pack doesn't handle sdists\[20\] |
| **pex (+ scie)** | Zipapp/venv artifacts for servers and monorepos; `--scie` makes self-contained binaries with python-build-standalone\[21\] | Rule 2: embedded in Pants\[21\] | Extremely active: 2.103.x in Sep 2026, dozens of releases in 2026\[22\]\[23\] | Windows-first desktop apps; little use outside Pants |
| **shiv / zipapp** | Zip of code + dependencies run by an existing Python | Like Browserify: does one thing | shiv: not verified; zipapp is stdlib | Bundle the interpreter or native libraries reliably |
| **PyInstaller** | End-user desktop/CLI executables | Rule 3 incumbent: the default by habit | 6.17 → 6.22.3 (Nov 2025–12 Sep 2026), about 9 releases\[24\]\[25\] | Cross-compiling; fast onefile startup (Windows Defender scans every unpacked file, per #5802 thread)\[1\] |
| **Nuitka** | Compiles Python to C, producing standalone/onefile builds | Rule 1, but on runtime speed and protection rather than build speed | 4.0 (Feb 2026), 4.2 (Aug 2026), 4.2.2 (22 Sep 2026); added `--project` mode for pyproject builds\[26\]\[27\]\[28\] | Fast builds; cross-compiling |
| **PyOxidizer** | Embedded-interpreter binaries | Lost despite being good (like Rome): single maintainer | Dormant: no meaningful updates since Jan 2023; Mar 2024 status update says "possibly dead"\[29\] | Anything new |
| **PyApp** | Rust launcher that fetches or embeds Python + project on first run\[30\] | Rule 2: embedded in Hatch\[30\] | v0.28 / v0.29 releases; exact 2025–26 dates not verified\[31\] | Fully offline by default; configured through environment variables\[32\] |
| **conda-pack** | Relocatable conda environments | Niche | Not verified | Python-only workflows |
| **Briefcase** | Native installers (MSI, DMG, mobile) | Rule 3: owns mobile/desktop for BeeWare | Not verified this session | General server artifacts |
| **scie / science** | Native multi-platform launchers (the scie-jump format) | Rule 2: the component under pex | Indirectly active through pex\[33\] | Direct user experience |
| **python-build-standalone** | Portable CPython builds that uv, PyApp, pex and Hatch all rely on | Rule 2 par excellence: the "esbuild" of Python distribution | Very active: release 20261003; maintained by Astral\[34\] | Not a user-facing tool |
| **Docker** | The default "works anywhere" escape hatch | Rule 5: the default | n/a | Desktop users, small artifacts, fast cold starts |

**Standards:** PEP 723 (inline script metadata) is accepted and the most effective of the four, because uv embeds it (`uv run script.py`). PEP 751 (pylock.toml) was accepted with full, final acceptance in March 2025.\[35\] pip, PDM and uv can export it,\[14\] and Poetry can via a plugin.\[11\] But uv keeps uv.lock as its primary lockfile because pylock "is not sufficient to replace uv.lock" (Marsh, #12584), so in practice pylock is an interchange format, like a modern requirements.txt.\[36\] PEP 711 (PyBI) is still listed as Draft since 2023 with no PEP-Delegate;\[37\]\[38\] python-build-standalone filled that role in practice. PEP 668 (externally managed environments) pushed users toward pipx and uv tools. Newer: PEP 817 (wheel variants), created 10 December 2025. A 30 Sep 2026 pull request converts it into an Informational umbrella PEP, with PEP 825 carrying the spec.\[39\]

**Which tool plays the esbuild/Vite role?** uv is Vite+pnpm. python-build-standalone is the embedded esbuild-like component. **Empty roles:** (a) a `bun build --compile`-style artifact builder integrated with the lockfile; (b) a tsup-style "one job, zero config" app packager; (c) an offline or mirror bundler.

## Part 3: Evidence of unmet needs

**Issue trackers** (reaction and comment counts could not be retrieved; GitHub API access was blocked, so none are shown rather than estimated):

| Repo / issue | Title (short) | Status | Signal |
|---|---|---|---|
| astral-sh/uv #5802 | "`uv bundle`, `uv build --release` … contained executable" | Open since 5 Aug 2024; label "wish"\[1\] | Duplicates closed into it (#10452);\[40\] thread still active in 2026 |
| astral-sh/uv #12035 | "Production Bundling … Single File Deployment" (Lambda) | Closed | Maintainers argue dynamic imports make inlining infeasible\[41\] |
| astral-sh/uv #11746 | "`uv layout` … portable offline Python distributions" | Appears open (unverified) | Enterprise offline need\[3\] |
| astral-sh/uv #10203 | Easier mirror for uv-python | Unverified | Air-gapped mirror is about 14 GB per uv version\[2\] |
| astral-sh/uv #6533 | Installer that also installs a tool | Unverified | Led to an experimental uvx.sh install-script service (Marsh: "don't make any guarantees")\[1\] |
| astral-sh/uv #15751 | Portable mode / relocatable venvs | Unverified | Shipping venvs as artifacts\[42\] |
| pypa/pip #13953 | "What's next for `pip lock`?" | Open, Apr 2026 | Single-platform locks only\[8\] |
| python-poetry/poetry #2184 | Offline installs (`--download-only`, `--offline`) | Long-running, apparently open | Community fork exists\[43\] |
| pypa/hatch #2210 / #1933 | Binaries not self-contained; cross-target naming bug | Unverified | PyApp's first-run network fetch\[17\] |
| Quantco/pixi-pack #192 | Large memory use extracting executable | Unverified | Self-extracting environments are heavy\[44\] |

**Discussion** (sparse: this pass found fewer dated posts than the brief asks for, which is a limitation of this report):
- In the #5802 thread (2025–26), a user reports that PyInstaller onefile "takes for ever for every CLI command". The maintainer-adjacent explanation is Windows Defender scanning of unpacked files.\[1\]
- A comment on HN's "Python Packaging, One Year Later" thread (Jan 2024, just outside the window) calls packaging a cross-OS app "such a horror show".\[45\]
- HN's pyx thread (Aug 2025) shows concern that Astral "will inevitably get acquired".\[46\] That happened in March 2026.\[47\]

**Surveys:** the PSF/JetBrains 2024 survey (published 18 Aug 2025; per JetBrains, "more than 25,000 responses collected in October 2024 – November 2024" after filtering) reports "uv hitting 11% in its first year of release". Stack Overflow 2025 calls uv "the most admired (74%) SO tag technology this year" (the ranking covers Stack Overflow tags, not all technologies). A repository study (aleyan.com, 2026) finds uv in 32% of Python repos created in 2025 but only 10% of the top 100k repos.\[48\] 2025 Python Developers Survey results and the 2025 Python Packaging Ecosystem Survey results: not found or verified.

**Themes ranked by evidence:**
1. **Standalone executable / single artifact** (strongest: uv #5802 plus duplicates, Hatch binary issues, PyInstaller startup complaints). Felt by CLI authors, internal-tools teams, and desktop app makers. Workaround today: `uv run --with pyinstaller pyinstaller --onefile`,\[1\] Nuitka, PyApp, pex `--scie`.\[30\]\[49\]
2. **Offline / air-gapped installs** (uv #11746, #10203, #13587, #16519;\[2\]\[3\]\[50\]\[51\] Poetry #2184; pixi-pack). Felt by enterprise, regulated, and HPC teams. Workaround: wheelhouses, private mirrors, Docker images, pixi-pack.\[52\]\[53\]
3. **Cross-platform builds** (Hatch #1933;\[54\] pex foreign-platform scie fixes; PyInstaller/Nuitka can't cross-compile).\[49\]\[55\] Felt by tool authors shipping to Windows/macOS. Workaround: a CI matrix of native runners.\[21\]
4. **Hardware-specific native wheels** (PEP 817 motivation: in the PEP 817 thread on discuss.python.org, a participant notes that per-GPU-architecture torch wheels "could be O(250 MB) rather than 900 MB"; PEP 817 says PyTorch published seven variants for every release as of October 2025). Felt by ML and data scientists. Workaround: custom indexes, conda/pixi.
5. **Lockfile interoperability** (pylock vs uv.lock vs poetry.lock). Felt by platform teams and tool authors. Workaround: `uv export`.\[56\]

## Part 4: What could come next

| Candidate | Job | JS lesson | Demand evidence | Who builds it / risk | Failure mode | Confidence |
|---|---|---|---|---|---|---|
| **1. Lockfile-to-artifact compiler** (`uv.lock` → scie/PyApp binary or OCI layer for N target platforms) | Last mile from project to runnable thing | Bun `--compile`; embedding (Rule 2) | Theme 1, the strongest | Astral/OpenAI is the obvious builder. pex/scie already does most of it but is tied to Pants | Astral ships it; native-library edge cases (Qt, CUDA) | High on demand; low for an independent winner |
| **2. Offline "layout" bundles** (interpreter + wheels + lock for each platform, verifiable) | Air-gapped installs and reproducible handoff | Owning one job (Rollup, tsup) | Theme 2 | Mirror/registry vendors. Astral's paid registry pyx (Aug 2025) is reportedly being wound down after the OpenAI deal (Talk Python #552), which leaves this space more open | Becomes a feature of a registry product | Medium-high |
| **3. Hardware-aware wheel selection** | Picking the right CUDA/CPU build automatically | Standard + embedded installer | PEP 817 thread; PyTorch | WheelNext / Quansight / NVIDIA / uv prototype\[57\] | PEP churn (moved to Informational, Sept 2026)\[39\] | Medium; timeline speculative |
| **4. Fast-start agent/sandbox environments** (snapshotted, content-addressed environments) | Shipping code into ephemeral sandboxes | Speed step change; Bun-in-Claude-Code embedding | Indirect: the Bun and Astral acquisitions were both framed around coding agents\[58\]\[59\] | AI labs in-house | Agent platforms build their own | Speculative |
| **5. Desktop app packager with zero config** (tsup for GUIs: signing, notarization, installers) | End-user desktops | Zero configuration (Parcel/Vite) | PyInstaller dominance plus complaints | Briefcase is closest | Small market; signing costs | Low-medium |

**Ideas the evidence argues against:** another resolver or installer (uv has won Rule 1 and incumbents copy, Rule 5); single-.py "tree-shaken" bundling (uv #12035 closed; Python's dynamic imports defeat it);\[41\] building on PEP 711/PyBI (stuck in draft; python-build-standalone already serves the role); replacing uv.lock with pylock.toml as a product thesis (uv explicitly declined).\[36\]

## One-page summary

**Lessons:** speed step changes plus embedding as a default win (esbuild, SWC, Turbopack, uv). Zero configuration wins but gets copied (Parcel → Vite). Good-but-orphaned tools die (Rome, PyOxidizer). Incumbents absorb single-feature advantages (npm ← Yarn).

**Biggest gaps:** (1) project → standalone, cross-built artifact (strongest evidence); (2) offline/air-gapped distribution; (3) cross-compilation for frozen apps; (4) hardware-specific wheels.

**Top candidates and confidence:**
- Lockfile-to-artifact compiler: **High** confidence it becomes the next widely adopted step; **Medium-high** probability Astral/OpenAI owns it, which means an independent entrant must be the embedded component (scie-like), not the front end.
- Offline layout bundles: **Medium-high** (enterprise demand is clear; it is likely to be monetized through registries).
- Wheel variants: **Medium** (real ML pain; the standard is not yet accepted).
- Agent-sandbox environment snapshots: **Low/speculative** (inferred from acquisitions, not user complaints).

**Caveats:** reaction counts are unverified; activity data for conda, PDM, Briefcase, shiv, pipx and PyApp in 2025–26 is unverified; discussion-forum evidence was thin; 2025 survey results were not found; and the OpenAI–Astral deal appears to have closed (Talk Python #552 says Marsh now leads the Astral team "from inside OpenAI"), but no formal closing date was found. Inferences in Part 4 are this author's, not sourced facts.

## Sources

1. [Suggestion: \`uv bundle\`, \`uv build --release\` or similar to create a contained executable a la pyinstaller, py2exe · Issue #5802 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5802)
2. [Make it easier to deploy a mirror for uv-python command · Issue #10203 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10203)
3. [Add \`uv layout\` to create portable offline Python distributions · Issue #11746 · astral-sh/uv](https://github.com/astral-sh/uv/issues/11746)
4. [React Framework Next.js 16 Makes Turbopack the Default Bundler](https://www.heise.de/en/news/React-Framework-Next-js-16-Makes-Turbopack-the-Default-Bundler-10794114.html)
5. [Turbopack in 2026: The Complete Guide to Next.js's Rust-Powered Bundler - DEV Community](https://dev.to/pockit_tools/turbopack-in-2026-the-complete-guide-to-nextjss-rust-powered-bundler-oda)
6. [Releases · astral-sh/uv](https://github.com/astral-sh/uv/releases)
7. [Pip (package manager)](<https://en.wikipedia.org/wiki/Pip_(package_manager)>)
8. [What's next for \`pip lock\` ? · Issue #13953 · pypa/pip](https://github.com/pypa/pip/issues/13953)
9. [poetry 2.3.0 on Python PyPI](https://newreleases.io/project/pypi/poetry/release/2.3.0)
10. [History](https://python-poetry.org/history/)
11. [Announcing Poetry 2.3.0](https://python-poetry.org/blog/announcing-poetry-2.3.0/)
12. [Support PEP 751 - Pylock · python-poetry · Discussion #10322](https://github.com/orgs/python-poetry/discussions/10322)
13. [Enable offline installations: poetry install --download-only; poetry install --offline · Issue #2184 · python-poetry/poetry](https://github.com/python-poetry/poetry/issues/2184)
14. [Community adoption of pylock.toml (PEP 751) - Packaging - Discussions on Python.org](https://discuss.python.org/t/community-adoption-of-pylock-toml-pep-751/89778)
15. [Hatchling history - Hatch](https://hatch.pypa.io/1.18/history/hatchling/)
16. [Hatch history - Hatch](https://hatch.pypa.io/latest/history/hatch/)
17. [Can't Hatch \`build -t binary\` include all dependencies into the bundle? · Issue #2210 · pypa/hatch](https://github.com/pypa/hatch/issues/2210)
18. [hatch standalone binaries "offline" · pypa/hatch · Discussion #1717](https://github.com/pypa/hatch/discussions/1717)
19. [Changelog - Pixi by prefix.dev](https://pixi.prefix.dev/v0.48.1/CHANGELOG/)
20. [pixi - Maxwell Documentation](https://docs.desy.de/maxwell/development/python/pixi/)
21. [Python monorepo with uv and pex](https://chrismati.cz/posts/uv-pex-monorepo/)
22. [pex · PyPI](https://pypi.org/project/pex/)
23. [pex Changelog](https://data.safetycli.com/packages/pypi/pex/changelog?page=2)
24. [PyInstaller Manual — PyInstaller 6.22.3 documentation](https://www.pyinstaller.org/)
25. [pyinstaller · PyPI](https://pypi.org/project/pyinstaller/)
26. [Nuitka · PyPI](https://pypi.org/project/Nuitka/)
27. [Nuitka Release 4.0 — Nuitka the Python Compiler](https://nuitka.net/posts/nuitka-release-40.html)
28. [Nuitka/Nuitka on GitHub](https://releasealert.dev/github/Nuitka/Nuitka)
29. [Project status update · Issue #741 · indygreg/PyOxidizer](https://github.com/indygreg/PyOxidizer/issues/741)
30. [How do I ship a Python application to end users?](https://pydevtools.com/handbook/explanation/how-do-i-ship-a-python-application-to-end-users/)
31. [Releases · ofek/pyapp](https://github.com/ofek/pyapp/releases)
32. [Announcement: PyApp - Announcements - Discussions on Python.org](https://discuss.python.org/t/announcement-pyapp/41030)
33. [pex 2.46.0 · pex-tool/pex · Discussion #2829](https://github.com/pex-tool/pex/discussions/2829)
34. [Release 20261003 · astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone/releases/tag/20261003)
35. [Python now has a standard package lock file format](https://devclass.com/2025/04/04/python-now-has-a-standard-package-lock-file-format-though-winning-full-adoption-will-be-a-challenge/)
36. [Add support for PEP 751 lockfiles · Issue #12584 · astral-sh/uv](https://github.com/astral-sh/uv/issues/12584)
37. [PEP 711](https://peps.python.org/pep-0711/)
38. [Packaging PEPs](https://peps.python.org/topic/packaging/)
39. [PEP 817: Wheel Variants: switch to Informational, major update by rgommers · Pull Request #5149 · python/peps](https://github.com/python/peps/pull/5149)
40. [Any plans to support packaged binary? · Issue #10452 · astral-sh/uv](https://github.com/astral-sh/uv/issues/10452)
41. [Feature Request: Production Bundling for Python – A Single File Deployment Approach](https://github.com/astral-sh/uv/issues/12035)
42. [Support portable mode: config lookup relative to uv binary & relocatable venv Python binaries · Issue #15751 · astral-sh/uv](https://github.com/astral-sh/uv/issues/15751)
43. [Poetry: Offline installation of packages - smhk](https://smhk.net/note/2023/11/poetry-offline-installation-of-packages/)
44. [Large memory use during extraction of pixi-pack executable archive · Issue #192 · Quantco/pixi-pack](https://github.com/Quantco/pixi-pack/issues/192)
45. [Python Packaging, One Year Later: A Look Back at 2023 in Python Packaging](https://news.ycombinator.com/item?id=39009445)
46. [PYX: The next step in Python packaging](https://news.ycombinator.com/item?id=44892209)
47. [OpenAI acquires Astral to bring open source Python developer tools to Codex — but details are still fuzzy - The New Stack](https://thenewstack.io/openai-astral-acquisition/)
48. [Why aren't we uv yet? - aleyan.com](https://aleyan.com/blog/2026-why-arent-we-uv-yet/)
49. [Releases · pex-tool/pex](https://github.com/pex-tool/pex/releases)
50. [Understanding best practices for Airgapped python packages with UV. · Issue #13587 · astral-sh/uv](https://github.com/astral-sh/uv/issues/13587)
51. [uv standalone: \`uv self update \[TARGET\_VERSION\]\` doesn't work in a mirrored/offline/non-internet environment · Issue #16519 · astral-sh/uv](https://github.com/astral-sh/uv/issues/16519)
52. [Pixi Pack - Pixi by prefix.dev](http://pixi.prefix.dev/v0.46.0/deployment/pixi_pack/)
53. [Bundling dependencies with poetry (or other tools) in an air-locked system](https://groups.google.com/g/pyweb-il/c/QfmIUuO3X-I)
54. [Hatch build binary looks for file based on build system instead of target system · Issue #1933 · pypa/hatch](https://github.com/pypa/hatch/issues/1933)
55. [pex 2.98.2 · pex-tool/pex · Discussion #3222](https://github.com/pex-tool/pex/discussions/3222)
56. [Exporting a lockfile](https://docs.astral.sh/uv/concepts/projects/export/)
57. [PEP 817 - Wheel Variants: Beyond Platform Tags - Packaging - Discussions on Python.org](https://discuss.python.org/t/pep-817-wheel-variants-beyond-platform-tags/105860)
58. [OpenAI tries to build its coding cred by acquiring Astral](https://www.theregister.com/2026/03/19/openai_aims_for_the_stars/)
59. [Bun is joining Anthropic](https://bun.com/blog/bun-joins-anthropic)
