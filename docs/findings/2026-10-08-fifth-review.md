# Findings 2026-10-08: the fifth independent review, and what was done about it

The second pass of the owner's two-pass request for 2026-10-08, by a fresh agent at `9a4b481` with
[the review brief](review-brief.md), after the fourth review's fixes. Condensed, with the working
agent's verdict on each point. The reviewer ran the checks (180 tests, ruff, pyright clean),
`bundleup check` on 20 gauntlet projects, and a skill-shaped project of its own every way the
recipe uses it, Apple's Python 3.9 re-running on 3.12 included; "all of that worked".

## Fourth-review fixes, as the reviewer judged them

Adequate: the workspace-member lock, `.gitignore` for folder apps, the `python3` re-run, `--entry
python` as a drop-in python, sibling scripts, resolving from the lowest Python, pruning (POSIX),
exact `--max-size`, the size-warning wording. Partly adequate: the import check (below).
"A label, not a fix": `manifest_version` 2.

## Findings and verdicts

| # | Finding | Verdict | Done |
|---|---|---|---|
| §1, 5.2 | The fourth review's write-up claims no false import warnings on the gauntlet; gauntlet 23 warns about modules its `.pth` files provide (pywin32's `win32api` likewise) | Agree, and worse: the claim came from a scan that searched for the diagnostic's code, which the text output never shows | Folders `.pth` files add, and setuptools' `distutils` shim, count as provided; the write-up is corrected; rechecked with a scan that matches the message text, verified on a known case: no warnings on the 24 projects |
| §1, 5.1 | A pure bundle's range ignores standard-library removals: `import imp` claimed for 3.9+ | Agree: an unbacked claim in the headline feature | `_imports.py` tables of each release's added and removed modules; the range stops where the standard library lacks an import (`imp`: 3.9-3.11; `tomllib`: 3.11+), with a `python-range` warning |
| 5.3 | The standard-library list is the build machine's, not the target's | Agree | Derived for the target version from the same tables; the load-time check for header-less scripts uses every version's modules, so it never refuses a standard-library import |
| 5.4 | `--strict` ignores `large-bundle` for a `.pyz` | Agree | Fails before writing |
| 5.5 | The `--entry python` scan walks the whole folder (a script's could be `~/Downloads`), ignores `.gitignore`, follows symlinks, skips tests only at the top | Agree | Projects and folder apps: `.gitignore`, no symlinked folders, tests/docs/examples at any depth, at most 1,000 files; a script: its own folder only |
| 5.6 | The macOS re-run probe can open the "install developer tools" dialog | Agree | Apple's `python3` stub is probed only when the developer tools or Xcode are installed |
| 5.7 | `BUNDLEUP_RUNTIME_SCRIPTS` lets any script under a broad folder activate the bundle, console scripts too | Agree | Only `.py` files count; console scripts never do |
| 5.8 | Pruning: age not re-checked after locking; same-named bundles prune each other; no pruning on Windows | Partly | The re-check added. Same names: only copies unused for 30 days, so harmless. Windows: written down (a copy in use can't be told apart there) |
| 5.9 | `find_uv_lock` walks past a project that is the repository root | Agree | Stops there |
| 5.10 | The `if ...platform` substring heuristic (`if args.platform:`) | Agree | Matches `sys.platform`, `platform.system`, `os.name`, `sys.version_info`, `TYPE_CHECKING` only |
| 5.11 | `imports_in` in `_source` imported lazily by `_check` to dodge a cycle | Agree | `_imports.py` holds import scanning and the standard-library tables |
| 5.3 (4th) | The secret regex misses `service-account.json`, `prod.env` | Agree | Whole-word matching: those count, `tokenizer.json` doesn't |
| §3, Rec. 2 | The founding recipe is the one recipe not in CI | Agree | `gauntlet/skill`: python-pptx, a helper beside the scripts, pywin32 on Windows, a sibling started with `sys.executable`; built on macOS for four platforms with `--strict`, run on Linux, Windows and macOS (CI `skill`, `skill-run`) |
| §6 | Untested: `.pth` imports, target-vs-host stdlib, `_lowest`, manifest v2 | Agree | Tests added for each |
| §7 | Recipe arithmetic (144 MiB vs the fourth review's 88.7 MiB); CLAUDE.md says three reviews; ADR-0004 contradicts ADR-0041 | Agree | The recipe explains (PyMuPDF is the difference); CLAUDE.md lists five; ADR-0004 marked refined by 0041 |
| Rec. 5 | For skills, one `.pyz` per platform (or layers as separate files) so each file stays under GitHub's 100 MB without LFS | Agree it's the biggest open problem for the founding case | Roadmap, for the owner: it changes the output's shape |
| Rec. 6, §2 | Measure `pex --scie eager` for the founding case: it brings an interpreter (Windows without Python), and git delivery may sidestep code signing | Agree it deserves a measurement | Roadmap, first step of the executables investigation |
| Rec. 1 | Pilot the skill with three colleagues on three OSes before more features | Agree: five reviews are no substitute for users | For the owner (the final report says so) |
| §4 | Cut `dir`, folder apps and requirements.txt input, `large-bundle` | Disagree | The owner asked for these inputs and for a size warning on 2026-10-08; `dir` is tested on three OSes and costs little |
| 5.7 (4th), §4 | One manifest shape (one payload as one layer) | Agree in principle | Still deferred: it changes what `verify`, the gauntlet and tests read for every bundle; do it with a published manifest schema |
| §6, Rec. 10 | Fixes pushed and written up as done before CI reports | Agree | CI no longer cancels runs on main (fourth review); the final report gives CI's results, not assumptions |
| §1 | "Dead simple" has drifted: the founding recipe is a five-line command | Partly | True for multi-platform builds; `[tool.bundleup]` keeps the flags in the project (`python-platform = [...]`, `entry = "python"`), which the recipe should show |

## Not done, written down

- `_prepare` is ~135 lines; splitting it into install and analyze is a refactor for a quieter day.
- The import check reads code; modules imported by name at run time aren't seen.
