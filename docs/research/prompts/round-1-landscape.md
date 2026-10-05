# Round 1: landscape and gaps

**Copy only the fenced block below into the research tool.**

Produced `round-1-landscape-compass.md` and `round-1-landscape-gemini.md`.

````markdown
# Research brief: The Python build and packaging ecosystem, compared with other languages, to find tooling gaps

## Who I am and why I'm asking
I've been a JavaScript/TypeScript developer for a long time and I'm newer to Python. I know Node's tools well: npm/pnpm/yarn, esbuild, Vite, tsx, Rollup, Bun, Deno. I want to build developer tools for Python and I'm looking for real, unsolved gaps. I'm especially interested in the equivalent of esbuild (bundle a project and its dependencies into one artifact that only needs the runtime) and tsx (point at a file and run it, with no setup and a watch mode). Don't limit the research to those two; I want to understand the whole landscape first.

Be skeptical and evidence-driven. If something I want to build already exists, say so plainly. "This is solved, use X" is a useful finding.

## Part 1: How Python works, as it affects tooling
Explain the runtime details a tool builder has to understand, comparing each with Node where it helps:
- How imports work: `sys.path`, `sys.modules`, import hooks (`sys.meta_path`), packages vs. namespace packages, relative imports, `python -m`, and why "attempted relative import with no known parent package" happens.
- Bytecode and `.pyc` caching; importing from zip files (`zipimport`) and its limits.
- Native extensions (C/C++/Rust through PyO3, Cython, mypyc): how they're built and loaded, why they can't be loaded from a zip or from memory, the ABI matrix (OS × CPU × libc × Python version × free-threaded build), and abi3/the Limited API. Compare with Node-API's ABI stability.
- How packages find their own data and version at runtime (`__file__`, `importlib.resources`, `importlib.metadata`, entry points), and what that means for bundling.
- How dynamic Python is in practice (`importlib.import_module`, optional imports, plugins) and whether static analysis or tree-shaking is realistic.
- How Python reaches users' machines in practice: macOS's system Python, the Windows Store stub, Linux distros and the "externally managed environment" rule (PEP 668), python.org installers, pyenv, conda, python-build-standalone.

## Part 2: Community and culture
- What Python developers value and complain about, with data: the PSF/JetBrains Python Developer Survey, discuss.python.org packaging threads, Reddit, Hacker News, conference talks.
- How decisions get made: PSF, the Steering Council, PyPA, the PEP process. How a new tool or standard gains adoption, and where proposals have stalled.
- How people feel about uv/Astral and "Rust-ifying" Python tooling, including concerns such as a VC-backed company owning core tools.
- Which groups have different needs: web/backend, data science/ML (the conda world), scripting/DevOps, library authors, app distributors, education.

## Part 3: Map the current toolchain
For each category, list the major tools, whether they're actively maintained (latest release date, recent activity), who uses them, and what they do and don't do. Note the relevant standards (PEP 517/518/621/660/668/723/751, the wheel format, manylinux/musllinux).
1. Getting a Python interpreter (pyenv, uv python, conda, python-build-standalone, rye)
2. Environments and dependency management, lockfiles (pip, pip-tools, Poetry, PDM, Hatch, uv, pixi/conda, pylock.toml)
3. Build backends and building native extensions (setuptools, hatchling, flit, PDM backend, uv_build, maturin, scikit-build-core, meson-python, cibuildwheel)
4. Publishing and registries (PyPI, Trusted Publishing, attestations, private indexes)
5. Running scripts and dev loops (python -m, uv run, pipx run, PEP 723 inline metadata, watchers like watchfiles/hupper)
6. Bundling and single-file distribution needing only the runtime (zipapp, shiv, pex, zipapps, stickytape, pinliner, `get-pip.py`-style embedding, pip's `vendoring` tool)
7. Freezing and standalone executables (PyInstaller, Nuitka, cx_Freeze, Briefcase, PyOxidizer, PyApp, scie/science, PyCrucible, pyfuze)
8. Linting, formatting, type checking, testing (Ruff, Black, mypy, pyright, ty, pytest), only as needed to explain the trend toward Rust-built tools
9. Monorepos and build systems (Pants, Bazel rules_python, uv workspaces)

Include abandoned or failed projects (e.g. PyOxidizer, stickytape, tinyBundle, Pipenv's decline, Rye being absorbed into uv) and explain why each failed or was abandoned.

## Part 4: Compare with other ecosystems
Compare Python with: **JavaScript/TypeScript (Node, npm, pnpm, esbuild, Vite, tsx, Bun, Deno)**, **Rust (Cargo, cargo-script)**, **Go (modules, `go run`, static binaries)**, **Java/JVM (Maven, Gradle, fat/uber JARs, Shade relocation, native libraries bundled inside JARs, jlink, GraalVM native-image)**, **.NET (NuGet, `dotnet run app.cs` with `#:package`, single-file publish)**, **Ruby (Bundler, `bundler/inline`)**, and briefly **PHP (Composer, phar)** and **Perl (App::FatPacker)**.

Build a comparison matrix with ecosystems as rows and these columns:
- Installing the runtime and managing versions
- Dependency declaration and lockfiles
- Running a single file with no setup, with dependencies declared inline
- Dev-loop runner and watch mode
- Bundling into one file that needs only the runtime
- Tree-shaking, minification, targeting an older runtime version (like esbuild's `--target`)
- Handling native code (prebuilt per-platform packages, ABI stability)
- Producing a standalone executable
- Workspaces and monorepos
- Registry, publishing and supply-chain security
- Speed of the main tools

Mark each cell "solved / partial / missing" for Python and cite evidence.

## Part 5: Gap analysis (the most important section)
List the concrete gaps where Python is clearly behind at least one other ecosystem. For each gap give:
- **What's missing**, with a concrete before/after developer workflow
- **Evidence it hurts**: issues, forum threads, surveys, Stack Overflow volume
- **Who it affects** and roughly how many people
- **Existing attempts** and why they fall short
- **Python-specific obstacles**: technical (dynamic imports, native code, metadata) and cultural/standards-related
- **Risk that someone else ships it soon**: e.g. open uv issues such as astral-sh/uv#7419 ("uv zipapp"), active PEPs, PyPA roadmaps
- **Feasibility for a small team or one developer**
- **Score out of 5** on pain, reach, feasibility and defensibility, with a short justification

Then rank the gaps and pick the top 3 opportunities, each with a short outline of what an MVP would do.

## Hypotheses to confirm or disprove
Address each one directly with evidence:
1. Python has no tool equivalent to esbuild: one that starts from an entry point, follows the imports, and bundles code plus dependencies into one artifact runnable by the bare interpreter.
2. `uv run` with PEP 723 covers most of what tsx does; the remaining gaps are watch mode and running files inside packages.
3. Native extensions are the biggest technical obstacle to bundling Python, and the multi-platform wheel approach (as in pex) is the most promising answer.
4. Python's dynamic imports make function-level tree-shaking impractical, but module-level pruning is feasible.
5. Python lacks syntax downleveling and minimum-version checking for bundled code (like esbuild's `--target`).

## Rules for the research
- Prefer primary sources: PEPs, official docs, GitHub repos and issues, discuss.python.org, maintainers' blog posts. Cite every non-trivial claim with a link.
- Date anything that changes over time ("as of <month year>"). Treat anything from before 2023 as possibly out of date and check its current status.
- Separate "doesn't exist", "exists but unmaintained", and "exists but little known".
- Don't pad with general Python praise or beginner explanations. Assume I'm an experienced engineer.
- If evidence is thin or conflicting, say so instead of smoothing it over.

## Output format
1. Executive summary (≤ 1 page): the biggest gaps and whether esbuild/tsx equivalents exist
2. How Python works, for tool builders (Part 1)
3. Community and governance (Part 2)
4. Toolchain map (Part 3), as tables
5. Comparison matrix across ecosystems (Part 4)
6. Ranked gap analysis, top 3 opportunities and MVP outlines (Part 5)
7. Verdicts on the hypotheses
8. Sources
````
