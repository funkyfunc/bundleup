# ADR-0018: Private modules, and a public API that loads lazily

- **Status:** Accepted (2026-10-05)
- **Date:** 2026-10-05
- **Deciders:** an agent, while implementing [ADR-0016](0016-cli-and-api-conventions.md); accepted by
  the user

## Context

The [style guide](../cli-style-guide.md) asks for two things that pull against each other:

- **Rule 38:** the public API is exactly `bundleup.__all__` (`build`, `BuildOptions`,
  `BuildResult`, the errors, `ExitCode`); everything else lives in `_private` modules.
- **Rule 35:** `bundleup --version` and `--help` must not import heavy modules.

The `bundleup` console script imports the `bundleup` package before anything else, so whatever
`bundleup/__init__.py` imports, every `--version` pays for. Importing the build machinery
(`packaging`, `zipfile`, `subprocess`, `concurrent.futures`, the verifier) costs about 35 ms;
`bundleup --version` takes about 10 ms without it. The
[review guide](../python-for-js-reviewers.md) lists `__getattr__` tricks as a smell unless an ADR
explains them, hence this ADR.

## Decision

- **Layout:** `bundleup/__init__.py` (public API), `_cli.py` (argparse, output, exit codes),
  `_build.py` (the build), `_verify.py` (lock and `RECORD` checks), `_errors.py` (exceptions and
  `ExitCode`), `_term.py` (colour, status line), `_loader.py` (the bundle's `__main__`), plus
  `__main__.py` for `python -m bundleup` and `py.typed`.
- **Lazy exports:** `__init__.py` imports the light names directly (errors, `ExitCode`) and loads
  `build`, `BuildOptions`, `BuildResult`, `ProgressEvent` and `Target` on first access through a
  module-level `__getattr__` (PEP 562, the standard mechanism since Python 3.7). Type checkers see
  them through an `if TYPE_CHECKING:` import. In JS terms: a barrel file whose heavy re-exports are
  lazy, like `export { build } from "./build"` behind a dynamic `import()`.
- **Guarded by tests:** `tests/test_cli.py` snapshots `__all__` and every public signature, and
  checks with `python -X importtime` that `--version` and `--help` import none of the build
  machinery.

## Consequences

- `--version` and `--help` stay instant; `from bundleup import build` works as usual.
- One small piece of "magic" (~10 lines in `__init__.py`), explained here and tested.
- Adding a public name means adding it to `__all__`, `_LAZY` or the eager imports, and to the API
  snapshot.

## Alternatives considered

- **Import everything eagerly in `__init__.py`:** simplest, but `--version` goes from ~10 ms to
  ~45 ms.
- **Defer imports inside every function of `_build.py`:** no magic, but imports scattered through
  the code and easy to regress.
- **A separate top-level module for the console script** (e.g. `_bundleup_cli`): avoids importing
  the package at all, but adds a second top-level name to the distribution.
