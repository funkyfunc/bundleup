# Vision: where we fit

The [mission](../MISSION.md) says what we're building. This page says where it sits among the
existing ways to ship Python, who it's for, and why the bet is on experience rather than on a new
capability. New to Python packaging? Read the [primer](python-primer.md) first. Where it could go next:
[roadmap.md](roadmap.md).

## The problem in one sentence

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
- One command, no config file needed. `bundleup app.py` should do the right thing.
- Reads the files you already have: `pyproject.toml`, `uv.lock`, `pylock.toml`, PEP 723 scripts.
- Sensible defaults: target the platform you're on and the Python range your project declares.
- Errors that name the cause and the fix, not stack traces.

**Powerful**
- Several target platforms and Python versions from one machine.
- Native dependencies handled correctly (extracted to a cache, not loaded from the zip).
- A pre-ship check that finds what will break.
- Escape hatches for the long tail: force-extract a package, include extra files, mark a
  dependency external.

**Fast**
- Measured, not claimed: build time compared with pex on every gauntlet project.
- Warm rebuilds should feel instant, the way esbuild made bundling disappear from the dev loop.
- Fast start-up of the bundle itself, including the first run.

## Before and after

The case that started this project: an agent skill that includes a python-pptx script.

**Before:** the user installs the skill, the script crashes with `ModuleNotFoundError: pptx`, and
the user has to figure out a venv and pip.

**After:**

```bash
bundleup scripts/make_deck.py --target macos-arm64,linux-x86_64
```

You ship `make_deck.pyz` inside the skill. On the user's machine, `python make_deck.pyz` just works: no install, no network.

If something can't work, you find out at **build** time, not from a user:
- "this needs Python 3.12 but you're targeting 3.9";
- "lxml has no wheel for linux-aarch64";
- "flask reads templates from disk, so I'll extract it".

## What we solve

1. **One command from the files you already have.** It reads your `pyproject.toml`, `uv.lock` or
   PEP 723 script and produces one `.pyz` per platform. There's nothing new to configure.
2. **It runs on the user's Python without installing anything.** That includes compiled packages:
   NumPy, cryptography, lxml. Those get unpacked to a cache on first run, because compiled code
   can't run from inside a zip. Pure-Python code runs straight from the zip.
3. **It tells you what will break before you ship.** It flags code that reads files relative to
   its own location, plugins and versions found through package metadata, modules imported by
   name at runtime, missing platform builds, and code that needs a newer Python. This check is
   what sets us apart from the existing tools.
4. **A clear message instead of a stack trace.** The bundle checks the Python version and platform
   first and explains the problem if they don't match.

## Who it's for

People shipping small-to-medium Python programs to machines they don't control:
- CLI tools and internal scripts;
- agent skills and plugins;
- serverless functions;
- scripts for locked-down or offline servers;
- anything that runs in a sandbox with no network.

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
- uv has publicly put bundling off its immediate roadmap (astral-sh/uv#5802, labelled "wish").

## What the baseline run is for

Running pex, shiv and zipapps against the [gauntlet](../gauntlet/README.md) doesn't decide
*whether* to build this. It tells us:
- what correctness bar we must at least match;
- where the existing experience is worst (setup, errors, speed, surprises at run time), which is
  where to lead;
- the numbers we have to beat on build time, bundle size and start-up time.
