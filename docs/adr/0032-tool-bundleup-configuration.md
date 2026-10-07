# ADR-0032: Project settings live in `[tool.bundleup]`

- **Status:** Accepted (2026-10-07)
- **Date:** 2026-10-07
- **Deciders:** the owner approved fixing the [independent review](../findings/2026-10-07-independent-review.md)'s
  findings, from a plan that named this fix; the details were designed by an agent and haven't
  been reviewed by the owner (it asked for configuration); design by an agent, following the
  [CLI style guide](../cli-style-guide.md) rules 28-31 (ADR-0016)

## Context

Every build had to repeat its settings on the command line (`--target lambda --entry
app:handler`). The style guide already said where configuration goes: `[tool.bundleup]` in
`pyproject.toml`, below flags and environment variables, above defaults (MISSION.md: "No new file
formats. Configuration lives in `[tool.<name>]`").

## Decision

- **Keys:** `target`, `format`, `python`, `python-platform`, `entry`, `output` (strings) and
  `strict` (boolean), meaning the same as the flags.
- **Where:** `[tool.bundleup]` in `pyproject.toml`, or in a PEP 723 script's `# /// script`
  block (PEP 723 allows `[tool]` tables), so a single-file tool carries its settings too.
- **Precedence:** flags, then `BUNDLEUP_*` environment variables, then the file, then defaults.
  `strict = true` can only add strictness. A relative `output` is relative to the file that names
  it.
- **Errors (exit 2):** unknown keys (with a suggestion), per-run settings (`json`, `quiet`,
  `verbose`, `color`, `dry-run`, `locked`, `frozen`) and wrong types.
- The library applies it too (`build()` and `check()`), so the CLI and the API behave the same;
  `-v` shows the settings taken from the file.

## Consequences

- `bundleup build` in a configured Lambda project does the right thing with no flags.
- No user-level configuration file (rule 31) until someone asks.
- Tests: `tests/test_config.py`.
