# ADR-0036: A plain `python3` shebang and a re-run with a matching Python; `check --matrix`; in-use copies are kept

- **Status:** Accepted (the owner, 2026-10-08)
- **Date:** 2026-10-07
- **Deciders:** an agent, from the [third independent review](../findings/2026-10-07-third-review.md)
- **Supersedes:** the versioned shebang of [ADR-0030](0030-pure-python-bundles-run-on-a-range.md);
  extends [ADR-0031](0031-wheel-coverage-from-the-lock.md) and [ADR-0022](0022-cache-command.md)

## Context

- ADR-0030 gave single-version bundles a `#!/usr/bin/env python3.X` shebang. The third review
  showed it fails on a stock Mac (`env: python3.9: No such file or directory`: macOS has only
  `python3`), and a `/bin/sh` preamble would trouble Windows' `py` launcher.
- "Where can I ship this?" needed one build per platform; the lock already answers it.
- `cache clean` could delete a copy a long-running program still used ("last used" is marked at
  start-up only).

## Decision

- **Every bundle's shebang is `#!/usr/bin/env python3`.** When the Python running it is outside
  the bundle's range, the loader looks for a matching `python3.X` on `PATH` (newest first; `py
  -3.X` on Windows) and runs the bundle again with it, once (`BUNDLEUP_RUNTIME_RERUN`, cleared
  before the app runs). Only if there's none does it print the one-sentence mismatch.
- **`bundleup check --matrix`** shows, from the lock alone, which of Linux (gnu, musl), macOS and
  Windows on x86_64 and arm64, for each Python the project allows, have a wheel for every locked
  package; `result.matrix` in `--json`.
- **A running bundle holds a shared lock on its copy's lock file** (POSIX); `cache clean` skips a
  copy it can't lock exclusively and reports it as `in_use`.

## Consequences

- `./app.pyz` works on a stock Mac whenever a matching Python is installed anywhere on `PATH`.
- Tests: `test_the_wrong_python_reruns_with_a_matching_one`, `test_check_matrix`,
  `test_the_matrix_covers_every_platform_and_python`,
  `test_clean_never_removes_a_copy_a_running_program_uses`.
