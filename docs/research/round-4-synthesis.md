# Synthesis: round 4 (use cases, input shapes, output formats), 2026-10-04

Reports: [round-4-use-cases-compass.md](round-4-use-cases-compass.md) (excellent, primary
reference) and [round-4-use-cases-gemini.md](round-4-use-cases-gemini.md) (agrees on structure,
but over-optimistic fits and some stale platform facts). Key platform facts verified by hand; see
[verification-notes.md](verification-notes.md).

## The headline

**`.pyz` stays the product.** The most important work is not a new format but making the `.pyz`
**honest about its target**: built for a specific Python version and platform, with a cache
location you can override, and a clear error when the host doesn't match. After that, add exactly
two thin outputs over the same resolved files: a **vendored directory** (`dir`) and an **AWS
Lambda zip/layer**. Both reports independently converge on this shape.

## What goes in (input shapes)

| Shape | bundleup's stance |
|---|---|
| A. Stdlib-only script | Works; adds little beyond a version check |
| B. Pure-Python deps | Home ground |
| C. Compiled deps | Home ground; the work is **target selection** (Python version, platform, libc) and extraction hygiene |
| D. Non-Python deps (system libs, ffmpeg, browsers, CUDA) | **Detect and warn, don't solve.** E.g. flag extension modules that need undeclared system libraries, or known post-install downloaders like Playwright. Solving D means becoming conda or Docker |
| E. Several entry points | Needs a small design: `app.pyz <command>` dispatch plus `--entry` |

## Who it's for: three lists

**Advertise now** (works today with a host-built `.pyz`, given a matching Python):
internal CLIs within a uniform fleet · CI scripts and composite GitHub Actions · push-and-run ops
scripts (Ansible-style) · incident-response scripts · HPC jobs built on the login node ·
air-gapped servers · Raspberry Pi (built on the Pi) · course tools and graders · agent sandboxes
and skills · Docker images via a 3-line `COPY app.pyz` Dockerfile.

**Support soon** (needs a feature or format):
- cross-platform `.pyz` (customers' laptops, mixed fleets, aarch64 devices);
- cache override and hardening (Lambda's read-only filesystem, read-only roots, HPC scratch);
- AWS Lambda zip/layer;
- `dir` output for Splunk, QGIS, Maya/Houdini and Azure Functions;
- wheel-set export for Blender (extbpy already does this from `uv.lock`);
- PySpark (`.pyz` as an interpreter, or a pure-Python `--py-files` zip);
- an opt-in PEP 723 header (blocked on uv#18662).

**Out of scope:** desktop apps for non-technical users (need an embedded interpreter), Cloudflare
Workers and Pyodide, Python in Excel, Vercel (already builds from `uv.lock` natively), Ray,
CUDA/system-library-heavy projects, building container images, wheelhouses (uv/pip already do it).

Where the reports disagree, **Compass is right** on the points checked: Gemini rates Cloud Run,
Ray and PySpark "strong", but Cloud Run builds from source (and from Python 3.14 uses uv itself),
Ray wants importable modules, and Spark's `--py-files` can't carry compiled code.

## What specific platforms need (verified)

- **AWS Lambda:** handler is `module.function`; only `/tmp` is writable; 50 MB zipped (direct
  upload) / 250 MB unzipped including layers; 5 layers; runtimes python3.10–3.14 on x86_64 and
  arm64 (3.15 in preview). A `.pyz` would re-extract on every cold start, since Lambda already
  unzips the package; a **native Lambda zip** is the right output.
- **Splunk:** dependencies go in `bin/lib/`, installed "for the platform Splunk is built and ran
  on, NOT the one you're writing your App on" (Splunk SDK README). That's exactly `dir` +
  cross-target.
- **Blender, QGIS:** host apps want wheels or a vendored directory, not a zipapp.
- **HPC:** build on the login node; point the cache at node-local scratch; extraction must be
  safe when 1,000 array jobs start at once.

## Output strategy and CLI shape

Lessons from esbuild, Bun, Deno, Go, .NET, PyInstaller and pex:
1. Keep **what format** and **what target** as separate axes (esbuild's `--format`/`--platform`).
2. A **preset** is a named, printable shorthand for ordinary flags, never a hidden mode (avoid
   .NET's confusing property combinations and pex's flag sprawl).
3. Every format that extracts at run time needs a **visible cache policy**.

Suggested shape (Compass):

```
bundleup                                        # .pyz for this machine (today)
bundleup --python 3.13 --platform linux-x86_64 --platform linux-aarch64
bundleup --format dir --python 3.11 --platform manylinux_2_17_aarch64   # Splunk / QGIS / Azure
bundleup --target lambda --python 3.14 --arch arm64                     # preset → prints what it expands to
bundleup targets                                # list presets and their expansions
BUNDLEUP_CACHE=/scratch/x python app.pyz        # cache override
```

**Order of work:** (1) cross-target `.pyz`; (2) runtime hardening (cache order, locks, stale-cache
cleanup, ABI self-check, isolated `sys.path`); (3) `--format dir`; (4) `--target lambda`;
(5) opt-in PEP 723 header once uv supports it.

### "Slim" / dual-mode (your question)

Both reports advise **against** making a uv-dependent or hybrid mode the default:
- A `.pyz` that also carries a PEP 723 header *can* be built, but uv can't run it yet (uv#18662).
- Worse, `python app.pyz` and `uv run app.pyz` would run **different dependency sets** (the
  locked wheels inside vs. whatever uv resolves), which breaks the "locked, no network" promise.
- A "use uv if present, else embedded deps" bootstrap means two code paths that can drift.

So: offer it later as an explicit opt-in (`--uv-header`), clearly labelled, never the default.

## Doc invitations

Ready-made one-liners per audience are in the Compass report §6 (e.g. HPC: "Compute nodes have no
internet? Build on the login node against your module's Python and point `BUNDLEUP_CACHE` at
node-local scratch."). Use them when writing the docs site.

## Decisions this suggests

Proposed as [ADR-0014](../adr/0014-output-formats-and-target-presets.md). It also informs the open
question in [ADR-0013](../adr/0013-agent-sandboxes-as-headline-use-case.md): target presets should
be a general mechanism (`lambda`, `splunk`, maybe `claude-api`), not an agent-only flag.
