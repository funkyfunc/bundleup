# ADR-0035: Versions in a range without an installed interpreter are checked with `ast`

- **Status:** Proposed (written 2026-10-07 while the owner was away)
- **Date:** 2026-10-07
- **Deciders:** an agent, after the [second independent review](../findings/2026-10-07-second-review.md)
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

- Each version below the target is checked with its own interpreter if one is installed;
  otherwise the target's interpreter checks the syntax for it with
  `ast.parse(source, feature_version=(3, X))`, which rejects newer syntax (`match`, walrus,
  positional-only parameters, `except*`, type parameters). Python documents it as best effort.
- The range starts at the oldest version that passes; there is no "unchecked" case and no
  download.

## Consequences

- Newer standard-library APIs aren't checked either way (only syntax), as before.
- Tests: `tests/test_check.py::test_the_range_starts_at_the_oldest_python_the_code_compiles_on`.
