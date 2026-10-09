# ADR-0033: A stale lock is an error by default; bundleup never rewrites it

- **Status:** Accepted (the owner, 2026-10-08)
- **Date:** 2026-10-07
- **Deciders:** an agent, from the [second independent review](../findings/2026-10-07-second-review.md)
- **Supersedes:** "CI implies `--locked`" (style guide rule 9, ADR-0016); completes
  [ADR-0028](0028-a-project-needs-a-lockfile.md)

## Context

ADR-0028 promised bundleup never writes a lockfile into a project, but only covered a missing
lock. Outside CI, `uv export` without `--locked` re-locks a lock that no longer matches
`pyproject.toml`: the second review changed `requires-python` in a copy of gauntlet 02, ran
`bundleup build`, and `git status` showed `M uv.lock`. Someone who adds a dependency and forgets
`uv lock` would ship versions nobody reviewed.

## Decision

- **Whenever a lock exists** (the project's or its workspace's `uv.lock`, or `<script>.lock`),
  bundleup passes `--locked`: a lock out of date with `pyproject.toml` or the script is an error
  (`lock-outdated`, hint: `uv lock`), in CI and everywhere else.
- **`--frozen`** (or `lock_mode="frozen"`) bundles the lock as it is, without checking it.
- A script without a lock still builds, with the `unlocked` warning (ADR-0028).

## Consequences

- `bundleup build` never modifies the project. Tests:
  `tests/test_pylock.py::test_a_stale_uv_lock_is_an_error_and_is_never_rewritten`.
- Editing `pyproject.toml` now needs `uv lock` before the next build, as `uv sync --locked` does.
