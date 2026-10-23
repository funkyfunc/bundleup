# ADR-0052: Native bundles run on every compatible Python version by default

- **Status:** Accepted
- **Date:** 2026-10-20
- **Deciders:** the owner (the requirement), an agent (the design)
- **Supersedes:** the "compiled bundles run on one Python version" rule of
  [ADR-0030](0030-pure-python-bundles-run-on-a-range.md); extends
  [ADR-0036](0036-wrong-python-reruns-and-a-platform-matrix.md),
  [ADR-0038](0038-one-pyz-for-several-platforms.md), and
  [ADR-0040](0040-entry-python-runs-any-script.md)
- **Changed before it was first committed** (2026-10-22, the owner's go-ahead on the
  [twelfth review](../findings/2026-10-22-twelfth-review.md)): `requires-python` is never lowered
  and the lock never re-locked (decision 4 below, as amended); payloads for other Python versions
  get their own code checks (decision 3); binaries are merged only for `.pyz` and `.py` outputs,
  and only extension files tagged with their version (decision 2); a missing interpreter is an
  error again, never the build machine's in its place. Each of these had produced bundles that
  claimed a Python they then crashed on.

## Context

In a real-world skill build (`playwright`, built with `bundleup 0.2.0` on a machine with CPython
3.13), the resulting `deps.pyz` required CPython 3.13 or 3.14 even though `playwright` and its
dependencies (`greenlet`, `pyee`) publish wheels for Python 3.9–3.14. Five compounding assumptions
caused this:

1. **All native payloads were locked to a single CPython minor version (ADR-0030).** Even wheels
   tagged `py3-none-<platform>` (such as `playwright` or `ruff`, which ship a platform binary or
   Node.js driver with no CPython C-API link) or `cp3X-abi3-<platform>` (such as `cryptography` or
   `orjson`) were treated as single-Python payloads, and `cp3XX` wheels (`greenlet`, `lxml`,
   `Pillow`, `numpy`) were installed only for the build host's Python unless the user manually
   repeated `--python 3.10 --python 3.11 ...` (which also duplicated whole payloads per Python).
2. **Universal locks fork package versions by Python marker.** In `playwright`, `uv.lock` selects
   `pyee 13.0.1` for `python_full_version < '3.12'` and `pyee 14.0.0` for `>= '3.12'`. Even after
   merging `greenlet`'s `cp310`–`cp314` extensions, the lock marker restricted a single payload's
   range to `3.12-3.14` unless the `<3.12` fork was also layered.
3. **`uv init` pins `requires-python` to the host interpreter.** Running `uv init --bare` on Python
   3.13 writes `requires-python = ">=3.13"` into `pyproject.toml`, silently excluding Python
   3.10–3.12 on virtual skill projects that have no own package code requiring 3.13.
4. **Runtime re-exec only searched `PATH` (`ADR-0036`).** On macOS, `/usr/bin/python3` is Apple's
   Python 3.9. When a user had newer Pythons installed via `uv python install` (stored in
   `~/.local/share/uv/python/` rather than symlinked onto `PATH`), `python3 deps.pyz` failed with a
   version mismatch instead of finding the `uv`-managed interpreter.
5. **Cross-platform builds required spelling four target triples (and omitted Linux ARM64), and
   fixed-entry bundles had no setup escape hatch.**

The owner's expectation matches JavaScript bundlers: a bundle built with default settings should
work across Python 3 environments out of the box without package-specific hardcoding or manual
per-Python flag matrices.

## Decision

1. **Compute each payload's `PythonRange` from PEP 425 `WHEEL` tags and `.cpython-3XX` binaries:**
   - `wheel_allows_python()` and `runtime_needs()` in `_platforms.py` inspect every installed
     distribution's `WHEEL` tags (`py3-none-*`, `cp3X-abi3-*`, `cp3XX-*`).
   - `python_range()` in `_payload.py` widens a native payload's range across every CPython minor
     version (`3.9`–`3.20`) allowed by the lock selection, `Requires-Python`, `WHEEL` tags, and the
     set of `.cpython-3XX` / `.cp3XX` extension binaries present in `site`.
2. **Automatically merge `cp3XX` native wheels across compatible Python versions (`merge_native_wheels`):**
   - Because CPython stacks `.cpython-310-*.so` through `.cpython-314-*.so` side by side in the same
     package directory without filename collisions, `_uv.merge_native_wheels()` resolves compatible
     Python versions (`3.9`–`3.14`) that share the same lock selection and copies each additional
     version's `.cpython-3XX` / `.cp3XX` extension binaries into the payload, merging `WHEEL` tags
     and `RECORD` hashes so `bundleup verify` checks every merged binary.
   - Non-runtime build metadata files that differ between per-Python wheel builds (`__config__.py`,
     `_build_config.py`, and static `.a` / `.lib` / `.pc` / `.cmake` archives, as in `numpy`) do not
     block merging.
   - Only files tagged with their version (`.cpython-3XX*`, `.cp3XX*`) may join a payload from
     another version's build; any other file only that build has is a conflict, and that version
     gets a payload of its own (amended: such files reached every Python the payload served).
   - Only outputs with a loader merge (`.pyz`, `.py`): a `dir` or `zip` is loaded by one known
     Python, and an executable brings its own (amended: a Lambda zip doubled for nothing).
3. **Automatically layer uncovered `uv.lock` Python marker forks and unmergeable native extensions (`_lock_fork_pythons`):**
   - When `options.python` is not pinned to a specific version and `uv.lock` forks package versions
     across the project's compatible Python range (e.g. `<3.12` vs `>=3.12`), or when a `cp3XX`
     package ships untagged binaries at identical paths across Python versions (such as `pywin32` on
     Windows, whose `win32/win32api.pyd` and `pythonwin/win32ui.pyd` lack `.cp3XX-win_amd64.pyd`
     ABI tags, or `Pillow` on `x86_64-apple-darwin`, whose `PIL/.dylibs/*.dylib` differ between
     `macosx_10_10`, `macosx_10_13`, and `macosx_10_15` wheel build groups), `_build.py`
     automatically builds an additional payload for each uncovered Python version or group on that
     platform.
   - `write_layers()` deduplicates shared files across forks so large shared wheels (such as
     `playwright`'s 44 MB driver or `python-pptx` / `xlsxwriter` / shared `.py` files) are stored
     once, and only the differing `.pyd` / `.dylib` binaries are stored in per-version layers.
   - Such a payload isn't compiled or analyzed like the build's own, so it claims only the
     versions on which the project's own code parses (`ast` with `feature_version`) and whose
     standard library has every module the code imports for sure (`_check.fork_range`); one with
     no version left isn't built (amended: a `match` statement got a payload claiming 3.9).
   - Every range stays within the lock's own `requires-python`: outside it the lock may lack what
     a marker selects there.
4. **Support `--python` ranges and `--python-platform all`; never lower `requires-python`
   (amended):**
   - Virtual/non-packaged projects (`uv init --bare`, `uv init --no-package`, or `pyproject.toml`
     without `[build-system]` and without package sources) are detected automatically without
     requiring `[tool.uv] package = false`, and support bundling local `.py` files (`main.py`,
     `--entry scripts/tool.py`, or `[project.scripts]`) when `--entry python` is not used.
   - `requires-python` is used as written. The first design lowered a bare `>=3.12`-`>=3.19` to
     `>=3.10` on virtual projects and re-locked a staged copy to match; the review found it
     overrode an explicit setting (code using `itertools.batched` claimed 3.10), shipped versions
     the lock never had, and could need the network. Instead, when `requires-python` is what keeps
     a bundle off older Pythons, the build says so and how to lower it (`uv init` writes the
     Python it ran on there).
   - A PEP 723 script that names no `requires-python` is resolved from 3.9 when unlocked (as a
     requirements file is), and built with the Python its lock was made for when locked: uv
     stamps its default Python into such a lock and calls it stale for any other.
   - `--python` and `[tool.bundleup] python` accept range and PEP 440 specifiers (`3.10-3.14`,
     `3.11..3.13`, `3.11+`, `>=3.10,<3.14`), and `_served()` skips redundant builds already covered
     by an earlier payload's `PythonRange` on the same platform.
   - `--python-platform all` (or `universal`) expands to `ALL_PLATFORMS`: `aarch64-apple-darwin`,
     `x86_64-apple-darwin`, `x86_64-pc-windows-msvc`, `x86_64-manylinux_2_28`, and
     `aarch64-manylinux_2_28`.
5. **Discover `uv`-managed Pythons at runtime and support `BUNDLEUP_ENTRY=python`:**
   - When the invoking Python is outside the bundle's range and no matching `python3.X` is on
     `PATH`, `_loader._rerun_with_another_python()` queries
     `uv python find --system --no-project --no-python-downloads 3.X` if `uv` (`uv.exe` on Windows)
     is on `PATH`, and probes `python3.X.exe` on Windows before re-execing to skip Microsoft Store
     `WindowsApps` stubs.
   - Setting `BUNDLEUP_ENTRY=python` at runtime switches any bundle into interpreter mode (`-m`,
     `-c`, script, or REPL) so one-time setup commands (`BUNDLEUP_ENTRY=python python3 app.pyz -m ...`)
     work even on bundles built with a fixed entry point.

## Consequences

- A zero-flag `bundleup build` on a native project (`numpy`, `lxml`, `Pillow`, `playwright`,
  `cryptography`) produces a bundle that runs on every Python its `requires-python`, lock and
  wheels allow, without `--python` matrices or duplicated pure-Python/driver files. A project
  `uv init` made still starts at the Python it ran on until `requires-python` is lowered.
- It costs size and build time: measured in the twelfth review, a pydantic CLI went from 5 to
  15 MiB and numpy + lxml from 18 to 75 MiB, and cold builds took about ten times as long. One
  `--python` keeps the single-version size.
- Only version-tagged extension files (~200 KB–2 MB per C extension) are added per Python
  version; when a package differs in any other file across versions, `merge_native_wheels()`
  leaves that version unmerged and it gets a separate payload, its shared files stored once.
- `bundleup check` analyzes `scripts/*.py` in virtual skill projects automatically, without requiring
  `--entry python` to be passed on the `check` command line.

## Alternatives considered

- **Require users to pass `--python 3.10 --python 3.11 --python 3.12 --python 3.13 --python 3.14`:**
  Rejected. Users expect `bundleup build` to work across Python 3 environments by default, and five
  separate full `uv pip install` + compile passes per platform are much slower than merging only the
  compiled `cp3XX` wheels from the lock.
- **Package-specific workarounds (e.g. special-casing `playwright` or `numpy`):** Rejected by the
  owner; every rule uses standard PEP 425 tags, PEP 508 lock markers, `RECORD` hashes, and generic
  build-metadata patterns.

## Evidence

- `tests/test_config.py::test_multi_python_abi3_py3_none_wheel_ranges_and_python_specifiers`
- Verified on gauntlet `13-native-bundled-libs` (`numpy`, `Python 3.9-3.14`) and `playwright`
  (`Python 3.10-3.14` across the `pyee` `<3.12` / `>=3.12` lock fork).
