# ADR-0011: CLI shape and build pipeline

- **Status:** Accepted for the pipeline and dependencies (2026-10-05); the command-line section
  is superseded by [ADR-0016](0016-cli-and-api-conventions.md)
- **Date:** 2026-10-04
- **Deciders:** an agent (milestone 1); the user asked for uv as a dependency (2026-10-04). The rest
  awaits the user's review

**User decision (2026-10-05):** the CLI follows the [style guide](../cli-style-guide.md) where it
differs from this ADR: verbs (`bundleup build [PATH]`), no `-p`/`-e` short flags, human output on
stderr in at most two lines, `error:`/`hint:` messages, `--locked` behaviour when `CI` is set, and
exit code 3 for bugs. The pipeline and dependency decisions below stand.

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

**Dependencies.** bundleup depends on `packaging` (specifiers, name normalisation), `tomli` on
Python < 3.11, and **`uv`**: the PyPI package that ships uv's binary, the way esbuild ships its
binary through npm. So `pipx install bundleup` or `pip install bundleup` works on a machine that
never had uv. Which uv runs: **the user's own uv on `PATH` if it's at least 0.9** (it's the one that
wrote and maintains their `uv.lock`, with their configuration), otherwise the bundled one. bundleup
itself still runs on Python ≥ 3.9.

## Consequences

- One command bundles every gauntlet project with no per-project flags.
- Builds take about as long as uv's install plus compile and zip; uv's cache makes rebuilds fast.
- Projects with several console scripts need `-e`. Projects with none need `-e`, or a
  `[project.scripts]` entry.
- `pylock.toml` and `requirements.txt` inputs (ADR-0006) aren't wired up yet.
- Installing bundleup downloads a ~35 MB uv binary even for people who already have uv. Accepted:
  "works on any machine" matters more than download size for a build tool.
- Two uv versions can be in play. Preferring the user's keeps their lockfile and config consistent;
  the bundled one is a floor, not a pin. `uv --version` costs one fast subprocess per build.

## Alternatives considered

- **`bundleup build` subcommand now:** leaves room for `bundleup check` and others, but the bare
  command is the esbuild experience; subcommands can be added alongside without breaking it.
- **Default to the Python bundleup runs on:** that's whatever uv tool / pipx picked, unrelated to
  the project; uv's choice respects `.python-version` and `requires-python`.
- **Always `--locked`:** stricter, but surprising for people used to `uv run` re-locking; offered
  as a flag instead.
- **uv only from `PATH`** (the first version of this ADR): a smaller install, but anyone without uv
  gets an error before anything else, which isn't "dead simple".
- **Always the bundled uv:** fully predictable, but a lockfile written by a newer uv on `PATH` might
  not be readable by an older bundled one.
- **`uv sync` into a temporary venv and copy site-packages:** more moving parts than `--target`
  and harder to point at a different interpreter.

## Evidence

- [docs/findings/2026-10-04-milestone-1.md](../findings/2026-10-04-milestone-1.md)
- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md) (other tools' error
  messages and build times)
