# A large pure-Python project, build cost, and whether Rust would help (2026-10-04)

Two questions from the user after milestone 1: add a gauntlet project big enough to be a real
performance check, and is Python still the right language for bundleup
([ADR-0008](../adr/0008-prototype-in-python.md))?

## Setup

- New gauntlet project **`21-large-pure-python`**: sympy, Django, boto3/botocore and networkx.
  8,232 files, 3,336 `.py`, 44 MB of Python source, no native code, ~35 MB of downloads. It runs on
  Python 3.9 too (the lock forks: Django 4.2 and networkx 3.2 there). It also checks data files:
  Django's translation catalogs and botocore's service models. Control group passes on 3.9, 3.10
  and 3.12.
- Correctness: `run_bundlers.py 21 --conditions`, all five tools, 3.9 and 3.12. Raw:
  [large-2026-10-04.md](../../gauntlet/results/large-2026-10-04.md).
- Speed: `bench.py 21 --builds 2 --cold-runs 5 --runs 10` (3.12, sequential). Raw:
  [bench-large-2026-10-04.json](../../gauntlet/results/bench-large-2026-10-04.json).
- Experiments on the extracted trees of 21 and of 20-heavy-ml (PyTorch: 16,561 files without
  `.pyc`, 585 MB, 5,381 `.py`, 98 MB of source), on a 14-core (10 performance) M-series Mac.

## Results

### Correctness

| Tool | 3.9 | 3.12 | Hostile conditions |
|---|---|---|---|
| bundleup | ✅ | ✅ | 4/4 on both |
| pex | ✅ | ✅ | 4/4 on both |
| shiv | ✅ | ✅ | read-only `HOME` fails (as always) |
| zipapps | ❌ | ❌ | – |
| zipapp-naive | ❌ | ❌ | – |

**New failure mode:** zipapps and the naive zipapp fail with *"No translation files found for
default language en"*. Django locates its `.mo` catalogs through the package's directory, which
doesn't exist inside a zip. Same family as 05 and 15, but in a framework's core rather than in user
code.

### Speed (3.12, sequential)

| | Build | First run | Warm start | Size |
|---|---|---|---|---|
| venv | – | – | 353 ms | – |
| **bundleup** | **5.19 s** | **1,404 ms** | **352 ms** | 57.5 MB |
| shiv | 7.75 s | 2,592 ms | 416 ms | 34.4 MB |
| pex | 5.45 s | 3,689 ms | 1,139 ms | 36.6 MB |

- Start-up holds up: warm equals the venv; first run is about half of shiv's.
- **The build lead over pex vanishes on large projects** (5.2 vs 5.5 s; it was 6× on 03). And the
  bundle is 57% bigger than pex's (precompiled `.pyc` plus compression level 1).

### Where bundleup's build time goes

`BUNDLEUP_TIMINGS=1` for 21:

| Step | 3.12 | 3.9 | Who does the work |
|---|---|---|---|
| Find/probe Python | 25 ms | 55 ms | target Python |
| Export + install | 0.17–0.31 s | 0.15–0.26 s | uv (Rust) |
| Compile bytecode | 1.3 s | 1.7 s | target Python's `compileall` |
| Zip (deflate + write) | 3.1 s | 2.7 s | zlib (C), one thread, via `zipfile` |
| Write bundle | 30–60 ms | 60 ms | |
| Delete the staging directory | ~0.6 s | ~0.6 s | filesystem (not in the breakdown) |
| **Total** | **5.2–5.3 s** | **5.3–5.4 s** | |

For PyTorch (20): 14.5 s total, of which zip 11.3 s and compile 2.0 s.

### Experiment 1: does compression parallelise in Python?

Deflate level 1 of every file (no `.pyc`), sequential vs a thread pool:

| | Sequential | 4 threads | 8 threads |
|---|---|---|---|
| 21 (83 MB) | 1.45 s | **0.31 s** (4.7×) | 0.50 s |
| 20 (585 MB) | 4.70 s | **2.13 s** (2.2×) | 2.28 s |

Yes. zlib releases the GIL, so plain Python threads get the speed-up Rust would. The build's zip
step takes ~2× longer than raw deflate (3.1 s vs 1.45 s for 21; 11.3 vs 4.7 s for 20), so
`zipfile`'s per-entry overhead and the extra `.pyc` files matter as much as compression itself.

### Experiment 2: what would the analyzer's scan cost?

The future analyzer (`bundleup check`) has to parse code. Proxy: `ast.parse` every `.py` and walk
every node, doing nothing else:

| | Parse only, 1 process | Parse + walk, 1 process | Parse + walk, 8 processes |
|---|---|---|---|
| 21 (44 MB source) | 3.42 s | 5.17 s | 0.81 s |
| 20 (98 MB source) | 6.77 s | 10.50 s | 1.60 s |

ADR-0008's Rust trigger is "a cold scan of 20-heavy-ml taking over 5 s". A single-process Python
scanner would already be past it before doing any analysis. With processes it's 1.6 s, and real
analysis on top could put it anywhere from 3 to 8 s. Ruff-class Rust parsers handle this much
source in well under a second.

## What it means

**For the bundler that exists today, Rust would not make builds meaningfully faster.** Almost none
of the time is bundleup's own Python code:

- **uv** (install) is already Rust.
- **Compiling bytecode** has to be done by the *target* Python (`.pyc` files are specific to one
  Python version), so no other language can take it over. The fix is to compile each wheel once and
  cache the result keyed by wheel hash + Python version. ADR-0008 already plans this caching for
  analysis results.
- **Compression** is zlib (C). Threads give 2–5× (experiment 1), and writing the zip records
  directly instead of through `zipfile` removes the rest.
- **Deleting the staging tree** (0.6 s) can be avoided by reusing it or deleting in the
  background.

Together these should bring 21 from ~5.2 s to roughly 1.5–2 s on a rebuild, all in Python.

**For the analyzer, Rust is plausibly needed, and it should be decided with measurements when the
scanner is prototyped.** Its job is parsing a lot of source fast, which is exactly what Rust
parsers are good at, and the proxy is at ADR-0008's trigger. Per-wheel caching means each wheel is
scanned once per machine, which softens it; a cold first build of a PyTorch project is the case
that would hurt. If the trigger fires, ADR-0008's path applies: a Rust extension (PyO3/maturin) for
the scanner only, with a new ADR.

**The runtime loader stays Python regardless**: it runs on the user's Python, and it already
matches an installed venv.

No decision changes: ADR-0008 stands. This adds evidence for when to apply its trigger.

## Next steps

1. Parallel compression and a direct zip writer (biggest build win; Python).
2. Per-wheel bytecode cache keyed by wheel hash + Python version.
3. Avoid the synchronous staging-tree deletion.
4. When prototyping `bundleup check`, measure the real scanner on 20 and 21 against the 5 s trigger
   before writing any Rust.
5. Re-run `bench.py` (03, 13, 21) after each of these.
