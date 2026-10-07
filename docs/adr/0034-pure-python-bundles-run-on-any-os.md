# ADR-0034: A pure-Python bundle runs on any OS when the lock selects the same packages everywhere

- **Status:** Proposed (written 2026-10-07 while the owner was away)
- **Date:** 2026-10-07
- **Deciders:** an agent, from the [second independent review](../findings/2026-10-07-second-review.md)
- **Extends:** [ADR-0030](0030-pure-python-bundles-run-on-a-range.md) (the same idea, for OS and
  CPU); amends [ADR-0010](0010-bundle-format-and-loader.md)'s "one OS per bundle"

## Context

A pure-Python bundle built on a Mac refused Linux and Windows, although nothing in it was
platform-specific; to hand a tool to colleagues on mixed operating systems you needed three
files, where shiv or pex make one. The reviewer called it the costliest limitation. The same
check also exposed a latent bug: pure bundles ran on any CPU without checking that the lock
selected the same packages for it.

## Decision

- When the payload has no compiled code, the lock's markers are evaluated for Linux, macOS and
  Windows on x86_64 and arm64, for every Python in the bundle's range. If every combination
  selects exactly the packages bundled, the bundle runs on **any OS and any CPU** (the loader's
  `PLATFORM` is empty; `Python 3.10+ on any OS`; `target.any_os` in `--json` and the manifest).
- If only the CPUs agree, it runs on its OS, any CPU; if they don't, it's pinned to its CPU too.
- Bundles with compiled code are unchanged: one OS, one CPU, one Python version.

## Consequences

- Gauntlet 02, 03, 07 and 19 built on macOS run anywhere; 21 doesn't (Django needs `tzdata` on
  Windows); 15 doesn't (compiled markupsafe). CI builds the gauntlet on macOS for the Mac and runs
  it on Linux arm64 and Windows (`cross.py --python-platform host`); OS-specific bundles are
  skipped there.
- Tests: `tests/test_portability.py`.
