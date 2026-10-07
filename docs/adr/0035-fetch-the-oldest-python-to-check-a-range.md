# ADR-0035: The oldest Python in a bundle's range is fetched, if missing, to check the code

- **Status:** Proposed (written 2026-10-07 while the owner was away)
- **Date:** 2026-10-07
- **Deciders:** an agent, after the [second independent review](../findings/2026-10-07-second-review.md)
- **Amends:** [ADR-0030](0030-pure-python-bundles-run-on-a-range.md)

## Context

ADR-0030 compiles the project's own code with the oldest Python in a pure bundle's range, when
one is installed. The second review found that on a typical CI runner (one Python) the check
silently didn't run, so a bundle could claim 3.9+ for code with a `match` statement. Warning
instead put a `python-range-unchecked` warning on nearly every build on such machines (CI's test
jobs showed it), which teaches people to ignore warnings.

## Decision

- If no interpreter of the range's oldest version is installed, bundleup installs a uv-managed
  one (`uv python install 3.X`), as `uv run` does by default; uv caches it, so it's a one-time
  cost (~20 MB).
- Other versions below the target are only used if already installed (they matter only when the
  oldest fails, to find where the range can start).
- Only if the fetch fails (offline, or `UV_PYTHON_DOWNLOADS=never`) is the range claimed
  unchecked, with the `python-range-unchecked` warning.

## Consequences

- The first build of a pure-Python project on a machine without its oldest Python downloads that
  Python. Builds already download wheels on first use.
