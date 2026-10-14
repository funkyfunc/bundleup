# Tenth Independent Review (Pass 2 of REPL of Improvement)

Date: 2026-10-13

## Scope

After fixing all 10 findings from the 9th review, we ran a second independent adversarial review auditing both the Pass 1 changes and the deeper static-analysis, coverage, platform-tag, audit, source-loading, and runtime modules (`_verify.py`, `_cli.py`, `_check.py`, `_imports.py`, `_audit.py`, `_source.py`, `_config.py`, `_uv.py`, `_build.py`, `_payload.py`, `_platforms.py`, `_runtime.py`, `_loader.py`, `_exe.py`, `_outputs.py`).

## Findings and Fixes

### 1. `_verify._walk_dir` could hang on a FIFO or silently skip unreadable subdirectories
- **Problem:** Pass 1 changed `_walk_dir` to use `os.lstat` and report symlinks and `OSError`, but:
  1. `os.walk(root)` ignores `OSError` on subdirectories unless an `onerror` callback is passed, so a `chmod 000` subdirectory inside a `--format dir` bundle or unpacked cache was silently skipped and its missing files were reported as `"missing file"` instead of `"corrupted: <dir> can't be read"`.
  2. A named pipe (FIFO) or Unix socket inside a directory passed `not stat.S_ISLNK(st.st_mode)` and blocked `Path(path).read_bytes()` indefinitely waiting for a writer.
- **Fix:** Passed `onerror` to `os.walk` in `src/bundleup/_verify.py` and checked `stat_mod.S_ISREG(st.st_mode)`, reporting non-regular files as `corrupted: <rel> isn't a regular file`.

### 2. `_verify` symlink resolution for `--split` parts and unpacked cache lookup
- **Problem:** While `_loader.py` resolved `os.path.realpath` on `__file__` before locating `<bundle>.parts` and computing `_roots(archive)` (Pass 1), `_verify._check_bundle` still looked up `bundle.parent / parts` and `_verify._find_cache` passed `str(bundle)` without `os.path.realpath` to `_loader._roots`. Verifying a symlink to a `--split` bundle failed to find the `.parts` folder beside the real bundle.
- **Fix:** Updated `_verify._check_bundle` to resolve `bundle.resolve().parent / parts` and `_verify._find_cache` to pass `os.path.realpath(bundle)` to `_loader._roots`.

### 3. `bundleup verify` printed `unpacked copy: not unpacked on this machine` for `--format lambda`
- **Problem:** Pass 1 guarded the `unpacked copy:` line in `_cli._run_verify` with `if not report.bundle.is_dir():`, which suppressed it for `--format dir` but still printed it for `--format lambda` `.zip` archives (which never unpack into bundleup's local cache).
- **Fix:** Added `unpacks(bundle)` in `src/bundleup/_verify.py` (True for `.pyz`, `.py`, and `exe`; False for `dir` and `lambda`) and gated the `unpacked copy:` line on `unpacks(report.bundle)`.

### 4. Malformed JSON types in `manifest.json` raised uncaught `AttributeError` / `TypeError`
- **Problem:** `_verify._read_manifest` caught `json.JSONDecodeError`, `KeyError`, and `ValueError`, but if `manifest.json` contained valid JSON of the wrong type (e.g. `[]` or `{"layers": []}`), `.get()` raised `AttributeError`.
- **Fix:** Validated `isinstance(manifest, dict)` and validated inner container types in `_verify._read_manifest`, raising `NotABundleError` cleanly.

### 5. `bundleup check` CLI and config handling (`-v` with 0 packages, multi-target CLI flags, duplicate `also_platforms`)
- **Problem:**
  1. `_cli._check_lines` computed `max(len(p.name) for p in report.packages)` under `-v` without checking `if report.packages:`, raising `ValueError` when `report.packages` was empty.
  2. `_cli._run_check` called `_expanded(opts, style)` before `check()`, printing `Building for ...` to stderr before `check()` rejected multiple `--python` / `--python-platform` CLI flags, and stripped `more_python_platforms` from `[tool.bundleup]` before `check()` could fold them into `also_platforms`.
  3. `check()` did not deduplicate `also_platforms` or filter out `options.python_platform`.
- **Fix:** Guarded `if opts.verbose >= 1 and report.packages:` in `_cli._check_lines`; checked `raw.more_pythons or raw.more_python_platforms` before `_expanded` in `_cli._run_check`; folded configured extra platforms into `also_platforms` and deduplicated `others` in `_build.check`.

### 6. Folder apps (`source.app`) were omitted from `owners()`, `analyze()`, and `oldest_python()`
- **Problem:** For a folder app (a directory of `.py` files without `pyproject.toml`), `install()` copied its files (`own`) into `site`, but `_check.owners()` only attributed files from `.dist-info/RECORD` and `script`. As a result, a folder app's own `.py` files were not checked by `oldest_python()` (so Python 3.10+ `match` syntax was still claimed to run on Python 3.9+) and were not counted in `report.packages` sizes. Additionally, `_check._source_of` used `name.split('.', 1)[0]`, truncating dotted module filenames like `api.v1.cpython-312.pyc` to `api.py`.
- **Fix:** Added `own: Sequence[str] = ()` to `owners()`, `analyze()`, and `oldest_python()` in `src/bundleup/_check.py`, wired `own=own` from `_build._prepare`, and changed `_source_of` to `name.rsplit('.', 2)[0]`.

### 7. `try: ... except ImportError:` fallback imports were flagged as undeclared
- **Problem:** `_imports.imports_in` marked the `try` body as `optional=True` when an `except ImportError:` handler was present, but recursed into the `except` handler body with the outer `optional` flag (`False`). Consequently, standard fallback idioms like `try: import tomllib except ImportError: import tomli` flagged `tomli` as an `undeclared-import` warning.
- **Fix:** Marked `except` handlers catching `OPTIONAL_ERRORS` (`ImportError`, `ModuleNotFoundError`, `Exception`, or bare `except:`) as `optional=True` in `src/bundleup/_imports.py`, and passed `path.read_bytes()` to `ast.parse()` in `imports_of()` so PEP 263 encoding cookies and UTF-8 BOMs are respected.

### 8. `check --audit` with marker-split multi-version packages in `uv.lock`
- **Problem:** `_build._audit_lock` passed only package names `selected: set[str]` to `_audit.from_pypi`. When `uv.lock` contained two versions of the same package for different Python/platform markers (e.g., an older version for Python 3.9 and a newer version for Python 3.12), `from_pypi` audited both versions even though only one applied to the target. In addition, `_audit._version_key` used a naive tuple split that sorted pre-releases and multi-segment versions inconsistently.
- **Fix:** Changed `_audit_lock` and `_audit.from_pypi` to filter by `(canonicalize_name(name), version)` pairs (while keeping backward compatibility if plain strings are passed), and updated `_version_key` to use `packaging.version.Version`.

### 9. Multi-target builds (`refresh=i == 0`) could skip refreshing target-specific local dependencies
- **Problem:** Pass 1 added `refresh=i == 0` so `--refresh-package` was only passed on the first target of a multi-target build. However, if a local directory dependency is platform- or Python-marker-guarded (or builds a C extension per target), skipping `--refresh-package` on subsequent targets could reuse a stale cached wheel for target `i > 0`.
- **Fix:** Removed the `refresh` toggle in `_uv.py` and `_build.py` so `_refresh_local(pylock)` is always passed for every target.

### 10. UTF-8 BOMs, PEP 723 TOML errors, patch specifiers in `requires-python`, and platform/entry edge cases
- **Problem:**
  1. `pyproject.toml`, `requirements.txt`, or PEP 723 scripts saved with a UTF-8 BOM (`\ufeff`, common on Windows) failed `tomllib.loads` or `Requirement()` or missed `# /// script` on line 1; malformed TOML inside `# /// script` raised raw `TOMLDecodeError` instead of `ProjectError`.
  2. `requires-python = ">=3.12.1"` tested `"3.12.0" in spec` (`False`) in `_uv._oldest_python`, `_payload.python_range`, and `_build._matrix`, falsely excluding Python 3.12.
  3. `_payload.resolve_entry` checked `canonicalize_name(source.name) in scripts` against raw uncanonicalized script keys, missing `my_tool` when the project was `my-tool`; `_uv.console_scripts` split `.dist-info` names on the first `-` instead of `rsplit("-", 1)[0]`.
  4. `_platforms.parse("x86_64-musllinux_1_1")` hardcoded `(1, 2)` before checking explicit `musllinux_X_Y`, and `_platform_tags()` omitted `linux_{arch}` tags that `Platform.accepts()` and `uv` accept.
  5. `_build._smoke_run` did not check `_loader._libc_fits` or `_loader._macos_fits` before running `--smoke`, and `_runtime.activate` did not clear an inherited `BUNDLEUP_RUNTIME_SCRIPTS` when switching to a different bundle.
- **Fix:** Fixed all five across `_source.py`, `_config.py`, `_uv.py`, `_payload.py`, `_platforms.py`, `_build.py`, `_runtime.py`, `_loader.py`, `_exe.py`, and `_outputs.py`, and added regression tests across `tests/test_verify.py`, `tests/test_check.py`, `tests/test_platforms.py`, and `tests/test_config.py`.
