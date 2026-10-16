# 0051. Learnings from JavaScript bundlers: `--external`, code frames, dependency chains, and CLI ergonomics

Date: 2026-10-15 · Status: Accepted

## Context

A study of six reference JavaScript bundlers (`esbuild`, `rollup`, `parcel`, `@vercel/ncc`, `tsup`,
and `rolldown`; see [synthesis](../findings/2026-10-15-js-bundlers-synthesis.md)) highlighted six
high-leverage gaps in `bundleup`'s CLI/API surface, diagnostics, size analysis, and warm-build speed:

1. **Host-provided packages (`--external`):** Every major JS bundler (`esbuild`, `tsup`, `ncc`,
   `rollup`, `rolldown`) supports `--external`. In Python, target environments often pre-install
   heavy or environment-bound packages — AWS Lambda provides `boto3`/`botocore` in the runtime or
   in a Lambda Layer; AI/ML sandboxes and notebooks provide `torch`/`numpy`/`pyarrow`; host apps
   (Blender, QGIS, FreeCAD) provide their own API packages. Previously, `bundleup` had no way to
   exclude a dependency (and its exclusive transitive dependencies) from the bundle and let the
   runtime fall back to the host's installed copy.
2. **Comma-separated list flags:** `esbuild` and `tsup` accept both repeated flags and
   comma-separated values (`--python-platform linux,windows`, `--python 3.11,3.12`), which is
   especially convenient in `BUNDLEUP_*` environment variables and CI matrices.
3. **Muscle-memory CLI error hints:** Users coming from `esbuild`, `pex`, `pyinstaller`, or `uv`
   frequently try `bundleup app.py` (forgetting `build`), `bundleup dist/app.pyz`, `--platform`,
   `--target`, `--outfile`, `--entrypoint`, or `--onefile`.
4. **Source code frames on diagnostics:** `esbuild`, `parcel`, and `rolldown` show the offending
   line of source code with a `^` pointer whenever reporting a syntax error, target-version syntax
   incompatibility, undeclared import, or config error.
5. **"Why is this package in my bundle?" (`required_by`) and size percentages:** `bundleup check -v`
   listed package sizes and file counts, but didn't show each package's percentage of the bundle or
   which dependency pulled a transitive package in.
6. **Warm-build lock export caching:** On locked projects, `uv export --format pylock.toml` ran a
   subprocess on every `build` and `check` even when `uv.lock` and `pyproject.toml` were unchanged.

## Decision

1. **Add `--external PKG` (`BuildOptions.external`, `BUNDLEUP_EXTERNAL`, `[tool.bundleup] external`):**
   - Excludes `PKG` (and, when exporting from a lock or project with `uv export --prune`, its
     exclusive transitive dependencies) from the bundle.
   - Marks `PKG`'s module names as provided during `bundleup check` so `undeclared-import` is not
     raised for host-provided packages.
   - Sets `EXTERNAL = True` in the `.pyz` loader when `external` is non-empty, which defaults
     `BUNDLEUP_INHERIT_PATH=1` so the bundle's `site` stays first on `sys.path` while retaining the
     host interpreter's `site-packages` after it.
2. **Support comma-separated values in list flags (`--python`, `--python-platform`, `--external`):**
   - Both repeated flags (`--python-platform linux --python-platform windows`) and comma-separated
     values (`--python-platform linux,windows`) are normalized identically across CLI arguments,
     `BUNDLEUP_*` environment variables, and `BuildOptions`.
3. **Teach the right flag or command on common CLI mistakes:**
   - `bundleup <path>.py` or `bundleup .` suggests `bundleup build <path>`.
   - `bundleup <path>.pyz` shows how to run it (`python3 <path>.pyz`) and how to verify it
     (`bundleup verify <path>.pyz`).
   - Muscle-memory flags (`--platform`, `--target`, `--outfile`, `--outdir`, `--entrypoint`,
     `--main`, `--externals`, `--onefile`, `--analyze`, `--metafile`) produce targeted hints.
4. **Attach source code frames (`detail`) to source and config diagnostics:**
   - `syntax-error`, `python-range`, `undeclared-import`, and `[tool.bundleup]` config errors include
     a 2-line code frame (`<line> | <source>` and `^` underline) in `Diagnostic.detail` and
     `ConfigError.detail`.
5. **Include `required_by` dependency chains and size percentages in `bundleup check`:**
   - `PackageSize` gains `required_by: tuple[str, ...]` (the shortest `Requires-Dist` chain from the
     project root to that package), serialized in `check --json` (`docs/schema/check-v1.json`) and
     shown alongside percentage share in `bundleup check -v`.
6. **Cache `uv export` output keyed by lock and manifest hashes:**
   - Locked `uv export` outputs (pre-path-relocation) are cached under `<cache>/exports/<sha256>.toml`
     and cleared by `bundleup cache clean --build`.

## Consequences

- Projects targeting AWS Lambda, AI sandboxes, or host applications with pre-installed libraries can
  dramatically shrink bundles using `--external PKG` while keeping `bundleup check` accurate.
- All JSON schema additions (`external` in `build-v1.json` and `required_by` in `check-v1.json`) are
  strictly additive within `schema_version: 1`.
- The `.pyz` loader adds only a single boolean check (`if EXTERNAL: os.environ.setdefault(...)`) with
  zero new imports on the warm startup path.
