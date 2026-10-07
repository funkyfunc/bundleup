# ADR-0029: Bundles check the C library and macOS version at start-up

- **Status:** Accepted (2026-10-07)
- **Date:** 2026-10-07
- **Deciders:** the owner asked for the [independent review](../findings/2026-10-07-independent-review.md)'s
  findings to be fixed; design by an agent
- **Extends:** the start-up checks of [ADR-0010](0010-bundle-format-and-loader.md)

## Context

The loader refused the wrong Python version, OS and CPU in one sentence, but a bundle with
manylinux wheels started on Alpine (musl), on a Linux whose glibc is older than its wheels need,
or on a macOS older than its wheels' deployment target failed with a raw `ImportError` deep in the
app.

## Decision

- At build time, the native wheels' tags give the strictest requirement: glibc (or musl) version
  on Linux (`manylinux_2_28` needs glibc 2.28; legacy `manylinux2014` is 2.17), macOS version
  (`macosx_11_0`). Each wheel counts with the most permissive of its tag alternatives. The loader
  gets `LIBC` and `MACOS`, both empty for pure-Python bundles.
- At start-up the loader compares them with the machine without importing anything: glibc through
  `os.confstr("CS_GNU_LIBC_VERSION")`, musl by its dynamic loader in `/lib`, macOS from the Darwin
  kernel version (Darwin 20 is macOS 11). A mismatch is one sentence; an unknown answer passes.
- The helpers (`_platforms.wheel_tags`, `is_native`, `runtime_needs`) replace three copies of the
  same `WHEEL`-file parsing the review found.

## Consequences

- musl's version isn't checked (it has no cheap way to report it), only that it's musl.
- Tests: `tests/test_platforms.py::test_runtime_needs_take_the_strictest_wheel`,
  `tests/test_bundle.py::test_too_old_system_is_explained` (macOS and Linux).
