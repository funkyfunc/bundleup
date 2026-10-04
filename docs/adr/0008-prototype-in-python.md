# ADR-0008: Build in Python first, with a measured path to Rust

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** the user (accepted after a pros/cons discussion); proposed by an agent

## Context

Astral's tools (uv, Ruff, ty) are written in Rust, users value speed, and one research report
recommended Rust from the start (reusing Ruff's parser). The question was which language bundleup
itself should be written in.

Users feel bundleup's speed in three places:

1. **Start-up of every bundle.** Controlled by the loader inside each `.pyz`, which runs on the
   user's Python and so **must be Python** regardless of bundleup's language. This is where pex
   loses most (273 ms vs 59 ms for an installed venv; see the
   [baseline](../findings/2026-10-03-baseline.md)).
2. **Dependency download and install during a build.** Done by uv, already Rust (0.1–0.2 s in the
   baseline).
3. **bundleup's own build work:** scanning code for problems, writing the zip. The only place
   Rust would help: scanning thousands of files in a large dependency could take seconds in
   Python.

## Decision

Write bundleup in **Python**. Put the speed effort where users feel it:
- a minimal, carefully designed loader (item 1);
- delegating installation to uv (item 2, [ADR-0006](0006-delegate-to-uv-and-existing-files.md));
- **caching analysis results per wheel, keyed by the wheel's hash** (item 3). Published wheels
  never change, so each wheel is scanned once and rebuilds skip the scan.

**Trigger for Rust:** if gauntlet measurements show bundleup's *own* build work (excluding uv) is
the bottleneck, for example a warm rebuild taking over 1 s, or a cold scan of
`20-heavy-ml` taking over 5 s, move only the hot path (most likely the scanner) to a Rust
extension built with maturin/PyO3, keeping the rest in Python, as pydantic did with
pydantic-core. That move needs its own ADR.

## Consequences

- Faster iteration on the hard part (correctness across the long tail of packages).
- One pure-Python wheel to publish; no per-platform binary builds yet.
- Python users can read and contribute to the code.
- We give up the "written in Rust" marketing for now; speed claims must come from measurements
  ([ADR-0007](0007-gauntlet-is-the-contract.md)).

## Alternatives considered

- **Rust from day one.** Rejected for now: it speeds up the part users feel least, slows
  experimentation, requires per-platform wheels, and narrows contributors. Ruff's parser is also
  not a stable public library.
- **Python with no plan for Rust.** Rejected: if the scanner becomes the bottleneck, we want the
  trigger and the path decided in advance.

## Evidence

- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md) (start-up and build
  times by tool)
- [docs/research/round-1-landscape-compass.md](../research/round-1-landscape-compass.md) (MVP
  outlines)
