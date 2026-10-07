# ADR-0030: A pure-Python bundle runs on every Python version its lock allows

- **Status:** Accepted (2026-10-07)
- **Date:** 2026-10-07
- **Deciders:** the owner approved fixing the [independent review](../findings/2026-10-07-independent-review.md)'s
  findings, from a plan that named this fix; the details were designed by an agent and haven't
  been reviewed by the owner; design by an agent
- **Supersedes:** the "one Python minor version" rule of [ADR-0010](0010-bundle-format-and-loader.md)
  for bundles without compiled code

## Context

Every bundle ran on exactly the minor version it was built with, so a pure-Python project
declaring `requires-python >=3.9` refused both macOS's `python3` (3.9) and 3.13 when built with
3.12, and its `python3` shebang pointed at whatever `python3` happened to be. The review called
this the main reason not to hand a bundle to unknown users. ADR-0010 kept one version because the
lock's markers were evaluated for one environment (click pulls in colorama only on Windows; tomli
only below 3.11).

## Decision

- **A bundle with compiled code still runs on exactly one version** (its extension modules are
  built for one ABI).
- **A pure-Python bundle runs on a range**: starting from the target's version, every
  neighbouring minor version (3.9 to 3.20 are evaluated) for which
  - the lock selects exactly the same packages (its markers evaluated for that version), and
  - the project's `requires-python` and every bundled package's `Requires-Python` allow it.
  A range still open at 3.20 has no upper limit.
- **The project's own code is compiled with the oldest Python in the range**, when an interpreter
  for it is installed. If it doesn't compile (requires-python promises more than the code
  delivers), the bundle runs on the target's version only, with a `python-range` warning.
- **Bytecode is precompiled for the target's version only**; other versions compile on first
  import, into the cache (or every time, when the cache is read-only).
- **The loader** refuses versions outside the range ("bundled for Python 3.10 or newer") and
  suggests the nearest allowed one. **The shebang** names the version when the bundle runs on
  only one (`#!/usr/bin/env python3.12`, which Windows' `py` launcher also reads), else
  `python3`.
- Outputs say it: `Python 3.10+ on macOS`; `target.python_range` (`{"min", "max"}`) in the
  `--json` results and the manifest (additive within schema version 1).

## Consequences

- Gauntlet 03 built with 3.12 runs on 3.10+ (its lock picks other versions for 3.9); gauntlet
  02 runs on 3.9+. The gauntlet's new `other-python-X` condition runs each pure bundle on every
  other installed Python in its range: 94 runs on 2026-10-07, all passing (3.9 to 3.13).
- A first run on a non-target version is slower (it compiles); later runs aren't.
- A dependency file that only compiles on newer Pythons (but declares support for older) is
  found only for the target version. The project's own code is checked on the oldest.

## Alternatives considered

- **Precompile for every version in the range:** needs every interpreter at build time and
  multiplies the bytecode; first-run compilation is cheap by comparison.
- **Ranges for native bundles too, via abi3 wheels:** possible when every compiled wheel is abi3;
  left for when someone needs it.
