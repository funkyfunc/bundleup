# ADR-0019: Every bundle carries a manifest; `bundleup verify` checks it

- **Status:** Accepted for the command (the user chose it, 2026-10-05); Proposed for the manifest
  format
- **Date:** 2026-10-05
- **Deciders:** the user chose a `bundleup verify` command over a hook inside every bundle; the
  manifest format is an agent's proposal

## Context

[testing-strategy.md](../testing-strategy.md) defines correctness as a hash chain from `uv.lock`
to every file that runs. Build-time checks cover lock → bundle and wheel → bundle
([`_verify.py`](../../src/bundleup/_verify.py)). Two links were missing: a record inside the bundle
of what it should contain, and a way to re-check a bundle (or its unpacked copy) later, on any
machine. The roadmap first phrased it as `python app.pyz --verify`, which would steal `--verify`
from every bundled app that has its own flag of that name. pex and shiv do ship runtime hooks
(~30 `PEX_*` and 10 `SHIV_*` environment variables) but neither has a verify mode.

## Decision

1. **`manifest.json` in the outer zip**, next to `__main__.py` (deflated; readable with
   `unzip -p app.pyz manifest.json`):

   | Key | What |
   |---|---|
   | `manifest_version` | `1`; additive changes only within a version |
   | `bundleup_version`, `name`, `version`, `target`, `entry`, `cache_dir` | What was built, for what, and where it unpacks |
   | `payload` | `sha256` and `size` of `payload.zip` |
   | `loader` | Hashes of `__main__.py` and `__main__.pyc`, which run first on every start |
   | `packages` | Every locked package that applies to the target, with its version |
   | `files` | Every payload file (bytecode included) with its `RECORD`-style `sha256=` hash |

   Sorted and deterministic, so reproducible builds stay byte-identical.
2. **`bundleup verify BUNDLE`** (and `bundleup.verify()` in the library) checks the loader, the
   payload's hash, every payload file, and, if this machine has unpacked the bundle, the unpacked
   copy (found the way the loader finds it). Bytecode may be absent from an unpacked copy (some
   Pythons keep it under `sys.pycache_prefix`), so it's only checked where present. Exit 0 when
   everything matches, 1 with `verify-mismatch` / `cache-mismatch` diagnostics otherwise;
   `--json` follows [verify-v1.json](../schema/verify-v1.json).
3. **No verify hook inside bundles.** The loader stays minimal ([ADR-0008](0008-prototype-in-python.md));
   machines without bundleup can use `uvx bundleup verify`.

## Consequences

- A reviewer can read exactly what a bundle contains, and check that the reviewed artifact is the
  one that runs.
- A corrupted download or a tampered cache is caught with the file that differs.
- An unpacked copy can't be checked on a machine with neither bundleup nor uv (e.g. an offline
  sandbox). Add a hook later only if a real use case needs it.
- The manifest adds ~100 bytes per file to the bundle (16 KB for gauntlet 03; a few MB for
  PyTorch-sized bundles, compressed).

## Alternatives considered

- **`python app.pyz --verify`:** steals an argument from the app.
- **`BUNDLEUP_VERIFY=1 python app.pyz`:** works offline, but puts verification code in every
  bundle's start-up path.
- **Manifest inside `payload.zip`:** it would then be covered by the payload's own hash, but a
  reviewer would have to unpack two zips to read it, and verifying would need the payload first.

## Evidence

- `tests/test_verify_command.py`: fresh bundle, unpacked copy, tampered copy, planted file, swapped
  payload, flipped bits in the payload and in the loader, not a bundle.
- [docs/learnings.md](../learnings.md) 2026-10-05 entries.
