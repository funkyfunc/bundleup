# Changelog

Versions follow uv's scheme until 1.0: a minor version may break things
([style guide](docs/cli-style-guide.md) rule 37).

## Unreleased (0.1.0)

The first working release. From a project with `uv.lock` or `pylock.toml`, or a PEP 723 script:

- `bundleup build`: one `.pyz` that runs on plain Python with no install step. A pure-Python one
  runs on every Python version its lock allows and, when the lock picks the same packages
  everywhere, on any OS and CPU; one with compiled code on the version and platform it was built
  for, or, with several `--python`/`--python-platform`, one file with a payload for each. Started
  with the wrong Python, a bundle runs itself again with a matching installed one. Also `--format
  dir` (a plain directory for host applications) and `--format lambda` (an AWS Lambda zip),
  builds for other platforms (`--python-platform`), and `--max-size` (refuse an output that's too
  big). Destinations such as Lambda and Claude API Skills are tested
  [recipes](docs/recipes.md), not named targets.
- `bundleup check`: what won't survive bundling, before shipping: code that doesn't compile on
  the target Python, packages without a wheel for a platform (from the lock alone, for any number
  of platforms with `--also-platform`, or as a grid with `--matrix`), data files outside packages,
  Lambda's size limits; package sizes. Every build runs the same checks; `--strict` makes warnings fail.
- `bundleup verify`: a bundle (and its unpacked copy) against its manifest of file hashes.
- `bundleup cache list|clean`.
- Every build is checked against the lock and every wheel's `RECORD`, and is reproducible.
- Bundles unpack once to a cache, start as fast as an installed venv, check the Python version,
  platform, CPU, C library and macOS version first, ignore the machine's own packages, and let
  child processes that run the bundle's code see its packages (no other Python or tool). `cache
  clean` never removes a copy a running program uses.
- A lock is checked against `pyproject.toml` by default (`--frozen` to skip); bundleup never
  writes or rewrites a project's lockfile.
- `--json` output with JSON Schemas, stable exit codes and diagnostic codes, `[tool.bundleup]`
  configuration, and a typed library API (`bundleup.build()`, `check()`, ...).
