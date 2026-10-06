# CI across platforms, and proving bundles contain the right files (2026-10-05)

Roadmap items 2 and 4: the gauntlet's first runs off the development Mac, and the checks that
prove a bundle contains exactly what `uv.lock` says ([testing-strategy.md](../testing-strategy.md)
"What correct means").

## Setup

- **CI** ([ci.yml](../../.github/workflows/ci.yml)), every push: Ruff and pyright; unit tests on
  `ubuntu-24.04`, `ubuntu-24.04-arm`, `macos-15`, `windows-2025`; the gauntlet for bundleup with
  `--conditions --check` on 9 jobs: Linux x64 (3.9, 3.11, 3.12), Linux arm64 and Windows x64
  (3.11, 3.12), macOS arm64 (Apple's `/usr/bin/python3` 3.9, and 3.12). Network blocked with
  `sandbox-exec` (macOS) and `sudo unshare --net` (Linux); Windows can't block it.
- **Build-time checks** ([`_verify.py`](../../src/bundleup/_verify.py)), every build: lock vs
  bundle, and every wheel's `RECORD` vs the payload.
- **`matches-venv`**, a new gauntlet condition: each bundle's packages compared with a `uv sync`
  install (distributions and versions, entry points, which top-level modules import).
- **`bundleup verify`** with an embedded manifest ([ADR-0019](../adr/0019-manifest-and-verify-command.md)).
- **Breadth smoke test** ([smoke.py](../../gauntlet/smoke.py), [nightly.yml](../../.github/workflows/nightly.yml)):
  the 100 most-downloaded PyPI packages (from hugovk/top-pypi-packages, 2026-10-05), each in a
  throwaway locked project, installed normally, bundled, and compared with `matches-venv`, on all
  four runner OSes with Python 3.12.

## Results

### The gauntlet off the Mac

| Platform | Pythons | Projects | Hostile conditions |
|---|---|---|---|
| Linux x64 | 3.9, 3.11, 3.12 | all pass; 17 refused below 3.12 | 4/4, network blocked |
| Linux arm64 | 3.11, 3.12 | all pass | 4/4, network blocked |
| Windows x64 | 3.11, 3.12 | all 21 pass | spaces and concurrent first runs pass; read-only skipped (Windows ignores it on directories); network not blocked |
| macOS arm64 | Apple 3.9, 3.12 | all pass; 17 refused on 3.9 | 4/4, network blocked |

bundleup had never run on Linux or Windows. It passed every project on first contact, with one
code change made in advance (the loader no longer refuses an *unknown* CPU, only a different one).

### Correctness checks

- **Build-time lock and `RECORD` checks** pass on every gauntlet project on every platform above,
  at 1–5 ms per build. Unit tests show each kind of mismatch is caught (missing, wrong version,
  extra, duplicate; missing, changed, extra file).
- **`matches-venv`** passes for every project on every platform. On its first local run it found
  one real difference: wheel *data files* (sympy's `share/man/...`) land at the payload root with
  `--target` instead of `<venv>/share/`, where `share` even imports as a namespace package.
  Harmless for a man page; recorded in [learnings](../learnings.md).
- **`bundleup verify`** catches a tampered or planted file in the unpacked copy, a swapped
  payload, flipped bits in the payload and in the loader. Writing that last test showed the
  loader wasn't hashed at first; it is now.
- **A harness flaw, fixed:** since milestone 1, "3.12" bundles had run on the repo's own `.venv`,
  whose packages could have masked a missing one. With a clean interpreter, every result held.

### Breadth smoke test

| OS | Packages | Pass | Skipped | Failed |
|---|---|---|---|---|
| Linux x64 | 100 | 100 | 0 | 0 |
| Linux arm64 | 100 | 100 | 0 | 0 |
| macOS arm64 | 100 | 100 | 0 | 0 |
| Windows x64 | 100 | 100 | 0 | 0 |

The 100 include pandas, numpy, scipy, pyarrow, pydantic-core, cryptography, grpcio, lxml,
pillow, regex, ruff, greenlet and other packages with compiled code, plus boto3/botocore, openai,
fastapi and pytest. Each bundle matched a normal install on every platform: same distributions
and versions, same entry points, and the same top-level modules importing.

## What it means

- **Cross-platform correctness of the core is good**, on Python 3.9–3.12 and four OS/CPU pairs.
  The remaining risk is breadth beyond the top 100 and real programs (not just imports), which the
  nightly run at 200 packages and the corpus testing (roadmap item 6) address.
- **"Contains exactly the right files" is now proven per build**, not assumed, and re-checkable
  later with `bundleup verify`.
- **Gaps:** Windows can't block network in CI; the read-only conditions don't apply on Windows;
  the smoke test only imports top-level modules; macOS Intel and Windows arm64 aren't in the
  matrix yet.
