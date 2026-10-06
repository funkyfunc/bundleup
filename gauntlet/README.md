# The gauntlet

Test projects that every bundler (pex, shiv, zipapps, and ours) gets run against. Each project is
small, and each one targets **one way bundling breaks**. See [MISSION.md](../MISSION.md) for why.

## How a project passes

Every project is a normal, locked uv project (or a PEP 723 script) that checks its own behaviour
with `assert`s and, on success, prints exactly:

```
GAUNTLET OK <id>
```

and exits 0. Anything else is a failure. No project needs network access at run time.

## Control group

```bash
uv run gauntlet/check_native.py
```

Runs every project installed the normal way on Python 3.9 (macOS system Python), 3.10 and 3.12.
If a project fails here, the *test* is broken, not the bundler. Add `--heavy` to include PyTorch,
`--python 3.11` to pick versions, or pass id prefixes (`05 13`) to run a subset.

Last run (2026-10-03, macOS arm64): all projects pass on every Python they support.

## Running the bundlers

```bash
uv run gauntlet/run_bundlers.py --conditions --out <name>
uv run gauntlet/run_bundlers.py --tool bundleup --conditions --check --python 3.11 --out <name>
uv run gauntlet/report.py gauntlet/results/<name>.json > gauntlet/results/<name>.md
```

Builds every project with bundleup (this repo's, via `uv sync`), pex, shiv, zipapps and a naive
`pip --target` + `zipapp`, for Python 3.9 and 3.12 by default (`--python` takes any version), then
runs each bundle from an empty directory with a fresh `HOME`. bundleup is given the project
directory itself; the other tools get pre-exported requirements and a pre-built wheel, so
bundleup's build time includes work theirs doesn't. Filter with `--tool`, `--python` and id
prefixes. Scratch output goes to `gauntlet/.work/` (git-ignored).

- **Pythons:** "3.9" on macOS means Apple's `/usr/bin/python3`; everything else is a uv-managed
  Python (`uv python install <version>`). Bundles never run on a virtual environment: a venv's own
  packages could mask one missing from a bundle, so the harness refuses one.
- **No network:** blocked with `sandbox-exec` on macOS and `sudo unshare --net` on Linux (needs
  passwordless sudo, as on CI). Windows can't block it; each result records `network_blocked`.
- **`--conditions`** adds the hostile runs (spaces in path, read-only cwd, read-only HOME,
  simultaneous first runs; Windows skips the read-only ones, since it ignores read-only on
  directories) and, for bundleup, **`matches-venv`**: the project installed normally with
  `uv sync` and the bundle's payload must have the same distributions and versions, the same
  entry points, and the same top-level modules importing ([snapshot.py](snapshot.py)).
- **`--check`** exits 1 if any result isn't what the project's `gauntlet.toml` expects. CI uses it.

bundleup also checks every bundle at build time: the payload must match `uv.lock` (every locked
package at its locked version, nothing extra) and every wheel's `RECORD` (every file present and
byte-identical, nothing unexplained). See [testing-strategy.md](../docs/testing-strategy.md).

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the gauntlet for bundleup with
`--conditions --check` on every push: Linux x64 (3.9, 3.11, 3.12), Linux arm64 and Windows x64
(3.11, 3.12), macOS arm64 (Apple's 3.9, 3.12). Each job uploads its results JSON as an artifact.

## Cross-target builds

```bash
uv run gauntlet/cross.py build --python 3.11 --python-platform x86_64-manylinux_2_28 --dir out
uv run gauntlet/cross.py run --python 3.11 --dir out --check    # on the target platform
```

[cross.py](cross.py) builds every project on one machine for another platform, then runs the
bundles on that platform with the hostile conditions and `matches-venv` (against a normal install
made on the target). CI runs three pairs on every push: macOS → Linux x86_64, Linux → Windows,
Linux → macOS arm64.

## Breadth smoke test (nightly)

```bash
uv run gauntlet/smoke.py --top 200 --out <name>    # the most-downloaded PyPI packages
uv run gauntlet/smoke.py click requests            # specific packages
```

[smoke.py](smoke.py) makes a throwaway locked project for each package, installs it normally,
bundles it, and runs the `matches-venv` comparison. Packages that don't install normally on the
platform are skipped. It imports third-party code, so it runs nightly on GitHub's runners
([`nightly.yml`](../.github/workflows/nightly.yml), Linux x64/arm64, macOS, Windows; ADR-0017), not
on personal machines. Every failure should become a gauntlet project or a learning.

## Corpus (nightly)

[corpus.toml](corpus.toml) lists real programs, each pinned: PyPI CLIs (wrapped in a throwaway
locked project) and GitHub repos with `uv.lock` (cloned at a commit). [corpus.py](corpus.py)
installs each normally and bundles it, runs the same commands both ways (`--version`, `--help`),
and compares exit codes and output. [corpus_issues.py](corpus_issues.py) groups failures by
signature into `corpus-failure` issues. Runs nightly on GitHub's runners only
([`corpus.yml`](../.github/workflows/corpus.yml), ADR-0017): it runs third-party code.

Every Monday [weekly_summary.py](weekly_summary.py) ([`weekly.yml`](../.github/workflows/weekly.yml))
collects the week's smoke and corpus results into `docs/findings/<date>-nightly-summary.md` and
proposes it as a pull request, so the results outlive GitHub's 90-day artifact limit. Try it
locally (it only reads results through `gh`; nothing third-party runs):
`uv run gauntlet/weekly_summary.py --repo funkyfunc/bundleup --out /tmp/summary.md`.

## Measuring speed

```bash
uv run gauntlet/bench.py                                   # 03, 13, 21 on 3.12: venv, bundleup, shiv, pex
uv run gauntlet/bench.py 03 --python 3.9 --tool bundleup --out <name>
```

`run_bundlers.py` runs builds in parallel, so its timings are noisy. `bench.py` runs one thing at a
time and reports medians: build (warm caches), first run (fresh `HOME`, so nothing cached) and warm
start, with an installed venv as the floor. Use it for any speed claim, and compare tools from the
same run.

Latest analysis: [docs/findings/2026-10-04-milestone-1.md](../docs/findings/2026-10-04-milestone-1.md)
(bundleup) and [docs/findings/2026-10-03-baseline.md](../docs/findings/2026-10-03-baseline.md)
(existing tools).

## Projects

| ID | Exercises | Expect |
|---|---|---|
| `00-hello-script` | PEP 723 script, stdlib only | pass |
| `01-script-with-deps` | PEP 723 script with an inline dependency (click) | pass |
| `02-multi-module-package` | First-party src layout, subpackages, relative imports, `__main__` | pass |
| `03-pure-deps` | Several pure-Python dependencies | pass |
| `04-resources-zip-safe` | `importlib.resources`; certifi's CA bundle must be a real file for `ssl` | pass |
| `05-dunder-file-data` | `Path(__file__).parent / "templates"`; pytz's `__file__`-then-resources fallback | pass |
| `06-metadata-version` | `importlib.metadata.version()` at import time; needs `.dist-info` | pass |
| `07-entry-point-plugins` | Plugin discovery via entry points from a second local distribution | pass |
| `08-namespace-packages` | PEP 420 namespace split across two distributions | pass |
| `09-dynamic-imports` | `import_module(f"...{name}")`; Pygments lexers loaded by name | pass |
| `10-optional-accelerators` | PyYAML LibYAML and mypyc'd charset-normalizer; reports whether compiled paths loaded | pass |
| `11-native-abi3` | cryptography (abi3 Rust extension) | pass |
| `12-native-per-version` | pydantic-core (one extension per Python version) | pass |
| `13-native-bundled-libs` | NumPy with vendored OpenBLAS shared libraries | pass |
| `14-real-world-pptx` | python-pptx: `__file__` template + lxml + Pillow. The original use case | pass |
| `15-flask-templates` | Flask templates and static files served from package directories | pass |
| `16-multiprocessing-spawn` | `spawn` workers must re-import the program's modules | pass |
| `17-modern-syntax` | PEP 695 / PEP 701 syntax, `requires-python >=3.12` | pass on ≥3.12, **refuse** when targeting older |
| `18-sdist-only-dep` | docopt has no wheel, only an sdist | pass |
| `19-subprocess-sys-executable` | Child `sys.executable -c "import click"` must see the bundle's dependencies | pass |
| `20-heavy-ml` | PyTorch + NumPy; size reporting. Marked `heavy`, skipped by default | pass |
| `21-large-pure-python` | ~8,000 files / 44 MB of pure-Python source (sympy, Django, boto3, networkx): the performance check for compile, zip, extract and analysis; Django locale and botocore model data files | pass |
| `22-wheel-executables` | ruff's compiled program ships as a wheel script (`bin/ruff`); its wrapper must find it next to the packages | pass |
| `23-pth-files` | `.pth` files run as in a venv: setuptools' distutils shim, a path line (also in a child process), pywin32 on Windows | pass |

## `gauntlet.toml`

| Key | Meaning |
|---|---|
| `id` | Same as the directory name |
| `title`, `exercises`, `notes` | What the project tests and why it's hard |
| `tier` | Rough difficulty, 0 (trivial) to 8 (heavy) |
| `entry` | `module:function` for project-style tests. The console script in `pyproject.toml` points at the same function |
| `script` | For PEP 723 projects: the script file to run |
| `args` | Command-line arguments the run must pass |
| `expect` | `pass` or `refuse` |
| `expect_refuse_below` | Python version below which a bundler must refuse at build time |
| `heavy` | Skipped unless explicitly requested |

## Run conditions

Each bundle should also be run under hostile conditions, because these break bundles that pass in
a normal shell. Covered by `run_bundlers.py`: no network, macOS's system Python 3.9, paths with
spaces and non-ASCII characters, read-only cwd, read-only `HOME`, simultaneous first runs, a
broken copy of every bundled package in the user's site-packages (`user-site-conflict`, bundleup
only), Linux and Windows (CI). Still to do:

- Read-only bundle location, and a read-only or missing cache directory
- No `HOME` / unusual `HOME`
- Built on one platform, run on another (cross-target builds, roadmap item 7)
