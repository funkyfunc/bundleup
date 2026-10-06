# ADR-0005: Use the standard importer and extract to a cache by default

- **Status:** Accepted (cache details settled by [ADR-0010](0010-bundle-format-and-loader.md), 2026-10-05)
- **Date:** 2026-10-03
- **Deciders:** the user (direction), agent (cache details from baseline evidence)

## Context

Compiled extensions can't be loaded from a zip or from memory. Many packages read data via
`__file__`. PyOxidizer's in-memory importer died on these edge cases. The baseline showed that
tools which extract everything to disk (pex, shiv) passed every `__file__`, metadata and native
project, while tools running from the zip (zipapps, naive zipapp) failed on files and metadata.
It also showed caching pitfalls: shiv fails 100% with an unwritable `HOME`; zipapps writes into
the working directory and races on simultaneous first runs.

## Decision

- Use Python's **standard import system** with real files on disk. No custom in-memory importer.
- **Extract to a cache by default** for correctness. Running directly from the zip is an
  optimisation enabled per package only when the analyzer shows it's safe.
- *(Proposed)* Cache location chain: user cache dir → temp dir → next to the bundle. **Never** the
  working directory. Extract into a temporary directory, then rename atomically, so simultaneous
  first runs are safe. Content-addressed so different bundle versions don't collide.

## Consequences

- First run pays an extraction cost; the warm-start path must be minimal to stay fast.
- `__file__`, `importlib.resources`, `importlib.metadata` and entry points behave as in a venv.

## Alternatives considered

- **Run everything from the zip.** Rejected as default: fails on `__file__` and frameworks.
- **In-memory importer.** Rejected: PyOxidizer's fate.

## Evidence

- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md)
- [docs/research/round-2-evolution-compass.md](../research/round-2-evolution-compass.md) §2.3
