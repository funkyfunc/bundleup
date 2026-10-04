# ADR-0003: Compete on experience and speed, not on new capability

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** the user

## Context

Research and the baseline run showed that pex can already bundle almost everything correctly.
The question was whether overlap with pex is a reason not to build.

## Decision

Overlap with pex is expected and acceptable. We win the way Rollup, esbuild and Vite won over
webpack: **dead simple to use, but also powerful and fast.** pex is the correctness bar we must
at least match; we lead on defaults, speed, build-time diagnostics and error messages.

## Consequences

- Every claim of "better" must be measured against pex on the gauntlet.
- Defaults matter more than options: the fast, correct path must need no flags.
- If pex closes the experience gap, we reassess (possibly contributing upstream instead).

## Alternatives considered

- **Only build where pex can't (e.g. just the analyzer).** Not rejected outright; the analyzer is
  part of the plan. But it alone doesn't deliver the "one command, just works" experience.
- **Contribute to pex instead.** Possible later. pex's design centres on monorepo build systems
  and many options, which makes "simple by default" hard to retrofit.

## Evidence

- [docs/vision.md](../vision.md), [docs/findings/2026-10-03-baseline.md](../findings/2026-10-03-baseline.md)
- [docs/research/round-2-evolution-compass.md](../research/round-2-evolution-compass.md) (how tools replaced each other)
