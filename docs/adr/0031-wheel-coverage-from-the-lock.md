# ADR-0031: Wheel coverage is checked from the lock, before installing, for any number of targets

- **Status:** Accepted (2026-10-07)
- **Date:** 2026-10-07
- **Deciders:** the owner asked for the [independent review](../findings/2026-10-07-independent-review.md)'s
  findings to be fixed; design by an agent
- **Extends:** [ADR-0014](0014-output-formats-and-target-presets.md) (cross-target builds) and
  [ADR-0024](0024-check-command-and-build-analysis.md) (`bundleup check`)

## Context

A cross build found a missing wheel only when uv failed to install ("the built wheel is not
compatible with the target"), and bundleup turned that into a wrong hint ("only publishes
source"); the claude-api preset failed this way on the project's founding example. Checking
another platform meant a full build for it. The review pointed out that a lock lists every file
of every locked version, so "pillow has no wheel for `manylinux_2_17`; `2_28` works" can be
answered in milliseconds, and called it the one differentiator neither pex nor uv offers.

## Decision

- **`_coverage.gaps(pylock, platform, python)`**: every locked package that applies to the target
  (markers evaluated for it) and has no wheel the target can install. Compatibility is the exact
  tag set pip and uv use (`packaging.tags`), built from uv's meaning of each platform name
  (`-gnu` is `manylinux_2_28`, musl `musllinux_1_2`, macOS 13.0 unless
  `MACOSX_DEPLOYMENT_TARGET` says otherwise). Local projects and URLs are skipped (built here).
- **Before a cross-platform install**, a package with wheels but none for the target stops the
  build (`incompatible-wheel`), naming the package, the platforms its wheels support (same OS
  first), and, on Linux, the newest-necessary manylinux level that would work. A package with no
  wheels at all is a `source-only` warning: uv builds it on this machine, which works if it's
  pure Python.
- **`bundleup check --also-platform OS`** (repeatable; `check(..., also_platforms=[...])`) runs
  the same check for more targets, from the lock alone, for the target's Python version:
  `no-wheel` errors and `source-only` warnings.

## Consequences

- The claude-api failure now reads: "pillow 12.3.0: wheels only for manylinux_2_27_x86_64,
  manylinux_2_28_x86_64, ...; x86_64-manylinux_2_28 would work".
- Cross builds of the whole gauntlet for Linux x86_64, Linux arm64 and Windows from macOS found
  no false gaps (2026-10-07).
- The check trusts the lock's file list: a lock without wheel URLs (some tools omit them) reads as
  source-only, which only warns.
- The post-install check (`_platforms.Platform.accepts`) stays lenient on purpose, for wheels
  built from source on a similar host.
