# Releasing

PyPI has only the 0.0.1 placeholder. The steps for the first real release (0.1.0) and later
ones. Only the owner publishes.

## Once

1. On pypi.org, project `bundleup` → Settings → Publishing → add a trusted publisher: GitHub,
   owner `funkyfunc`, repository `bundleup`, workflow `release.yml`, environment `pypi`.
2. On GitHub, Settings → Environments → create `pypi` (optionally require the owner's approval).

## Each release

1. Check `main` is green in CI and the latest nightly runs passed (or their issues are understood).
2. Set the version in both `pyproject.toml` and `src/bundleup/__init__.py` (`__version__`), move
   the "Unreleased" notes in [CHANGELOG.md](../CHANGELOG.md) under the version, and update the
   README's status line and the classifier (`Development Status :: 3 - Alpha` for 0.1).
3. `uv run pytest -q tests` (the API snapshot and `--version` test change with the version), commit,
   push.
4. `git tag v0.1.0 && git push origin v0.1.0`. [release.yml](../.github/workflows/release.yml)
   checks the tag matches the version, builds with `uv build` and publishes.
5. Try it from PyPI on a clean machine: `uvx bundleup build` on a gauntlet project.
