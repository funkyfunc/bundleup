# Testing strategy

How a one-person project gets enough coverage that bundleup doesn't fall over the first time
someone tries it on a personal project. Decided direction: [ADR-0017](adr/0017-platform-matrix-and-corpus-testing.md)
(**Proposed**). Prices and limits verified 2026-10-04 against GitHub's docs.

## Layers, from cheapest to broadest

| Layer | What it proves | Where it runs | Status |
|---|---|---|---|
| Unit tests (`tests/`) | Loader and CLI edge cases | Every commit (hooks) and CI | Exists |
| Gauntlet (22 projects) | Bundles run and *behave* for known failure modes, incl. hostile conditions | CI, every push | Exists (Linux, Windows, macOS since 2026-10-05) |
| Correctness checks | Bundles contain *exactly* the right files: lock vs bundle, wheel `RECORD` hashes, differential test vs a `uv sync` venv | Every build (lock, `RECORD`); CI (`matches-venv`) | Exists (2026-10-05); manifest + `--verify` to do |
| Platform matrix | All of the above on Linux, Windows and macOS, x64 and arm64, Python 3.9–3.14 | CI | Exists for Linux x64/arm64, Windows x64, macOS arm64 × 3.9/3.11/3.12 |
| **Corpus testing** | bundleup works on real projects nobody wrote for us | Nightly CI | Roadmap (below) |
| Dogfooding and early users | Real workflows, starting with the owner's own skills | By hand | Ongoing |

## What "correct" means for a bundle

bundleup can't prove someone's program is correct; that's their tests' job. What it **can**
promise, and prove, is narrower and more useful:

> **The bundle runs exactly the same files as a normal install, in an environment that behaves
> the same way.**

If both halves hold, the program behaves as it does when installed normally. Each half is checked
separately.

### 1. Fidelity: nothing dropped, nothing changed (provable)

Every file can be traced back through a chain of hashes:

| Link | Check |
|---|---|
| PyPI → `uv.lock` | The lockfile records each wheel's sha256; uv verifies downloads against it |
| `uv.lock` → bundle | Every locked runtime package is in the bundle at its locked version; nothing extra (no dev dependencies) |
| Wheel → bundle | Every wheel has a `RECORD` file listing **every file it contains with its sha256 and size**. Each of those files must be in the bundle, byte-identical. Your own project goes through the same path: it's built into a wheel with its own `RECORD` |
| Bundle → manifest | The bundle embeds a manifest of every file and its hash |
| Manifest → extracted cache | At run time, extracted files can be re-checked against the manifest (`python app.pyz --verify`; also catches a corrupted or tampered cache) |
| Build → rebuild | Reproducible builds: the same inputs give the same bytes, so anyone can rebuild and compare one hash (already tested) |

If any link fails, the build (or `--verify`) fails with the file that differs.

### 2. Equivalence: the environment behaves the same (tested)

Identical files can still behave differently if the environment around them differs. The known
ways, each covered by a gauntlet project: import search order, `__file__` locations and data files,
package metadata and plugins, child processes, worker processes, read-only or unusual paths. On top
of that:
- **Environment snapshot comparison:** inside the bundle and inside a `uv sync` venv, record the
  installed distributions and versions, entry points, and which top-level modules import; they must
  match.
- **Differential runs:** the same command from the venv and from the bundle must give the same exit
  code and output (the corpus oracle below).
- **The project's own tests:** where feasible, run a project's test suite against the bundle's
  packages.

## The platform matrix, by spend

### $0: enough for everything we need now

- **The Mac:** macOS arm64, including the system Python 3.9 and uv-managed Pythons.
- **Linux on the Mac:** containers via a free runtime (Colima, Lima, or Docker Desktop for
  personal use). arm64 Linux runs natively; x86_64 runs under emulation, which is slow but fine
  for spot checks. UTM gives full VMs when needed.
- **The System76 laptop (Pop!_OS):** a real x86_64 Linux machine. Fast for interactive Linux
  debugging, and it can host a Windows VM (KVM/virt-manager; Microsoft's evaluation editions run
  free for a limited period).
- **GitHub Actions, if the repo is public:** "free" and "unlimited" on standard GitHub-hosted
  runners (verified). That covers every target we care about:

  | OS | Runner labels |
  |---|---|
  | Linux x64 | `ubuntu-latest`, `ubuntu-24.04`, `ubuntu-22.04` |
  | Linux arm64 | `ubuntu-24.04-arm`, `ubuntu-22.04-arm` |
  | Windows x64 | `windows-latest`, `windows-2025`, `windows-2022` |
  | Windows arm64 | `windows-11-arm` |
  | macOS Apple Silicon | `macos-latest`, `macos-14`, `macos-15`, `macos-26` |
  | macOS Intel | `macos-15-intel`, `macos-26-intel` |

  Limits on the Free plan: 20 concurrent jobs (5 macOS), 6 hours per job.

**Making the repo public is the single biggest lever.** It turns the full matrix into $0 and
also makes the PyPI page's links work. That's the owner's decision.

### If the repo stays private

Free plan: 2,000 minutes/month. After that, standard runners cost (per minute):
Linux x64 $0.006, Linux arm64 $0.005, Windows $0.010, macOS $0.062.

Rough example: a nightly matrix of 12 jobs × 10 minutes (4 Linux, 4 Windows, 4 macOS) is about
40 × $0.006 + 40 × $0.010 + 40 × $0.062 ≈ **$3.10 a night, ~$95 a month**, almost all of it macOS.
Self-hosted runners (e.g. the System76 laptop) are free.

### Small hardware spend (only when a real need appears)

- **A Raspberry Pi** for real arm64 edge-device testing (the "Raspberry Pi" use case).
- **A Windows machine** only if interactive Windows debugging becomes frequent. GitHub's Windows
  runners plus a VM on the System76 laptop should cover it for a long time. Not needed now.

### Capacity: what actually runs out

Hitting limits quickly is typical of **private** repos: 2,000 minutes a month disappears fast
with macOS jobs, which also cost the most once you're paying. On a **public** repo the minutes are
unlimited; what you can still hit:
- **concurrency:** 20 jobs at once (5 macOS); extra jobs queue rather than fail;
- **6 hours per job**;
- **artifact and cache storage** quotas: keep corpus results small (JSON, not whole bundles);
- **fair use:** GitHub's terms forbid activity "unrelated to the production, testing, deployment,
  or publication of the software project" and burdens "disproportionate to the benefits".
  Corpus testing *is* testing bundleup, but keep batches modest (tens of projects a night, not
  thousands).

If GitHub capacity becomes the bottleneck, the System76 laptop can run corpus batches as a
**self-hosted runner, but only inside a throwaway VM or container** with no access to your files
or credentials, recreated for every batch.

### Safety rule

**Never run random projects' code directly on personal machines.** Corpus testing runs
third-party code, so it belongs on ephemeral GitHub-hosted runners with no secrets, or inside a
throwaway VM/container on the System76 laptop. Personal machines otherwise are for interactive
debugging of specific, known projects.

## Corpus testing: real projects, every night

The idea: every night, take a batch of real open-source projects, bundle them on several
platforms, run them, and turn every failure into an issue, a fix and a new gauntlet project.

### 1. Choosing projects
Not random repos (most aren't runnable programs). A **stratified corpus**:
- **Apps with a lockfile:** public GitHub repos with `pyproject.toml` + `uv.lock` and a
  `[project.scripts]` entry point (a CLI). They're bundleable without guessing.
- **Popular CLI apps from PyPI:** tools people install with `pipx`/`uv tool` (formatters, HTTP
  clients, scaffolding tools, downloaders). For these, generate a tiny locked project that depends
  on the app.
- **PEP 723 scripts** found on GitHub.
- **Top PyPI packages** (import-only smoke test; see roadmap item 4).

Pin every project to a commit SHA so failures are reproducible. Prefer clearly licensed
repositories. We only build and run them in CI; we never redistribute them.

### 2. Deciding whether it worked (the oracle)
Random projects have no "GAUNTLET OK" line, so compare against the normal install:
- run the same command (`--help`, `--version`, or a documented smoke command) **in a `uv sync`
  venv and from the bundle**; exit codes and output must match;
- run the correctness checks (lock vs bundle, `RECORD` hashes, importability of every top-level
  module);
- when feasible, run the project's own test suite against the bundle's packages.

A project that bundleup *correctly refuses* (e.g. it needs system libraries) counts as a pass if
the refusal message is clear.

### 3. The nightly run
A scheduled GitHub Actions workflow:
- picks N projects (start with ~20, grow as it stays green);
- runs the matrix (Linux x64/arm64, Windows x64, macOS arm64; a few Python versions);
- writes one JSON record per run: project + commit, OS, Python, bundleup version, phase that
  failed (build / run / compare), exit code, error excerpt, timings.

### 4. Deduplicating failures
Group failures by a **signature** (phase + exception type + failing package + bundleup function),
so 40 projects failing for one reason become one issue. Open or update a GitHub issue per new
signature, labelled `corpus-failure`, with every reproduction attached.

### 5. AI triage, with a human gate
A scheduled agent picks up new `corpus-failure` issues and:
1. reproduces the failure from the recorded project, commit, OS and Python;
2. classifies it: **bundleup bug**, **expected refusal with a bad message**, **project issue**, or
   **flaky/environment**;
3. for bundleup bugs, **reduces it to a minimal gauntlet project** (ADR-0007: every new failure
   mode becomes a test), then proposes a fix in a pull request;
4. re-runs the gauntlet, the correctness checks and the original corpus project.

The owner reviews and merges. Agents don't merge their own fixes.

### 6. Budget and guardrails
- Batch size and matrix width are configuration; start small.
- Cap agent triage per night.
- A weekly summary (pass rate by OS/Python, new signatures, fixed signatures) goes into
  `docs/findings/`.

## What this doesn't replace

Years of real users. It narrows the gap: the corpus finds "works on my machine" problems before
users do, and every fix leaves a gauntlet project behind so the same bug can't return.
