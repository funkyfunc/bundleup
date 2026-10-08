# ADR-0040: `--entry python`: a bundle that runs the scripts it's given

- **Status:** Proposed (the owner asked for the feature on 2026-10-07; this design is an agent's)
- **Date:** 2026-10-07
- **Deciders:** the owner (the feature), an agent (the design)

## Context

The case bundleup started from is a Claude Code skill installed by a package manager onto
people's laptops: several Python scripts (`deck_edit.py`, `check_setup.py`, ...) sharing
python-pptx, Pillow, PyMuPDF and friends. A bundle had one entry point, so each script would
need its own `.pyz` with its own copy of every package (tens of MB each), and the scripts would
disappear into zips the agent can't read. The owner's workaround installed the packages on first
use with pip, which needs a package index and the network.

pex has the same idea: a `.pex` with no entry point behaves like the Python interpreter.

## Decision

- `--entry python` (also `entry = "python"` in `[tool.bundleup]`) makes a `.pyz` that runs what
  it's given, the way `python` does, with the bundle's packages importable:
  - `python deps.pyz tool.py ARGS`: the script, with `sys.argv = ["tool.py", ARGS...]` and the
    script's directory first on `sys.path` (so its own helper modules import);
  - `python deps.pyz -m module ARGS`, `python deps.pyz -c CODE ARGS`;
  - no arguments: an interactive prompt; an unknown option is a one-line usage error.
- The dependencies come from a project (a `pyproject.toml` with only `dependencies` and a lock
  is enough) or a PEP 723 script, whose own code isn't run.
- Only for a `.pyz`: `dir` and `lambda` outputs have no entry point to choose (a usage error).
- Everything else is unchanged: the same checks, isolation, multi-platform payloads, cache.

## Consequences

- A skill ships one `scripts/deps.pyz` and keeps its scripts as plain `.py` files the agent can
  read; SKILL.md says `python3 scripts/deps.pyz scripts/deck_edit.py ...`. No install step, no
  network, no index.
- A child process that runs another script outside the bundle with `sys.executable` doesn't get
  the packages (ADR-0027 activates children only for the bundle's own code); running it through
  the bundle again does.
- A module literally named `python` can't be an entry point (none is published).

## Alternatives considered

- **One bundle per script.** Every script repeats every package: a 39 MiB bundle per script per
  platform for the founding skill.
- **Several entry points in one bundle (busybox style, `deps.pyz deck_edit ...`).** Needs the
  scripts to be packaged as a project with `[project.scripts]`, and hides them from the agent.
- **A PYTHONPATH-style directory (`--format dir`).** Needs the right Python and platform on
  every machine and a wrapper to set the path; the `.pyz` already checks both and isolates.

## Evidence

- `tests/test_bundle.py::test_entry_python_runs_scripts_beside_it_with_the_bundles_packages`.
- The owner's skill's dependencies: [ADR-0038](0038-one-pyz-for-several-platforms.md)'s sizes.
