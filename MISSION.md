# Mission

> **Pack a locked Python project into one checked `.pyz` per target platform that runs on any
> matching Python with no install step, and tell you before you ship what won't survive packing.**

**Dead simple to use, but also powerful and fast.** pex can already do much of the core job; we
win the way esbuild and Rollup won over webpack, on experience and speed rather than on a new
capability. Positioning, audience and before/after: [docs/vision.md](docs/vision.md).

Name: **bundleup** ([ADR-0009](docs/adr/0009-name-bundleup.md)). Where it could go next: [docs/roadmap.md](docs/roadmap.md).

---

## Why

Python code is easy to write and annoying to hand to someone else. Today there are three ways to
ship a Python program, and none of them is good enough for small tools, scripts and services:

| Option | What the user needs | Problem |
|---|---|---|
| Standalone executable (PyInstaller, Nuitka, PyApp) | Nothing | Platform-specific binaries, code signing and notarization, antivirus false positives, slow onefile start |
| Source + dependencies | Python **and** an install step (`pip install`, `uv sync`) | The install step is where things fail: no network, wrong Python, PEP 668 blocks, users who don't know what a venv is |
| **Runtime only** (one file, runs on the user's Python) | Python | **This tier is what's missing.** JavaScript has it (esbuild → `node bundle.js`). Java has it (fat JARs). PHP has it (phar). Python has pieces (zipapp, shiv, pex) but no tool that makes it easy and reliable |

This project started from a concrete case: agent skills that bundle a Python script. Once a user
installed the skill, the script didn't work until they also installed its dependencies. An
executable brought code signing problems. `uv run` needs uv and network access, which some
environments (sandboxed agent containers, locked-down servers) don't have. The general problem is
bigger than skills: anyone shipping a CLI, an internal tool, a serverless function or a script to
a machine that "has some Python" hits it.

## What we're building

A bundler in the spirit of esbuild: **one fast command, sensible defaults, one artifact out.**

- **In:** a project that already declares its dependencies: `pyproject.toml` + `uv.lock` or
  `pylock.toml` (PEP 751), or a single PEP 723 script.
- **Out:** one `.pyz`. Runs with `python app.pyz`; when it's pure Python, on every Python version
  the lock allows and on any OS ([ADR-0034](docs/adr/0034-pure-python-bundles-run-on-any-os.md));
  with compiled code, one `.pyz` can carry a payload per platform and Python version
  ([ADR-0038](docs/adr/0038-one-pyz-for-several-platforms.md)). No install, no network. Thin variants from the same resolved
  files: a plain directory for host apps and an AWS Lambda zip
  ([ADR-0025](docs/adr/0025-dir-and-lambda-formats-and-presets.md)). Destinations are tested
  recipes of ordinary flags, not named targets
  ([ADR-0039](docs/adr/0039-recipes-instead-of-target-presets.md)).
- **Check:** a report of what will break once packed, *before* you ship: targets with no matching
  wheel (from the lock, for any number of platforms), code that doesn't compile on the Python you
  target, data files a package expects under `sys.prefix`, Lambda size limits. `__file__` reads,
  metadata lookups and dynamic imports aren't flagged because they work: the payload is unpacked
  to real files ([ADR-0024](docs/adr/0024-check-command-and-build-analysis.md)).
- **Run time:** a small bootstrap that checks the Python version, platform, CPU, C library and
  macOS version first and fails with a clear message, then unpacks the whole payload once to a
  content-addressed cache and runs from there ([ADR-0010](docs/adr/0010-bundle-format-and-loader.md)).

## What we're not building

| Not this | Why |
|---|---|
| A standalone executable | Reintroduces code signing. If needed later, hand off to `pex --scie` |
| A single `.py` file that inlines everything | stickytape tried it. Breaks native code, data files and metadata |
| An in-memory importer | PyOxidizer tried it and died at the edges |
| Tree-shaking or minification | Unsafe in Python (imports run code). Size is dominated by native wheels anyway |
| A syntax downleveler (`--target` that rewrites code) | Little demand. We *check* the minimum version instead |
| A dependency resolver | uv already does this well. We delegate to it |
| A watch-mode runner / "tsx for Python" | `uv run` covers most of it, and uv can absorb the rest at any time |
| A competitor to uv | We aim to be the piece uv could call |

## Where the ecosystem stands (Oct 2026)

- **No esbuild equivalent exists.** Nothing starts from a project, produces one checked artifact,
  and tells you what will break.
- **pex can already do the core job** (very active, multi-platform, lock-aware), but it ships whole
  environments, is configuration-heavy, and gives no up-front diagnostics. It is Python's webpack;
  the opening is to be its esbuild.
- **shiv** is dormant (last release Nov 2024). **zipapp** can't bundle dependencies or load native
  code from the zip. **stickytape / pinliner / tinyBundle** are abandoned.
- **uv** has had requests open since 2024 for `uv zipapp` (#7419) and `uv bundle` (#5802). #5802 is
  labelled *"wish – Not on the immediate roadmap."*
- **Astral** (uv, Ruff, ty) agreed to be acquired by OpenAI in March 2026. Governance worries are
  real; so is the chance uv ships bundling whenever it decides to.

Full research and its known errors: [docs/research/](docs/research/README.md).

## What history teaches (and what we'll do about it)

From how Yarn, esbuild, Vite, Rolldown, Ruff, Biome and uv replaced the tools before them, and
how Pipenv, Yarn 2, PyOxidizer and stickytape failed:

1. **Compatibility first, speed as proof, consolidation later.** Every winner was a drop-in for
   something on day one (npm's registry, Rollup's plugin API, flake8's rule codes, pip's CLI).
   → Read the files people already have (`uv.lock`, `pylock.toml`, PEP 723). Use uv's flag names
   (`--python`, `--python-platform`, `--locked`). Show a measured speedup over pex, not a claim.
2. **Boring beats clever in Python.** PyOxidizer's in-memory imports failed; PyApp's "install it
   normally, cache on disk" works. pnpm's ordinary-looking `node_modules` beat Yarn 2's
   Plug'n'Play.
   → Standard importer. Real files on disk for native code. `__file__`, `importlib.resources`,
   `importlib.metadata` and entry points must behave exactly as in a venv.
3. **Copy esbuild's experience, not its algorithm.** JavaScript imports are static enough to build
   a bundle from; Python's aren't.
   → **The lockfile decides what goes in.** Import tracing is for diagnostics and optional pruning,
   never for deciding correctness.
4. **The best tools became components.** esbuild won inside Vite and webpack loaders;
   python-build-standalone won inside uv.
   → Design to be callable by other tools (a library and a CLI), not just used directly.
5. **Tools lose by being endorsed before they're reliable, by forcing breaking changes, and by
   having one maintainer.**
   → Earn trust with the test suite before promoting. Never make a breaking behaviour the default.
   Plan for co-maintainers.
6. **Python switches waited on standards; this one doesn't have to.** The `.pyz` format (PEP 441),
   wheels, PEP 723 and PEP 751 already exist.
   → No new file formats. Configuration lives in `[tool.<name>]` in `pyproject.toml`.

## The hard parts

- **Native extensions** can't load from a zip or from memory. They must be extracted, and a wheel
  must exist for every target (OS × CPU × libc × Python version, plus free-threaded builds).
- **Code that assumes real files:** `__file__`-relative paths, frameworks that serve templates from
  directories.
- **Metadata:** `importlib.metadata.version()` and plugin discovery need the `.dist-info`
  directories.
- **Dynamic imports** limit how much static analysis can promise.
- **Which Python the user has:** macOS's `/usr/bin/python3` is 3.9 (or only a stub until the
  Command Line Tools are installed); Windows' `python` may be a
  Store stub; Linux distros vary.
- **Concurrency and environment hostility:** two processes extracting at once, read-only
  filesystems, no `HOME`, paths with spaces.

## Risks

- **uv ships `uv bundle`.** Astral (now joining OpenAI) is the most prominent Python toolchain
  vendor, and could build this. Evidence so far says not soon: they've said they're "focused on
  core functionality outside of bundling" (uv#7419, Oct 2024), labelled `uv bundle` a wish
  (#5802), and closed PyInstaller output as not planned (#13503). Mitigation: the analyzer and
  target profiles keep their value regardless, and we stay compatible with uv's files so we can
  become the engine rather than the competitor.
  **We build anyway, deliberately** (the user's call, 2026-10-04): the gap exists today. If uv
  later ships something better, users win, and bundleup remains a worthwhile project: a learning
  experience and public, measured work.
- **pex improves its ergonomics.** Overlapping with pex on capability is expected; the bet is on a
  simpler, faster experience. Mitigation: measure against pex continuously and keep the lead on
  setup, error messages, speed and up-front diagnostics.
- **Wheel coverage.** Some dependencies only ship source. Those can't be built for other platforms
  and must be refused clearly.

## How we'll know it works

The [gauntlet](gauntlet/README.md) is a set of test projects, each built to exercise one way
bundling breaks. Every candidate tool (pex, shiv, zipapps, and ours) runs against it.

Before writing the bundler:
1. Run the existing tools through the gauntlet and record what breaks and why. This sets the
   correctness bar to match and shows where the existing experience is worst, which is where to
   lead. It doesn't decide *whether* to build.
2. Answer the open question from the research: does `__file__`/metadata breakage outnumber native
   breakage?

Both done 2026-10-03: [docs/findings/2026-10-03-baseline.md](docs/findings/2026-10-03-baseline.md).
pex sets the correctness bar; the gaps are speed by default, build time, up-front diagnostics,
error messages, child processes and robust caching.

The first version is done when, from one machine:
- Every gauntlet project marked `pass` builds and runs for `macos-arm64` and `linux-x86_64` on
  every Python version it targets, including macOS's system Python 3.9 where applicable.
- Every project marked `refuse` fails at build time with a message that names the cause.
- It beats pex on build time and matches it on correctness.
