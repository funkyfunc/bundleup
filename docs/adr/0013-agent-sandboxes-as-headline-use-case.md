# ADR-0013: Agent sandboxes as the headline use case, served by target profiles and skill output

- **Status:** Accepted (positioning, point 1); Proposed (features, points 2–3)
- **Date:** 2026-10-04
- **Deciders:** the user accepted agents as a use case; proposed by an agent from round 3 research

**User's position (2026-10-04):** agent sandboxes are a good use case to feature. Whether target
profiles become a first-class flag (e.g. `--target claude-api`) is undecided: "definitely
something to consider". Revisit once round 4 (use cases and output formats) is back, since it
may suggest presets for several platforms, not just agents.

## Context

Round 3 research asked whether "the bundler for agents" is authentic
([synthesis](../research/round-3-and-2b-synthesis.md)). Findings, verified by hand:

- Claude API Skills run with no network and no runtime package installation (Python 3.11,
  Linux x86_64), yet the Agent Skills guide recommends PEP 723 + `uv run`, which needs network.
- Most other agent surfaces (cloud coding agents, desktop MCP) have network at install time and
  have standardized on uv; MCPB moved Python to host-side uv because compiled dependencies can't be
  bundled portably.

[ADR-0012](0012-lead-with-what-it-does.md) already says to lead with what bundleup does.

## Decision

1. **Positioning:** agents are a use case, not the category. Agent sandboxes and skills are the
   **headline example** under the general description, using the one-sentence answer from the
   synthesis.
2. **Agent-specific features, in order:**
   1. **Target profiles** for known sandboxes, starting with `claude-api` (CPython 3.11, manylinux
      x86_64, no network), built on cross-target builds.
   2. **Skill output:** `scripts/<tool>.pyz` plus a ready `SKILL.md` stanza and an honest
      `compatibility` line.
   3. **Compatibility pre-check** in `bundleup check`: refuse or warn when native code doesn't
      match the declared target.
   4. **Agent-operable CLI:** `--json`, stable exit codes, no prompts (also good for CI).
3. **Deferred:** MCPB output (MCPB's own `uv` type serves online desktop hosts) and a skill that
   teaches agents to bundle their own scripts (no evidence of demand yet).

## Consequences

- Cross-target builds become the next major capability after milestone 1.
- The gauntlet needs Linux x86_64 and Python 3.11 runs (CI) to back the `claude-api` profile.
- Marketing stays honest: "what do you mean it's for agents?" has a concrete, checkable answer.

## Alternatives considered

- **Lead with agents as the category.** Rejected: most of the value is general, and the claim
  invites "what's actually different?" with no good answer for most agent surfaces.
- **Ignore agents.** Rejected: the Claude API skills gap is real, documented and unserved.
- **MCPB first.** Rejected for now: the ecosystem is solving desktop MCP with host-side uv.
