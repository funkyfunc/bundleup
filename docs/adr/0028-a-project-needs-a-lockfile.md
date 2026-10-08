# ADR-0028: A project needs a lockfile; bundleup never writes one into it

- **Status:** Accepted (2026-10-07); the first decision (a project needs a lockfile) superseded by [ADR-0041](0041-input-without-a-lock.md)
- **Date:** 2026-10-07
- **Deciders:** the owner approved fixing the [independent review](../findings/2026-10-07-independent-review.md)'s
  findings, from a plan that named this fix; the details were designed by an agent and haven't
  been reviewed by the owner; design by an agent
- **Refines:** [ADR-0004](0004-lockfile-decides-contents.md) (the lockfile decides what goes in)

## Context

`uv export` locks a project that has no `uv.lock`, so `bundleup build` silently resolved the
dependencies and wrote a `uv.lock` into the user's project (confirmed 2026-10-07). The bundle then
matched a lock nobody had reviewed, and the lock-vs-bundle check compared the bundle with its own
fresh resolution. PEP 723 scripts usually have no lock; uv resolves them without writing one.

## Decision

- **A project directory needs `uv.lock` (its own, or its uv workspace's) or `pylock.toml`**;
  otherwise the build stops with `no-lockfile` and the hint `run uv lock`. Nothing is written into
  the project.
- **A script with dependencies and no `<script>.lock` builds, with a warning** (`unlocked`):
  its dependencies were resolved just now, so a later build may bundle different versions. Hint:
  `uv lock --script`. `--strict` turns it into a failure. A script without dependencies gets no
  warning.

## Consequences

- One more step for a brand-new project (`uv lock`), which uv users run anyway.
- `bundleup build` never modifies the project. Tests: `tests/test_pylock.py`,
  `tests/test_cli.py::test_error_no_lockfile`.

## Alternatives considered

- **Lock as uv does, and say so:** still writes into the project from a command named `build`.
- **Resolve into a temporary lock:** silently bundles versions nobody pinned; a warning would be
  easy to miss in CI, where `--locked` already refuses a stale lock.
