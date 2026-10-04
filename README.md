# bundleup

**Bundle up your Python app with everything it needs.** One command turns a locked project into a
single `.pyz` that runs on plain Python: no install step, no network, native extensions included.
And it tells you *before* you ship what won't survive the trip.

Dead simple to use, but also powerful and fast: esbuild's experience, for Python.

> **Status: pre-alpha.** Research, positioning and the test suite are done; the bundler itself
> isn't written yet. Nothing is published on PyPI.

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
