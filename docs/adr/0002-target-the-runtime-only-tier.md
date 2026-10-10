# ADR-0002: Ship a `.pyz` that needs only Python; no standalone executables

- **Status:** Accepted; the single `.py` point refined by [ADR-0046](0046-one-py-file-output.md) (a `.py` that carries the bundle as data, not one that inlines it); the exclusion of standalone executables superseded by [ADR-0047](0047-standalone-executables.md)
- **Date:** 2026-10-03
- **Deciders:** the user

## Context

There are three ways to ship a Python program (see [MISSION.md](../../MISSION.md)): a standalone
executable, source plus an install step, or one file that runs on the user's existing Python. The
project started from agent skills whose Python scripts failed until users installed dependencies.
The user first tried single executables and dropped them because of code signing and
notarization. `uv run` needs uv and network access, which sandboxed and offline environments
lack.

## Decision

The product outputs **`.pyz` files (PEP 441 zip applications) that run with `python app.pyz`** on
a matching Python, with no install step and no network. One `.pyz` per target platform, or one
multi-platform `.pyz`.

Out of scope for the core tool:
- standalone executables that embed an interpreter (if ever needed, hand off to `pex --scie`);
- a single `.py` file that inlines all code;
- tree-shaking or minification;
- syntax downleveling (we check the minimum Python version instead);
- a dependency resolver of our own (see [ADR-0006](0006-delegate-to-uv-and-existing-files.md));
- a watch-mode runner.

## Consequences

- No code signing, notarization or antivirus problems.
- The user must have a suitable Python. The bundle must check the version and platform first and
  fail with a clear message.
- Size is dominated by native wheels; we report it rather than shrink it.

## Alternatives considered

- **Standalone executables.** Rejected: signing and per-OS builds, the problem that started this.
- **Rely on `uv run` + PEP 723.** Rejected as the answer: needs uv and network. Still a good
  option where those exist.
- **Single inlined `.py` (stickytape-style).** Rejected: breaks native code, data files and
  metadata; every prior attempt was abandoned.

## Evidence

- [docs/research/round-1-landscape-compass.md](../research/round-1-landscape-compass.md)
- [docs/vision.md](../vision.md)
