# Findings 2026-10-07: speed against pex's fastest configuration

The independent review ([findings](2026-10-07-independent-review.md)) pointed out that
"builds 2-9× faster than pex" compared bundleup with pex resolving through pip, and that most of
bundleup's build speed is uv's. This run adds pex's fastest paths.

## Setup

`uv run gauntlet/bench.py 03 13 21 --python 3.12` on a MacBook (macOS, arm64), sequential, with
warm caches: build = median of 3 builds; first run = median of cold runs with a fresh `HOME`;
warm start = median of runs after one priming run. Tools:

- **pex**: pex 2.103.4 from exported requirements and built wheels (pip resolves): the earlier
  comparison.
- **pex-pylock**: `uv export --format pylock.toml`, then `pex --pylock ... --project ... --venv
  prepend`.
- **pex-venv**: `uv sync` into a venv, then `pex --venv-repository ... --venv prepend`. The sync is
  included in the build time, as bundleup's install is in its own.
- **venv**: `uv sync` and run the console script: the floor for start-up.

Results: [gauntlet/results/bench-vs-pex-best-2026-10-07.md](../../gauntlet/results/bench-vs-pex-best-2026-10-07.md).

## Results (milliseconds, medians)

| Project | Tool | Build | First run | Warm start |
|---|---|---|---|---|
| 03 small, pure | venv | – | – | 29 |
| | **bundleup** | **208** | **48** | **28** |
| | pex | 1,472 | 589 | 203 |
| | pex-pylock | 3,595 | 711 | 78 |
| | pex-venv | 496 | 711 | 84 |
| 13 NumPy | venv | – | – | 38 |
| | **bundleup** | **486** | **562** | **38** |
| | pex | 1,858 | 1,165 | 228 |
| | pex-pylock | 5,155 | 1,372 | 88 |
| | pex-venv | 807 | 1,318 | 88 |
| 21 large, 147 MB | venv | – | – | 340 |
| | **bundleup** | **2,838** | **1,370** | **341** |
| | pex | 4,783 | 3,173 | 726 |
| | pex-pylock | can't build | | |
| | pex-venv | 3,082 | 3,591 | 422 |

## What it means

- **Build time against pex's best path is 1.1-2.4× faster, not 2-9×.** On the large project
  the difference is small (2.8 s vs 3.1 s); uv does most of the work for both.
- **Start-up is where bundleup clearly leads**, with no flags: warm start equals an installed venv
  (pex's fastest mode adds 45-80 ms), and first runs are 2.3-15× faster (48 ms vs 711 ms on the
  small project).
- **pex can't build gauntlet 21 from uv's `pylock.toml`**: "the lock created by uv likely does
  not include optional `dependencies` metadata ... required for Pex to subset a PEP-751 lock".
  `--pylock` is also pex's slowest path here (it fetches each file itself).
- `pex-venv` needed its `--python` flag removed for gauntlet 21 (pex refused the venv's target);
  the venv fixes the interpreter anyway.

Claims to use from now on: "builds as fast as or faster than pex's fastest configuration, starts
as fast as an installed venv, first runs several times faster than pex", with this page as the
source.
