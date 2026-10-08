# ADR-0037: A child process activates the bundle only when it runs the bundle's code

- **Status:** Proposed (written 2026-10-07 while the owner was away)
- **Date:** 2026-10-07
- **Deciders:** an agent, from the [third independent review](../findings/2026-10-07-third-review.md)
- **Amends:** [ADR-0027](0027-children-see-the-bundle-only-from-its-own-python.md)

## Context

ADR-0027 activated the bundle (with ADR-0021's isolation) in every child process of the bundle's
own interpreter. The third review reproduced the cost: in a venv or Docker image where a tool is
installed with the same Python that runs the bundle (`pip install awscli`, then the bundle calls
`aws`), the tool lost its own packages: `ModuleNotFoundError`.

## Decision

The payload's `sitecustomize` activates the bundle only when the child, besides being the same
interpreter, runs the bundle's code, judged from `sys.argv` (already set when `sitecustomize`
runs):

- `-c ...`: yes (`sys.executable -c`, multiprocessing's spawn and forkserver children);
- `-m module`: yes if the module is in the payload (from `sys.orig_argv`, 3.10+); on 3.9, which
  can't tell, yes;
- a script inside the payload: yes; any other script (a console script installed with that
  Python): no;
- a program on stdin (`python -`, or `python` with piped input) or a prompt: yes. (Changed
  2026-10-08: first "no" for an interactive interpreter, which also left out stdin programs;
  click's own test suite runs `python -` and failed in a bundle. Code the bundle's program hands
  its own interpreter is its code, as with `-c`; a console script always has its path in
  `sys.argv[0]`.)
- When no other `sitecustomize` exists on `sys.path` (a few stat calls), the payload's imports
  nothing beyond `os` and `sys`, so a child loads the same modules plain Python does.

## Consequences

- Tools installed alongside the bundle's Python keep working; gauntlet 19 and multiprocessing
  are unchanged. Test: `test_tools_installed_with_the_same_python_keep_their_packages`.
- On Python 3.9, `python -m pip` started by a bundle still sees the bundle, not its environment.
