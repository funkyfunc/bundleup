# ADR-0049: `--format zip` replaces `--format lambda`

- **Status:** Accepted (the owner, 2026-10-14)
- **Date:** 2026-10-14
- **Deciders:** the owner

## Context

[ADR-0039](0039-recipes-instead-of-target-presets.md) removed named target presets (`--target lambda`, `--target claude-api`) in favor of recipes and destination data files (`--against FILE`, [ADR-0044](0044-destinations-as-data-files.md)). However, `--format lambda` remained as the one output format named after a specific cloud vendor's product rather than the shape of the artifact it writes (`pyz`, `py`, `exe`, `dir`). It also hardcoded AWS-specific checks (`lambda-not-linux`, `lambda-too-big`, `lambda-upload-size`) inside the core build pipeline.

## Decision

- **Rename `--format lambda` to `--format zip`** (`FORMATS = ("pyz", "py", "exe", "dir", "zip")`):
  - `--format zip` writes a flat `.zip` archive (default `dist/<name>.zip`) containing the project's code, its dependencies, hash-checked `.pyc` files, and `bundleup-manifest.json` at the root, with no loader — the `.zip` twin of `--format dir`.
  - Remove the hardcoded AWS-specific `lambda-not-linux`, `lambda-too-big`, and `lambda-upload-size` checks from `_build.py` and `_outputs.py`.
  - Move AWS Lambda's platform (`x86_64-manylinux_2_34` / `aarch64-manylinux_2_34`) and direct upload limit (`max-size = "50MB"`) to [`docs/targets/aws-lambda-python3.13-*.toml`](../targets/) and [`docs/recipes.md`](../recipes.md).
  - `bundleup verify` accepts both `"zip"` and legacy `"lambda"` manifests so existing archives still verify.

## Consequences

- Every `--format` value describes an artifact shape (`pyz`, `py`, `exe`, `dir`, `zip`), while destination-specific constraints live in `--against` target files and `--max-size`.
- Supersedes the `--format lambda` naming and hardcoded AWS checks in [ADR-0025](0025-dir-and-lambda-formats-and-presets.md).
