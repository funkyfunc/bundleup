# ADR-0016: CLI and Python API follow the style guide

- **Status:** Accepted (2026-10-05)
- **Date:** 2026-10-04
- **Deciders:** proposed by an agent from round 5 research; accepted by the user, who chose
  verbs for the command shape

## Context

Round 5 research studied uv, Ruff, cargo, esbuild, gh, git, pytest, HTTPie, pip, pypa/build and
clig.dev to produce concrete CLI and library API rules for bundleup
([Compass](../research/round-5-cli-compass.md), [Gemini](../research/round-5-cli-gemini.md)). The two
reports agree on almost everything. [ADR-0011](0011-cli-and-build-pipeline.md) (Proposed) describes
the CLI milestone 1 actually built.

## Decision

1. bundleup's CLI and API follow [docs/cli-style-guide.md](../cli-style-guide.md): uv's flag
   vocabulary, `error:`/`hint:` messages, stdout for machine output and stderr for people, a
   versioned single-document `--json`, the five-code exit table, flags > env > `[tool.bundleup]` >
   defaults, a typed library API that never prints or exits, argparse with a small in-house
   terminal helper, and snapshot/contract tests for every output mode.
2. **Command shape (decided 2026-10-05): verbs.** `bundleup build [PATH]`, later `bundleup check`,
   `bundleup targets`, `bundleup cache …`; bare `bundleup` prints help. See the style guide's
   "Command shape".
3. Where this conflicts with [ADR-0011](0011-cli-and-build-pipeline.md), this ADR wins (the user's
   decision, 2026-10-05); ADR-0011's pipeline and dependency decisions stand.

## Consequences

- One reference for every CLI change; agents check new flags, messages and outputs against it.
- Adopting it changes some current behaviour (e.g. human output to stderr, exit codes), which is
  cheap now because nothing is released.
- Adds work: `--json` schema, `_term.py`, snapshot tests, docs generation.

## Alternatives considered

- **Click or Typer.** Rejected: extra dependencies and slower startup (Typer and Cyclopts pull in
  Rich) for a CLI with only a few commands.
- **Rich for output.** Rejected: import cost for four colours and a spinner.
- **No machine output.** Rejected: CI and agents are first-class users.
