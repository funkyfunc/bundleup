# ADR-0021: Bundles don't see the machine's own packages, unless asked to

- **Status:** Accepted (2026-10-05)
- **Date:** 2026-10-05
- **Deciders:** the user chose isolation with an opt-out; proposed by an agent (roadmap item 8)

## Context

[ADR-0010](0010-bundle-format-and-loader.md) puts a bundle's packages where a venv's
site-packages would be: before the machine's user and system site-packages, which stayed on
`sys.path` behind them. A package missing from a bundle (which the build-time checks of
[ADR-0019](0019-manifest-and-verify-command.md) now make very unlikely) would then be imported
silently from whatever the machine had, the same kind of masking the gauntlet harness suffered
when it ran bundles on the repo's venv ([learnings](../learnings.md), 2026-10-05). pex isolates by
default (`PEX_INHERIT_PATH=false`).

## Decision

- **By default the loader drops everything from the first `site-packages`/`dist-packages` entry
  on**: the user's and the system's site-packages and whatever their `.pth` files added. What comes
  before stays: `PYTHONPATH` entries and the standard library. The bundle's packages take their
  place.
- **`BUNDLEUP_INHERIT_PATH=1`** (also `true`/`yes`) keeps the machine's packages, after the
  bundle's, as before. For apps that need something the OS installs, such as a Linux distro's
  PyGObject.

## Consequences

- Nothing outside the bundle and the standard library is imported by accident.
- **Child processes still see the machine's packages**: `PYTHONPATH` can only add to a child's
  path. A child gets the bundle's packages first, so it only matters for modules the bundle lacks.
- Modules the machine's `.pth` files imported at interpreter start-up (before the loader runs)
  stay imported.
- Tests: `tests/test_bundle.py::test_machine_packages_are_hidden_unless_inherited` (a module
  planted in the user site-packages is invisible, and visible with the opt-out), and the gauntlet
  condition `user-site-conflict` (a broken copy of every bundled package in the user
  site-packages, with the opt-out on, must not win).

## Alternatives considered

- **Keep the machine's packages as a fallback** (the previous behaviour): friendlier to apps
  that rely on system packages, but hides bundling mistakes.
- **Remove only the user site-packages:** system site-packages can be just as stale.
- **Run with `python -I`/`-s` semantics:** can't be chosen by a file; the interpreter is already
  running when the loader starts.
