# ADR-0035: A range's oldest Python is checked with a real interpreter, installed privately if needed

- **Status:** Proposed (written 2026-10-07 while the owner was away)
- **Date:** 2026-10-07
- **Deciders:** an agent, after the second and third independent reviews
  ([second](../findings/2026-10-07-second-review.md), [third](../findings/2026-10-07-third-review.md))
- **Amends:** [ADR-0030](0030-pure-python-bundles-run-on-a-range.md)

## Context

ADR-0030 compiles the project's own code with the oldest Python in a pure bundle's range, when
one is installed. The second review found that on a typical CI runner (one Python) the check
silently didn't run, so a bundle could claim 3.9+ for code with a `match` statement. Two fixes
were tried and dropped:

- **Warn when it can't run:** CI's test jobs showed the warning on nearly every build, which
  teaches people to ignore warnings.
- **Install the missing interpreter** (`uv python install`), as `uv run` would: on Windows, a
  concurrent install made another running uv-managed Python lose its standard library
  (`__future__.py` not found) in the gauntlet. A build must not change the Pythons other programs
  are using.

## Decision

- The range's **oldest** version is checked with a real interpreter: an installed one, or one
  bundleup installs into **its own directory** (`<build cache>/pythons`, `uv python install
  --no-bin --no-registry` with `UV_PYTHON_INSTALL_DIR`), used through its real path. The user's
  uv-managed Pythons, PATH and Windows registry are never touched, and uv's per-version links
  (which an install can repoint) aren't used.
- Other versions below the target use an installed interpreter if there is one, otherwise the
  target's interpreter with `ast.parse(source, feature_version=(3, X))` (best effort: it misses
  tokenizer changes such as PEP 701 f-strings, as the third review showed).
- The range starts at the oldest version that passes. If the oldest couldn't be checked with an
  interpreter (offline, `UV_PYTHON_DOWNLOADS=never`), the `python-range-approximate` warning says
  so.

## Consequences

- The first build of a pure project on a machine without its oldest Python downloads that
  Python once (~20 MB) into bundleup's cache; `bundleup cache clean --build` removes it.
- Newer standard-library APIs aren't checked either way (only syntax), as before.
- Tests: `tests/test_check.py::test_the_range_starts_at_the_oldest_python_the_code_compiles_on`,
  `test_an_older_interpreter_catches_what_ast_cannot` (a PEP 701 f-string on 3.11).
