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

## Running the existing bundlers

```bash
uv run gauntlet/run_bundlers.py --conditions --out <name>
uv run gauntlet/report.py gauntlet/results/<name>.json > gauntlet/results/<name>.md
```

Builds every project with bundleup (this repo's, via `uv sync`), pex, shiv, zipapps and a naive
`pip --target` + `zipapp`, for Python 3.9 and 3.12, then runs each bundle with network blocked from an
empty directory. bundleup is given the project directory itself; the other tools get pre-exported
requirements and a pre-built wheel, so bundleup's build time includes work theirs doesn't. `--conditions` adds
the hostile runs (spaces in path, read-only cwd, read-only HOME, simultaneous first runs). Filter
with `--tool`, `--python` and id prefixes. Scratch output goes to `gauntlet/.work/` (git-ignored).

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

Each bundle should also be run under hostile conditions, because these break bundles that pass
in a normal shell. `run_bundlers.py` covers the base run with no network, paths with spaces,
read-only cwd, read-only HOME and simultaneous first runs; the rest are still to do:

- macOS system Python (`/usr/bin/python3`, 3.9)
- No network access
- Read-only bundle location, and a read-only or missing cache directory
- No `HOME` / unusual `HOME`
- A path containing spaces and non-ASCII characters
- Two processes starting the same bundle at once (first-run extraction race)
- An older, conflicting version of a dependency already installed in the user's site-packages
- Built on one platform, run on another (macOS arm64 → Linux x86_64 in a container)
