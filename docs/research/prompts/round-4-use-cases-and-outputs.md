# Round 4: use cases, input shapes and output formats

Run 2026-10-04 (reports: `round-4-*`). Attach `MISSION.md`, `docs/vision.md` and `docs/roadmap.md` as
context. Don't attach earlier research reports (to avoid anchoring).

**Copy only the fenced block below into the research tool.**

````markdown
# Research brief: Who needs self-contained Python programs, what each situation requires, and which output formats a bundler should offer

## Context
I'm building bundleup (attached: mission, vision, roadmap). It makes **self-contained Python
files**: a locked project (pyproject.toml + uv.lock, or a PEP 723 script) becomes one `.pyz` that
runs with plain `python`, no install step, no network. Compiled extensions are extracted to a cache
on first run. Today it builds for the machine it runs on; building for other platforms is planned.

I want to map **every situation where someone needs a self-contained Python program**, so that:
1. the docs can invite each audience explicitly ("yes, this works for AWS Lambda, here's how");
2. I know what each situation specifically needs from the tool (formats, limits, flags, docs);
3. I can decide which **output formats** to offer beyond `.pyz`.

Be concrete and skeptical. "This use case isn't a fit" is a useful answer. I lead with what the tool
does, and use cases are examples, so breadth matters, but so does honesty about fit.

## Part 1: What goes in (input shapes)
Describe each shape: how common it is, what breaks when bundling it, and how existing tools cope:
- A. A single script using only the standard library
- B. Code plus pure-Python dependencies
- C. Code plus compiled Python dependencies (wheels with C/C++/Rust extensions)
- D. Code plus **non-Python** dependencies: system shared libraries (libpq, libGL, OpenSSL),
  external executables (ffmpeg, a headless browser for Playwright), other language runtimes
  (Node), large data or model files, GPU/CUDA libraries
- E. Projects with several entry points (CLIs with subcommands, web services, scheduled jobs,
  plugins loaded by a host application)

## Part 2: What could come out (output formats)
For each format: what it is, what the target machine needs to run it (nothing / Python / uv and
network / a container runtime), whether it works offline, how it handles compiled and non-Python
dependencies, size and start-up trade-offs, signing or security implications, and which existing
tool produces it today:
- A PEP 723 script with inline dependencies (runs with `uv run`/`pipx run`; needs network on first
  run), optionally with a lockfile (`uv lock --script`)
- A `.pyz` zip application (needs only Python), single-platform or multi-platform
- A PEX file
- Platform deployment packages: AWS Lambda zip and Lambda layers, Google Cloud Run functions,
  Azure Functions, Vercel/Netlify Python functions, Cloudflare Python Workers (Pyodide)
- A container image built without a Dockerfile (like Go's `ko` or Java's `jib`)
- A standalone executable with an embedded interpreter (python-build-standalone with scie/PyApp,
  PyInstaller, Nuitka)
- A vendored directory to embed in another application or plugin
- A wheelhouse for offline `pip install`
- Environment archives (conda-pack, pixi-pack)
- Data-platform formats such as a zip for PySpark `--py-files`
- WebAssembly/Pyodide bundles

Also: **can one artifact serve several modes?** For example, a `.pyz` that also carries PEP 723
metadata so `uv run app.pyz` works (see astral-sh/uv#18662), or a script that uses uv when it's
available and falls back to embedded dependencies when it isn't.

## Part 3: Who needs it (use cases and platforms)
Research each of these at minimum, and add any I've missed:
- **Serverless:** AWS Lambda (zip, layers, container images), Google Cloud Run functions, Azure
  Functions, Vercel Python functions, Cloudflare Python Workers
- **Data and batch:** PySpark / Databricks / EMR jobs, Airflow and Dagster tasks, Ray, HPC
  clusters whose compute nodes have no internet
- **CI and automation:** CI scripts, GitHub Actions written in Python, pre-commit hooks, Ansible
  (which already ships modules as zips, "AnsiballZ"), configuration-management agents
- **Applications that embed Python** and load user scripts or plugins: Blender, Maya/Houdini,
  QGIS/ArcGIS, Excel's Python, KNIME, Splunk apps, and similar
- **Internal tools and CLIs** handed to colleagues or customers
- **Desktop tools for non-technical users**
- **Edge and embedded:** Raspberry Pi, appliances, devices with no internet
- **Air-gapped or regulated environments**, incident-response scripts run on locked-down machines
- **Agent sandboxes and skills** (already researched; summarize briefly, don't re-do)
- **Education:** assignments and course tools
- **Notebooks** turned into runnable programs

For each use case, answer:
1. **Who** has this need, with evidence it's real (docs, issues, forum threads, blog posts).
2. **The environment's constraints:** who controls the Python version, OS/CPU, network at run time,
   writable directories, size limits, start-up/cold-start sensitivity, required entry-point
   conventions. **Cite official docs for limits** (e.g. Lambda's package size limits); don't
   rely on memory.
3. **How people package for it today**, and what goes wrong.
4. **Which output format** from Part 2 fits, and which input shapes from Part 1 it must handle.
5. **What a bundler would specifically need to do:** features, flags, presets, documentation.
6. **Fit with bundleup's scope:** strong / partial / poor, and why. Note where a use case needs
   something bundleup has ruled out (e.g. standalone executables, see the roadmap).

## Part 4: How should a bundler offer multiple outputs?
Look at how other tools present several output modes and what users found simple or confusing:
esbuild (`--format`, `--platform`), Bun (`bun build` vs `--compile`), Deno (`deno compile`),
pex/scie, PyInstaller (onedir vs onefile), .NET (`dotnet publish` modes), Vite/Rollup outputs,
Go (`GOOS`/`GOARCH`).
- Flags vs named presets/profiles ("--target lambda") vs separate commands: what keeps it dead
  simple while still powerful?
- Which outputs should come first, and which should be left to other tools?
- Steelman "offer only `.pyz` and do it extremely well" against "offer several formats".

## Output
1. Summary (one page): the use cases worth tuning for, and the output formats worth offering
2. Input shapes (Part 1)
3. Output formats (Part 2) as a comparison table
4. Use cases (Part 3), one section each, plus a summary table: use case × required input shapes ×
   best output format × fit
5. Output strategy recommendation (Part 4), including CLI shape
6. Three lists: **advertise now** (works today with `.pyz`), **support soon** (needs a feature or
   format), **out of scope**
7. For each "advertise now" and "support soon" use case: one or two sentences the docs could use
   so that audience feels explicitly invited
8. Sources

## Rules
- Prefer primary sources: official platform docs, specs, GitHub issues, maintainer posts. Cite
  every non-trivial claim with a link, and date anything that changes quickly (limits, runtimes).
- Separate documented facts from interpretation.
- Don't invent numbers, market sizes or adoption figures. If there's no data, say so.
- Skip beginner explanations.
````
