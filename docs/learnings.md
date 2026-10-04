# Learnings

Short, dated lessons: facts we discovered, surprises, gotchas. Newest first. Each entry links to
its evidence. If a lesson changes a decision, also write an ADR (see
[ADR-0001](adr/0001-record-decisions-and-learnings.md)).

Format: `- **YYYY-MM-DD** · <area> · <lesson>. Evidence: <link>.`

- **2026-10-03** · naming · Names built on "zip" read as "this makes zip files"; name the experience
  (ready to run), not the container format. Evidence: [ADR-0009](adr/0009-name-bundleup.md).
- **2026-10-03** · naming · `bundle`/`bundler` are Ruby commands preinstalled on macOS
  (`/usr/bin/bundle`); `packer` is HashiCorp's; `pack` is Cloud Native Buildpacks' CLI. Check
  command clashes, not just PyPI. Evidence: [ADR-0009](adr/0009-name-bundleup.md).
- **2026-10-03** · naming · PyPI `pack` is an empty placeholder (0.0.1, no files, Paul J. Davis):
  likely eligible for PEP 541 transfer, but transfers take months (owner contacted, ~6-week wait,
  small review team). Evidence: [PEP 541](https://peps.python.org/pep-0541/).
- **2026-10-03** · prior art · Abandoned attempts at the same idea exist on PyPI: `carryon` (0.1.3,
  Nov 2024: "Pack your Python script with its dependencies", appends a zip to the script) and
  `carton` (2016: "make self-extracting virtualenvs"). More evidence of demand and of nobody
  sticking with it.
- **2026-10-03** · tools · pex is the correctness bar: it passed every applicable gauntlet project
  except child processes (19), and every hostile condition. Evidence:
  [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · pex adds ~210 ms to every start by default (273 ms vs 59 ms for an
  installed venv). `--venv --sh-boot` gets 32 ms, but an `--sh-boot` pex runs the first `python3`
  on `PATH`, and on macOS that's 3.9, so a 3.12 pex fails with a confusing "no cp39
  distributions" error. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · On Python 3.9, pex resolves with a vendored pip 20.3.4 and its legacy
  resolver: builds take ~12 s vs ~2 s on 3.12. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · shiv always extracts to `~/.shiv` with no fallback; every bundle fails
  when `HOME` isn't writable. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · zipapps deletes all `.dist-info` by default (`--rm-patterns`), breaking
  `importlib.metadata` and entry points; it unpacks native code into `./zipapps_cache` in the
  *working directory*, so it fails from read-only directories and races on simultaneous first runs.
  Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · A naive `pip --target` + `zipapp` bundle silently loses compiled
  accelerators (PyYAML's LibYAML, mypyc'd charset-normalizer) and falls back to pure Python with
  no warning. Evidence: gauntlet project 10 in the [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · runtime · Child interpreters started with `sys.executable` don't inherit a
  bundle's `sys.path`; only zipapps handles this (via the environment). Evidence: gauntlet 19.
- **2026-10-03** · runtime · Extract-everything tools avoid `__file__`, metadata *and* native
  failures; run-from-zip tools fail more on files/metadata than on native code. Answers the
  research's open question. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · ecosystem · Every tool refused the 3.12-only project on 3.9 only because pip
  checked `requires-python`; none inspects the code, and none gave a plain-language message.
  Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · ecosystem · python-pptx reads its default template via `__file__` (zip-unsafe);
  pytz tries `__file__` and falls back to `importlib.resources`; docopt 0.6.2 ships only an sdist.
  Evidence: gauntlet projects 05, 14, 18.
- **2026-10-03** · environment · macOS's `/usr/bin/python3` is 3.9.6 (Command Line Tools), a
  realistic "user's Python" target.
- **2026-10-03** · environment · `sandbox-exec -p '(version 1)(allow default)(deny network*)'`
  blocks network for a process on macOS; used by the harness to prove bundles need no network.
- **2026-10-03** · environment · No Docker on the development machine; Linux/cross-platform runs
  need CI or another host.
- **2026-10-03** · tooling · `uv export --script file.py` exports a PEP 723 script's resolved
  dependencies as requirements.
- **2026-10-03** · research · The "gemini" research reports hallucinate and recycle sources (round 2
  cites round 1 as its main source). Trust the "compass" reports, and verify anything decisive.
  Evidence: [verification notes](research/verification-notes.md).
- **2026-10-03** · research · uv's `uv bundle` request (#5802) is labelled "wish – Not on the
  immediate roadmap"; the `uv run --watch` PR (#12847) was closed unmerged. Evidence:
  [verification notes](research/verification-notes.md).
