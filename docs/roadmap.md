# Roadmap

**Agents: start with "Next up". It's the ordered work list.** Take the first unfinished item,
check its ADR, and mark it done here (with a link to the findings or commit) when it's finished.
Everything below "Next up" is a possibility, not a commitment: each direction needs its own ADR
before work starts, and everything has to respect the accepted ADRs (in particular
[ADR-0002](adr/0002-target-the-runtime-only-tier.md) on scope and
[ADR-0006](adr/0006-delegate-to-uv-and-existing-files.md) on staying out of uv's territory).

## Next up

In order. Items marked *Proposed* need the user's confirmation of the ADR before the work is
merged; ask if unsure.

1. ~~**Engineering tooling**~~ **Done 2026-10-05** (`bf90979`). ([ADR-0015](adr/0015-engineering-tooling.md)): Ruff (format + lint,
   `target-version = "py39"`), pyright, a `pre-commit`-compatible hook config (format, lint, type
   check on commit; tests on push). Land it as one checkpoint commit that also reformats existing
   code. Follow [python-for-js-reviewers.md](python-for-js-reviewers.md) when fixing what the
   checks flag.
2. ~~**CI on GitHub Actions**~~ **Done 2026-10-05:** [`ci.yml`](../.github/workflows/ci.yml); every
   push runs checks, tests on 4 OSes and the gauntlet on 9 OS × Python jobs. Was: **CI on GitHub Actions, across the platform matrix** ([ADR-0015](adr/0015-engineering-tooling.md),
   [ADR-0017](adr/0017-platform-matrix-and-corpus-testing.md), [testing-strategy.md](testing-strategy.md)).
   - **First, ask the owner to make the repo public** (they're fine with it): GitHub Actions is
     free and unlimited on standard runners for public repos. Private repos get 2,000 minutes a
     month, then per-minute charges (macOS $0.062/min), which runs out fast.
   - **Every push:** lint, type check, unit tests.
   - **Every push (or nightly if slow):** the gauntlet, including hostile conditions, on this
     matrix:

     | OS | Runner | Pythons |
     |---|---|---|
     | Linux x64 | `ubuntu-24.04` | 3.9, 3.11, 3.12 (+ 3.13/3.14 as they matter) |
     | Linux arm64 | `ubuntu-24.04-arm` | 3.11, 3.12 |
     | Windows x64 | `windows-2025` | 3.11, 3.12 |
     | macOS arm64 | `macos-15` | system 3.9, 3.12 |
     | macOS Intel / Windows arm64 | `macos-15-intel` / `windows-11-arm` | nightly spot checks |

   - **Limits to design around:** 20 concurrent jobs (5 macOS), 6 hours per job, artifact storage
     quotas (store JSON results, not bundles).
   - **Local machines are for debugging, not CI:** the Mac (macOS, system Python 3.9, Linux
     containers/VMs via Colima/Lima/UTM) and the owner's System76 laptop (real x86_64 Linux, can host
     a Windows VM). No hardware purchases until a concrete need appears.
3. ~~**User review**~~ **Done 2026-10-05:** ADR-0010 accepted, ADR-0016 accepted with verbs
   (`bundleup build`), ADR-0011's CLI superseded by ADR-0016. Was: **User review of [ADR-0010](adr/0010-bundle-format-and-loader.md),
   [ADR-0011](adr/0011-cli-and-build-pipeline.md) and [ADR-0016](adr/0016-cli-and-api-conventions.md)**
   (all Proposed). Summarize each for the user in JavaScript terms and ask for decisions,
   including the **command shape** (verbs vs default action; see
   [cli-style-guide.md](cli-style-guide.md) "Open decision").
4. **Correctness verification beyond the gauntlet.** The gauntlet proves bundles *run and behave*
   for 22 hand-written projects; nothing yet proves a bundle contains *exactly* the right files.
   In order of value (**done 2026-10-05:** lock vs bundle and `RECORD` checks on every build, the
   differential test as the gauntlet's `matches-venv` condition):
   - **Lockfile vs bundle check:** every locked runtime distribution present at the locked
     version; nothing extra (no dev dependencies); a build-time error if not.
   - **Wheel integrity:** every bundled file matches the sha256 in its wheel's `RECORD`.
   - ~~**Embedded manifest + `bundleup verify`**~~ **Done 2026-10-05**
     ([ADR-0019](adr/0019-manifest-and-verify-command.md)): the bundle records every file's hash;
     `bundleup verify app.pyz` (or `uvx bundleup verify`) re-checks it. The owner chose a command
     over a hook inside every bundle (2026-10-05); it lands after item 5 adds verb commands. Together with the two checks above and reproducible
     builds, this is a hash chain from `uv.lock` to every file that runs
     ([testing-strategy.md](testing-strategy.md) "What correct means").
   - **Differential test vs an installed venv:** for any project, compare the bundle with
     `uv sync` (same distributions and versions via `importlib.metadata`, every top-level module
     importable, same entry points).
   - ~~**Breadth smoke test (nightly CI)**~~ **Built 2026-10-05**
     ([`gauntlet/smoke.py`](../gauntlet/smoke.py), [`nightly.yml`](../.github/workflows/nightly.yml)):
     bundle the top few hundred PyPI packages and import
     each one's top-level modules; turn every failure into a gauntlet project or a learning.
   - **Real-world suites:** run a few real projects' own test suites against their bundles.
5. ~~**Align the CLI with the style guide**~~ **Done 2026-10-05** (see the style guide's
   "Implementation status" for the rules still open). Was: **Align the CLI with the style guide** ([cli-style-guide.md](cli-style-guide.md),
   [ADR-0016](adr/0016-cli-and-api-conventions.md)): `bundleup build [PATH]` (verbs), stderr/stdout split,
   `error:`/`hint:` messages, exit codes, `--json`, library API (`build()`, `BuildOptions`,
   `BundleupError`), snapshot tests.
6. **Nightly corpus testing with AI triage** (**steps 1-5 built 2026-10-05**:
   [`corpus.toml`](../gauntlet/corpus.toml), [`corpus.py`](../gauntlet/corpus.py),
   [`corpus_issues.py`](../gauntlet/corpus_issues.py), [`corpus.yml`](../.github/workflows/corpus.yml);
   step 6 deferred by the owner, step 7 once there's a week of results) ([testing-strategy.md](testing-strategy.md),
   [ADR-0017](adr/0017-platform-matrix-and-corpus-testing.md), accepted 2026-10-05: issues first, agent
   triage (step 6) later). Real open-source projects,
   cloned and bundled every night, so bundleup is tested on code nobody wrote for us. Needs items
   4–5 first (correctness checks, stable `--json` and exit codes). Build it in this order:
   1. **Corpus list** (a checked-in file): a stratified mix, not random repos. Public, clearly
      licensed GitHub projects with `pyproject.toml` + `uv.lock` + a CLI entry point; popular CLI
      apps from PyPI (wrapped in a tiny locked project); PEP 723 scripts; top PyPI packages
      (import-only). **Pin every entry to a commit SHA.** Start with ~20 and grow.
   2. **Nightly workflow** on GitHub-hosted runners across the matrix (item 2): for each project,
      clone at the pinned commit, install it normally (`uv sync`) **and** bundle it, then run the
      same command both ways (`--help`, `--version`, or a documented smoke command).
   3. **Pass/fail oracle:** same exit code and output both ways, plus the correctness checks from
      item 4 (lock vs bundle, `RECORD` hashes, environment snapshot). A clear refusal (e.g. "needs
      system libraries") counts as a pass.
   4. **Results:** one small JSON record per run: project, commit, OS, Python, bundleup version,
      failing phase (build / run / compare), exit code, error excerpt, timings.
   5. **Deduplicate** by failure signature (phase + exception + package + bundleup function) and
      open or update **one GitHub issue per signature**, labelled `corpus-failure`, with every
      reproduction attached.
   6. **AI triage:** a scheduled agent takes new `corpus-failure` issues, reproduces each, classifies
      it (bundleup bug / bad refusal message / project problem / flaky), **reduces real bugs to a
      new gauntlet project**, proposes a fix as a pull request, and re-runs the gauntlet plus the
      original project. **The owner merges; agents never merge their own fixes.**
   7. **Weekly summary** in `docs/findings/`: pass rate by OS and Python, new and fixed signatures.
   - **Safety:** third-party code runs only on ephemeral GitHub-hosted runners with no secrets, or
     in a throwaway VM/container on the System76 laptop. Never directly on personal machines.
   - **Budget and fair use:** batch size and matrix width are configuration; cap agent triage per
     night; keep batches modest (tens of projects a night), since GitHub's terms forbid
     "disproportionate burden".
7. ~~**Cross-target builds**~~ **Done 2026-10-05** (`--python-platform`; CI builds on macOS → runs on
   Linux, Linux → Windows, Linux → macOS; [`gauntlet/cross.py`](../gauntlet/cross.py)). Was: (`--python`, `--python-platform` in uv's vocabulary;
   [ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted): build a Linux bundle from
   a Mac. Gauntlet coverage for at least manylinux x86_64 + CPython 3.11.
8. **Runtime hardening:** `BUNDLEUP_CACHE` override and cache order (done in milestone 1); per-build
   unpack lock (**done 2026-10-05**: 16 simultaneous first runs 3.2 s → 0.55 s); stale-cache cleanup
   and isolated `sys.path` (**waiting for the owner's decision**: both change default behaviour).
9. ~~**Faster large builds**~~ **Done 2026-10-05** ([findings](findings/2026-10-05-faster-builds.md),
   [ADR-0020](adr/0020-parallel-zip-and-bytecode-cache.md)). Was: threaded compression, per-wheel `.pyc` cache
   ([findings](findings/2026-10-04-large-project-and-rust.md)).
10. **`bundleup check`**, the pre-ship analyzer, including the compatibility pre-check
   (native code that doesn't match the target).
11. **`--format dir`** and **`--target lambda`** ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted).
12. **`pylock.toml` input** ([ADR-0006](adr/0006-delegate-to-uv-and-existing-files.md)): a hedge against depending on uv's own lockfile.

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
| **`bundleup check`** | The pre-ship analyzer as its own command, runnable in CI on any project: "will this survive bundling?" | Useful even to people who bundle with something else; the most defensible part of the tool |
| **Multi-platform bundles** | One `.pyz` that runs on several OS/CPU/Python combinations, or one per target from a single machine (`--python`, `--platform`) | Build once on a Mac, ship to Linux servers. Round 4's #1 priority: it unlocks most strong-fit use cases ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted) |
| **Cache override and runtime hardening** | `BUNDLEUP_CACHE`, cache order (env → user cache → temp), per-build locks, stale-cache cleanup, isolated `sys.path` | Lambda's read-only filesystem, read-only roots, HPC node-local scratch, 1,000 jobs starting at once |
| **`--format dir`** | A vendored directory built for a host application's Python and platform | Splunk, QGIS, Maya/Houdini, Azure Functions' `.python_packages` all hand-roll `pip install --target --platform` today ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted) |
| **Target profiles** | Named targets for environments with a fixed, known Python and platform, starting with `claude-api` (CPython 3.11, manylinux x86_64, no network) | Known targets make compiled wheels (pydantic, numpy) shippable; the most agent-specific feature ([ADR-0013](adr/0013-agent-sandboxes-as-headline-use-case.md), Proposed) |
| **Skill output** | `scripts/<tool>.pyz` plus a ready `SKILL.md` stanza and an honest `compatibility` line | No platform offers skill scripts with dependencies that run offline ([ADR-0013](adr/0013-agent-sandboxes-as-headline-use-case.md), Proposed) |
| **Size and contents report** | What's in the bundle, what's heavy, why (like webpack-bundle-analyzer / esbuild's metafile) | Native wheels dominate size; people need to see it |
| **Python API** | Call bundleup as a library from uv, Hatch, Pants, CI scripts | Be the component others call, the way Vite calls esbuild |
| **Machine-readable output** | `--json` for build results and `check` findings | CI systems and agents can act on results without parsing prose |
| **Bundle manifest** | A list of exactly what's inside each bundle, with hashes and versions | Trust and supply-chain review: the reviewed artifact is the executed artifact. Secondary: doesn't address malicious skill instructions |
| **Tested offline guarantee** | State, and test on every gauntlet run, that a bundle never touches the network | Makes "runs offline" a promise rather than a hope (the harness already blocks network) |
| **Opt-in pruning** | Drop whole distributions that are provably unreachable | Smaller bundles without the risk of function-level tree-shaking |

## Middle: the same bundle, different destinations

| Destination | What we'd produce | Why it's a real gap |
|---|---|---|
| **AWS Lambda** | `--target lambda`: a native Lambda zip or layer (not a `.pyz`: Lambda already unzips, and only `/tmp` is writable), with a size report against the 250 MB limit | Most common serverless request; hand-built packages often ship Mac wheels ([ADR-0014](adr/0014-output-formats-and-target-presets.md), accepted) |
| **Container images (docs only)** | Document the 3-line Dockerfile that copies `app.pyz` onto `python:3.x-slim` | Round 4 recommends against building images ourselves; Dockerfile + uv already works |
| **Standalone executables** (high value, deferred) | An opt-in output that pairs the `.pyz` with a portable Python (python-build-standalone), like pex `--scie` or PyApp: one file per OS/CPU that needs **nothing** installed | Serves desktop users without Python, the one big audience a `.pyz` can't reach (round 4). Deferred, not rejected: excluded from the core by [ADR-0002](adr/0002-target-the-runtime-only-tier.md) because of code signing/notarization and size (~tens of MB per platform), so it needs its own ADR first. Build on cross-target builds; consider handing off to pex's scie tooling rather than writing a launcher |
| **"No Python installed"** | A tiny launcher that downloads a Python on first run, then runs the bundle | The "user has no usable Python" problem ([primer](python-primer.md) §3) |
| **MCP servers (deferred)** | A bundled MCP server that starts with `python server.pyz` | Only for offline or single-platform cases: MCPB already moved Python to a host-side `uv` server type, and compiled deps (pydantic) can't be bundled portably for unknown desktops |
| **Agents as operators (hypothesis)** | A bundleup skill so an agent can bundle a script it wrote (build where there's network, run in an offline sandbox) | Plausible and unserved, but no evidence of demand found yet; validate with users first |
| **Notebooks (docs only)** | Document the recipe: `nbconvert` → PEP 723 script → bundleup | Magics and display calls break automatic conversion; a recipe is enough |

## Far: bigger bets

- **Run bundles from a URL:** `bundleup run https://…/tool.pyz`, cached and verified, like `npx`
  or `uvx` but for bundles.
- **Bundles for the browser:** packaging Python for Pyodide/WebAssembly, which is painful today.
- **Vendoring for libraries:** bundle a library's own dependencies under renamed imports (like
  Java's Shade) so they can't conflict with the user's versions.
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
