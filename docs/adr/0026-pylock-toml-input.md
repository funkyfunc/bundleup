# ADR-0026: A project's `pylock.toml` is used when it has no `uv.lock`

- **Status:** Accepted (the owner, 2026-10-08)
- **Date:** 2026-10-06
- **Deciders:** an agent, while the user was away (roadmap item 12); needs the user's confirmation

## Context

[ADR-0006](0006-delegate-to-uv-and-existing-files.md) says bundleup reads the files projects
already have, and the roadmap lists `pylock.toml` (PEP 751, the standard lockfile) as a hedge
against depending on uv's own format. pip (`pip lock`, experimental), uv
(`uv export --format pylock.toml`) and PDM can write one. uv 0.12 installs one directly
(`uv pip install -r pylock.toml`), but refuses to combine it with other requirements.

## Decision

- **For a project directory: `uv.lock` if present, otherwise `pylock.toml` next to
  `pyproject.toml`.** Scripts keep using their own lock (PEP 723 has no pylock convention).
  Named locks (`pylock.<name>.toml`) aren't picked up yet.
- The file is installed in place (`uv pip install --no-deps -r pylock.toml`), so its relative
  paths resolve as its author meant. The lock-vs-bundle and RECORD checks
  ([ADR-0019](0019-manifest-and-verify-command.md)) compare the bundle with the same file.
- **If the lock doesn't list the project itself** (other tools may leave it out), the project is
  installed in a second `uv pip install` and added to the copy of the lock the check reads.
- **An editable entry for the project is refused**: it would point the bundle back at the source
  tree.
- `--locked` can't check a `pylock.toml` against `pyproject.toml` (the format records no hash
  of its inputs), so it has no effect there.

## Consequences

- Projects managed by pip or PDM can be bundled without adopting uv's lockfile.
- uv still does the installing, so a pylock.toml uv can't read can't be bundled; the uv error is
  shown as is.
- Tests: `tests/test_pylock.py` (project listed or not, editable refused); by hand on
  2026-10-06, gauntlet 13 (NumPy, also for Lambda) from a uv-written lock and gauntlet 03 from a
  `pip lock` one.

## Alternatives considered

- **Prefer `pylock.toml` over `uv.lock` when both exist:** uv users who export one for others
  would silently get a different input.
- **Convert the pylock to requirements ourselves:** loses its exact wheel URLs and hashes, and
  repeats uv's work.
