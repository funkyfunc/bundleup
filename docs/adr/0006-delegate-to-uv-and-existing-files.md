# ADR-0006: Delegate resolution and installation to uv; read the files people already have

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** the user (via the vision), proposed by an agent

## Context

Every successful tool switch in JS and Python started by being compatible with what users
already had (npm's registry, Rollup's plugin API, pip's CLI). Pipenv invented a file format no
standard backed and suffered for it. uv resolves and installs quickly and correctly, including for
other platforms (`--python-platform`). In the baseline, builds driven by uv took 0.1–0.2 s versus
0.7–12 s for tools driving pip.

## Decision

- **Inputs:** `pyproject.toml` + `uv.lock`, `pylock.toml` (PEP 751), PEP 723 scripts.
  `requirements.txt` as a fallback.
- **Resolution and installation:** delegate to uv. We don't write a resolver.
- **Configuration:** `[tool.<name>]` in `pyproject.toml` when needed. No new file formats.
- Aim to be a component other tools (including uv) could call, not a competitor to uv.

## Consequences

- Hard dependency on uv at **build** time (not at run time).
- Exposure to uv's direction under Astral/OpenAI; mitigated by also accepting `pylock.toml`.

## Alternatives considered

- **Drive pip.** Rejected: slow (see baseline), weaker cross-platform support.
- **Own config file.** Rejected: Pipenv's mistake.

## Evidence

- [docs/research/round-2-evolution-compass.md](../research/round-2-evolution-compass.md) §5
- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md) (build times)
