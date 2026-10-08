# bundleup

An esbuild-style bundler for Python: pack a locked project into one checked `.pyz` per platform
that runs on plain Python with no install step, and report before shipping what won't survive
packing. **Dead simple to use, but also powerful and fast.**

Many agents work on this across fresh conversations. The files below are the project's memory.
If it isn't written down, the next agent won't know it.

## Read first

1. [MISSION.md](MISSION.md): goal, why, scope, what "done" means.
2. [docs/adr/README.md](docs/adr/README.md): decisions already made. **Don't contradict an
   accepted ADR without writing a new one that supersedes it.**
3. [docs/learnings.md](docs/learnings.md): lessons and gotchas already discovered.
4. Latest file in [docs/findings/](docs/findings/): most recent measurements.
5. [docs/roadmap.md](docs/roadmap.md) **"Next up"**: the ordered work list. Pick the first
   unfinished item.
6. Writing code? [docs/python-for-js-reviewers.md](docs/python-for-js-reviewers.md) has the code
   style rules (the owner reviews as a JS developer), and [docs/references.md](docs/references.md)
   lists projects to learn from before building something new. Changing the CLI or public API?
   Follow [docs/cli-style-guide.md](docs/cli-style-guide.md).

Also: [docs/vision.md](docs/vision.md) (positioning and use cases), [docs/python-primer.md](docs/python-primer.md)
(Python packaging for JS developers), [docs/research/](docs/research/README.md) (background; the
"gemini" reports are unreliable, see the README there).

## Keeping knowledge (required)

Do these **as you go**, not only at the end:

- **Made or changed an important decision?** Write an ADR: copy
  [docs/adr/template.md](docs/adr/template.md) to the next number, add it to the index. Important
  means it affects direction, scope, architecture, public behaviour, dependencies, or reverses
  earlier work. If the user hasn't confirmed it, mark it **Proposed** and say so.
- **Never rewrite an accepted ADR.** Supersede it with a new one; only change the old one's status.
- **Learned something non-obvious?** Add a dated line to [docs/learnings.md](docs/learnings.md)
  with a link to the evidence: tool behaviour, a failure mode, an environment quirk, a dead end.
- **Ran an experiment or measurement?** Write it up in `docs/findings/YYYY-MM-DD-<topic>.md`:
  setup, results, what it means. Link it from learnings and any ADR it affects.
- **Found a new way bundling breaks?** Add a gauntlet project for it (see
  [ADR-0007](docs/adr/0007-gauntlet-is-the-contract.md)).
- **Before finishing a session:** check whether anything decided or learned is still only in the
  conversation, and write it down. Update "Current state" below if it changed.

## Current state

A snapshot, not a changelog: history is in [docs/roadmap.md](docs/roadmap.md) "Done", the ADRs
and git.

- **What works (2026-10-07):** `bundleup build|check|targets|verify|cache` from a project
  (`uv.lock` or `pylock.toml`; a lockfile is required, ADR-0028) or a PEP 723 script. Outputs: a
  `.pyz` (default), `--format dir`, `--format lambda`; `--max-size`. No named targets: each
  destination is a tested recipe in docs/recipes.md (ADR-0039). Builds for this machine or another
  platform. Pure-Python bundles run on every
  Python version their lock allows (ADR-0030) and on any OS when the lock agrees (ADR-0034);
  compiled ones on one version and platform, and one `.pyz` can carry a payload per platform and
  version (ADR-0038). A stale lock is an error (ADR-0033). Every build checks the code
  and, for other platforms, wheel coverage from the lock (ADR-0024, ADR-0031).
- **Runtime:** unpacks once to a content-addressed cache; checks Python version, platform, CPU,
  C library, macOS version; isolates from the machine's packages; children of the bundle's own
  interpreter see its packages, other Pythons don't (ADR-0027).
- **Evidence:** the gauntlet (24 projects, every hostile condition, plus running pure bundles on
  every other installed Python) passes locally and in CI on Linux x64/arm64, macOS arm64 and
  Windows; Lambda zips run in AWS's Lambda image; nightly: top-200 PyPI smoke test, a 22-program
  corpus and four real test suites (failures open issues). Warm start equals an installed venv.
- **Speed** ([findings](docs/findings/2026-10-07-speed-vs-pex-best.md)): against pex's fastest
  configuration, builds 1.1-2.4× faster; warm start equals a venv; first runs 2.3-15× faster.
- **Not yet:** a PyPI release (0.0.1 is a placeholder; [docs/releasing.md](docs/releasing.md)).
- **ADR status:** 0023-0026 and 0033-0038 are **Proposed** (written while the owner was
  away); 0039 is accepted; 0027-0032 are accepted fixes the owner asked for, with designs the owner hasn't reviewed.
  Three independent reviews: [first](docs/findings/2026-10-07-independent-review.md),
  [second](docs/findings/2026-10-07-second-review.md), [third](docs/findings/2026-10-07-third-review.md).
- bundleup depends on the `uv` package (bundled binary) but prefers a uv ≥ 0.9 on `PATH`
  (ADR-0011). Rust stays reserved for a future scanner (ADR-0008).

## Layout

```
MISSION.md              goal and scope
pyproject.toml, src/bundleup/  the package (ADR-0018): __init__.py (public API), _cli.py; the build
                        in steps: _build.py (orchestration, build()/check()), _source.py (project
                        or script, lockfile), _python.py (target interpreter), _uv.py (export,
                        install), _payload.py (installed tree, entry, bytecode, lock checks),
                        _outputs.py (pyz/dir/lambda writers), _steps.py (progress, run);
                        _check.py (the analysis), _verify.py (lock/RECORD checks, `verify`),
                        _loader.py (the bundle's __main__), _runtime.py + _sitecustomize.py
                        (copied into each payload, ADR-0027), _platforms.py, _formats.py
                        (Format, sizes), _zipwriter.py, _bytecode.py, _cache.py, _errors.py,
                        _term.py, _text.py
tests/snapshots/        CLI output and API snapshots; docs/cli-reference.md is generated too
docs/schema/            JSON Schemas of each command's `--json` (build, check, targets, verify, cache)
tests/                  pytest: loader/CLI edge cases the gauntlet doesn't reach
docs/roadmap.md         "Next up" work list, then possible future directions
docs/python-for-js-reviewers.md  code style rules + review guide for the JS-fluent owner
docs/references.md      open-source projects to learn from, by area
docs/cli-style-guide.md CLI and library API rules (ADR-0016)
docs/adr/               decisions (ADRs)
docs/learnings.md       lessons log
docs/findings/          experiment write-ups
docs/research/          research reports, syntheses, verification notes; prompts/ = one brief per round
gauntlet/projects/      test projects, one failure mode each (gauntlet.toml describes each)
gauntlet/check_native.py  control group: projects run installed normally
gauntlet/run_bundlers.py  build + run with bundleup and existing bundlers, hostile conditions
gauntlet/bench.py       sequential speed benchmark (build, first run, warm start) vs venv/shiv/pex
gauntlet/snapshot.py    describes installed packages; the matches-venv condition compares two snapshots
gauntlet/smoke.py       nightly breadth test: top PyPI packages bundled and compared with a venv
gauntlet/corpus*.py, corpus.toml  nightly corpus: real CLIs run installed vs bundled; failures -> issues
gauntlet/weekly_summary.py  weekly findings page from the nightly smoke + corpus results (weekly.yml)
gauntlet/cross.py       cross-target gauntlet: build on one OS for another, run on the target
gauntlet/formats.py     `dir` and Lambda outputs: run as a host app would, Lambda in AWS's image
gauntlet/suites.py, suites.toml  real projects' test suites, venv vs bundle (CI only, suites.yml)
.github/workflows/       ci.yml (every push: checks, tests, gauntlet matrix); nightly.yml (smoke
                        test); corpus.yml (corpus run + corpus-failure issues); suites.yml (test
                        suites); weekly.yml (Monday summary of the nightly runs)
gauntlet/report.py      results JSON -> markdown
gauntlet/results/       committed results
gauntlet/.work/         scratch (git-ignored)
```

## Commands

```bash
uv run gauntlet/check_native.py                       # control group: must all pass
uv run gauntlet/run_bundlers.py --conditions --out <name>
uv run gauntlet/report.py gauntlet/results/<name>.json > gauntlet/results/<name>.md
uv run gauntlet/run_bundlers.py --tool bundleup --conditions --out <name>   # just bundleup
uv run gauntlet/bench.py 03 13 --python 3.12 --python 3.9                   # speed claims
uv run pytest -q tests                                                      # loader/CLI edge cases
uv run ruff format . && uv run ruff check . && uv run pyright               # the checks (ADR-0015)
uvx pre-commit install                                                      # git hooks, once per clone
uv run bundleup build <project-or-script> [--python 3.9] [-o out.pyz] [-v]  # try it
uv run bundleup check <project-or-script> [--python 3.9] [-v]              # findings + sizes
UPDATE_SNAPSHOTS=1 uv run pytest -q tests/test_cli.py                       # after an intended CLI change
```

## Working rules

- **Scope is frozen until 0.1 has users** (third review): no new formats, named targets or nightly
  automation. Write an ADR only for public behaviour; the owner reviews the Proposed ones.
- **Measure, don't claim.** Speed, size and correctness claims come from gauntlet runs compared
  with pex.
- **The control group must pass** before trusting any bundler result. A failure there is a broken
  test.
- **The checks must pass** (Ruff format + lint, pyright, pytest) before committing; the git hooks
  run them. Fix what they flag following [python-for-js-reviewers.md](docs/python-for-js-reviewers.md);
  every `noqa` / `pyright: ignore` carries a reason.
- **Use uv** for all Python tooling. Standalone scripts use PEP 723 headers and run with `uv run`.
- **Mind the target Pythons:** the runtime bootstrap must work on macOS's system Python 3.9.
- **Git:** stage explicit paths, never `git add -A`: other sessions may be editing the repo at the
  same time. Work on a branch and merge to `main` when CI is green; commit each fix as soon as it
  passes (never `git checkout -- .` over uncommitted work). Commit only when asked. Commit messages describe the change only. No AI attribution
  (no `Co-Authored-By`, no "Generated with" lines).

## Working with the user

The user is an experienced JavaScript/TypeScript developer who is newer to Python. Explain Python
concepts by comparison with Node/npm equivalents. They prefer a recommendation over a survey of
options.
