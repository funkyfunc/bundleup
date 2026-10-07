# Findings 2026-10-07: an independent review of the repo

The owner asked for a skeptical review, not a flattering one. An agent that hadn't worked on the
code reviewed the whole repo read-only on 2026-10-06/07: docs, all of `src/`, tests, the gauntlet
and CI history. It ran the checks and built several gauntlet projects. Its report is below,
lightly edited for length. The working agent then checked the most surprising claims (notes at
the end). The owner asked for all of it to be fixed (2026-10-07); the roadmap tracks the work.

## The report

### 1. Mission alignment

The core works and is fast: gauntlet 03 builds in 0.34 s with a 48 ms warm start, mismatch
errors are one clear sentence, builds are reproducible and checked against each wheel's `RECORD`.
But the docs promise more than the code delivers:

- **"Runs on any matching Python" is really "runs on exactly one minor version."** A pure-Python
  project with `requires-python >=3.9`, built by default, targets 3.12 and refuses macOS's
  `python3` (3.9) and 3.13. vision.md says the default targets "the Python range your project
  declares". The shebang is `#!/usr/bin/env python3`, so `./app.pyz` fails on a stock Mac.
- **MISSION says pure-Python code runs from the zip**; the loader extracts everything (shiv's
  model).
- **`check` is thinner than advertised**: two checks (`syntax-error`, `data-files`) plus format
  checks, while vision.md lists `__file__` reads, metadata, dynamic imports and missing wheels and
  calls the check "what sets us apart". (`_check.py` itself correctly says full extraction makes
  most of those unnecessary.)
- **"The lockfile decides" doesn't hold without a lockfile**: a project with no `uv.lock` builds
  silently and gets a `uv.lock` written into it; a PEP 723 script without a lock is re-resolved on
  every build, and the lock-vs-bundle check then compares the bundle with its own resolution.
- **Promised but missing**: verb-less `bundleup app.py`, `--target a,b`, a multi-platform
  `.pyz`, `[tool.bundleup]` configuration.
- **README's status line is stale.**
- **Scope creep**: Lambda and `dir` formats, presets, nightly corpus, real suites, a weekly
  summary and planned AI triage, all before a 0.1 release or one external user.

### 2. Differentiator

Better, with evidence: fast warm start by default (pex adds ~210 ms unless you know
`--venv --sh-boot`); child processes see the bundle's packages (gauntlet 19, pex and shiv fail);
cache hardening beyond shiv's; plain errors; reads `uv.lock`; reproducible output with `RECORD`
verification.

A re-implementation: the runtime is shiv's model with better hardening. pex already has
`--pylock`, `--project`, `--venv-repository` (reuses a uv-synced venv), multi-platform artifacts
and `--scie` executables. **"2-9× faster than pex" compares against pex resolving through pip**;
most of bundleup's build speed is uv's.

Defensibility is low: a `uv zipapp` would make it redundant (uv#5802 is still a "wish"); a
"fast defaults" profile in pex would close the start-up gap. The one defensible asset would be a
strong target-aware analyzer, not built yet. Lambda is three uv commands or SAM. Claude Skills
is the genuine niche, but **`--target claude-api` fails on gauntlet 14** (pillow 12.3 publishes
only `manylinux_2_27/2_28` wheels; the preset pins `manylinux_2_17`), with a wrong hint ("only
publishes source").

### 3. Would the reviewer use it?

Yes today for an internal CLI going to a fleet with one known Python, CI helper scripts, offline
HPC jobs (over shiv, for the cache hardening and warm start). No for tools handed to unknown users
(one minor version), Lambda (uv recipe or SAM), Claude Skills (broken preset), or anything that
launches other Python programs (the PYTHONPATH leak). Needed to adopt: a PyPI release,
pure-Python bundles that run on several minor versions, the leak fixed, `[tool.bundleup]`, a
working claude-api preset.

### 4. Keep / cut / defer

Keep: loader and cache hardening, uv-driven builds, reproducibility, lock and RECORD verification
(softened), `--json` and exit codes, cross builds, `syntax-error`, the gauntlet.
Simplify or cut: `verify` (a manifest inside the same file proves no corruption, not
authenticity; fold the cache check elsewhere); the weekly summary, corpus auto-issues and AI
triage before there are users; `dir` (no evidence of demand); freeze Lambda; presets only when
tested end to end with a native dependency.
Missing and more important: pure-Python bundles for several minor versions; a lock-only,
multi-target wheel coverage check (`uv.lock` lists every wheel filename, so "pillow has no wheel
for `manylinux_2_17`; `2_28` works" is answerable in milliseconds); runtime libc/macOS-version
checks; a versioned shebang; warnings on unlocked input; `[tool.bundleup]`.

### 5. Code quality (most severe first)

1. **PYTHONPATH leak** (`_loader.py` `_activate`): any Python the app launches, in any venv and
   at any version, imports the bundle's packages first (demonstrated: a bundled script running
   `python3.13 -c "import rich"` got the bundle's rich). Contradicts ADR-0021's isolation.
   multiprocessing doesn't need it (spawn passes `sys.path`).
2. One Python version by default, with a `python3` shebang.
3. The cross-target error turns any "not compatible with the target" into "only publishes source".
4. Unlocked inputs: silent `uv.lock` creation; unpinned script builds.
5. Self-verification hard-fails builds on wheel quirks: the nightly smoke run of 2026-10-06 failed
   on Windows (langchain → ormsgpack, backslash paths in `RECORD`) and blamed itself.
6. `dir` and `lambda` outputs use unchecked-hash `.pyc`, so edited `.py` files are ignored.
7. The printed Lambda handler comes from any console script (`handler g14_pptx.main` for a CLI).
8. `--strict` with an oversized Lambda zip writes the output, then deletes it, destroying the
   previous good artifact.
9. No libc or macOS-version check at start-up; `_platforms.accepts` ignores the glibc level.
10. `.pyc` files under `sys.pycache_prefix` sit outside the cache; `cache clean` misses them.

Structure: `_build.py` is 1,212 lines with about eight jobs (split into source, Python, uv,
outputs, orchestration); wheel-tag parsing is written three times; pluralising and "... and N
more" are duplicated about six times; the entry point is a bare `tuple[str, str, str]`; `_cli.py`
repeats the same boilerplate per command. Earned positives: the loader (compiles on any
Python 3, stat-only warm path, atomic rename plus `flock`); the zip writer's ZIP64 tests; CLI
snapshot and API-surface tests.

### 6. Testing and process

The gauntlet is the best asset and proportionate; unit tests are fast and meaningful. Five
workflows are overbuilt before a release: the red smoke run opened no issue, so nobody watches
it. Gaps that would have caught real bugs: presets end to end with a native dependency, unlocked
input, leakage into a different Python, musl, Windows-style `RECORD` paths. Benchmarks should
include pex's best configuration. The ADR/docs process now costs more than it saves: 26 ADRs in 4
days and ~9.7k lines of docs, yet mission, vision and README contradict the code; the roadmap's
struck-through history and CLAUDE.md's "Current state" have become changelogs.

### 7. Repo in general

Onboarding has six must-read documents; there's no install path (PyPI placeholder); `targets` and
`cache list` print listings to stderr, so piping them doesn't work; the Skills recipe is untested.

### 8. Top 10 recommendations, by impact

1. Pure-Python bundles that run on every minor version in `requires-python`; a versioned shebang.
2. Stop exporting PYTHONPATH to every child by default.
3. Fix the claude-api preset (probably `manylinux_2_28`) and test every preset end to end on
   gauntlet 14.
4. A lock-only, multi-target wheel coverage check from the lock's wheel list.
5. Refuse or loudly warn on unlocked input; never write `uv.lock` into the user's project.
6. Ship 0.1 to PyPI with `[tool.bundleup]` configuration.
7. Rewrite mission, vision and README to match the code.
8. Re-benchmark against pex's best path (`--venv-repository` / `--pylock`, `--venv`).
9. Normalise `RECORD` paths; checked-hash `.pyc` for `dir` and `lambda`.
10. Freeze the nightly/weekly machinery and new formats; split `_build.py`; remove duplicated
    helpers.

## Checked by the working agent (2026-10-07)

- **Silent `uv.lock`: confirmed.** Gauntlet 03 copied without its lock built with exit 0 and a
  new `uv.lock` appeared in the copy.
- **claude-api preset: confirmed.** Gauntlet 14 with `--target claude-api` fails with the wrong
  hint; the same build with `--python-platform x86_64-manylinux_2_28` succeeds (14.0 MiB).
- **Windows smoke failure: confirmed.** ormsgpack 1.12.2's Windows wheels list `RECORD` paths with
  backslashes (`ormsgpack\py.typed`); pip and uv install them, bundleup's check compared literally.
  The 2026-10-06 scheduled smoke run otherwise passed 799 of 800 (top 200 × 4 OSes; uvloop's skip
  on Windows is correct). The corpus and suites runs that night passed everywhere.

Where the working agent partly disagreed, and what it proposed instead:

- **Children:** keep `sys.executable` children working (gauntlet 19, a real difference from pex
  and shiv) but scope it, so only the same interpreter picks up the bundle.
- **`verify`:** keep it (already built; checking the unpacked copy is useful), lower priority.
- **Nightlies:** keep smoke, corpus and suites (the first night found a real bug, and they're free
  on a public repo); make smoke failures file issues; pause the weekly summary and AI triage.
- **`dir` and Lambda:** freeze rather than cut; both are tested.
