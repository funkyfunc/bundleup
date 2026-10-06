# ADR-0017: Free platform matrix on GitHub Actions, plus nightly corpus testing with AI triage

- **Status:** Proposed
- **Date:** 2026-10-04
- **Deciders:** proposed by an agent from the owner's questions; awaiting the owner (incl. whether
  to make the repo public)

**Owner decision (2026-10-05):** the repository will be made public (the owner flips it), so CI
runs the full matrix. The rest of this ADR stays Proposed.

## Context

bundleup is a one-person project developed on one Mac, but it must work on Linux, Windows and
macOS, x64 and arm64, Python 3.9–3.14, and on projects nobody wrote tests for. The gauntlet (22
projects) runs only on macOS. See [testing-strategy.md](../testing-strategy.md) for the full plan.

Verified 2026-10-04: GitHub Actions is free and unlimited for public repositories on standard
GitHub-hosted runners, which include Linux x64/arm64, Windows x64/arm64 and macOS Apple
Silicon/Intel. Private repos get 2,000 free minutes/month, then per-minute charges (macOS
$0.062/min dominates). Self-hosted runners are free.

## Decision

1. **Run the platform matrix on GitHub-hosted runners.** Recommend making the repository public so
   the matrix costs nothing (owner's call). If it stays private, keep macOS jobs to the minimum.
2. **Local machines for interactive debugging only:** the Mac (macOS, system Python 3.9), Linux
   containers/VMs on it, and the System76 laptop (real x86_64 Linux, optionally a Windows VM).
3. **Never run third-party projects' code directly on personal machines.** Corpus runs use
   ephemeral GitHub-hosted runners without secrets, or a throwaway VM/container on the System76
   laptop if GitHub capacity runs short.
4. **Correctness is defined and checked in two halves** (see testing-strategy.md "What correct
   means"): *fidelity* (a hash chain from `uv.lock` through each wheel's `RECORD` to the bundle's
   embedded manifest and the extracted cache, plus reproducible builds) and *equivalence* (the
   environment behaves like a `uv sync` venv: snapshot comparison, differential runs, gauntlet).
5. **Nightly corpus testing** of real projects (stratified, pinned to commits), judged by
   differential comparison with a `uv sync` venv plus the correctness checks.
6. **Failures are deduplicated by signature into GitHub issues, triaged by an agent** that
   reproduces, classifies, reduces each bundleup bug to a new gauntlet project, and proposes a
   fix. **The owner merges.**
7. Buy no hardware until a concrete need appears (candidates: a Raspberry Pi for real arm64 edge
   testing; a Windows machine only if interactive Windows debugging becomes frequent).

## Consequences

- Broad coverage at $0 (if public), without a test lab.
- Requires the correctness checks and a stable `--json`/exit-code contract first, so the nightly
  job can tell pass from fail.
- New ongoing cost: reviewing agent-proposed fixes.

## Alternatives considered

- **Buy Windows and Linux machines.** Rejected for now: GitHub's runners plus the existing System76
  laptop cover it.
- **Self-hosted runner on the System76 laptop for corpus runs.** Rejected: runs untrusted code on a
  personal machine.
- **Truly random repos.** Rejected: most aren't runnable programs; a stratified corpus finds more
  real failures per run.
