# ADR-0010: Bundle format, loader and cache layout

- **Status:** Accepted (2026-10-05); the payload's compression level is superseded by
  [ADR-0020](0020-parallel-zip-and-bytecode-cache.md); `PYTHONPATH` for child processes by
  [ADR-0027](0027-children-see-the-bundle-only-from-its-own-python.md); one Python version, for
  bundles without compiled code, by [ADR-0030](0030-pure-python-bundles-run-on-a-range.md)
- **Date:** 2026-10-04
- **Deciders:** an agent (milestone 1); accepted as written by the user, including
  `PYTHONPATH` for child processes on by default

## Context

[ADR-0005](0005-extract-to-cache-by-default.md) settled the direction: the standard importer,
real files on disk, extraction to a cache, and a fallback chain with atomic extraction (the cache
details were left Proposed). Milestone 1 needed the concrete format and loader. Constraints:

- The loader runs on every start, on the user's Python, including macOS's system 3.9
  ([ADR-0008](0008-prototype-in-python.md)). Warm start should be no slower than an installed venv.
- Running a `.pyz` makes `zipimport` parse the **whole** zip directory before `__main__` runs.
  Measured: ~1.5–2 µs per entry on every start, so 20,000 entries (PyTorch-sized) add 27 ms (3.12)
  to 43 ms (3.9) to every run
  ([findings](../findings/2026-10-04-milestone-1.md#why-two-zips)).
- Gauntlet 19 needs child interpreters (`sys.executable -c ...`) to see the bundle's packages.

## Decision

**File layout.** A `.pyz` is `#!/usr/bin/env python3` followed by a zip with three entries:

| Entry | What |
|---|---|
| `payload.zip` | Stored (not compressed) inner zip holding the installed packages, each deflated (level 1) |
| `__main__.py` | The loader (`src/bundleup/_loader.py` with a generated config block) |
| `__main__.pyc` | The loader compiled by the target Python. Other Pythons reject its magic number and fall back to `__main__.py`, which then prints the version message |

Warm start therefore never depends on bundle size. The payload is what `uv pip install --target`
produces (without `bin/` launchers and uv's `.lock`), with every `.py` precompiled by the target
Python as **unchecked-hash** `.pyc` files: the cache is immutable, so the source is never
re-checked and extraction doesn't need to preserve mtimes. PEP 723 scripts go in
`__bundleup_script__/` so they can't shadow a dependency of the same name. Entries are sorted,
timestamped 1980-01-01 and compiled with relative file names, so the same inputs give
byte-identical bundles (checked by `tests/test_bundle.py`).

**Cache key and layout.** `<cache root>/<name>-<first 16 hex of sha256(payload.zip)>/`. Cache
roots, tried in order (never the working directory):

1. `$BUNDLEUP_CACHE`, if set;
2. the user cache directory: `~/Library/Caches/bundleup` (macOS), `$XDG_CACHE_HOME/bundleup` or
   `~/.cache/bundleup` (Linux), `%LOCALAPPDATA%\bundleup\Cache` (Windows);
3. `$TMPDIR/bundleup-<uid>` (or `/tmp`), created `0700` and used only if owned by the current user
   and not writable by group or others, so another user can't plant code there;
4. `.bundleup/` next to the bundle.

**Loader steps.**

1. **Check** the Python minor version exactly, and `sys.platform`. When the bundle contains native
   code (any wheel tag that isn't `-any`), also check the CPU (`os.uname().machine`), CPython, and
   `sys.abiflags`. Failures print one plain sentence and exit 1, for example
   *"this app was bundled for Python 3.12, but it's running on Python 3.9 (/usr/bin/python3). Run it
   with Python 3.12 instead, for example: python3.12 app.pyz"*.
2. **Find** an existing extraction: one `isdir` per cache root. This is the whole warm path; it
   imports nothing beyond `os` and `sys`.
3. **Extract** (first run only): read `payload.zip` in place through a file window (no copy into
   memory), unpack into `.tmp-<dir>-<pid>-<random>` in the cache root, then `rename` it into place.
   If another process got there first, use its copy and delete ours. Executable bits are restored.
   If a root fails (read-only, full), try the next. If the running Python has `sys.pycache_prefix`
   set (macOS's `/usr/bin/python3` sets it to `~/Library/Caches/com.apple.python`), it never looks
   in `__pycache__`, so each `.pyc` is written where that Python will look for it instead.
4. **Activate**: remove the archive from `sys.path` and insert the extracted directory **before the
   first `site-packages` entry**, where a venv's site-packages would be: the standard library can't
   be shadowed, and the bundle wins over user or system site-packages. Prepend it to `PYTHONPATH`
   and set `BUNDLEUP_SITE`, so `sys.executable` children and `multiprocessing` workers see the same
   packages; a bundle started from another bundle removes its parent's `BUNDLEUP_SITE` entry first.
5. **Run** the entry like a console script: `sys.exit(module.attr())`. A module entry uses
   `runpy.run_module(..., run_name="__main__")`; a script uses `runpy.run_path`.

## Consequences

- Warm start costs one stat call and a 3-entry zip read on top of the app's own imports. First run
  pays extraction once per bundle version.
- Bundles are tied to one Python minor version and one OS (plus CPU when native). A pure-Python
  bundle could run more widely, but the lock's markers were evaluated for one environment (click
  pulls in `colorama` only on Windows), so relaxing this needs the analyzer first.
- **`PYTHONPATH` leaks to every child Python**, not just `sys.executable`. A child running a
  *different* Python version would see packages built for this one. Accepted for now because
  gauntlet 19 is a common pattern; revisit if it bites (an opt-out in `[tool.bundleup]`).
- The cache only grows. No garbage collection yet; a crashed first run can leave a `.tmp-*`
  directory behind. Both need a `bundleup cache` command or age-based cleanup later.
- Editing files inside the cache has no effect on `.py` files (their unchecked-hash `.pyc` wins).
  That's intended: the cache is not a place to edit code.
- Nothing is shared between bundles: two bundles with NumPy extract it twice. Per-wheel
  content-addressing (as pex does) is a possible later optimisation.
- `.dist-info/direct_url.json` of local projects records the build machine's path, as in a venv.

## Alternatives considered

- **One flat zip with every file** (pex, shiv, zipapps): simpler, but `zipimport` parses every
  entry on every start (measured above).
- **Payload appended outside the zip** (custom offsets): same effect as the inner zip, but the
  bundle stops being inspectable with ordinary zip tools.
- **Compile on first run instead of at build time:** about half the bundle size and a faster build
  (03: 0.1 s less; 13: 0.4 s less), but every first run compiles (03: +31 ms on 3.12, +19 ms on
  3.9; 13: +50 ms / +39 ms) and a read-only cache never gets `.pyc` files. Measured in the
  [findings](../findings/2026-10-04-milestone-1.md).
- **Timestamp or checked-hash `.pyc`:** timestamps break because extraction doesn't keep mtimes;
  checked-hash reads and hashes every source file on every import.
- **`sitecustomize` / `.pth` for child processes:** needs writing into the user's Python; only
  `PYTHONPATH` works from inside a process.
- **Inserting the payload at `sys.path[0]`:** a dependency named like a stdlib module would
  shadow the standard library.
- **No `__main__.pyc`:** the loader is recompiled on every start, 2–3 ms each time.
- **Setting `sys.pycache_prefix = None` in the loader** to make Apple's Python read `__pycache__`:
  its standard library has no `__pycache__`, so every later stdlib import would recompile.
- **Shebang `python3.X`:** finds the right version more often, but when it's missing the user gets
  `env: python3.12: No such file or directory` instead of the loader's explanation.

## Evidence

- [docs/findings/2026-10-04-milestone-1.md](../findings/2026-10-04-milestone-1.md)
- [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md) (shiv's `HOME`
  failure, zipapps' working-directory cache and race)
- Gauntlet 16, 19 and the hostile conditions
