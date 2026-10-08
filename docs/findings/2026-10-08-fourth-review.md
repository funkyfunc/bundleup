# Findings 2026-10-08: the fourth independent review, and what was done about it

A fresh agent at `b073eb9`, with [the review brief](review-brief.md), after multi-platform layers,
recipes, `--entry python`, lock-file installs and input without a lock. Condensed, with the
working agent's verdict on each point. The reviewer ran the checks (176 tests, ruff, pyright
clean), built the founding skill's shape for four platforms (88.7 MiB, 10 s, `verify` ok) and
small inputs of its own.

## What it found working

Warm start 60 ms with python-pptx imported; `check --matrix` from the lock in 0.47 s; builds
never write into the input; the nightly suites caught a real bug (click's `python -` child) and
the fix came with a test; installing from the lock with hashes; recipes instead of presets ("a
good reversal"); layered multi-platform output; tests "real evidence, not theatre".

## Findings and verdicts

| # | Finding | Verdict | Done |
|---|---|---|---|
| 5.1 | An unrelated `uv.lock` higher in the repository was taken as the project's: unlocked subprojects failed with uv's "--locked was provided" | Agree, reproduced | A lock above counts only if that root's `[tool.uv.workspace]` members include the project, minus `exclude` |
| 5.2 / §1 | Undeclared imports aren't checked except for header-less scripts, though a bundle can't see the machine's packages; `--entry python` scripts never | Agree: the most common run-time failure | `undeclared-import` warning on every build: the script, a folder app, the project's installed files, and with `--entry python` the scripts in the folder (their neighbours count). Optional imports (`try/except ImportError`, `TYPE_CHECKING`, platform or version checks) don't count. No false warnings across the 24 gauntlet projects |
| 5.3 | A folder app bundled everything not hidden: credentials, data, earlier `.pyz` outputs | Agree | In a git work tree only what git would track (`.gitignore` applies); `.pyz` and `requirements*.txt` never; `secret-file` warning for keys, certificates and credentials files |
| 5.4 / §3.2 | The re-run looked only for `python3.X`, which Apple's `/usr/bin/python3` lacks; the error named one payload | Agree, reproduced: the founding case on a typical Mac | On the failure path, plain `python3`/`python` on PATH (and `/usr/bin/python3`) are asked their version; the message names every version a multi-payload bundle allows |
| 5.5 | `--entry python` isn't a drop-in `python`: piped input opened a prompt, `-` rejected, `-c` code not the real `__main__` (pickle), the usage named the project | Agree | All fixed; interpreter options (`-u`, `-X`) get a message saying to put them before the bundle |
| 5.6 / §3.3 | A skill script that runs a sibling with `sys.executable` loses the packages | Agree, reproduced | Scripts under the folder of the script `--entry python` was given count as the bundle's code ([ADR-0040](../adr/0040-entry-python-runs-any-script.md), [ADR-0037](../adr/0037-children-activate-only-for-bundle-code.md)) |
| 5.7 | Two manifest shapes share `manifest_version: 1`; `write_pyz` branches on one payload | Partly | Layered manifests are `manifest_version: 2`. Unifying (one payload as one layer) changes what `verify`, the gauntlet and tests read for every bundle; left for when a manifest schema is published |
| 5.8 | Unlocked multi-target builds resolve per payload, so payloads can bundle different versions | Agree | Resolved from the lowest Python asked for; checked: two payloads, same PyYAML |
| 5.9 / §3.5 | No cache pruning outside the CLI: every skill update leaves a 35-40 MB copy on users' laptops | Agree | A new copy removes older copies of the same bundle unused for 30 days and held by no running program (POSIX) |
| 5.10 | The `unlocked` hint for a setup.py project says `uv lock`, which needs a pyproject.toml | Agree | `pip lock .` for those |
| 5.11 | `--max-size` ignores the loader and manifest | Agree, minor | The finished file is checked before it replaces anything |
| 5.12 | The `large-bundle` hint shows one payload's sizes as if each; merged findings labelled with the first payload's target | Agree | Worded honestly; a finding every payload has is unlabelled, others list each payload |
| 5.13 | Duplicated C-library and macOS checks in the loader | Agree | `_check_system` reuses the fit checks |
| 5.14 | Raw uv failures surface as "uv export failed" with uv's text | Partly | uv's text is the useful part (style guide rule 25); the common causes already have their own messages |
| §4 | `large-bundle` encodes a GitHub fact in code, what ADR-0039 removed presets to avoid | Partly | Kept (the owner asked for a size warning) but only when the bundle is written into a git work tree, where the fact applies |
| §1 | README: suites "pass from bundles" (click fails 6 in the venv too); vision: `macos` "just works" (it's arm64 only); `build --help`, MISSION and CLAUDE.md describe a lock as required | Agree | All corrected |
| §3.4 / Rec. 8 | Windows usually has no Python; APM's Git LFS support is unverified | Agree | The skill recipe says both plainly; executables stay on the roadmap |
| §6 | Commits on main without a completed CI run (cancel-in-progress) | Agree | CI no longer cancels runs on `main` |
| Rec. 1 | Ship 0.1 now and actually freeze scope | Disagree for now | The owner chose to build the value proposition first and test it themselves before others see it (2026-10-07); the freeze rule in CLAUDE.md reflects the owner's current direction, not the third review's |
| Rec. 10 | Stop writing ADRs for designs the owner hasn't reviewed | Partly | ADRs are how the owner asked decisions to be kept; the ones awaiting review are listed in the report to the owner instead |
| §2 | `verify` checks a bundle against its own manifest; it proves integrity, not provenance | Agree | Nothing claims otherwise; signing is out of scope until there are users |

## Not done, written down

- `_prepare` (~110 lines) could split into install and analyze.
- One manifest shape for all bundles, with a published schema.
- The import check reads code, not behaviour: a module imported by name at run time
  (`importlib.import_module(name)`) isn't seen; a false warning can be silenced by making the
  import optional or adding the package.
