# ADR-0043: `check --audit` asks PyPI about the locked packages

- **Status:** Accepted (the owner, 2026-10-09: "go ahead and implement everything else", after
  rounds 6 and 7)
- **Date:** 2026-10-09
- **Deciders:** the owner (the direction), an agent (the design)

## Context

Round 7 ([synthesis](../research/round-6-and-7-synthesis.md)): agents now choose most new
dependencies. Models name packages that don't exist about 5% of the time (some of those names are
registrable by an attacker), and pick versions with known vulnerabilities in a third to a half of
tasks. A tool that ships dependencies to other machines is a natural place to check them.

## Decision

- `bundleup check --audit` (and `check(..., audit=True)`) asks PyPI's JSON API about each locked
  package that comes from pypi.org, for the target being checked:
  - known vulnerabilities of the locked version (PyPI's data, from OSV; withdrawn ones don't
    count): `vulnerable`, with the version that fixes them;
  - a yanked version: `yanked`; a version PyPI no longer has: `not-on-pypi`;
  - a project first published under 90 days ago: `new-project` (only looked up when the locked
    version itself is that recent, so old projects cost one small request).
- All are warnings (`--strict` makes them fail). Packages from other indexes aren't checked. If
  PyPI can't be reached, one `audit-incomplete` warning says which packages weren't audited.
- Opt-in, because it needs the network; it's not part of `build`.

## Consequences

- One flag in CI catches vulnerable or suspicious dependencies before they're bundled.
- It depends on PyPI's JSON API and its vulnerability data; a private index's packages need
  their own scanner.
- Tests: `tests/test_audit.py` (PyPI's answers faked, no network).

## Alternatives considered

- **pip-audit or Socket as a dependency:** more thorough, but another tool and its policies;
  PyPI's own data covers the common case with the standard library's HTTP client.
- **Checking at every build:** builds would need the network and get slower; the audit belongs in
  CI and before release.
