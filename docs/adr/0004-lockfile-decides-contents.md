# ADR-0004: The lockfile decides what goes in; import tracing is for diagnostics only

- **Status:** Accepted; refined by [ADR-0041](0041-input-without-a-lock.md): without a lock, the versions resolved at build time decide, and the manifest records them
- **Date:** 2026-10-03
- **Deciders:** the user (via the vision), proposed by an agent

## Context

esbuild builds its bundle by following imports from an entry point. Python's imports are too
dynamic for that: `importlib.import_module()` with computed names, plugins found via entry points,
optional imports, lazily loaded submodules (e.g. Pygments lexers). stickytape built bundles from
import scanning and failed on exactly these.

## Decision

The **set of distributions in the bundle comes from the resolved lockfile / installed
environment** (`uv.lock`, `pylock.toml`, PEP 723 resolution), always complete per distribution,
including `.dist-info` and data files. Static import tracing is used **only** for diagnostics
(warnings, reports) and possibly for opt-in pruning of whole unreachable distributions, never to
decide correctness.

## Consequences

- Bundles are larger than an esbuild-style traced bundle, but correct by construction.
- `09-dynamic-imports`, `07-entry-point-plugins` and `06-metadata-version` pass without special
  handling.
- Copy esbuild's *experience*, not its algorithm.

## Alternatives considered

- **Trace imports to decide contents.** Rejected: unsound in Python; the failure mode of
  stickytape.
- **Trace plus a hook database (PyInstaller-style).** Rejected as the basis: a permanent
  maintenance burden. A small knowledge base may still feed diagnostics.

## Evidence

- [docs/research/round-2-evolution-compass.md](../research/round-2-evolution-compass.md) §5.3
- Gauntlet projects 06, 07, 09
