# Roadmap

Where bundleup could go. **These are possibilities, not commitments.** Each direction needs its
own ADR before work starts, and everything here has to respect the accepted ADRs (in particular
[ADR-0002](adr/0002-target-the-runtime-only-tier.md) on scope and
[ADR-0006](adr/0006-delegate-to-uv-and-existing-files.md) on staying out of uv's territory).

The common thread: **every direction is a form of bundling something for a destination.** That's
why the name is `bundleup` and not something tied to zip files or Python
([ADR-0009](adr/0009-name-bundleup.md)).

## Now: the first version

What [MISSION.md](../MISSION.md) defines as done:

- One command from `pyproject.toml` + `uv.lock` / `pylock.toml` / PEP 723 to a checked `.pyz`.
- Runs on the user's Python with no install and no network, native extensions included
  (extracted to a cache, [ADR-0005](adr/0005-extract-to-cache-by-default.md)).
- Version and platform check at start-up with a plain-language error.
- Matches pex on the [gauntlet](../gauntlet/README.md); beats it on default start-up time, build
  time, warnings and error messages ([baseline](findings/2026-10-03-baseline.md)).

## Near: make the core deeper

| Idea | What it is | Why |
|---|---|---|
| **`bundleup check`** | The pre-ship analyzer as its own command, runnable in CI on any project: "will this survive bundling?" | Useful even to people who bundle with something else; the most defensible part of the tool |
| **Multi-platform bundles** | One `.pyz` that runs on several OS/CPU/Python combinations, or one per target from a single machine | Build once on a Mac, ship to Linux servers |
| **Size and contents report** | What's in the bundle, what's heavy, why (like webpack-bundle-analyzer / esbuild's metafile) | Native wheels dominate size; people need to see it |
| **Python API** | Call bundleup as a library from uv, Hatch, Pants, CI scripts | Be the component others call, the way Vite calls esbuild |
| **Opt-in pruning** | Drop whole distributions that are provably unreachable | Smaller bundles without the risk of function-level tree-shaking |

## Middle: the same bundle, different destinations

| Destination | What we'd produce | Why it's a real gap |
|---|---|---|
| **Serverless** (AWS Lambda etc.) | The provider's zip or layer format | uv issue #12035 asks for exactly this |
| **Container images** | A minimal image built straight from the bundle, no Dockerfile | Go has `ko`, Java has `jib`; Python has nothing comparable |
| **Standalone executables** | Bundle + a portable Python via pex's `scie` | Out of scope for the core ([ADR-0002](adr/0002-target-the-runtime-only-tier.md)) because of code signing; possible later as an opt-in output |
| **"No Python installed"** | A tiny launcher that downloads a Python on first run, then runs the bundle | The "user has no usable Python" problem ([primer](python-primer.md) §3) |
| **Agent skills and plugins** | Output shaped for skill/plugin packaging (apm etc.) | The use case that started the project |
| **Notebooks** | Turn a Jupyter notebook into a runnable bundle | A common data-science request |

## Far: bigger bets

- **Run bundles from a URL:** `bundleup run https://…/tool.pyz`, cached and verified, like `npx`
  or `uvx` but for bundles.
- **Bundles for the browser:** packaging Python for Pyodide/WebAssembly, which is painful today.
- **Vendoring for libraries:** bundle a library's own dependencies under renamed imports (like
  Java's Shade) so they can't conflict with the user's versions.
- **Other languages:** skills ship Python *and* Node scripts. One tool that bundles either (driving
  esbuild for Node) is plausible; nothing in the name says Python.

## Not our territory

Package management, task runners, an `upgrade` command, a watch-mode dev runner: these belong to
uv (or are absorbed by it quickly). Competing there contradicts
[ADR-0006](adr/0006-delegate-to-uv-and-existing-files.md).
