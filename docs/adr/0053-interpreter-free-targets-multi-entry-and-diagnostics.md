# ADR-0053: Interpreter-free Python targets, opt-in downloads, multi-entry dispatch, and network diagnostics

- **Status:** Accepted
- **Date:** 2026-11-18
- **Deciders:** the owner, an agent (the design)
- **Refines:** [ADR-0019](0019-manifest-and-verify-command.md) (manifest provenance),
  [ADR-0024](0024-check-command-and-build-analysis.md) (`undeclared-import` scopes and range notes),
  [ADR-0040](0040-entry-python-runs-any-script.md) (entry dispatch),
  [ADR-0045](0045-split-a-bundle-into-parts.md) (split deliverables and sizes),
  [ADR-0052](0052-native-bundles-run-on-a-python-range.md) (explicit `--python` targets without extra interpreters)

## Context

Seven practical gaps remained around multi-Python `.pyz` builds, private registries, multi-command
projects, and build provenance:

1. **Explicit `--python` ranges and missing minor interpreters triggered unnecessary downloads.**
   While ADR-0052 made zero-flag builds merge `cp3XX` wheels across Python 3.9–3.14 using only the
   host interpreter, passing `--python 3.10-3.14` or `--python 3.11` still asked `find_python()` for
   each interpreter and attempted automatic `uv python install` downloads (and swallowed `uv`'s
   download error when offline or blocked). In addition, fork payloads set `TAG` to the
   unprecompiled target tag, skipping first-run `.pyc` caching when `PYTHONDONTWRITEBYTECODE=1` was
   set.
2. **Custom `pip.conf` indices, TLS proxies, and registry wheel 403s produced raw `uv` errors.**
   `uv` ignores `pip.conf` / `PIP_INDEX_URL` / `PIP_CERT`, and private mirrors can list a package
   version in `/simple/` while returning HTTP 403 on its `.whl` (access policy or missing upstream
   cache permission).
3. **Dependency-imposed Python range floors weren't explained.** When `requires-python` allowed
   older Pythons than a dependency's `Requires-Python` or available wheels, neither `check` nor
   `build` named which package narrowed the range.
4. **Optional extras and lazy function imports looked like broken top-level dependencies.**
   `undeclared-import` treated a lazy `import playwright` inside a helper function or unselected
   `[project.optional-dependencies]` extra identically to a top-level broken import, and didn't
   clarify whether external browser binaries are included in Python bundles.
5. **Split deliverables and multi-platform size contributions weren't visible upfront.** Multi-part
   and multi-platform builds needed compressed size, extracted cache size, per-target payload
   contributions, and an explicit deliverable list / archive command for `--split`.
6. **Choosing between `[project.scripts]` CLIs and authoring scripts.** Projects with multiple
   `[project.scripts]` failed unless `--entry` picked one, and running arbitrary scripts alongside a
   CLI required POSIX-style `BUNDLEUP_ENTRY=python` environment prefixes.
7. **Reviewing dependency updates and package provenance.** Rebuilds gave no summary of what grew or
   changed, and `manifest.json` omitted license identifiers and registry origins already present in
   `.dist-info/METADATA` and `pylock.toml`.

## Decision

1. **Assemble `.pyz` and `.py` targets without extra build interpreters; make Python downloads opt-in:**
   - Interpreter downloads (`uv python install` into `<build-cache>/pythons`) are off by default and
     require `BUNDLEUP_PYTHON_DOWNLOADS=1` or `UV_PYTHON_DOWNLOADS=automatic`.
   - For `.pyz` and `.py` outputs, multi-Python builds prepare locally installed interpreters first
     so `merge_native_wheels` covers neighbouring versions in one pass, and any uninstalled CPython
     minor version (`3.9`–`3.14`) is assembled with a host CPython (`Target.has_interpreter = False`),
     verifying wheel compatibility, syntax (`ast.parse(..., feature_version=...)`), and standard
     library coverage in-process while deferring payload `.pyc` compilation to first run (`TAG = ""`).
2. **Diagnose registry 401/403s, TLS proxies, blocked runtime downloads, and `pip.conf`:**
   - `_network.py` inspects `pip.conf` / `pip.ini` / `PIP_*` only on failure, redacting credentials
     and secret query parameters from all URLs.
   - Wheel HTTP 403 errors name the exact package, version, wheel tag, and host, advising an
     explicit version constraint and re-lock rather than public-index fallback. TLS certificate
     errors point to `UV_NATIVE_TLS=1` and `SSL_CERT_FILE` (naming `pip`'s `cert` when configured).
     Blocked runtime/launcher downloads surface their HTTP status and point to `.pyz` or
     `UV_PYTHON_INSTALL_MIRROR` / `BUNDLEUP_JUMP_MIRROR`.
3. **Name dependencies that narrow the Python range:**
   - When `options.python` is unset and a bundle's minimum Python is above `requires-python` due to
     a dependency's `Requires-Python` or missing wheels rather than project syntax, `build` and
     `check` emit a note naming the limiting package(s).
4. **Distinguish `[project.optional-dependencies]` and function/branch-scoped imports:**
   - `_imports.imports_with_scopes()` separates unconditional module-level imports from imports
     deferred inside functions or branches, and `_source.py` maps `[project.optional-dependencies]`
     to import names so `undeclared-import` distinguishes excluded optional features from broken
     dependencies and notes external browser-binary prerequisites for `playwright`.
5. **Report compressed, unpacked, and per-target sizes, split deliverables, provenance, and diffs:**
   - `BuildResult` (and `build --json` / `build -v`) reports `unpacked_bytes`, `shared_bytes`,
     per-payload `exclusive_bytes` and `unpacked_bytes`, `deliverables` (also in split
     `manifest.json`) with a `tar` + `bundleup verify` command on `-v`, and `changes` (size delta,
     package additions/removals/updates, native library changes, and target changes) when
     overwriting an existing bundle.
   - `manifest.json` records each package's SPDX `license` (from `.dist-info/METADATA`) and
     credential-redacted remote `origin` URL (omitting local paths so builds stay reproducible).
6. **Preserve multiple entry points automatically:**
   - Every `.pyz` and `.py` records validated `[project.scripts]` in `SCRIPTS`. Projects with
     several `[project.scripts]` and no `--entry` default to `Entry("scripts", "")`, supporting
     `<cmd> ARGS...` and `run <script.py> ARGS...`; `--entry python` also dispatches named
     `[project.scripts]` and `run <script.py>`; fixed-entry bundles accept `--bundleup-python` and
     `--bundleup-entry <cmd>` on every OS in addition to `BUNDLEUP_ENTRY`.

## Consequences

- Machines with a single CPython installation can build multi-Python `.pyz` artifacts offline
  without downloading extra interpreters or adding a separate `bundleup doctor` subcommand.
- The CLI surface stays at `build | check | verify | cache`; `build-v1.json` and `manifest.json`
  gain additive fields only, preserving reproducibility and existing contracts.
- Full SBOM formats (CycloneDX/SPDX documents) and cryptographic signing remain external CI steps
  (`cosign`, GitHub Artifact Attestations).

## Alternatives considered

- **Add a `bundleup doctor` subcommand:** Rejected in favour of diagnosing `pip.conf`, TLS, and
  HTTP 401/403 directly on the failing command, keeping the top-level CLI minimal.
- **Keep automatic interpreter downloads on by default:** Rejected; `.pyz` and `.py` builds no
  longer need extra interpreters for wheel assembly, and unexpected GitHub downloads fail on offline
  or restricted networks.
- **Embed a standalone SBOM / signing subsystem:** Rejected for the same reason `check --audit` was
  removed in ADR-0050; `manifest.json` carries package versions, hashes, licenses, and registry
  origins, which external tools and CI pipelines can attest.

## Evidence

- `tests/test_targets_and_diagnostics.py`
