# ADR-0044: Destinations described as data files (`--against FILE`)

- **Status:** Accepted (the owner, 2026-10-09: "go ahead and implement everything else", after
  rounds 6 and 7)
- **Date:** 2026-10-09
- **Deciders:** the owner (the direction), an agent (the design)
- **Refines:** [ADR-0039](0039-recipes-instead-of-target-presets.md) (no named targets in code)

## Context

Round 7 ranks "check against a described target" as the largest unmet need: agent sandboxes and
serverless runtimes each have their own Python, platform, size limit and rules (no network, no
installs), and code that works in one fails in another. ADR-0039 removed named presets because
names in code age and hide their meaning. The owner prefers capabilities to named targets.

## Decision

- A destination is described in a small TOML file: `name`, `source` (a link) and `checked` (a
  date) are required; `python`, `python-platform`, `max-size` and `format` are settings;
  `network` and `installs` are facts; `notes` is free text. Unknown keys are errors with a
  suggestion.
- `--against FILE` on `build` and `check` (`BuildOptions(against=...)`) fills every setting not
  given by a flag or the environment, and outranks `[tool.bundleup]` (it was asked for on this
  run). The CLI prints what it applied and the facts; `--json` has it as `result.against`.
- bundleup ships no names: the files its recipes use live in `docs/targets/` (the Claude API
  sandbox, AWS Lambda for Python 3.13 on x86_64 and arm64), each with its source and date, and
  are tested to load. Anyone can copy, change or write one.

## Consequences

- The recipes become one flag (`--against docs/targets/claude-api.toml`), and the facts behind
  them are visible and dated in one place.
- The facts (`network`, `installs`) are reported, not checked: a bundle carries its packages, so
  they explain why a bundle is the right shape rather than gate the build.
- Not done: checking a script that relies on a sandbox's preinstalled packages (the bundle's
  isolation hides them, ADR-0021), and fetching target files from a URL.
