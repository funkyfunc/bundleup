# ADR-0015: Enforce code quality with Ruff, a type checker, git hooks and CI

- **Status:** Accepted (direction 2026-10-04; tool choices and rule sets 2026-10-05)
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

## Implementation (confirmed by the user 2026-10-05)

What landed, including where it differs from the proposal above:

| Choice | Value | Why |
|---|---|---|
| Ruff rules | `E, F, W, I, B, UP, SIM, RUF` **plus `ANN`** | `ANN` turns "type hints on every signature" ([review guide](../python-for-js-reviewers.md)) from guidance into a check |
| Line length | 100 | The code ran to ~120 and the docs wrap at ~100; 88 (Ruff's default) would split most signatures |
| Targets | `py39` for `src/` and `tests/`; `py311` for `gauntlet/*.py` | The harness scripts use `tomllib`; gauntlet *projects* are excluded (17 uses 3.12-only syntax on purpose) |
| Loader exceptions | `UP004`, `UP031`, `UP032` off in `_loader.py` | It must compile on any Python 3 to print its version message |
| Type checker | `pyright[nodejs]`, standard mode, on `src/`, `tests/` and `gauntlet/*.py` | The `nodejs` extra avoids a run-time Node download; the harness is code agents edit too |
| Hooks | `.pre-commit-config.yaml`, local hooks calling `uv run --frozen …` | Same pinned tool versions as CI and the lockfile; works with `pre-commit` or `prek` |
| Hook stages | commit: format, lint, types (~1–4 s); push: pytest (~3 s) | As decided above |

## Consequences

- Style, import order and common bugs stop being review topics.
- Type hints become mandatory, which also makes the code read more like TypeScript.
- Existing code needs a one-time formatting and typing pass.

## Alternatives considered

- **Black + flake8 + isort.** Rejected: Ruff replaces all three, faster, in one config.
- **mypy.** Reasonable; pyright is faster and its inference is closer to what TypeScript users
  expect. Either is fine; the important part is having one.
- **Hooks only, no CI.** Rejected: hooks can be skipped, and Linux coverage needs CI anyway.
