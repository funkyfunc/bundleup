# ADR-0015: Enforce code quality with Ruff, a type checker, git hooks and CI

- **Status:** Accepted (tooling direction); Proposed (specific tool choices and rule sets)
- **Date:** 2026-10-04
- **Deciders:** the user asked for Ruff, a type checker and git hooks; tool choices proposed by an
  agent

## Context

bundleup is written mostly by agents across many sessions, and reviewed by a user who is fluent in
JavaScript but new to Python ([python-for-js-reviewers.md](../python-for-js-reviewers.md)). Agents
follow automated checks far more reliably than written guidance, and checks let the user judge
quality from evidence rather than by reading every line. The repo currently has pytest and the
gauntlet, but no formatter, linter, type checker, hooks or CI.

## Decision

1. **Ruff** for formatting (`ruff format`) and linting (`ruff check`), configured in
   `pyproject.toml`. *(Proposed)* Rule set to start: `E, F, W, I, B, UP, SIM, RUF`, with
   `target-version = "py39"` because the loader must run on macOS's system Python 3.9.
2. **A type checker on everything in `src/` and `tests/`.** *(Proposed)* **pyright** (installed
   from PyPI) in standard mode, tightening later. ty (Astral) is faster and fits the uv ecosystem
   but is still pre-1.0; re-evaluate it when it reaches a stable release.
3. **Git hooks** via a `pre-commit`-compatible config (`.pre-commit-config.yaml`, runnable with
   `uvx pre-commit` or `prek`):
   - on commit: `ruff format`, `ruff check --fix`, type check;
   - on push: `pytest -q`.
   The gauntlet is too slow for hooks; it runs in CI.
4. **CI (GitHub Actions):** lint, type check and tests on every push; the gauntlet on macOS **and
   Linux** across Python 3.9, 3.11 and 3.12. This also closes the long-standing "no Linux runs" gap.
5. Adopt at a checkpoint: one commit that adds the config and reformats existing code, so the
   reformat doesn't mix with feature changes.

## Consequences

- Style, import order and common bugs stop being review topics.
- Type hints become mandatory, which also makes the code read more like TypeScript.
- Existing code needs a one-time formatting and typing pass.

## Alternatives considered

- **Black + flake8 + isort.** Rejected: Ruff replaces all three, faster, in one config.
- **mypy.** Reasonable; pyright is faster and its inference is closer to what TypeScript users
  expect. Either is fine; the important part is having one.
- **Hooks only, no CI.** Rejected: hooks can be skipped, and Linux coverage needs CI anyway.
