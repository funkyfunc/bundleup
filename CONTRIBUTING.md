# Contributing to bundleup

Thank you for your interest in contributing to `bundleup`!

## Development Setup

`bundleup` uses [`uv`](https://docs.astral.sh/uv/) for environment and dependency management:

```bash
uv sync --locked --python 3.12
```

## Running Checks and Tests

Every change must pass formatting, linting, strict type checking, and the unit test suite with zero warnings:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q tests
```

## Architecture & Style Conventions

Before making changes, please review:

- [`MISSION.md`](MISSION.md) and [`docs/vision.md`](docs/vision.md) for project scope and principles.
- [`docs/cli-style-guide.md`](docs/cli-style-guide.md) for CLI contracts (help line limits, exit codes, `--json` schemas, startup import budget, and lazy public exports in `src/bundleup/__init__.py`).
- [`docs/adr/`](docs/adr/README.md) for Architecture Decision Records explaining why key subsystems work the way they do.
- Runtime modules copied into bundles (`_loader.py`, `_runtime.py`, `_sitecustomize.py`) must remain compatible with **Python 3.9+** and use only the Python standard library.

## Reporting Issues

When reporting a bug, please include:

1. Your operating system, CPU architecture, and `bundleup --version`.
2. The target Python version (`--python`) and platform (`--python-platform`), if cross-bundling.
3. A minimal `pyproject.toml` / `uv.lock` or PEP 723 script that reproduces the issue.
