# bundleup

**Bundle up your Python app with everything it needs.** One command turns a locked project into a
single `.pyz` that runs on plain Python: no install step, no network, native extensions included.
And it tells you *before* you ship what won't survive the trip.

Dead simple to use, but also powerful and fast: esbuild's experience, for Python.

> **Status: pre-alpha.** The bundler works for the machine you build on (one platform, one Python
> version per bundle) and passes the [gauntlet](https://github.com/funkyfunc/bundleup/blob/main/gauntlet/README.md)
> on macOS. The PyPI release (0.0.1) is still a placeholder; run it from a checkout for now.

## Usage

```bash
bundleup build                  # the project in this directory -> dist/<name>.pyz
bundleup build path/to/script.py  # a PEP 723 script with inline dependencies
bundleup build --python 3.9     # build for another Python (a bundle runs on one Python version)
bundleup build --python 3.11 --python-platform linux   # build on a Mac for Linux x86_64
bundleup build --json           # the result as JSON on stdout, for scripts and agents
bundleup check                  # what won't survive bundling, and each package's size
bundleup verify dist/app.pyz    # check a bundle (and its unpacked copy) against its manifest
bundleup cache clean            # remove unpacked bundles not used for 30 days
python dist/<name>.pyz          # run it: no install, no network
```

bundleup reads `pyproject.toml` + `uv.lock` (or the script's `# /// script` block) and needs
[uv](https://docs.astral.sh/uv/) at build time; the bundle needs only Python. On first run it
unpacks to a cache (`~/Library/Caches/bundleup`, `~/.cache/bundleup`, or a temp directory if
those aren't writable), so later runs start as fast as an installed virtualenv. A bundle only sees
its own packages and the standard library; set `BUNDLEUP_INHERIT_PATH=1` to also let it use
packages installed on the machine (they come after the bundle's, but a machine package can still
win over a bundled namespace package of the same name: a Python rule, PEP 420). If it's started
with the wrong Python or on the wrong platform, it says so in one sentence.

Every build checks the code first: a file of your project that doesn't compile on the target
Python stops the build, and anything that may not work in a bundle (a dependency's file that needs
a newer Python, data files a package expects under `sys.prefix`) is a warning. `bundleup check`
runs the same checks without writing a bundle and shows how big each package is; `--strict` makes
warnings fail too.

## Why

Python has three ways to hand a program to someone else, and the middle one is missing:

| Ship as | The other machine needs | Problem |
|---|---|---|
| Standalone executable | Nothing | Per-OS builds, code signing, antivirus |
| Source + `pip install` / `uv sync` | Python, an installer, network | The install step is where things break |
| **One file that runs on the user's Python** | **Python** | **No easy, reliable tool. That's bundleup** |

pex, shiv and zipapps can do parts of this. bundleup's bet is a much better experience on top of
the same correct approach: no flags to get it fast, plain-language errors, and a pre-ship check.
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
