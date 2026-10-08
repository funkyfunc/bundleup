# ADR-0041: Input without a lock builds, resolved at build time, with a warning

- **Status:** Accepted (the owner, 2026-10-08: "go ahead and do all the recommended things"); the
  details are an agent's design
- **Date:** 2026-10-08
- **Deciders:** the owner (the direction), an agent (the design)
- **Supersedes:** the first decision of [ADR-0028](0028-a-project-needs-a-lockfile.md) ("a
  project directory needs uv.lock or pylock.toml"); its second ("bundleup never writes a lock into
  a project") stands and is extended to build output

## Context

bundleup refused anything without a lockfile: a `pyproject.toml` project installed with
`pip install .`, a legacy `setup.py` project, a folder with `requirements.txt`, a plain script.
The owner: much of the Python world doesn't use uv, and bundleup should cover the majority of use
cases. The strict rule protected one thing, knowing exactly what is in a bundle, and that comes
from the bundle's manifest (every file hashed, every package and version recorded, `verify`), not
from how the input was written. ADR-0028's refusal was a reaction to a real bug: `uv export`
silently wrote a `uv.lock` into the project.

## Decision

1. **Strict about the output, flexible about the input.** Every bundle still records exactly what
   is in it, hash-checked; only where the versions come from changes.
2. **Inputs** (besides `uv.lock`, `pylock.toml` and PEP 723 scripts, which are unchanged):
   - a project with `pyproject.toml` and no lock (setuptools, Hatch, Flit, Poetry 2, Poetry 1's
     `[tool.poetry]` too);
   - a setuptools project with only `setup.py` or `setup.cfg`;
   - a **folder of modules** with `requirements.txt` (or none, if it imports only the standard
     library): its files go into the payload as they are, except hidden files, virtual
     environments, caches and build output; it runs `__main__.py`, `main.py` or `app.py`, or what
     `--entry` names (`--entry server.py`, `module:function`, `python`);
   - a script without a `# /// script` block: its dependencies come from a `requirements.txt`
     beside it; with neither, it builds if it imports only the standard library and its
     neighbours, and is refused with the missing imports named otherwise.
3. **Resolution:** `uv pip compile --universal --format pylock.toml` in the stage, from the
   project's lowest `requires-python` (else the target's version), so the platform markers and
   wheels for every platform are known, as with `uv.lock` (portability, wheel coverage, `--matrix`
   keep working). The project itself is built from its folder (`pip install .`).
4. **Warnings:** `unlocked`, with the way to lock (`uv lock`, `pip lock .`, a pinned
   requirements.txt). A `requirements.txt` that pins every package it needs to one version (`==`,
   nothing from `-r`, `-c`, `-e`, URLs or paths) **is a lock**: no warning. If every line also has
   a `--hash`, it's installed from the file itself, so uv checks those hashes. `--strict` fails on
   the warning; `--locked` refuses unlocked input outright (before resolving a project).
5. **Nothing is written into the input.** Resolution happens in the stage; setuptools' `build/`
   and `*.egg-info`, which building a project writes into it, are removed afterwards if they
   weren't there before (this also fixes it for locked setuptools projects).

## Consequences

- `bundleup build` works on most Python projects as they are, and every refusal that remains is
  about something that would break (no wheel for a platform, syntax too new, a stale lock).
- Two builds of unlocked input can differ; the warning says so, and the manifest of each says
  exactly what it holds.
- `poetry.lock` and `Pipfile.lock` aren't read: their projects build from `pyproject.toml` /
  an exported `requirements.txt` (`poetry export --with-hashes`, `pipenv requirements --hash`).
  Read them directly if users ask.
- The import check behind header-less scripts is a heuristic (optional imports in
  `try/except ImportError` and `if TYPE_CHECKING:` are skipped); an empty `requirements.txt` or a
  `# /// script` block with `dependencies = []` overrides it. On Python 3.9 (no
  `sys.stdlib_module_names`) it can't tell and lets the script through.
- Tests: `tests/test_inputs.py`, `tests/test_pylock.py`. The gauntlet stays uv-based (its other
  bundlers are fed from `uv export`).

## Alternatives considered

- **Keep refusing, with better hints** (done 2026-10-07): correct, but leaves most of the
  ecosystem a conversion step away.
- **Resolve and write a lock into the project:** the bug ADR-0028 fixed.
- **Read requirements.txt as given, without resolving:** a loose file doesn't list transitive
  dependencies, so the bundle would be incomplete.
