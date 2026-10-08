# Vision: where we fit

The [mission](../MISSION.md) says what we're building. This page says where it sits among the
existing ways to ship Python, who it's for, and why the bet is on experience rather than on a new
capability. New to Python packaging? Read the [primer](python-primer.md) first. Where it could go next:
[roadmap.md](roadmap.md).

## What it does

bundleup makes **self-contained Python files**: your code and its dependencies in one `.pyz` that
runs with plain `python`, no install step, no network ([ADR-0012](adr/0012-lead-with-what-it-does.md):
lead with what it does; use cases are examples).

## The problem it solves

You have Python code with dependencies, and you want to hand it to a machine that **has Python but
nothing else**: no uv, no pip setup, maybe no network. Today there's no easy, reliable way to do
that.

## The options today

| How you ship it | What the other machine needs | The catch |
|---|---|---|
| Docker image | Docker | Heavy; fine for servers, absurd for a script |
| PyInstaller / Nuitka executable | Nothing | One build per OS, code signing, antivirus warnings |
| `pip install` / `uv sync` | Python, pip or uv, network, some venv know-how | The install step is where things fail |
| `uv run` / `pipx run` | uv or pipx, and network on first run | Fails offline and in sandboxed containers |
| pex / shiv | **Python** | Works, but complicated to use, and you only find out what breaks when it breaks |
| **Us** | **Python** | Dead simple to use, and checked before you ship |

We sit in the same place as pex and shiv: the "needs only Python" option.

## The bet: a better experience, not a new capability

pex can already do most of the core job. **That's fine.** JavaScript bundling followed the same
path: webpack could already bundle everything when Rollup, Parcel, esbuild and Vite arrived. They
won by being simpler, faster and more predictable, not by bundling things webpack couldn't.

pex is Python's webpack: capable, configuration-heavy, built for monorepo build systems. We're
aiming to be the esbuild: **dead simple to use, but also powerful and fast.**

What that means concretely:

**Dead simple**
- One command, no config file needed: `bundleup build app.py` does the right thing.
- Reads the files you already have: `pyproject.toml`, `uv.lock`, `pylock.toml`, PEP 723 scripts.
- Sensible defaults: the platform you're on; for pure-Python code, every Python version the lock
  allows ([ADR-0030](adr/0030-pure-python-bundles-run-on-a-range.md)); with compiled code, the
  one version it was built for.
- Errors that name the cause and the fix, not stack traces.

**Powerful**
- Other platforms from one machine (`--python-platform`), one bundle per target or one for
  several; a destination's settings are a [recipe](recipes.md), not a name to remember.
- Native dependencies handled correctly: the whole payload unpacks once to a cache, so compiled
  code, `__file__` paths and package metadata work as in a venv.
- A pre-ship check that finds what will break (`bundleup check`).
- Not built yet: escape hatches for the long tail (include extra files, mark a dependency
  external) and one bundle for several platforms.

**Fast**
- Measured, not claimed: build time compared with pex, including pex's fastest configuration
  ([findings](findings/)).
- Warm rebuilds should feel instant, the way esbuild made bundling disappear from the dev loop.
- Fast start-up of the bundle itself, including the first run.

## Before and after

The case that started this project: an agent skill that includes a python-pptx script.

**Before:** the user installs the skill, the script crashes with `ModuleNotFoundError: pptx`, and
the user has to figure out a venv and pip.

**After:**

```bash
bundleup build scripts/make_deck.py -o scripts/make_deck.pyz
```

Add `--python-platform macos --python-platform linux --python-platform windows` (and more
`--python` versions if your users vary) and `make_deck.pyz` carries a payload for each; on the
user's machine, `python make_deck.pyz` picks the right one and just works: no install, no network.
`bundleup check --matrix` shows which platforms the lock's wheels can serve. Pure-Python scripts
need no extra payloads: one runs on every OS. (In the Claude API sandbox python-pptx is
preinstalled; the [recipe](recipes.md) is for scripts that need packages it doesn't have.)

If something can't work, you find out at **build** time, not from a user:
- "make_deck needs Python >=3.12, but the target is Python 3.11";
- "pillow 12.3.0: wheels only for manylinux_2_27_x86_64, manylinux_2_28_x86_64, ...;
  x86_64-manylinux_2_28 would work";
- "deck.py:12 doesn't compile on Python 3.11".

## What we solve

1. **One command from the files you already have.** It reads your `pyproject.toml` with `uv.lock`
   or `pylock.toml`, or a PEP 723 script, and produces one `.pyz` per platform. There's nothing
   new to configure, and nothing is written into your project.
2. **It runs on the user's Python without installing anything.** That includes compiled packages:
   NumPy, cryptography, lxml. The payload unpacks once to a cache on first run (compiled code
   can't run from inside a zip, and plenty of pure-Python code expects real files), so later runs
   start as fast as an installed venv.
3. **It tells you what will break before you ship.** Because everything is unpacked, `__file__`
   paths, package metadata, plugins and imports by name simply work (the gauntlet proves each), so
   the check looks for what's left: packages with no wheel for a target (from the lock alone, for
   any number of platforms), code that doesn't compile on the Python you target, data files a
   package expects under `sys.prefix`, and size limits for Lambda.
4. **A clear message instead of a stack trace.** The bundle checks the Python version, platform,
   CPU, C library and macOS version first and explains the problem if they don't match.

## What people use it for

Examples, not the definition (from [round 4 research](research/round-4-synthesis.md)):
- **Works today:** internal tools and CLIs, CI scripts, push-and-run ops and incident-response
  scripts, HPC jobs on offline compute nodes, air-gapped servers, Raspberry Pi, course tools and
  graders, agent sandboxes and skills (e.g. Claude API Skills, which have no network), and Docker
  images built by copying one `app.pyz`.
- **Also built (2026-10):** builds for other platforms from one machine, AWS Lambda zips
  (`--format lambda`), plain directories for apps with Python built in such as Splunk and QGIS
  (`--format dir`). See [ADR-0025](adr/0025-dir-and-lambda-formats-and-presets.md).
- **Not for:** desktop apps for people who don't have Python, Cloudflare Workers/Pyodide, Python in
  Excel, projects that depend on system libraries or CUDA.

## What we're not

- **Not a replacement for uv.** uv builds the environment; we pack it. Ideally uv could call us.
- **Not an executable builder.** That would bring code signing back.
- **Not a Docker replacement** for big services, and not meant for multi-gigabyte ML stacks. Those
  get a size warning, not a promise.

## Why now

All the building blocks became available in 2024–2025:
- uv resolves dependencies quickly and correctly;
- lockfiles finally have a standard (`pylock.toml`, PEP 751);
- almost every package ships prebuilt wheels;
- uv has publicly put bundling off its immediate roadmap: "focused on core functionality outside
  of bundling" (uv#7419), `uv bundle` labelled a wish (#5802), PyInstaller output closed as not
  planned (#13503).

## What the baseline run is for

Running pex, shiv and zipapps against the [gauntlet](../gauntlet/README.md) doesn't decide
*whether* to build this. It tells us:
- what correctness bar we must at least match;
- where the existing experience is worst (setup, errors, speed, surprises at run time), which is
  where to lead;
- the numbers we have to beat on build time, bundle size and start-up time.
