# Roadmap

**Agents: start with "Next up". It's the ordered work list.** Take the first unfinished item,
check its ADR, and mark it done here (with a link to the findings or commit) when it's finished.
Everything below "Next up" is a possibility, not a commitment: each direction needs its own ADR
before work starts, and everything has to respect the accepted ADRs (in particular
[ADR-0002](adr/0002-target-the-runtime-only-tier.md) on scope and
[ADR-0006](adr/0006-delegate-to-uv-and-existing-files.md) on staying out of uv's territory).

## Next up

In order. Take the first open item. Decisions need an ADR; one the owner hasn't confirmed is
marked *Proposed*.

19. **Release 0.1.0**: everything is prepared ([docs/releasing.md](releasing.md), [CHANGELOG](../CHANGELOG.md),
    [release.yml](../.github/workflows/release.yml)); publishing needs the owner (trusted publishing on pypi.org, then a tag).


Frozen until 0.1 has users: new formats, named targets and nightly automation. Deferred: faster warm
rebuilds (cache compressed zip members per wheel); packages a target already provides (would break "the lock decides"); agent triage of `corpus-failure` issues (ADR-0017, by the owner); standalone executables
(needs its own ADR); Lambda layers; escape hatches (extra files,
external dependencies).

### Done

Details are in the linked ADRs and findings, and in git history.

| # | Item | Done | Where |
|---|---|---|---|
| 1 | Engineering tooling: Ruff, pyright, hooks | 2026-10-05 | [ADR-0015](adr/0015-engineering-tooling.md) |
| 2 | CI on 4 OSes: checks, tests, gauntlet | 2026-10-05 | [ci.yml](../.github/workflows/ci.yml), [ADR-0017](adr/0017-platform-matrix-and-corpus-testing.md) |
| 3 | Owner review of ADRs 0010, 0011, 0016 (verbs: `bundleup build`) | 2026-10-05 | [ADR-0016](adr/0016-cli-and-api-conventions.md) |
| 4 | Correctness: lock and RECORD checks, manifest + `verify`, `matches-venv`, nightly smoke test, real projects' test suites | 2026-10-06 | [ADR-0019](adr/0019-manifest-and-verify-command.md), [findings](findings/2026-10-06-formats-checks-and-suites.md) |
| 5 | CLI follows the style guide; typed library API | 2026-10-05 | [cli-style-guide.md](cli-style-guide.md), [ADR-0018](adr/0018-package-layout-and-lazy-api.md) |
| 6 | Nightly corpus with `corpus-failure` issues (agent triage deferred) | 2026-10-05 | [corpus.yml](../.github/workflows/corpus.yml), [ADR-0017](adr/0017-platform-matrix-and-corpus-testing.md) |
| 7 | Cross-target builds | 2026-10-05 | [ADR-0014](adr/0014-output-formats-and-target-presets.md) |
| 8 | Runtime hardening: unpack lock, isolation, `cache list/clean` | 2026-10-05 | [ADR-0021](adr/0021-isolate-from-machine-packages.md), [ADR-0022](adr/0022-cache-command.md) |
| 9 | Faster builds: parallel zip, bytecode cache | 2026-10-05 | [ADR-0020](adr/0020-parallel-zip-and-bytecode-cache.md) |
| 10 | `bundleup check`; wheel executables and `.pth` files | 2026-10-05 | [ADR-0023](adr/0023-payload-behaves-like-site-packages.md), [ADR-0024](adr/0024-check-command-and-build-analysis.md) |
| 11 | `--format dir/lambda`, presets, `bundleup targets` (presets replaced by recipes and `--max-size`, [ADR-0039](adr/0039-recipes-instead-of-target-presets.md)) | 2026-10-06 | [ADR-0025](adr/0025-dir-and-lambda-formats-and-presets.md) |
| 12 | `pylock.toml` input | 2026-10-06 | [ADR-0026](adr/0026-pylock-toml-input.md) |
| 13 | The independent review's bugs: child-process leak, lockfiles, libc/macOS checks, claude-api preset, RECORD paths, and more | 2026-10-07 | [ADR-0027](adr/0027-children-see-the-bundle-only-from-its-own-python.md), [ADR-0028](adr/0028-a-project-needs-a-lockfile.md), [ADR-0029](adr/0029-start-up-checks-c-library-and-macos-version.md), [review](findings/2026-10-07-independent-review.md) |
| 14 | Pure-Python bundles run on a range of Python versions | 2026-10-07 | [ADR-0030](adr/0030-pure-python-bundles-run-on-a-range.md) |
| 15 | Wheel coverage from the lock, for any number of targets | 2026-10-07 | [ADR-0031](adr/0031-wheel-coverage-from-the-lock.md) |
| 16 | `_build.py` split by step; shared helpers | 2026-10-07 | `src/bundleup/` |
| 18 | Re-benchmark against pex's fastest configuration: builds 1.1-2.4× faster, start-up far ahead | 2026-10-07 | [findings](findings/2026-10-07-speed-vs-pex-best.md) |
| 19a | `[tool.bundleup]` configuration | 2026-10-07 | [ADR-0032](adr/0032-tool-bundleup-configuration.md) |
| 20 | The second review's fixes: `--locked` by default, cache-root trust, runtime variables, range check, any-OS pure bundles, Skills size limit | 2026-10-07 | [findings](findings/2026-10-07-second-review.md), [ADR-0033](adr/0033-a-stale-lock-is-an-error.md), [ADR-0034](adr/0034-pure-python-bundles-run-on-any-os.md) |
| 22 | The third review's fixes: children activate only for bundle code, exact range check, re-run with a matching Python, macOS 26 / Windows CPU, in-use copies kept, `check --matrix` | 2026-10-07 | [findings](findings/2026-10-07-third-review.md), [ADR-0036](adr/0036-wrong-python-reruns-and-a-platform-matrix.md), [ADR-0037](adr/0037-children-activate-only-for-bundle-code.md) |
| 21 | One `.pyz` for several platforms and Python versions | 2026-10-07 | [ADR-0038](adr/0038-one-pyz-for-several-platforms.md) |
| 17 | Docs match the code: MISSION, vision, README, roadmap, CLAUDE.md | 2026-10-07 | the review's section 1 |

Before writing code in an unfamiliar area, look at [references.md](references.md) for projects
that solved similar problems.

The common thread: **every direction is a form of bundling something for a destination.** That's
why the name is `bundleup` and not something tied to zip files or Python
([ADR-0009](adr/0009-name-bundleup.md)).

## What it does, and what people use it for

**What it does:** bundleup makes **self-contained Python files**. Your code and all its
dependencies go into one `.pyz` that runs with plain `python`: no install step, no uv, no network.
Lead with that, literally ([ADR-0012](adr/0012-lead-with-what-it-does.md)).

**What people use it for** (examples, never the definition):

- **Simplicity:** one file to hand over or keep, instead of a project plus setup instructions.
- **Easier distribution:** internal tools and CLIs for colleagues or customers, scripts shared
  between machines.
- **Places you can't set things up:**
  - AI agents and sandboxes: skills and scripts in sandboxes with no network, such as Claude API
    Skills (see "Agents" below);
  - serverless: AWS Lambda and similar, where you upload an artifact and can't run installers;
  - CI runners and build machines you don't own;
  - locked-down or air-gapped servers where outbound network or `pip install` isn't allowed.

Nobody should read the description and conclude "this isn't for me". The engine stays general;
destinations are outputs and examples.

## Gaps in today's tools, and what answers them

Measured in the [baseline](findings/2026-10-03-baseline.md) against pex, shiv, zipapps and a naive
zipapp. Each gap maps to work in this roadmap.

| Gap today | Evidence | Answered by |
|---|---|---|
| pex adds ~210 ms to every start unless you know two flags (which then break with the wrong `python3` on `PATH`) | baseline: 273 ms vs 59 ms installed venv | Fast-by-default loader (Now) |
| Builds take 1.8–12 s (pex drives an old pip on 3.9) | baseline build times | uv-driven builds (Now), per-wheel analysis cache (Near) |
| No tool warns before shipping; every failure appeared at run time | baseline: zero build-time warnings | `bundleup check` (Near) |
| Errors are pip logs or "Pip install failed!" | baseline: refusal messages for project 17 | Plain-language errors (Now), machine-readable output (Near) |
| Child `sys.executable` processes can't see the bundle's packages (pex, shiv) | gauntlet 19 | Loader sets up child processes (Now) |
| shiv fails 100% with an unwritable `HOME`; zipapps writes into the working directory and races on simultaneous first runs | baseline hostile conditions | Cache fallback chain + atomic extraction (Now, [ADR-0005](adr/0005-extract-to-cache-by-default.md)) |
| A naive zipapp silently drops compiled speedups | gauntlet 10 | `check` warnings (Near) |
| Every tool needed requirements exported and wheels built by hand | baseline setup | Reads `uv.lock` / `pylock.toml` / PEP 723 directly (Now) |
| No tool targets other machines from one machine with a check that it will work | baseline: no cross-platform coverage | Multi-platform bundles (Near) |
| Skill scripts with dependencies can't run in no-network sandboxes: Claude API Skills have "no network access and no runtime package installation", yet the Agent Skills guide recommends `uv run` | [round 3 synthesis](research/round-3-and-2b-synthesis.md) | Target profiles + skill output (Near) |

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
| ~~**`bundleup check`**~~ done ([ADR-0024](adr/0024-check-command-and-build-analysis.md)) | The pre-ship analyzer as its own command, runnable in CI on any project: "will this survive bundling?" | Useful even to people who bundle with something else; the most defensible part of the tool |
| ~~**Multi-platform bundles**~~ done (one per target: ADR-0014; one for several: ADR-0038) | One `.pyz` that runs on several OS/CPU/Python combinations, or one per target from a single machine (`--python`, `--platform`) | Build once on a Mac, ship to Linux servers. Round 4's #1 priority: it unlocks most strong-fit use cases ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted) |
| ~~**Cache override and runtime hardening**~~ done (item 8) | `BUNDLEUP_CACHE`, cache order (env → user cache → temp), per-build locks, stale-cache cleanup, isolated `sys.path` | Lambda's read-only filesystem, read-only roots, HPC node-local scratch, 1,000 jobs starting at once |
| ~~**`--format dir`**~~ done ([ADR-0025](adr/0025-dir-and-lambda-formats-and-presets.md)) | A vendored directory built for a host application's Python and platform | Splunk, QGIS, Maya/Houdini, Azure Functions' `.python_packages` all hand-roll `pip install --target --platform` today ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted) |
| ~~**Target profiles**~~ (built, then replaced by [recipes](recipes.md) and `--max-size`: ADR-0039) | Named targets for environments with a fixed, known Python and platform, starting with `claude-api` (CPython 3.11, manylinux x86_64, no network) | Known targets make compiled wheels (pydantic, numpy) shippable; the most agent-specific feature ([ADR-0013](adr/0013-agent-sandboxes-as-headline-use-case.md), Proposed) |
| **Skill output** (a [recipe](recipes.md) for now) | `scripts/<tool>.pyz` plus a ready `SKILL.md` stanza and an honest `compatibility` line | No platform offers skill scripts with dependencies that run offline ([ADR-0013](adr/0013-agent-sandboxes-as-headline-use-case.md), Proposed) |
| **Size and contents report** (per package: `bundleup check -v`) | What's in the bundle, what's heavy, why (like webpack-bundle-analyzer / esbuild's metafile) | Native wheels dominate size; people need to see it |
| ~~**Python API**~~ done ([ADR-0018](adr/0018-package-layout-and-lazy-api.md)) | Call bundleup as a library from uv, Hatch, Pants, CI scripts | Be the component others call, the way Vite calls esbuild |
| ~~**Machine-readable output**~~ done (`--json`, [schemas](schema/)) | `--json` for build results and `check` findings | CI systems and agents can act on results without parsing prose |
| ~~**Bundle manifest**~~ done ([ADR-0019](adr/0019-manifest-and-verify-command.md)) | A list of exactly what's inside each bundle, with hashes and versions | Trust and supply-chain review: the reviewed artifact is the executed artifact. Secondary: doesn't address malicious skill instructions |
| ~~**Tested offline guarantee**~~ done (every gauntlet run blocks the network on macOS and Linux) | State, and test on every gauntlet run, that a bundle never touches the network | Makes "runs offline" a promise rather than a hope (the harness already blocks network) |
| **Opt-in pruning** | Drop whole distributions that are provably unreachable | Smaller bundles without the risk of function-level tree-shaking |

## Middle: the same bundle, different destinations

| Destination | What we'd produce | Why it's a real gap |
|---|---|---|
| ~~**AWS Lambda**~~ done (`--format lambda`; layers not yet) | `--format lambda`: a native Lambda zip or layer (not a `.pyz`: Lambda already unzips, and only `/tmp` is writable), with a size report against the 250 MB limit | Most common serverless request; hand-built packages often ship Mac wheels ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted) |
| **Container images (docs now; revisit)** | Document the 3-line Dockerfile that copies `app.pyz` onto `python:3.x-slim`; later perhaps a daemonless image writer (base image + one layer, as `ko` and `jib` do) | Round 4 recommends against building images ourselves; the owner wants it revisited ([2026-10-08 note](findings/2026-10-08-inputs-outputs-and-transforms.md)) |
| **One literal `.py` file** (proposed 2026-10-08) | `--format py`: a readable header (contents, pinned versions as a PEP 723-style block) and the bundle as base64 with a ~30-line unpacker; `python tool.py` | Goes where only `.py` files go (gists, agent tools, uploads); +33% size, so for small tools. The owner's idea; [note](findings/2026-10-08-inputs-outputs-and-transforms.md) |
| **Standalone executables** (high value, deferred; the owner wants a deep investigation, maybe our own format) | An opt-in output that pairs the `.pyz` with a portable Python (python-build-standalone), like pex `--scie` or PyApp: one file per OS/CPU that needs **nothing** installed | Serves desktop users without Python, the one big audience a `.pyz` can't reach (round 4). Deferred, not rejected: excluded from the core by [ADR-0002](adr/0002-target-the-runtime-only-tier.md) because of code signing/notarization and size (~tens of MB per platform), so it needs its own ADR first. Build on cross-target builds; consider handing off to pex's scie tooling rather than writing a launcher. Start with a research round on Node's single executable applications, Deno/Bun `compile`, scie, PyInstaller, PyOxidizer, Nuitka, Cosmopolitan Python and PEP 711 ([note](findings/2026-10-08-inputs-outputs-and-transforms.md)) |
| **"No Python installed"** | A tiny launcher that downloads a Python on first run, then runs the bundle | The "user has no usable Python" problem ([primer](python-primer.md) §3) |
| **MCP servers (deferred)** | A bundled MCP server that starts with `python server.pyz` | Only for offline or single-platform cases: MCPB already moved Python to a host-side `uv` server type, and compiled deps (pydantic) can't be bundled portably for unknown desktops |
| **Agents as operators (hypothesis)** | A bundleup skill so an agent can bundle a script it wrote (build where there's network, run in an offline sandbox) | Plausible and unserved, but no evidence of demand found yet; validate with users first |
| **Notebooks (docs only)** | Document the recipe: `nbconvert` → PEP 723 script → bundleup | Magics and display calls break automatic conversion; a recipe is enough |

## Far: bigger bets

- **Run bundles from a URL:** `bundleup run https://…/tool.pyz`, cached and verified, like `npx`
  or `uvx` but for bundles.
- **Bundles for the browser:** packaging Python for Pyodide/WebAssembly, which is painful today.
- **Vendoring for libraries:** bundle a library's own dependencies under renamed imports (like
  Java's Shade) so they can't conflict with the user's versions. Also for `--format dir`: two
  plugins in one host application with different versions of a package
  ([note](findings/2026-10-08-inputs-outputs-and-transforms.md)).
- **`--strip` of known-dead files** (C headers, Cython sources, type stubs, test folders): ~1 MB
  of a 40 MB payload measured; small, so only if users ask.
- **Other languages:** skills ship Python *and* Node scripts. One tool that bundles either (driving
  esbuild for Node) is plausible; nothing in the name says Python.

## Agents (answered by round 3 research)

Agents are a **use case, not the category** ([round 3 synthesis](research/round-3-and-2b-synthesis.md)).
The one concrete, documented gap is no-network sandboxes, above all Claude API Skills (Python 3.11,
Linux x86_64, no network, no installs), where the officially recommended `uv run` can't work.
Elsewhere (cloud coding agents, desktop MCP) the ecosystem already installs dependencies at setup
time with uv.

The answer to "what do you mean it's for agents?":

> Agent sandboxes are the most common place you can't install anything, so bundleup turns a
> skill's script and its locked dependencies into one file that runs there with plain `python`.

Features: target profiles and skill output (Near), compatibility pre-check (part of `check`),
agent-operable CLI (machine-readable output). See
[ADR-0013](adr/0013-agent-sandboxes-as-headline-use-case.md) (Proposed).

## Not our territory

Package management, task runners, an `upgrade` command, a watch-mode dev runner: these belong to
uv (or are absorbed by it quickly). Competing there contradicts
[ADR-0006](adr/0006-delegate-to-uv-and-existing-files.md).
