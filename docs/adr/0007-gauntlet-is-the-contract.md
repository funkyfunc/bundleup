# ADR-0007: The gauntlet is the acceptance test, and claims must be measured

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** the user

## Context

Bundling fails in the long tail. The user asked for a set of test projects, from hello world to
native extensions, to run every candidate tool against.

## Decision

- [gauntlet/](../../gauntlet/README.md) is the acceptance test for our tool and the benchmark for
  existing ones. Each project targets one way bundling breaks and self-checks, printing
  `GAUNTLET OK <id>`.
- The **native control group** (`gauntlet/check_native.py`) must pass before any bundler result is
  trusted. A failure there means the test is broken.
- Claims about speed, size or correctness are **measured** on the gauntlet and compared with pex,
  not asserted.
- New failure modes found in the wild become new gauntlet projects.

## Consequences

- Adding a feature usually starts with adding or updating a gauntlet project.
- Coverage gaps (Linux, Windows, cross-platform runs) are tracked in the gauntlet README and
  findings until closed.

## Evidence

- [gauntlet/README.md](../../gauntlet/README.md), [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md)
