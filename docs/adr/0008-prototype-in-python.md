# ADR-0008: Prototype in Python, not Rust

- **Status:** Proposed
- **Date:** 2026-10-03
- **Deciders:** proposed by an agent; not yet confirmed by the user

## Context

One research report recommended Rust from the start (using Ruff's parser crates). esbuild's speed
mattered because bundling ran on every save; our tool runs at build/publish time, and the
baseline shows most build time is dependency installation, which uv already does fast. The hard
part is correctness in the long tail.

## Decision

Build the first version in Python, delegating heavy work to uv. Revisit Rust for hot paths (e.g.
the analyzer over large dependency trees) only when measurements show Python is the bottleneck.

## Consequences

- Faster iteration on the hard part; easier for Python users to contribute.
- The runtime bootstrap inside each `.pyz` must be Python anyway (it runs on the user's
  interpreter), and must support the oldest targeted Python (3.9).

## Alternatives considered

- **Rust from day one.** Deferred: optimises the wrong thing first.

## Evidence

- [docs/research/round-1-landscape-compass.md](../research/round-1-landscape-compass.md) (MVP outlines)
- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md) (build time breakdown)
