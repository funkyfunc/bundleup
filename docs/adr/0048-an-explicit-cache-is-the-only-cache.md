# ADR-0048: An explicit `BUNDLEUP_CACHE` is the only cache folder

- **Status:** Accepted (the owner asked for the seventh review's fixes to be judged and made,
  2026-10-10; the design not yet reviewed by the owner)
- **Date:** 2026-10-10
- **Deciders:** an agent, on the [seventh review](../findings/2026-10-10-seventh-review.md)
- **Supersedes:** the first cache root of [ADR-0010](0010-bundle-format-and-loader.md) ("tried in
  order"), for `BUNDLEUP_CACHE` only

## Context

ADR-0010 made `$BUNDLEUP_CACHE` the first of four cache folders tried in order, and a bundle uses
the first that already holds an unpacked copy. So a copy in the user cache wins over the one you
asked for. The HPC recipe says to point the cache at local scratch; when the login node ran the
bundle first and home is on NFS, every compute node then imports from NFS, which is exactly what
the recipe was for (seventh review, reproduced). Learnings recorded the behaviour on 2026-10-07
without changing it.

## Decision

When `BUNDLEUP_CACHE` is set, it is the only folder a bundle looks in and unpacks to; if it can't
be used, the bundle says so (the existing "couldn't unpack" message, naming it) rather than
falling back. Unset, the order of ADR-0010 is unchanged. `bundleup cache` and `verify` follow the
same rule.

## Consequences

- What you set is what you get: cluster jobs, CI and tests stay in their own folder.
- An unwritable `BUNDLEUP_CACHE` is now an error instead of a silent fallback, which is what an
  explicit setting should do.

## Alternatives considered

- **Keep the order and fix the recipe** (tell HPC users to clean the user cache first): leaves a
  setting that doesn't do what it says.

## Evidence

- `tests/test_bundle.py::test_an_explicit_cache_is_the_only_one`.
- [Seventh review](../findings/2026-10-10-seventh-review.md), finding 6.
