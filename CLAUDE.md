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

Also: [docs/vision.md](docs/vision.md) (positioning), [docs/roadmap.md](docs/roadmap.md) (possible
future directions, not commitments), [docs/python-primer.md](docs/python-primer.md)
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

- Done: research (2 rounds), mission/vision, gauntlet of 21 projects, baseline of pex/shiv/zipapps
  ([findings](docs/findings/2026-10-03-baseline.md)).
- Named `bundleup` ([ADR-0009](docs/adr/0009-name-bundleup.md)); repo github.com/funkyfunc/bundleup.
  PyPI has only the 0.0.1 placeholder; the working bundler isn't released yet.
- **Milestone 1 done (2026-10-04):** `bundleup <project-dir | script.py>` builds `dist/<name>.pyz`
  for the current platform and one Python version. Passes every gauntlet project on 3.9 and 3.12
  (incl. 19, child processes) and every hostile condition; first run faster than shiv; warm start
  equal to an installed venv (on 3.9, only when both use the same binary: `/usr/bin/python3`'s
  xcrun shim adds ~5 ms); builds 1.8–6× faster than pex
  ([findings](docs/findings/2026-10-04-milestone-1.md)). Design in
  [ADR-0010](docs/adr/0010-bundle-format-and-loader.md) (format, loader, cache) and
  [ADR-0011](docs/adr/0011-cli-and-build-pipeline.md) (CLI, pipeline), both **Proposed**: awaiting
  the user's review.
- Next: user review of ADR-0010/0011; Linux runs (CI); cross-platform and multi-platform bundles;
  the build-time analyzer (`bundleup check`); `pylock.toml` input; cache cleanup. See the
  findings' "Gaps and next steps".

## Layout

```
MISSION.md              goal and scope
pyproject.toml, src/bundleup/  the bundleup package: cli.py, build.py, _loader.py (bundle's __main__)
tests/                  pytest: loader/CLI edge cases the gauntlet doesn't reach
docs/roadmap.md         possible future directions (each needs an ADR first)
docs/adr/               decisions (ADRs)
docs/learnings.md       lessons log
docs/findings/          experiment write-ups
docs/research/          research reports, prompts, verification notes
gauntlet/projects/      test projects, one failure mode each (gauntlet.toml describes each)
gauntlet/check_native.py  control group: projects run installed normally
gauntlet/run_bundlers.py  build + run with bundleup and existing bundlers, hostile conditions
gauntlet/bench.py       sequential speed benchmark (build, first run, warm start) vs venv/shiv/pex
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
uv run bundleup <project-or-script> [-p 3.9] [-o out.pyz]                   # try it
```

## Working rules

- **Measure, don't claim.** Speed, size and correctness claims come from gauntlet runs compared
  with pex.
- **The control group must pass** before trusting any bundler result. A failure there is a broken
  test.
- **Use uv** for all Python tooling. Standalone scripts use PEP 723 headers and run with `uv run`.
- **Mind the target Pythons:** the runtime bootstrap must work on macOS's system Python 3.9.
- **Git:** commit only when asked. Commit messages describe the change only. No AI attribution
  (no `Co-Authored-By`, no "Generated with" lines).

## Working with the user

The user is an experienced JavaScript/TypeScript developer who is newer to Python. Explain Python
concepts by comparison with Node/npm equivalents. They prefer a recommendation over a survey of
options.
