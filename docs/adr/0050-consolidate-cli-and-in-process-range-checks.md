# ADR-0050: Consolidate CLI flags and check older Pythons' syntax in-process

- **Status:** Accepted (the owner, 2026-10-14)
- **Date:** 2026-10-14
- **Deciders:** the owner, after an independent evaluation of the CLI, configuration and codebase
- **Supersedes:** [ADR-0035](0035-check-older-pythons-syntax-without-their-interpreters.md)
  (downloading older interpreters for range syntax checks),
  [ADR-0043](0043-check-audit-asks-pypi-about-the-lock.md) (`check --audit`), and
  [ADR-0044](0044-destinations-as-data-files.md) (`--against FILE`)
- **Amends:** [ADR-0031](0031-wheel-coverage-from-the-lock.md) (`--python-platform` replaces
  `--also-platform` on `check`)

## Context

A hands-on evaluation of `bundleup` across single-file scripts, `pyproject.toml` projects, legacy
`requirements.txt` folders, cross-platform builds and all output formats identified four places
where surface area or mechanism got in the way:

1. **`--against FILE` (ADR-0044)** recreated target presets as external TOML files whose actionable
   fields (`python`, `python-platform`, `max-size`, `format`) already live directly in
   `[tool.bundleup]` (ADR-0032), while its prose fields (`notes`, `checked`) mixed documentation
   with build flags.
2. **`check --audit` (ADR-0043)** made live network requests to PyPI inside a bundler whose
   checks are otherwise local and deterministic, overlapping dedicated vulnerability scanners
   (`pip-audit`, `uvx pip-audit`, OSV-Scanner) and violating [ADR-0006](0006-delegate-to-uv-and-existing-files.md).
3. **`check --also-platform` (ADR-0031)** forced users to learn two different flag spellings for
   the same concept (`build` repeated `--python-platform`; `check` used `--python-platform` once
   plus `--also-platform`).
4. **Downloading older Python interpreters for range checks (ADR-0035)** triggered a ~20–30 MB
   download into `~/.cache/bundleup/pythons/` on a user's first build whenever `requires-python`
   started below the active Python, even though Python's built-in `ast.parse(...,
   feature_version=(3, minor))` checks older minor-version grammar in-process in milliseconds.

## Decision

- **Remove `--against FILE`** and `docs/targets/*.toml`. Destination recipes belong in
  `docs/recipes.md` as copy-pasteable `[tool.bundleup]` blocks and CLI commands (ADR-0039).
- **Remove `bundleup check --audit`**. Vulnerability and PyPI metadata auditing is left to
  dedicated tools (`uvx pip-audit`).
- **Unify `--python-platform` across `build` and `check`:** `bundleup check` accepts repeatable
  `--python-platform` (and a list in `[tool.bundleup] python-platform = [...]`), checking the
  first target by installing and the rest from the lock; `--also-platform` is removed.
- **Check older Python syntax in-process with `ast.parse(source, feature_version=version)`** in
  `_check.oldest_python` instead of downloading older Python interpreters into a private cache.
  (`fetch_interpreter` remains only for explicit `--python 3.X` requests when `3.X` is not
  installed locally.)
- **Validate `--entry` at build/check time** against the installed payload (`site`) so typos in
  script names, modules or callables fail during `build` and `check` with `no-entry-point` and a
  "did you mean ...?" hint rather than at runtime.
