# Faster large builds (2026-10-05)

Roadmap item 9: the large-project findings showed bundleup's build no faster than pex on gauntlet
21, with the time in zipping and compiling ([2026-10-04](2026-10-04-large-project-and-rust.md)).
Design: [ADR-0020](../adr/0020-parallel-zip-and-bytecode-cache.md) (Proposed).

## Setup

macOS arm64, Python 3.12, warm uv cache. Step timings from `bundleup build -v`; builds and runs
from `gauntlet/bench.py` (median of 3 builds, 5 first runs, 10 warm runs);
[bench-faster-builds-2026-10-05.json](../../gauntlet/results/bench-faster-builds-2026-10-05.json).

## Results

### Where the time went, step by step (gauntlet 21)

| Step | Before | Parallel zip (level 1) | + bytecode cache, warm | + `os.walk` instead of `relative_to` | Final (level 6) |
|---|---|---|---|---|---|
| compile | 1,264 ms | 1,241 ms | 758 ms | 565 ms | ~570 ms |
| zip | 3,156 ms | 1,360 ms | 1,288 ms | 1,000 ms | 1,061 ms |

- **Parallel compression:** 2.3× on 21 and 3.8× on 13 (603 → 160 ms).
- **The bytecode cache:** compile 1.26 → 0.76 s on a rebuild; hard links instead of copies were no
  faster.
- **The biggest single surprise:** `pathlib.Path.relative_to()` cost ~60 µs a call, over a second
  for 18,000 files across the zip, cache-restore and source scans. Plain `os.walk` strings fixed it.

### Compression level, now that it's parallel (gauntlet 21)

| Level | Zip time | Payload |
|---|---|---|
| 1 | 1,012 ms | 62.6 MB |
| 3 | 1,022 ms | 60.4 MB |
| 6 | 1,062 ms | 57.4 MB |

The old `zipfile` code was meant to use level 1 but really used 6: `writestr()` ignores
`compresslevel` for a `ZipInfo`. Level 6 keeps bundles at their previous size (NumPy 9.1 MiB) for
~5% more zip time.

### Reproducibility

A networkx test module's `.pyc` differed between a cold-cache and a warm-cache build: set literals
are stored in hash order, and string hashes are randomised per process. Compiling with
`PYTHONHASHSEED=0` makes cold, warm and repeat-cold builds byte-identical (now a test).

### Before and after (3.12)

| Project | Build before | Build after | pex | First run before → after |
|---|---|---|---|---|
| 03 (pure) | 245 ms | **156 ms** | 1,469 ms | 47 → 49 ms |
| 13 (NumPy) | 994 ms | **400 ms** | 1,824 ms | 579 → 576 ms (same-session A/B) |
| 21 (large) | 5,188 ms | **2,470 ms** warm cache, 3,360 ms cold | 5,451 ms | — → 1,420 ms |

Builds are now 2-9× faster than pex. First runs are unchanged: a benchmark run showed 13 at
812 ms, but an A/B of old and new bundles in the same session measured 579/559 vs 576/564 ms.

## What it means

- No Rust needed for build speed; the remaining time on 21 is reading 11,568 files, zlib, and
  compiling the project's own code.
- Next build-speed levers if needed: skip the staging tree's deletion (~0.6 s on 21), or cache
  whole installed distributions rather than only their bytecode.
