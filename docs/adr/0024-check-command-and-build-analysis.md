# ADR-0024: `bundleup check` reports what won't survive bundling, and every build runs it

- **Status:** Proposed
- **Date:** 2026-10-05
- **Deciders:** an agent, while the user was away (roadmap item 10); needs the user's confirmation

## Context

"It tells you before you ship what won't survive" is the promise that sets bundleup apart
([vision](../vision.md), [MISSION.md](../../MISSION.md)); the [baseline](../findings/2026-10-03-baseline.md)
found no existing tool warns at build time. The vision lists what to flag: `__file__` paths,
metadata and plugins, imports by name, missing platform builds, code needing a newer Python.

Since bundles unpack everything to a real directory ([ADR-0005](0005-extract-to-cache-by-default.md),
[ADR-0010](0010-bundle-format-and-loader.md)), most of that list already works and the gauntlet
proves it (04-09). Missing platform builds already fail the build (ADR-0014). Executables and
`.pth` files now work too ([ADR-0023](0023-payload-behaves-like-site-packages.md)). Warning about
things that work would be noise. Two problems remained, both silent until run time:

- **Code the target Python can't compile.** The build compiles everything with `compileall` in
  quiet mode, which skips such files without a word; the app then crashes on import.
- **Data files outside packages** (a wheel's `.data/data`, e.g. ipykernel's
  `share/jupyter/kernels/`): a venv puts them under `sys.prefix`, a bundle next to the packages.

## Decision

- **`bundleup check [PATH]`** takes `build`'s options except `-o`, installs and compiles exactly as
  `build` does, and reports without writing anything:
  - `syntax-error`: a `.py` file the target interpreter can't compile (files without bytecode
    after the build's compile step, confirmed by the target interpreter, with file and line).
    **An error in the project's own code** (or the script); **a warning in a dependency**, which
    may import such a file only on newer Pythons. One warning per dependency, listing its files.
  - `data-files` (warning): files a distribution installs under `share/` or `etc/`, except
    documentation (`share/man`, `share/doc`, `share/info`, `share/licenses`). Headers under
    `include/` are ignored: nothing loads them at run time.
  - A size report: each distribution unpacked, bytecode included, largest first; every package
    with `-v`, all of them in `--json` ([check-v1.json](../schema/check-v1.json)).
- **Every `bundleup build` runs the same analysis** (a "check" step after "compile"): errors stop
  the build before anything is written; warnings are printed (and returned in
  `BuildResult.diagnostics`, and in the `--json` document's `diagnostics`) and don't change the
  exit code.
- **`--strict`** on both commands makes warnings fail too (exit 1), per the style guide's rule 27.
- Library: `bundleup.check(BuildOptions) -> CheckReport` (findings in `report.diagnostics`, `ok`
  is False when there are errors; it raises only when the build itself fails), `Diagnostic` (shared
  by the CLI and the library, with `code`, `level`, `message`, `hint`, `detail`, `package`, `file`,
  `line`), `PackageSize`, and `CheckFailedError` (code `check-failed`) from `build()`.

## Consequences

- A project that used to build with a broken file now fails to build. That's the point: the
  bundle would have crashed on import.
- The check costs one directory walk plus, only when something didn't compile, one run of the
  target interpreter: 0.1-0.3 s on gauntlet 21's 14 packages / 147 MB (measured as part of whole
  `check` runs of 2-4 s).
- No false positives on gauntlet 03, 10, 13-15, 20-23 on Python 3.9 and 3.12 (torch, sympy,
  Django, boto3 included); ipykernel's kernel spec is the one real `data-files` case found so far.
- New checks get a new `code`; consumers branch on codes. Candidates when evidence appears:
  source-only packages built on the build machine, libraries that won't load on an older glibc,
  `.pth` `import` lines that child processes miss.

## Alternatives considered

- **Warn about the vision's whole list** (`__file__`, metadata, dynamic imports): all of them work
  in an unpacked bundle; warnings would teach people to ignore warnings.
- **A static import scanner** (the "analyzer" with a Rust scanner in mind, ADR-0008): no
  confirmed failure needs it yet. The check module is where it would go.
- **`check` only, builds silent:** people who don't run `check` would ship the crash.
- **Errors for dependencies too:** packages legitimately ship files for newer Pythons behind
  version checks; failing those builds would block working apps.

## Evidence

- Library runs on 2026-10-05 over gauntlet 03, 10, 13-15, 20-23 (3.9 and 3.12): no findings; a
  project with a `match` statement and `requires-python >=3.9`, built for 3.9: one
  `syntax-error`; ipykernel 6.30.1: one `data-files` warning.
- Tests: `tests/test_check.py`, `tests/test_cli.py::test_check_*`.
