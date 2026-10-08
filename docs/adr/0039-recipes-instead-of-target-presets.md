# ADR-0039: Recipes and capabilities instead of named target presets

- **Status:** Accepted (2026-10-07)
- **Date:** 2026-10-07
- **Deciders:** the owner; proposed by an agent
- **Supersedes:** the preset parts of [ADR-0014](0014-output-formats-and-target-presets.md)
  (decision 4) and [ADR-0025](0025-dir-and-lambda-formats-and-presets.md) ("Presets")

## Context

Round 4's research asked what each destination needs from a bundled Python program: which
Python, which platform, which layout, how big it may be. ADR-0014 answered with presets: names
(`--target lambda`, `lambda-arm64`, `claude-api`) that expand to ordinary flags, listed by
`bundleup targets`.

The owner questioned this on 2026-10-07: the research was about the *capabilities* each
destination needs, and those capabilities had all been built as flags anyway (`--format lambda`,
`--python-platform`, `--python`, `check --also-platform`, `check --matrix`, several platforms in
one `.pyz`). A preset added only:

- a name, which ages whenever AWS or Anthropic changes a runtime, a C library or a limit, and
  whose meaning a user can't see without running `bundleup targets`;
- a size limit (claude-api's 30 MB), which only a preset could carry;
- for Lambda, the choice of manylinux level from the Python version.

Every new destination would need code, a release and a name. The skill use case that started the
project (a skill installed by a package manager onto users' laptops) isn't any of the named
destinations at all, but it is served by the capabilities.

## Decision

1. **No named targets.** `--target`, `BUNDLEUP_TARGET`, `[tool.bundleup] target`,
   `bundleup targets`, `bundleup.list_targets()`, `bundleup.Preset` and the `targets` JSON schema
   are removed.
2. **Size limits are a general capability:** `--max-size SIZE` (`30MB`, `250MiB`, or bytes;
   `BUNDLEUP_MAX_SIZE`; `max-size = "30MB"` in `[tool.bundleup]`). Over it, the build fails with
   the `max-size` error before writing anything, for every format: a `.pyz`, a Lambda zip, or a
   directory's unpacked size. An explicit limit is an error, not a warning, because the
   destination will reject the output. Units are decimal (`MB` = 10⁶), as upload limits are
   written; `MiB` and friends are binary.
3. **Formats check what they need themselves.** `--format lambda` for compiled packages built
   for anything but Linux is an error (`lambda-not-linux`), with the platform to use in the hint.
   (Lambda's size limits were already checked by the format.)
4. **Destinations are [recipes](../recipes.md):** documented command lines that say which
   Python, platform, format and limit each destination needs, with the source and date of each
   fact. CI builds gauntlet 14 with each recipe on every push (the `recipes` job), from Linux
   and macOS.

## Consequences

- One mental model: every setting is a flag the user can see, and a new destination is a doc
  change.
- Users type longer commands for Lambda and the Claude API. `[tool.bundleup]` keeps them in the
  project (`format`, `python`, `python-platform`, `max-size`).
- Lambda's runtime facts (which Python versions exist, glibc 2.26 vs 2.34) are no longer
  enforced: building `--python 3.9` for Lambda now builds, and fails when the function is
  created. The recipe's table states them.
- Nothing has been released, so removing the commands breaks no user.
- Revisit if users repeat the same long command lines often enough that a name would save them
  real work; a name would then expand to flags in a config file, not in code.

## Alternatives considered

- **Keep presets, add `--max-size` alongside.** Two ways to say the same thing, and presets keep
  needing code changes as platforms change.
- **Presets as data (a TOML file users can extend).** A config-file feature with no user asking
  for it; `[tool.bundleup]` already stores a project's settings.
- **A size limit as a warning** (as claude-api's was). The user set the limit because the
  destination rejects anything bigger; a warning lets a broken artifact through by default.

## Evidence

- The owner's question, 2026-10-07 (conversation): "I thought more from the perspective of making
  sure that we had capabilities that they needed."
- [Third review](../findings/2026-10-07-third-review.md): scope frozen, no new presets.
- [docs/recipes.md](../recipes.md), CI job `recipes`.
