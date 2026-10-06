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

- Done: research (4 rounds, see [docs/research/](docs/research/README.md)), mission/vision, gauntlet of 23 projects (21 is the large pure-Python
  performance check), baseline of pex/shiv/zipapps ([findings](docs/findings/2026-10-03-baseline.md)).
- Named `bundleup` ([ADR-0009](docs/adr/0009-name-bundleup.md)); repo github.com/funkyfunc/bundleup.
  PyPI has only the 0.0.1 placeholder; the working bundler isn't released yet.
- **Milestone 1 done (2026-10-04):** `bundleup <project-dir | script.py>` builds `dist/<name>.pyz`
  for the current platform and one Python version. Passes every gauntlet project on 3.9 and 3.12
  (incl. 19, child processes) and every hostile condition; first run faster than shiv; warm start
  equal to an installed venv (on 3.9, only when both use the same binary: `/usr/bin/python3`'s
  xcrun shim adds ~5 ms); builds 1.8–6× faster than pex
  ([findings](docs/findings/2026-10-04-milestone-1.md)). Design in
  [ADR-0010](docs/adr/0010-bundle-format-and-loader.md) (format, loader, cache; accepted) and
  [ADR-0011](docs/adr/0011-cli-and-build-pipeline.md) (pipeline accepted; its CLI is superseded by
  [ADR-0016](docs/adr/0016-cli-and-api-conventions.md): verbs, `bundleup build [PATH]`, not built
  yet).
- bundleup depends on the `uv` package (bundled binary) but prefers a uv ≥ 0.9 on `PATH`
  (ADR-0011, at the user's request).
- **Builds are 2-9× faster than pex** after parallel compression and a per-wheel bytecode cache
  (gauntlet 21: 2.5 s vs pex 5.5 s; [findings](docs/findings/2026-10-05-faster-builds.md),
  [ADR-0020](docs/adr/0020-parallel-zip-and-bytecode-cache.md)). Rust stays reserved
  for the analyzer's scanner ([findings](docs/findings/2026-10-04-large-project-and-rust.md)).
- Engineering tooling done (Ruff, pyright, hooks; [ADR-0015](docs/adr/0015-engineering-tooling.md)).
- **CI** (public repo, free): checks, tests on 4 OSes, and the gauntlet on Linux x64/arm64, Windows
  x64 and macOS arm64 × Python 3.9/3.11/3.12. bundleup passes everywhere, including Windows.
- **Correctness checks:** every build fails unless the payload matches `uv.lock` and every
  wheel's `RECORD` exactly (`src/bundleup/_verify.py`); the gauntlet's `matches-venv` condition
  compares each bundle with a `uv sync` install. Every bundle carries `manifest.json`;
  `bundleup verify` checks a bundle and its unpacked copy against it
  ([ADR-0019](docs/adr/0019-manifest-and-verify-command.md)). Still to do from roadmap item 4:
  real-world test suites. The nightly top-PyPI smoke test exists: the top 100 pass on all four
  OSes ([findings](docs/findings/2026-10-05-ci-and-correctness.md)).
- **CLI follows the style guide** (ADR-0016): `bundleup build [PATH]`, `--json`, `error:`/`hint:`,
  exit codes, a typed library API with lazy exports
  ([ADR-0018](docs/adr/0018-package-layout-and-lazy-api.md)). Open rules are listed
  in the style guide's "Implementation status".
- **Cross-target builds** (ADR-0014): `bundleup build --python 3.11 --python-platform linux` on a Mac;
  wheels checked against the target; CI proves three build→run pairs.
- **Nightly corpus** (item 6): 20 PyPI CLIs + 2 repos run installed vs bundled; failures become
  `corpus-failure` issues (agent triage deferred).
- **Runtime hardening** (item 8): unpack lock for simultaneous first runs; bundles hide the
  machine's own packages unless `BUNDLEUP_INHERIT_PATH=1` ([ADR-0021](docs/adr/0021-isolate-from-machine-packages.md));
  `bundleup cache list|clean` ([ADR-0022](docs/adr/0022-cache-command.md)).
- Next: see [docs/roadmap.md](docs/roadmap.md) "Next up" (item 10, `bundleup check`).

## Layout

```
MISSION.md              goal and scope
pyproject.toml, src/bundleup/  the package (ADR-0018): __init__.py (public API), _cli.py, _build.py,
                        _verify.py (lock and RECORD checks), _errors.py, _term.py, _loader.py
                        (the bundle's __main__), _platforms.py (cross targets), _zipwriter.py
                        (parallel zip), _bytecode.py (bytecode cache), _cache.py (cache list/clean)
tests/snapshots/        CLI output and API snapshots; docs/cli-reference.md is generated too
docs/schema/            JSON Schemas of each command's `--json` (build, verify, cache)
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
gauntlet/cross.py       cross-target gauntlet: build on one OS for another, run on the target
.github/workflows/       ci.yml (every push: checks, tests, gauntlet matrix); nightly.yml (smoke
                        test); corpus.yml (corpus run + corpus-failure issues)
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
UPDATE_SNAPSHOTS=1 uv run pytest -q tests/test_cli.py                       # after an intended CLI change
```

## Working rules

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
  same time. Commit only when asked. Commit messages describe the change only. No AI attribution
  (no `Co-Authored-By`, no "Generated with" lines).

## Working with the user

The user is an experienced JavaScript/TypeScript developer who is newer to Python. Explain Python
concepts by comparison with Node/npm equivalents. They prefer a recommendation over a survey of
options.
