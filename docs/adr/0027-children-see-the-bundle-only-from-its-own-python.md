# ADR-0027: Child processes see the bundle only when they run the bundle's own Python

- **Status:** Accepted (2026-10-07); which children activate is amended by
  [ADR-0037](0037-children-activate-only-for-bundle-code.md)
- **Date:** 2026-10-07
- **Deciders:** the owner approved fixing the [independent review](../findings/2026-10-07-independent-review.md)'s
  findings, from a plan that named this fix; the details were designed by an agent and haven't
  been reviewed by the owner; design by an agent
- **Supersedes:** the child-process part of [ADR-0010](0010-bundle-format-and-loader.md)
  (`PYTHONPATH` pointing at the payload); amends [ADR-0021](0021-isolate-from-machine-packages.md)'s
  consequence that children still see the machine's packages

## Context

ADR-0010 put the unpacked payload on `PYTHONPATH` so `sys.executable -c ...` children see the
bundle's packages (gauntlet 19, which pex and shiv fail), and accepted that the leak reaches every
Python the program starts. The review demonstrated the cost: a bundled script running
`python3.13 -c "import rich"` imported the bundle's rich. Any tool the app launches (aws,
pre-commit, a project's own venv) imports the bundle's packages first, and compiled ones crash in a
different Python version. ADR-0010 rejected `sitecustomize` because it would mean writing into the
user's Python; a `sitecustomize` inside the payload, reached through `PYTHONPATH`, doesn't.

## Decision

- **`PYTHONPATH` points at a shim, `__bundleup__/` in the payload, never at the packages.** It
  holds `sitecustomize.py`, which every Python the program starts imports at start-up, and
  `_bundleup_runtime.py`, the code that activates the payload.
- **The shim activates the bundle only in the bundle's own interpreter**: same `sys.prefix`,
  Python version and ABI flags (`BUNDLEUP_RUNTIME_PYTHON`, set by the parent; renamed from `BUNDLEUP_PYTHON`, which is also
  `--python`'s variable, after the second review). That covers
  `sys.executable` children and multiprocessing; another venv, version or build of Python is left
  alone.
- **Either way, it then runs the `sitecustomize` it shadows**, so the other Python behaves as it
  would without the bundle (its error, if any, reported as site.py would).
- **The loader and the shim share one implementation** (`_bundleup_runtime.activate`): children
  of the bundle's interpreter get the same isolation (ADR-0021) and `.pth` processing, `import`
  lines included (ADR-0023), as the bundle itself.
- A bundle started from another bundle drops everything the parent added (`BUNDLEUP_RUNTIME_PATHS`) and
  the parent's shim.

## Consequences

- Gauntlet 19 keeps passing; other Pythons no longer see the bundle
  (`tests/test_bundle.py::test_other_pythons_are_left_alone`, which also checks the shadowed
  `sitecustomize` still runs).
- Every Python the program starts imports one small extra file (a few `stat` calls and, when it
  isn't the bundle's interpreter, a lookup of the next `sitecustomize`).
- A child started with `-S`, `-I` or `-E` skips the shim, so it doesn't see the bundle.
- The payload has two files no wheel installed (`__bundleup__/`); the RECORD check expects them.

## Alternatives considered

- **No `PYTHONPATH` at all** (the review's suggestion): loses gauntlet 19, a real difference
  from pex and shiv; multiprocessing would still work (spawn passes `sys.path`).
- **Opt-in `PYTHONPATH`:** the default would still be wrong for one of the two cases.
- **Matching on version only:** a different venv of the same version would still be hijacked.
