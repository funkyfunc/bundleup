# bundleup

**Bundle up your Python app with everything it needs.** One command turns a locked project into a
single `.pyz` that runs on plain Python: no install step, no network, native extensions included.
And it tells you *before* you ship what won't survive the trip.

Dead simple to use, but also powerful and fast: esbuild's experience, for Python.

> **Status: pre-alpha.** Builds for this machine or another platform (Linux, macOS, Windows;
> x86_64 and arm64), passes the [gauntlet](https://github.com/funkyfunc/bundleup/blob/main/gauntlet/README.md)
> on all four in CI, and the own test suites of click, packaging, markupsafe and itsdangerous give
> the same results from a bundle as from a venv (nightly). Not yet released: the PyPI package (0.0.1) is a placeholder; run it from a
> checkout for now.

## Usage

```bash
bundleup build                  # the project in this directory -> dist/<name>.pyz
bundleup build path/to/script.py  # a PEP 723 script with inline dependencies
bundleup build --python 3.9     # build with Python 3.9 (pure Python: runs on 3.9 and newer)
bundleup build --python 3.11 --python-platform linux   # build on a Mac for Linux x86_64
bundleup build --python-platform linux --python-platform macos --python-platform windows   # one file for all three
bundleup build --json           # the result as JSON on stdout, for scripts and agents
bundleup check                  # what won't survive bundling, and each package's size
bundleup check --also-platform windows   # which packages lack a wheel for another OS
bundleup check --matrix         # which OS, CPU and Python versions the lock's wheels cover
bundleup build --smoke          # then run it once: fresh home folder, no network
bundleup check --audit          # ask PyPI: vulnerable, yanked or brand-new dependencies?
bundleup build --max-size 30MB # fail, writing nothing, if the bundle is bigger
bundleup build --format dir     # a plain directory, for apps that load packages from one
bundleup verify dist/app.pyz    # bundle and unpacked copy vs its manifest (corruption; not a signature)
bundleup cache clean            # remove unpacked bundles not used for 30 days
python dist/<name>.pyz          # run it: no install, no network
```

bundleup reads what you have: `pyproject.toml` with `uv.lock` or `pylock.toml`, a script's
`# /// script` block, or, without a lock, a `pyproject.toml`, `setup.py` or `requirements.txt`
(resolved at build time, with a warning; [recipes](docs/recipes.md)). It brings its own
[uv](https://docs.astral.sh/uv/) for the build; the bundle needs only Python. On first run it
unpacks to a cache (`~/Library/Caches/bundleup`, `~/.cache/bundleup`, or a temp directory if
those aren't writable), so later runs start as fast as an installed virtualenv; unpacking a new version removes older
copies of the same bundle that went unused for 30 days. A pure-Python
bundle runs on every Python version its lock allows (`Python 3.10+`), and on any OS when the lock
picks the same packages everywhere (`on any OS`); one with compiled code runs on the version and
platform it was built for. A bundle only sees
its own packages and the standard library; set `BUNDLEUP_INHERIT_PATH=1` to also let it use
packages installed on the machine (they come after the bundle's, but a machine package can still
win over a bundled namespace package of the same name: a Python rule, PEP 420). If it's started
with the wrong Python, it runs itself again with a matching one if one is installed; otherwise, and on
the wrong platform, it says so in one sentence. Programs it starts with
its own Python see its packages; any other Python it starts doesn't. bundleup never writes into
your project.

Every build checks the code first: a file of your project that doesn't compile on the target
Python stops the build, and anything that may not work in a bundle (a dependency's file that needs
a newer Python, data files a package expects under `sys.prefix`) is a warning. `bundleup check`
runs the same checks without writing a bundle and shows how big each package is; `--strict` makes
warnings fail too.

Recipes for Claude Skills, AWS Lambda, host applications, CI and HPC:
[docs/recipes.md](docs/recipes.md).

## Why

Python has three ways to hand a program to someone else, and the middle one is missing:

| Ship as | The other machine needs | Problem |
|---|---|---|
| Standalone executable | Nothing | Per-OS builds, code signing, antivirus |
| Source + `pip install` / `uv sync` | Python, an installer, network | The install step is where things break |
| **One file that runs on the user's Python** | **Python** | **No easy, reliable tool. That's bundleup** |

pex, shiv and zipapps can do parts of this. bundleup's bet is a much better experience on top of
the same correct approach: no flags to get it fast, plain-language errors, and a pre-ship check.
Measured against pex's fastest configuration: builds 1.1-2.4× faster, warm starts as fast as an
installed venv (pex adds 45-80 ms), first runs 2.3-15× faster
([findings](https://github.com/funkyfunc/bundleup/blob/main/docs/findings/2026-10-07-speed-vs-pex-best.md)).
See [docs/vision.md](https://github.com/funkyfunc/bundleup/blob/main/docs/vision.md).

## Where to start reading

- [MISSION.md](https://github.com/funkyfunc/bundleup/blob/main/MISSION.md): goal, scope, what "done" means
- [docs/vision.md](https://github.com/funkyfunc/bundleup/blob/main/docs/vision.md): where bundleup fits and who it's for
- [docs/roadmap.md](https://github.com/funkyfunc/bundleup/blob/main/docs/roadmap.md): where it could go next
- [docs/python-primer.md](https://github.com/funkyfunc/bundleup/blob/main/docs/python-primer.md): Python packaging explained for JavaScript developers
- [docs/adr/](https://github.com/funkyfunc/bundleup/blob/main/docs/adr/README.md): decisions and why they were made
- [docs/findings/2026-10-03-baseline.md](https://github.com/funkyfunc/bundleup/blob/main/docs/findings/2026-10-03-baseline.md): how pex, shiv and zipapps fare today
- [gauntlet/](https://github.com/funkyfunc/bundleup/blob/main/gauntlet/README.md): the test projects every bundler is measured against

## Gauntlet

```bash
uv run gauntlet/check_native.py                         # control group: projects run normally
uv run gauntlet/run_bundlers.py --conditions --out run  # existing bundlers, incl. hostile conditions
uv run gauntlet/report.py gauntlet/results/run.json > gauntlet/results/run.md
```

## License

[MIT](https://github.com/funkyfunc/bundleup/blob/main/LICENSE)
