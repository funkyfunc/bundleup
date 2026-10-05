# Round 5: CLI and library design for developer tools

Not run yet. Written 2026-10-04. Attach `MISSION.md`, `docs/vision.md`, `docs/roadmap.md` and
`docs/adr/0011-cli-and-build-pipeline.md`, plus the current output of `uv run bundleup --help`.
Don't attach earlier research reports.

**Copy only the fenced block below into the research tool.**

````markdown
# Research brief: What makes a developer CLI (and its library API) great, as a concrete style guide for bundleup

## Context
I'm building bundleup (attached: mission, vision, roadmap, the CLI design ADR and current
`--help`). It's a Python tool that turns a locked Python project into one self-contained file.
Our promise is "dead simple to use, but also powerful and fast", in the spirit of esbuild and uv.
It will be used by people in terminals, by CI systems, and by AI agents, and later as a Python
library called by other tools.

I want a **concrete, opinionated style guide** for bundleup's command line and Python API, grounded
in what the best developer tools actually do and what users praise or complain about. Not general
advice: specific rules we can implement and test.

## Part 1: Learn from the best
Study these tools' real behaviour (docs, source, issue trackers, user reactions): **uv, Ruff,
cargo, esbuild, Bun, Deno, gh (GitHub CLI), git, pipx, pytest, httpie**, plus the Command Line
Interface Guidelines (clig.dev). For each, note what it does especially well or badly in the areas
below, with examples of actual output where possible.

## Part 2: The command line
For each topic, give the recommended rule for bundleup, the evidence, and an example:
1. **Command structure:** one command with flags vs subcommands; when a subcommand is justified
   (e.g. `bundleup targets`, `bundleup check`); positional vs named arguments; presets that expand
   to flags (`--target lambda`) and how to show their expansion.
2. **Flag naming and defaults:** short vs long flags, consistency with uv/pip where we overlap
   (`--python`, `--locked`, `--frozen`), boolean flags, repeated flags (`--platform a --platform b`),
   zero-config defaults.
3. **Output for humans:** what to print on success (how little is enough?), progress for slow
   steps, colour, Unicode, and how uv/cargo/esbuild summarize results. Respecting `NO_COLOR`,
   non-TTY output, `--quiet`/`--verbose`.
4. **Output for machines and agents:** `--json` (schema, stability, versioning), what goes to stdout
   vs stderr, never prompting, deterministic output.
5. **Errors:** the anatomy of a great error message (what happened, why, what to do next; uv's
   `error:` / `hint:` style, Rust compiler style), showing context (file, line, package), avoiding
   tracebacks for expected failures, and when a traceback *is* appropriate.
6. **Exit codes:** a small, documented table, and how other tools distinguish user error, build
   failure and internal bug.
7. **Configuration:** precedence (flags > environment variables > `[tool.bundleup]` in
   `pyproject.toml` > defaults), naming environment variables, and when *not* to add config.
8. **Help and docs:** `--help` content and length, examples in help, man pages vs web docs,
   generating reference docs from the parser.
9. **Speed you can feel:** instant `--help`/`--version`, lazy imports, startup budgets.
10. **Stability:** versioning the CLI and JSON output, deprecating flags gracefully.

## Part 3: The Python library API
1. How tools that are both a CLI and a library structure that split (pypa/build, pip's lack of a
   public API and the problems that caused, Ruff/uv's lack of a Python API, pytest's API).
2. Recommended shape for bundleup's public API: entry functions, typed options and result objects,
   an exception hierarchy, what's public vs private, and how to keep it stable.
3. How the CLI should be a thin layer over the API.

## Part 4: Implementation in Python
1. CLI frameworks: argparse (standard library) vs click vs typer vs cyclopts, judged on startup
   time, dependency cost, help quality, testability and maintenance. bundleup already depends on
   `uv` and `packaging`; is another dependency worth it?
2. Libraries for colour/progress output (e.g. rich) vs plain ANSI: startup cost and dependencies.
3. How to test CLI behaviour: snapshot tests of output and errors, exit-code tests, `NO_COLOR` and
   non-TTY cases.

## Output
1. **The style guide** (the main deliverable): numbered rules with a one-line rationale and an
   example each, covering Parts 2 and 3
2. Example outputs for bundleup: a successful build, a build with warnings, three common errors,
   `--json` output, and `--help`
3. Exit code table
4. Configuration precedence table
5. Library API outline (signatures with type hints)
6. Framework recommendation (Part 4) with trade-offs
7. Sources

## Rules
- Prefer primary sources: official docs, source code, issue trackers, maintainers' writing. Cite
  claims with links.
- Show real output from the tools you cite where you can.
- Separate documented facts from your recommendations.
- Skip beginner explanations.
````
