# ADR-0011: CLI shape and build pipeline

- **Status:** Proposed
- **Date:** 2026-10-04
- **Deciders:** an agent (milestone 1), awaiting the user

## Context

Milestone 1 replaces the placeholder CLI. The mission asks for esbuild's experience: one command,
sensible defaults, one artifact out. [ADR-0006](0006-delegate-to-uv-and-existing-files.md) says to
read the files people already have and let uv resolve and install.

## Decision

**Command line.**

```
bundleup [PATH] [-o FILE] [-p PYTHON] [-e ENTRY] [--locked | --frozen] [-q]
```

| Option | Default | Notes |
|---|---|---|
| `PATH` | `.` | A project directory (`pyproject.toml`) or a PEP 723 `.py` script |
| `-o/--output` | `dist/<name>.pyz` next to the input | Like `uv build`'s `dist/` |
| `-p/--python` | the interpreter `uv python find` picks for the project (or `--script`) | Same values uv accepts: `3.12`, a path |
| `-e/--entry` | the project's only console script, or the one named after the project | A `[project.scripts]` name, `module:function`, or `module` (run like `python -m`). Read from the installed `entry_points.txt`, so dynamic scripts work |
| `--locked`, `--frozen` | uv's default (re-lock if `pyproject.toml` changed) | Same meaning as in uv |
| `-q/--quiet` | off | |

`-o`, `-p` and `-e` match pex/shiv where they overlap (`-o`, `-e`), and uv where uv has the concept
(`--python`, `--locked`, `--frozen`). If the target Python doesn't satisfy `requires-python`, the
build stops before installing anything: *"g17-modern needs Python >=3.12, but the target is Python
3.9.6 (…). Build for a matching Python, for example: bundleup --python 3.12 ..."*. Success prints
the output path, size, target and package count, then the time taken.

**Pipeline.**

1. `uv python find` (skipped when `--python` is a file) → probe the interpreter (version,
   platform, CPU, ABI flags, real `sys.executable`) in one subprocess, without importing
   `platform`. Later steps use the real executable: uv re-inspects shims like `/usr/bin/python3` on
   every call (+120 ms) but caches real interpreters.
2. `uv export --no-dev --no-editable --no-hashes` (or `--script`): the complete pinned set,
   including the project and workspace members as local paths.
3. `uv pip install --target <stage> --no-deps --python <target>`, run from the project directory
   (relative paths in the export resolve against the working directory). `--no-deps` makes the
   install exactly the lock.
4. Compile all bytecode with the target Python (`compileall`, unchecked-hash, relative file
   names). It runs in one process below 300 `.py` files and on all cores above: on macOS, worker
   processes are spawned interpreters, and for small projects starting them costs more than they
   save (03 on 3.9: 125 ms single vs 317 ms parallel).
5. Write the payload and the bundle ([ADR-0010](0010-bundle-format-and-loader.md)); the output is
   written to a temporary file and renamed, so a failed build never leaves a half-written bundle.

**Dependencies.** bundleup depends on `packaging` (specifiers, name normalisation) and `tomli` on
Python < 3.11. uv is found on `PATH` and is not a Python dependency; a missing uv is a plain error
with an install link. bundleup itself still runs on Python ≥ 3.9.

## Consequences

- One command bundles every gauntlet project with no per-project flags.
- Builds take about as long as uv's install plus compile and zip; uv's cache makes rebuilds fast.
- Projects with several console scripts need `-e`. Projects with none need `-e`, or a
  `[project.scripts]` entry.
- `pylock.toml` and `requirements.txt` inputs (ADR-0006) aren't wired up yet.
- Depending on uv on `PATH` means pipx users without uv get an error. Depending on the `uv` PyPI
  package instead is possible later if that turns out to be common.

## Alternatives considered

- **`bundleup build` subcommand now:** leaves room for `bundleup check` and others, but the bare
  command is the esbuild experience; subcommands can be added alongside without breaking it.
- **Default to the Python bundleup runs on:** that's whatever uv tool / pipx picked, unrelated to
  the project; uv's choice respects `.python-version` and `requires-python`.
- **Always `--locked`:** stricter, but surprising for people used to `uv run` re-locking; offered
  as a flag instead.
- **`uv sync` into a temporary venv and copy site-packages:** more moving parts than `--target`
  and harder to point at a different interpreter.

## Evidence

- [docs/findings/2026-10-04-milestone-1.md](../findings/2026-10-04-milestone-1.md)
- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md) (other tools' error
  messages and build times)
