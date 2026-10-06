# ADR-0022: Unpacked bundles are cleaned up by a command, never by bundles themselves

- **Status:** Accepted (2026-10-05)
- **Date:** 2026-10-05
- **Deciders:** the user chose a cleanup command; proposed by an agent (roadmap item 8)

## Context

A bundle unpacks once per version into a cache ([ADR-0010](0010-bundle-format-and-loader.md));
the directory name includes the payload's hash, so every new build of an app adds a directory and
old ones stay. Interrupted unpacks can leave `.tmp-*` directories, and the unpack lock leaves
`.lock-*` files. bundleup's build cache ([ADR-0020](0020-parallel-zip-and-bytecode-cache.md)) also
grows. Deleting from inside a bundle is unsafe: another process may still be running an older
version, and deleting its files would break its later imports.

## Decision

- **`bundleup cache list`** shows each unpacked bundle (name, size, last used, path) in the cache
  roots the loader uses: `$BUNDLEUP_CACHE`, the user cache directory and the private temp
  directory. Only directories named like the loader names them (`<name>-<16 hex>`) count;
  anything else, such as the build cache under the same folder, is left alone.
- **`bundleup cache clean [--older-than DAYS] [--build] [-n/--dry-run]`** removes copies not used
  for `DAYS` (default 30; `0` removes all), `.tmp-*` directories older than an hour, and lock files
  of removed or missing copies. `--build` also clears the build cache.
- **"Used" is recorded by the loader**: on a warm start it refreshes its directory's timestamp if
  it's more than a day old, so warm starts almost never write; on a read-only cache it silently
  doesn't.
- Library: `bundleup.list_cache()`, `bundleup.clean_cache()`, `CachedBundle`, `CleanReport`;
  `--json` follows [cache-v1.json](../schema/cache-v1.json).

## Consequences

- Nothing is ever deleted unless someone asks; a removed copy simply unpacks again on its next
  run.
- `.bundleup/` directories next to bundles (the loader's last fallback) aren't found by the
  command.
- A bundle that has been running continuously for over `DAYS` without restarting still looks
  unused. Restarting it refreshes the mark; long-lived services should use a larger `DAYS`.

## Alternatives considered

- **The loader removes old versions of the same app on first run of a new one:** hands-off, but
  deletes files another process may still need.
- **Track use in a separate file per start:** more writes on every warm start for no gain over
  the directory's own timestamp.
