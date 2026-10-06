# ADR-0020: Compress the payload in parallel at level 6, and cache compiled bytecode per wheel

- **Status:** Proposed
- **Date:** 2026-10-05
- **Deciders:** an agent (roadmap item 9); awaiting the user. Once accepted, it supersedes
  [ADR-0010](0010-bundle-format-and-loader.md)'s "deflated (level 1)" detail only, and ADR-0010's
  status line gets a pointer here

## Context

On large projects bundleup's build was no faster than pex (gauntlet 21: 5.2 vs 5.5 s), almost
all of it in zipping (3.1 s, one thread) and compiling bytecode (1.3 s)
([findings](../findings/2026-10-04-large-project-and-rust.md)). Two facts surfaced while fixing it:

- `zipfile.writestr()` ignores the archive's `compresslevel` when given a `ZipInfo`, so payloads
  were in fact deflated at zlib's default level 6, not the level 1 ADR-0010 states.
- Compiling the same file twice can give different bytes: set literals are stored in hash order,
  and string hashes are randomised per process.

## Decision

1. **A small zip writer** ([`_zipwriter.py`](../../src/bundleup/_zipwriter.py)) compresses members on
   up to 8 threads (zlib releases the GIL) and writes them in sorted order: ordinary deflate
   members, fixed timestamps, ZIP64 only when needed. **Level 6**: in parallel it costs ~5% more
   time than level 1 on gauntlet 21 and keeps bundles 8-13% smaller.
2. **A per-wheel bytecode cache** ([`_bytecode.py`](../../src/bundleup/_bytecode.py)): each
   distribution's `.pyc` files are kept under bundleup's build cache
   (`~/Library/Caches/bundleup/build/bytecode`, `$XDG_CACHE_HOME/bundleup/build/bytecode` or
   `~/.cache/...`, `%LOCALAPPDATA%\bundleup\build\bytecode`; `BUNDLEUP_BUILD_CACHE` overrides),
   keyed by a format version, the exact Python version and the distribution's `RECORD`. Entries
   are written atomically.
3. **Bytecode is compiled with `PYTHONHASHSEED=0`**, so builds stay byte-identical whether the
   bytecode is compiled now or restored from the cache (tested).

## Consequences

- Builds: 03 0.25 → 0.16 s, 13 (NumPy) 0.99 → 0.40 s, 21 5.2 → 2.5 s with a warm cache (3.4 s
  cold); 2-9× faster than pex. First runs unchanged.
- The build cache grows without limit (tens of MB per large project); cleaning it belongs with
  the cache command planned for runtime hardening.
- Bundles built before this change have different bytes (file order and compression), as
  expected across bundleup versions; reproducibility holds within a version.

## Alternatives considered

- **Level 1:** 13% bigger bundles for ~5% faster zipping on large trees.
- **Hard links when restoring cached bytecode:** measured no faster than copying here.
- **Rust for the build:** not needed; the time was in zlib and in Python bookkeeping (pathlib's
  `relative_to()` alone cost over a second for 18,000 files).

## Evidence

- [docs/findings/2026-10-05-faster-builds.md](../findings/2026-10-05-faster-builds.md)
- `tests/test_zipwriter.py`, `tests/test_bundle.py::test_reproducible_with_and_without_the_bytecode_cache`
