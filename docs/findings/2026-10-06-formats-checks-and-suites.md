# Findings 2026-10-06: the check, other formats, and real test suites

Work done while the owner was away (roadmap items 10-12 and the rest of item 4). Everything below
was measured; links go to the runs.

## Two new ways bundling broke, both fixed

| Gauntlet | What broke | bundleup before | after | pex | shiv | zipapps | plain zipapp |
|---|---|---|---|---|---|---|---|
| 22-wheel-executables | ruff's program is a wheel *script* (`bin/ruff`) | dropped (`bin/` removed) | pass | fail | pass | fail | (not run) |
| 23-pth-files | setuptools' distutils shim, a path `.pth`, pywin32 on Windows | `.pth` ignored | pass | fail | fail | pass | fail |

Both on Python 3.9 and 3.12 under every hostile condition, locally and in CI (Windows covers
pywin32). [ADR-0023](../adr/0023-payload-behaves-like-site-packages.md).

## `bundleup check` (and every build)

- No findings on gauntlet 03, 10, 13-15, 20-23 on Python 3.9 and 3.12: torch, sympy, Django,
  boto3, NumPy, lxml, Pillow. Real findings: a project with a `match` statement built for 3.9
  (error); ipykernel's kernel spec under `share/jupyter/` (warning).
- Whole `check` runs: 0.1-0.7 s for small projects, 2-4 s for gauntlet 21 (147 MB unpacked).
- [ADR-0024](../adr/0024-check-command-and-build-analysis.md).

## `--format dir` and `--target lambda`

- `dir`: every gauntlet project runs with only the directory on `PYTHONPATH` on macOS
  ([local results](../../gauntlet/results/formats-dir-2026-10-06.json)), Linux and Windows (CI),
  except 23 (`.pth` files need the loader; `check` warns `pth-not-run`).
- Lambda: every gauntlet project, built on Linux with `--target lambda` / `lambda-arm64`, runs
  inside AWS's own image (`public.ecr.aws/lambda/python:3.13`, runtime interface emulator,
  read-only `/var/task`) on x86_64 and arm64, except 23. Gauntlet 19 (child processes) passes:
  the working directory is `/var/task`. CI run
  [37412908169](https://github.com/funkyfunc/bundleup/actions/runs/37412908169).
- NumPy for Lambda from a Mac: 19.8 MiB zip in 4.5 s.
- [ADR-0025](../adr/0025-dir-and-lambda-formats-and-presets.md).

## Real projects' own test suites against their bundles

[`gauntlet/suites.py`](../../gauntlet/suites.py) on GitHub's runners: each suite runs in a venv and
from a bundle whose entry point is pytest; a probe confirms the module under test came from the
bundle's cache. Run [37412915457](https://github.com/funkyfunc/bundleup/actions/runs/37412915457),
Python 3.12:

| Suite | Linux x64 | Linux arm64 | macOS arm64 | Windows x64 |
|---|---|---|---|---|
| click 8.5.0 | 1,985 passed, 6 failed* | same | 1,984 / 6* | 1,908 / 6* |
| packaging 26.3 | 62,423 passed | same | 62,422 + 1 skipped | 62,422 + 1 skipped |
| markupsafe 3.0.4 (compiled) | 79 passed, 1 skipped | same | same | same |
| itsdangerous 2.2.0 | 297 passed | same | same | same |

Bundle and venv counts are identical everywhere. *The same 6 click tests fail in the venv: they
test the repository at the tag against the released package, not bundling.

## pylock.toml input

Builds from a uv-written lock (gauntlet 13, also for Lambda) and a `pip lock` one (gauntlet 03).
uv refuses a `pylock.toml` alongside other requirements, so a project the lock doesn't list is
installed in a second step. [ADR-0026](../adr/0026-pylock-toml-input.md).
