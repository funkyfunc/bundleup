# Eleventh independent review (Pass 3 of 3) — 2026-10-13

Pass 3 of the three-pass adversarial review cycle after `0.1.0` and the
[ninth](2026-10-13-ninth-review.md) and [tenth](2026-10-13-tenth-review.md) reviews.

## Findings and fixes

1. **`_uv._oldest_python` started minor-version search at `3.0` (`src/bundleup/_uv.py:139`)**
   - **Problem:** When a project declared `requires-python = ">=3"` (or `~=3.0`), `_oldest_python`
     tested `3.0` first and passed `--python-version 3.0` to `uv pip compile`, which `uv` rejects
     (minimum supported version is `3.7`, and `bundleup` targets `>=3.9`).
   - **Fix:** Start the minor-version search at `min(9, python[1])`.

2. **Corrupted deflate streams and malformed inner manifest types in `verify()` (`src/bundleup/_verify.py`)**
   - **Problem:** `ZipFile.read()` raises `zlib.error` or `EOFError` on corrupted deflate streams
     even when zip headers parse cleanly; `_read_manifest()` only checked top-level key existence,
     so non-dict `"loader"`, `"payload"`, `"files"`, `"payloads"`, or `"layers"` raised `TypeError` /
     `AttributeError` instead of `NotABundleError`.
   - **Fix:** Catch `zlib.error` and `EOFError` alongside `BadZipFile` across `_verify.py`, and
     validate inner manifest structure and string maps in `_read_manifest()`.

3. **PEP 263 non-UTF-8 source scripts (`src/bundleup/_source.py`, `src/bundleup/_config.py`, `src/bundleup/_build.py`)**
   - **Problem:** While `_imports.py` used `tokenize.open()` to honor PEP 263 `# -*- coding: ... -*-`
     cookies, `_source.py`, `_config.py`, and `_build.py` still called `path.read_text(encoding="utf-8-sig")`,
     crashing with `UnicodeDecodeError` on valid `latin-1` / `cp1252` scripts.
   - **Fix:** Added `read_python_text(path)` in `_source.py` using `tokenize.open()` with a
     `utf-8-sig` fallback, and used it across `_source.py`, `_config.py`, and `_build.py`.

4. **Non-canonical project names in `_check.py` (`src/bundleup/_check.py:67, 134, 211`)**
   - **Problem:** `owners()` canonicalized distribution names from `.dist-info/METADATA` (`my-app`)
     before comparing them with `project` (`My_App`), so non-canonical project names were treated
     as third-party dependencies in `owners()`, `oldest_python()`, and `syntax_errors()`.
   - **Fix:** Canonicalize `project = canonicalize_name(project)` at the start of `owners()`,
     `oldest_python()`, and `syntax_errors()`, and handle standalone `.pyc` paths in `_source_of()`.

5. **`try ... except ImportError ... else:` in `_imports.py` (`src/bundleup/_imports.py:82`)**
   - **Problem:** `imports_in()` visited `node.body` with `optional or guarded`, but visited
     `node.orelse` with `optional`, flagging imports inside the `else:` branch of an
     `ImportError`-guarded `try` block as mandatory (`undeclared-import`). Also handled `TryStar`
     (`except*`), `BaseException`, and UTF-8 BOMs / hidden files in `.pth` scanning.
   - **Fix:** Visit `[*node.body, *node.orelse]` with `optional or guarded`, include `BaseException`,
     and read `.pth` files with `encoding="utf-8-sig"` while skipping dot-prefixed `.pth` files.

6. **Canonical deduplication of `also_platforms` and case-insensitive aliases (`src/bundleup/_build.py`, `src/bundleup/_platforms.py`)**
   - **Problem:** `_platforms.parse("LINUX")` failed because `ALIASES` was matched before `.lower()`,
     and `check()` deduplicated `also_platforms` by raw string before parsing, so `python_platform="macos"`
     with `also_platforms=["aarch64-apple-darwin"]` checked the same platform twice.
   - **Fix:** Lowercase input before checking `ALIASES` in `_platforms.parse()`, and deduplicate
     `also_platforms` by canonical `Platform` identity (`replace(_platforms.parse(name), name="")`).

7. **Output path overwriting input files, empty `BUNDLEUP_*` env vars, `--entry` / `--smoke` / `--against` / `_audit` / `_cache` / `_sitecustomize` hardening**
   - **Fix:**
     - Reject `-o` paths that resolve to the source script, `pyproject.toml`, or `pylock.toml` in `_build._prepare`.
     - Treat empty `BUNDLEUP_ENTRY=""`, `BUNDLEUP_MAX_SIZE=""`, and `BUNDLEUP_SPLIT=""` as unset in `_cli.py`.
     - Reject empty module or attribute in `_payload.resolve_entry` (`:func` or `mod:`).
     - Catch `shlex` `ValueError` in `_smoke.parse_args` and raise `UsageError`.
     - Read `--against` target files with `encoding="utf-8-sig"` and catch `UnicodeDecodeError`.
     - Guard naive/malformed timestamps and null `releases` in `_audit._oldest_upload`.
     - Exclude dot-prefixed names from `_cache.UNPACKED` and suppress `OSError` races during `scandir`.
     - Use `_same()` (comparing both `abspath` and `realpath`) in `_sitecustomize.py`.
