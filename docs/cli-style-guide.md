# CLI and Python API style guide

How bundleup's command line and library API should look and behave. Synthesized from round 5
research ([compass](research/round-5-cli-compass.md), primary; [gemini](research/round-5-cli-gemini.md),
agrees on almost everything). Adopted via [ADR-0016](adr/0016-cli-and-api-conventions.md)
(**Proposed**). Where this guide and [ADR-0011](adr/0011-cli-and-build-pipeline.md) differ, the user
decides during the ADR-0011 review.

## Open decision: command shape

| Option | Example | For | Against |
|---|---|---|---|
| **A. Verbs** (Compass) | `bundleup build`, `bundleup check`, `bundleup targets`; bare `bundleup` prints help | Matches uv and cargo, which users run alongside bundleup. Adding commands later (`check`, `targets`, `cache clean`) never collides with a project path. clig.dev warns against default commands | Two extra words for the main action |
| **B. Default action** (Gemini, current code) | `bundleup [path]` builds; `bundleup check`, `bundleup targets` are extras | The esbuild feel: `bundleup` alone does the job | `bundleup check` is ambiguous if a folder is named `check`; every new subcommand is a potential breaking change |

**Agent's recommendation: A, with one optional positional on `build`** (`bundleup build [PATH]`,
where PATH is a project directory or a script). It keeps "one obvious command" while staying
safe to extend. Until the user decides, don't add new subcommands.

## Rules

### Flags and defaults
1. **Zero config builds correctly for this machine.** Python version from `requires-python` /
   `.python-version` as uv resolves it; output `dist/<name>.pyz`.
2. **Reuse uv's flag names and meanings where we overlap:** `--python`, `--locked`, `--frozen`,
   `--project`, `--python-platform` (uv's platform vocabulary, e.g. `x86_64-manylinux_2_28`). No
   synonyms.
3. **Every flag has a long form.** Short flags only for `-o/--output`, `-q/--quiet`,
   `-v/--verbose`, `-n/--dry-run`, `-h/--help`, `-V/--version`.
4. **No abbreviations:** `ArgumentParser(allow_abbrev=False)`.
5. **Booleans come in pairs** (`--compile/--no-compile`, argparse `BooleanOptionalAction`).
6. **List options repeat** (`--python-platform a --python-platform b`); no comma lists.
7. **Presets expand to ordinary flags and print the expansion** (`Using target lambda: --python
   3.14 --python-platform …`). Explicit flags override preset values. A `targets` listing shows
   every expansion.
8. **`--dry-run` / `-n`** resolves everything, prints the plan and where each setting came from,
   and writes nothing.
9. **In CI (`CI` set), behave as `--locked`**: a stale lockfile is an error, not a silent bundle
   missing a new dependency.

### Output
10. **stdout is for machine output only** (`--json`, listings). **All human messages, warnings and
    errors go to stderr.**
11. **On success, print at most two short lines**, e.g.
    `Bundled myapp 1.4.0 → dist/myapp.pyz (8.2 MiB) in 1.37s`.
12. **Progress only on a TTY and only for steps over ~200 ms**: one rewriting line, never in CI.
13. **Colour off** when the stream isn't a TTY (checked per stream), `NO_COLOR` is set,
    `TERM=dumb`, or `--color never`. `FORCE_COLOR` / `--color always` turn it on. Colour only for
    `error` (red), `warning` (yellow), `hint` (cyan), and bold paths.
14. **ASCII fallback** (`->`, no spinner) when stderr isn't UTF-8.
15. **Quiet and verbose levels:** `-q` = warnings and errors only, `-qq` = errors only; `-v` = step
    timings, `-vv` = the uv commands run.

### Machine output and agents
16. **`--json` writes exactly one JSON document to stdout at exit**, on success and failure, with
    the normal exit code. Human stderr output is suppressed.
17. **It carries `schema_version`.** Within a version, changes are additive only; consumers ignore
    unknown keys. Breaking changes need a new version. Publish a JSON Schema.
18. **Every diagnostic has a stable `code` slug** (e.g. `lock-outdated`), `level`, `message`, and
    optional `hint`, `file`/`line`, `package`. Scripts and agents branch on codes, not prose.
19. **Never prompt.**
20. **Deterministic output:** sort lists; paths relative to the project; durations and absolute
    paths isolated in known fields.

### Errors
21. **Format:** `error: <what happened>`, optional context lines, then `hint: <what to do next>`
    last (uv's style).
22. **Point at what to edit:** `file:line` with a caret for config errors; `package==version` for
    dependency errors.
23. **Expected failures never show a traceback.** Every expected failure is a `BundleupError`
    subclass the CLI renders. Unexpected exceptions are bugs: exit 3, "this is a bug" line, issue
    link, full traceback with `-v`.
24. **Suggest fixes for typos** in subcommands, choices and preset names, but never auto-run them
    (argparse `suggest_on_error` on 3.14+, `difflib` before).
25. **When uv fails, quote its stderr verbatim**, indented under bundleup's one-line explanation.

### Exit codes

| Code | `bundleup.ExitCode` | Meaning |
|---|---|---|
| 0 | `OK` | Success (warnings allowed unless `--strict`) |
| 1 | `BUILD_FAILED` | Expected failure: stale or missing lock, no compatible wheel, uv failure, `check` found problems, `--strict` warnings |
| 2 | `USAGE_ERROR` | Invalid flags, unknown command or target, invalid `[tool.bundleup]` |
| 3 | `INTERNAL_ERROR` | A bug in bundleup |
| 130 | `INTERRUPTED` | Ctrl-C |

26. **Don't add codes per failure type**; use the JSON `code` for detail.
27. **Warnings never change the exit code** unless `--strict`.

### Configuration

| Rank | Source | Example |
|---|---|---|
| 1 | Flags | `--target lambda --python 3.13` |
| 2 | Environment | `BUNDLEUP_PYTHON=3.12`, `UV_LOCKED`, `NO_COLOR`, `CI` |
| 3 | `[tool.bundleup]` in `pyproject.toml` | `target = "lambda"` |
| 4 | Defaults | host platform, `dist/<name>.pyz` |

28. **Env vars are `BUNDLEUP_` + the long flag in SCREAMING_SNAKE.** Show them in `--help`.
29. **Per-run settings** (`--json`, `-q`, `--dry-run`, `--color`) are flags/env only, rejected in
    `[tool.bundleup]`.
30. **Unknown keys in `[tool.bundleup]` are errors with a suggestion.**
31. **No user-level config files** until users ask.

### Help, speed, stability
32. **`--help`:** one-line purpose, 3–4 examples, common options first, docs and bug-report URLs.
    Under ~30 lines.
33. **Per-flag help shows default, allowed values and `[env: …]`.**
34. **Generate the CLI reference doc from the parser in CI**, and fail if it drifts.
35. **Startup budget:** `--version` and `--help` must not import heavy modules or start uv. Measure
    on CI with `python -X importtime`.
36. **Contracts:** commands, flags, env vars, `[tool.bundleup]` keys, exit codes, JSON schema and
    diagnostic codes. Human-readable text is not a contract.
37. **Versioning:** uv's scheme until 1.0 (minor = breaking). **Deprecate in three steps:** warn,
    then error with the replacement, then remove. Never change what an existing flag means.

### Feel: delight, with restraint
From "Satisfying Terminal UX" research done for another project (filegoblin), keeping only what
fits a build tool. Everything here applies to TTY output only; rules 10–15 still hold.

51. **Show the work, not a bare spinner.** For steps over ~1 s, the progress line names the step
    and the current item or count (`Fetching wheels 12/23 · numpy-2.1.3`), so it's obviously alive.
    A spinner with no detail is reserved for short, unknown-length waits.
52. **Steps read like cargo and uv:** a short bold verb at the left margin (`Resolved`, `Fetched`,
    `Bundled`), then the detail. Easy to scan.
53. **End with one clear completion line** (rule 11), visually distinct from the progress that
    preceded it, so the task feels finished.
54. **Colour has meaning; metadata is dimmed.** Sizes, timings and paths in dim/grey, the important
    word bold, red/yellow/cyan only for error/warning/hint. No decorative colour.
55. **No emoji.** At most `✓`/`→` on UTF-8 terminals, with ASCII fallbacks.
56. **The output path is a clickable link** (OSC 8 hyperlink) when stderr is a TTY that supports it;
    plain text otherwise.
57. **Rejected from that research:** artificial stutters or fake progress, animated "illusion"
    bars, sounds and haptics. They manipulate rather than inform, and they don't belong in CI-adjacent
    tools.

### Python library API
38. **The public API is exactly `bundleup.__all__`.** Everything else lives in `_underscore`
    modules. Ship `py.typed`.
39. **Entry points:** `build()`, `check()`, `list_targets()`, with keyword-only typed options (a
    frozen `BuildOptions` dataclass mirroring the CLI).
40. **Results are frozen dataclasses** whose `to_json_dict()` *is* the `--json` schema.
41. **One exception root, `BundleupError`**, with `.code`, `.hint`, `.exit_code`; subclasses such as
    `ConfigError`, `LockfileOutdatedError`, `NoCompatibleWheelError`, `UvError`.
42. **The library never prints, exits, configures logging, or touches `sys.stdout`/`os.environ`.**
    Progress goes through an optional callback; warnings come back in the result.
43. **The CLI is a thin layer:** `argv → BuildOptions → build() → render → ExitCode`, in one
    `main(argv: list[str] | None = None) -> int`.
44. **Guard the API with a test** that snapshots `__all__` and every public signature.

### Implementation
45. **argparse**, not Click/Typer/Cyclopts: no extra dependencies, fastest startup. Add an
    `Examples:` epilog and `[env: …]` suffixes with a custom `HelpFormatter`.
46. **No Rich.** A ~80-line `_term.py` handles TTY detection, the colour rules, four styles, ASCII
    fallback and a TTY-only spinner.

### Testing the CLI
47. **Snapshot every output mode** (success, warnings, each error class, crash) for stdout and
    stderr, with durations and paths redacted.
48. **Exit-code contract tests** through a real subprocess (`python -m bundleup`), including
    Ctrl-C → 130 and an injected crash → 3.
49. **Output-mode matrix:** `NO_COLOR`, `FORCE_COLOR`, `TERM=dumb`, piped (non-TTY) and a real TTY.
50. **JSON contract test:** validate against the published schema; one document on stdout even
    with warnings.
