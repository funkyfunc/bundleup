# ADR-0042: `--smoke` runs the finished bundle once before shipping

- **Status:** Accepted (the owner, 2026-10-08: "smoke I think is good")
- **Date:** 2026-10-08
- **Deciders:** the owner (the feature), an agent (the design)

## Context

The sixth review: `check` reads code and the lock, so it can't see failures that happen only when
the bundle runs (a package that reads a file at import, a missing module loaded by name, code that
needs the network). The gauntlet catches those by running every bundle in hostile conditions;
users had no equivalent.

## Decision

- `bundleup build --smoke [ARGS]` (`BuildOptions(smoke=...)`) runs the finished `.pyz` once with
  ARGS (default `--help`), as a user would on a fresh machine: a new empty home folder, cache,
  temporary folder and working directory; none of the build machine's PYTHONPATH, virtual
  environment or uv settings; stdin closed; at most 120 seconds; the network blocked where the OS
  allows it (`sandbox-exec` on macOS, an empty network namespace with `unshare -rn` on Linux; not
  on Windows, and the result says so).
- A non-zero exit or a timeout is an error (`smoke-failed`) with the program's last output; the
  bundle stays written so it can be inspected. A bundle only for other platforms can't run here:
  a `smoke-skipped` warning.
- It runs the author's program, so it's opt-in; `.pyz` only. With `--entry python` there's no
  default to run, so ARGS (a script) is required. The result is `result.smoke` in `--json`.

## Consequences

- One flag catches run-time failures before users do, in CI too.
- `--help` is only a start: a program that does nothing with `--help` is barely exercised; pass
  real arguments for a real test.
- Tests: `tests/test_smoke.py`.
