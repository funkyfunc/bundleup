# Synthesis: round 5 (CLI and library design), 2026-10-04

Reports: [round-5-cli-compass.md](round-5-cli-compass.md) (primary; note it did **not** receive the
attachments, so its bundleup specifics are assumptions) and [round-5-cli-gemini.md](round-5-cli-gemini.md).

**The output of this round is [docs/cli-style-guide.md](../cli-style-guide.md)**, proposed via
[ADR-0016](../adr/0016-cli-and-api-conventions.md).

## Agreement (both reports)
argparse (no Click/Typer/Cyclopts), no Rich (a small in-house terminal helper), uv-style
`error:`/`hint:` messages, stdout for machine output and stderr for people, `NO_COLOR`/TTY rules,
a versioned `--json`, a small exit-code table (0 ok, 1 build failed, 2 usage error, plus 3 internal
error in Compass), config precedence flags > env > `[tool.bundleup]` > defaults, a typed library
API the CLI wraps, snapshot and contract tests.

## Disagreement
**Command shape.** Compass: verbs (`bundleup build | check | targets`), no default action, no
positionals (`--project`). Gemini: the bare command builds, with one optional positional path, and
subcommands only for auxiliary actions (matches the current code). Left to the user; see the style
guide's "Open decision".

## Quality notes
- Gemini's startup figures are not credible ("argparse 0.00 ms", Cyclopts faster than Click);
  Compass cites a measured third-party benchmark (argparse 44 ms, Click 56, Typer 179, Cyclopts 198
  for `--help`) and flags it as a single, environment-specific source. Re-measure on our CI.
- Verified: Python 3.14 argparse added `suggest_on_error` (default off) and `color` (default on);
  `allow_abbrev` exists since 3.5. bundleup supports 3.9+, so typo suggestions need a `difflib`
  fallback.

## External reports reviewed
- **"Satisfying Terminal UX"** (research for filegoblin, at
  `~/Development/filegoblin/docs/research/`): kept six rules on output feel (style guide rules
  51–57: show the work, cargo-style step verbs, clear completion line, dimmed metadata, no emoji,
  clickable output path). Rejected its manipulative suggestions (fake stutters, illusion bars,
  sounds, haptics).
- **"Delightful Terminal UI"** (research for comfyclaude): about full-screen TUIs (panels, diffs,
  image protocols). Not applicable to a run-once build command; not used.

## Not used
A separate "CLI UX and Grammar Specification" from another project (a Rust text-extraction CLI)
was reviewed. Its general points (headless composability, stdout/stderr isolation) are already
covered here; the rest is specific to that tool, so it wasn't added to the repo.
