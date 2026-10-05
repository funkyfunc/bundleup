# ADR-0012: Describe bundleup by what it does, with use cases as examples

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** the user

## Context

Several framings were considered for explaining bundleup: "for environments you don't control",
"the bundler for the agent era", "needs only Python". Each describes a real use, but each also
narrows the audience: people whose reason is different ("I just want one file", "I want to hand a
tool to a colleague") could conclude the tool isn't for them.

## Decision

Describe bundleup by what it literally does first: **it makes self-contained Python files** (your
code and its dependencies in one `.pyz` that runs with plain `python`, no install step). Then list
what people use that for (simplicity, easier distribution, agents, serverless, CI, locked-down
servers) as **examples, never as the definition**.

This applies to the README, PyPI description, docs, taglines and talks.

## Consequences

- Taglines stay literal; use cases rotate in examples and docs without redefining the product.
- Audience-specific angles (e.g. agents, see [roadmap](../roadmap.md) "Open question") are
  marketing layers on top, and need evidence before being used.

## Alternatives considered

- **"For environments you don't control."** Rejected as the lead: true for many users, but
  excludes people who just want simplicity or easy sharing.
- **"The bundler for the agent era."** Rejected as the lead: catchy, but most of the value is not
  agent-specific; kept as an open question pending research.
