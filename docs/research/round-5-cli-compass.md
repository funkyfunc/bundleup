# bundleup CLI and Python API style guide

Build bundleup as a **verb-based CLI on top of a typed, side-effect-free Python API, using stdlib argparse and plain ANSI output**. Copy uv's flag vocabulary and its `error:`/`hint:` style. Follow clig.dev's stdout/stderr and colour rules exactly. Make `--json` and exit codes versioned contracts, and treat human-readable output as free to change.

## TL;DR
- **Interface:** use `bundleup build | check | targets` with zero-config defaults. Reuse uv's flags and meanings (`--python`, `--locked`, `--frozen`, `--python-platform`). Presets (`--target lambda`) expand to ordinary flags, and bundleup prints that expansion. Human messages go to stderr; one `--json` document goes to stdout. Exit codes: 0 ok, 1 build failed, 2 usage/config error, 3 internal bug, 130 interrupted.
- **Library:** expose `bundleup.build()` and `bundleup.check()` with keyword-only typed options, frozen result dataclasses and one `BundleupError` hierarchy. The API never prints, exits or touches global state; pip's documented failure modes show what happens when it does. The CLI should be about 200 lines that parse, call, render and map exceptions to exit codes.
- **Implementation:** argparse (3.14 adds `color` and `suggest_on_error`) plus a ~50-line colour helper. Typer and Cyclopts pull in Rich and measurably slow startup. Click is the only reasonable alternative. Enforce a startup budget and snapshot-test every output mode.

## Assumptions (the attachments did not arrive)
- I haven't seen the mission, vision, roadmap, CLI design ADR or current `--help`. Everything bundleup-specific below comes from the brief: a Python tool that turns a locked (uv) project into one self-contained file, used by humans, CI and AI agents, and later as a library. Where this guide conflicts with your ADR, treat it as a proposal to argue against, not a correction.
- **Placeholders:** the output is shown as `dist/<name>.pyz`, and the preset names are `lambda`, `docker` and `local`. Package names, sizes and timings in the examples are illustrative.
- **Platform names:** I assume bundleup passes platform names through to uv, so platform values use uv's `--python-platform` vocabulary (e.g. `x86_64-manylinux_2_28`, `aarch64-apple-darwin`).

## Part 1 — What the best tools actually do

| Tool | What it does well (evidence) | What to avoid / lessons |
|---|---|---|
| **uv** | Terse, timed summaries (`Resolved 21 packages in 33ms`). Two-line errors: `error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.` followed by `hint: To update the lockfile, run `uv lock`.`\[1\]\[2\] Each flag's help shows its env var (`--locked … [env: UV_LOCKED=]`). `UV_LOCKED=0` disables the setting for one invocation.\[1\]\[3\] Its versioning policy is explicit: "the minor version number is bumped for breaking changes", and the lockfile schema "is considered part of the public API".\[4\] | It has no Python API: the uv crates' Rust interface "does not follow semantic versioning", and the PyPI package mostly locates the binary (`uv.find_uv_bin()`, which has had path bugs: issue #5808).\[4\]\[5\] The `--locked`/`--frozen` difference trips users up: CodeHubJournal tested a stale lock and found `uv sync --locked` exits 1 while `uv sync --frozen` exits 0 with "packaging was absent". |
| **Ruff** | Small documented exit-code table: 0 = clean, 1 = violations, 2 = abnormal termination. `--exit-zero` "will still exit with a status code of 2 if it terminates abnormally".\[6\]\[7\] Config errors show Rust-style source context (`TOML parse error at line 2, column 18 … unknown variant `py36`, expected one of `py37` …`).\[8\] | Panics once exited 0, and maintainers agreed it "should probably be exit code 2, to indicate that the process crashed with an internal error" (#11107).\[9\] No Python API: "We actually don't support a Python API … there is a lot of design work that needs to happen first".\[10\] A minimal-API proposal (#8401) was closed as not planned, so users fall back to subprocess and temp files, which the proposer called "footguns".\[11\] |
| **cargo** | `--message-format=json` writes "JSON object per line" to stdout with a `reason` discriminator.\[12\] Maintainers' stance: new fields and message types may be added, and an incompatible change would get `--message-format=json-v2`.\[13\] Its test suite asserts exact stderr with redaction placeholders (`[ERROR] cannot specify two kinds of `message-format` arguments`, `[..]`).\[14\] | Non-JSON from child tools leaks into the stream, so the book tells consumers to "only interpret a line as JSON if it starts with `{`".\[12\] Its own status messages aren't JSON yet (#8283), and users ask to get human and JSON output in one run (#14555).\[15\]\[16\] |
| **esbuild** | Once silent on success (to fit into tool chains). Later added a summary, which recent versions print by default: `out.js  27.6kb` / `⚡ Done in 6ms`.\[17\]\[18\] The `--metafile` JSON and `--analyze` give machine and human detail on demand.\[17\] One API for CLI, JS and Go. | The `--metafile` + `--watch` combination was broken for a while (#1357).\[19\]\[20\] Machine output belongs in an explicit artefact, not in scraped logs. |
| **gh** | `--json fields` with `--jq`/`--template`. Running `--json` without fields lists the available fields. Has dedicated `gh help formatting` and `gh help exit-codes` topics.\[21\]\[22\] Documents exit code 4 for "authentication required".\[23\] | Contract drift: `gh attestation` returned other codes on HTTP 401, which broke Homebrew, since it relies on exit code 4 (#9338).\[23\] Requiring field lists annoys users ("cannot use `--jq` without specifying `--json`", #10385).\[24\] |
| **git** (as quoted by clig.dev) | `git status` prints state plus next-step hints (`use "git add <file>..."`). `git push` reports exactly what changed.\[25\] | Huge flag surface; don't copy its inconsistency. |
| **pytest** | Exit codes 0–6 cover distinct cases: tests failed (1), interrupted (2), internal error (3), usage error (4), nothing collected (5), and a warnings limit (6). They are exposed as the public `pytest.ExitCode` enum.\[26\] | Few, and only via plugins: users who want different semantics (e.g. "no tests collected") need `pytest-custom_exit_code`.\[26\] |
| **HTTPie** | `--check-status` maps HTTP 3xx/4xx/5xx to exit codes 3/4/5. An `ExitStatus` IntEnum sits in the code. `-q`/`-qq` gives quiet levels.\[27\]\[28\]\[29\] | By default it exits 0 on HTTP errors, which surprises script authors.\[28\] Make the strict behaviour easy to reach. |
| **pip** | Its docs are honest about why it has no API. | "everything inside of pip is considered an implementation detail. Even the fact that the import name is pip is subject to change". It "assumes that it is in sole control of the global state" (logging, stdio) and is "*not* thread safe".\[30\] pip 10 moved internals to `pip._internal`, breaking `pip.get_installed_distributions()` callers (#5243), and an unofficial `pip-api` package now exists just to wrap the CLI.\[31\]\[32\] |
| **pypa/build** | Clean split: a CLI (`python -m build`, `pyproject-build`) over `ProjectBuilder` ("The PEP 517 consumer API"), plus a high-level `build.util` added in 0.7.0.\[33\]\[34\]\[35\] Ships `py.typed`.\[34\] | 1.0.0 changed the `ProjectBuilder` constructor signature and replaced `IsolatedEnvBuilder`.\[34\] Low-level classes as the only API make breaking changes inevitable, so expose a high-level function first. |
| **clig.dev** | The baseline for everything below. | — |
| **Bun, Deno, pipx** | Not examined in depth in this research pass; no claims made. | — |

## Part 2 — The style guide: command line

Each rule has a one-line rationale and an example. The evidence for each is in Part 1 or noted inline.

### A. Command structure
1. **Use verb subcommands: `build`, `check`, `targets`. Running bare `bundleup` prints concise help and exits 0.** *Why:* uv, cargo and Bun all use a build verb. clig.dev warns against catch-all default commands, because "you can never add a subcommand named `echo`—or anything at all—without risking breaking existing usages."\[25\] *Example:* `bundleup build`.
2. **Add a subcommand only for a different verb with different output or side effects.** `check` validates and writes nothing. `targets` lists presets. Modes of the same action stay as flags (`--dry-run`, `--json`). *Example:* `bundleup check --target lambda` exits 1 if bundling would fail.
3. **No positional arguments on `build`. The project is the current directory, overridable with `--project DIR`** (uv's name). *Why:* clig: "Prefer flags to args… it makes it easier to make changes to how you accept input in the future."\[25\] *Example:* `bundleup build --project services/api`.
4. **No abbreviations or implicit aliases.** Turn off argparse's `allow_abbrev`. *Why:* clig: arbitrary abbreviations mean "you can't add any more commands beginning with `i`".\[25\] *Example:* `bundleup build --pyth 3.12` is an error, not `--python`.
5. **A preset is a named bundle of ordinary flags. It is printed on use and listed with its full expansion.** Explicit flags always override preset values. *Example:* `bundleup build --target lambda` prints `Using target lambda: --python 3.12 --python-platform x86_64-manylinux_2_28` first. `bundleup targets` shows every expansion, and `bundleup targets --json` returns it as data.
6. **Every subcommand supports `--dry-run`/`-n`, which resolves everything, prints the plan and the origin of each setting, and writes nothing.** *Why:* clig lists `-n, --dry-run` as a standard flag.\[25\] *Example:* `bundleup build -n` reports `python = 3.12 (from: target lambda)`.

### B. Flags and defaults
7. **Every flag has a long form. Short flags only for `-o/--output`, `-q/--quiet`, `-v/--verbose`, `-n/--dry-run`, `-h/--help`, `-V/--version`.** *Why:* clig: "Only use one-letter flags for commonly used flags".\[25\] uv uses `-V` for version, and clig notes `-v` is ambiguous.\[25\] *Example:* `bundleup build -o app.pyz -q`.
8. **Where bundleup overlaps with uv, use the identical flag name, meaning and env-var behaviour.** That means `--python`, `--locked` ("Assert that the uv.lock will remain unchanged") and `--frozen` (use the lockfile without checking it), plus `--project` and `--python-platform`.\[3\]\[36\] Don't invent synonyms. *Why:* clig says "Use standard names for flags, if there is a standard",\[25\] and users will copy commands from uv. *Example:* `bundleup build --locked` fails exactly when `uv sync --locked` would.
9. **Default to `--locked` behaviour in CI (`CI` env var set) and to "use the lock, warn if stale" interactively.** `--frozen` is opt-in. *Why:* a stale lock silently producing a bundle that lacks a newly added dependency is the worst outcome for a deployment tool.\[37\] *Example:* in GitHub Actions, `bundleup build` with a stale lock exits 1 with the uv-style hint.
10. **Boolean options come as `--x/--no-x` pairs (argparse `BooleanOptionalAction`). Boolean env vars accept `1/0/true/false`.** *Why:* this lets a flag override a config or env value in either direction, the way `UV_LOCKED=0` works.\[1\] *Example:* `BUNDLEUP_COMPILE=1 bundleup build --no-compile`.
11. **List options repeat (`--python-platform a --python-platform b`) and don't take comma lists.** In config files they are TOML arrays. *Example:* `bundleup build --python-platform x86_64-manylinux_2_28 --python-platform aarch64-apple-darwin` produces one artefact per platform, or one multi-platform artefact if supported.
12. **Zero config must produce a correct bundle for the host platform.** Python comes from `requires-python`/`.python-version` (as uv resolves it), and output goes to `dist/<name>.pyz`. *Why:* clig: "If it's not the default, you're making the experience worse for most of your users."\[25\] *Example:* `cd myapp && bundleup build` just works.

### C. Output for humans
13. **On success, print at most two lines to stderr, uv style: what was resolved, and what was written (with size and time).** *Why:* clig says to display brief output on success ("err on the side of less"),\[25\] and esbuild's two-line summary set the norm.\[17\] *Example:* `Bundled myapp 1.4.0 → dist/myapp.pyz (8.2 MiB) in 1.37s`.
14. **stdout carries only machine output (`--json`, or `targets` listings). All human messages, warnings and errors go to stderr.** *Why:* clig: "Send output to stdout… Send messaging to stderr."\[25\] *Example:* `bundleup build --json | jq .artifact.path` works even when warnings are printed.
15. **Show progress only when stderr is a TTY and a step takes more than ~200 ms. Use a single rewriting line with no bars for unknown totals.** On a non-TTY, print nothing for progress. *Why:* clig: "If `stdout` is not an interactive terminal, don't display any animations… Christmas trees in CI log output", and "Print something to the user in <100ms".\[25\] *Example:* `⠋ Building sdist for sqlalchemy 2.0.36…`, which vanishes when the step ends.
16. **Colour is off when any of these hold: the stream is not a TTY (checked per stream), `NO_COLOR` is non-empty, `TERM=dumb`, or `--color never` is passed. `FORCE_COLOR`/`--color always` turn it on.** Colour is used only for `error` (red), `warning` (yellow), `hint` (cyan) and bold paths. *Why:* these conditions are clig's list verbatim.\[25\] *Example:* `NO_COLOR=1 bundleup build` has no escape codes.
17. **Unicode is fine only for `→` and the spinner. Fall back to ASCII (`->`, no spinner) when stderr's encoding isn't UTF-8.** No emoji in CI. *Example:* on a `cp1252` Windows console the success line uses `->`.
18. **`-q` drops everything except warnings and errors, and `-qq` drops warnings too. `-v` adds per-step timing, and `-vv` adds the uv commands run.** Never print log-level prefixes by default. *Why:* HTTPie's `-q`/`-qq` model, and clig: "Don't treat `stderr` like a log file".\[25\]\[27\] *Example:* `bundleup build -vv` shows `$ uv export --frozen --format requirements.txt …`.

### D. Output for machines and agents
19. **`--json` writes exactly one JSON document to stdout at exit, on success and on failure. Exit codes are unchanged, and human stderr is reduced to nothing (as if `-qq`).** *Why:* agents parse one document. cargo-style NDJSON streams invite the line-filter hack its own book recommends.\[12\] *Example:* `bundleup check --json` → `{"schema_version": 1, "status": "error", …}` with exit 1.
20. **The document carries `schema_version` (an integer). Within a version, changes are additive only, and consumers must ignore unknown keys.** A breaking change means a new version that you opt into first (`--json-schema 2`) before it becomes the default. Publish a JSON Schema file. *Why:* this is cargo's stated policy ("add new fields… json-v2").\[13\] Arduino CLI likewise treats only `--format json` as a breaking-change surface.\[38\] *Example:* see the `--json` example output below.
21. **Every diagnostic has a stable `code` slug, a `level`, a `message`, and optional `hint`, `file`/`line` and `package`.** *Why:* agents branch on codes, not prose, and prose may change (rule 41). *Example:* `"code": "lock-outdated"`.
22. **Never prompt.** bundleup has no destructive interactive steps. If it ever needs one, it must fail on a non-TTY and name the flag to pass. *Why:* clig: "Never *require* a prompt."\[25\] *Example:* overwriting an existing output is allowed (it's a build artefact), and `--no-clobber` makes that an error.
23. **Deterministic output:** sort packages and diagnostics by name, emit paths relative to the project root, and isolate the only non-deterministic values (durations, absolute paths) under `timing` and `project.root`. *Why:* this enables snapshot tests and diffing between CI runs. *Example:* two runs of `bundleup build --json` differ only in `timing.total_ms`.

### E. Errors
24. **Errors follow `error: <what happened>`, then optional context lines, then `hint: <next command>` on the last line.** *Why:* this is uv's format, and clig says to "Put the most important information at the end".\[1\]\[25\] *Example:* see the error examples below.
25. **Show the location the user must edit (file:line:col with a caret snippet for config errors, package==version for dependency errors).** *Why:* Ruff's TOML errors point straight at the offending token.\[8\] *Example:* `--> pyproject.toml:14:10`.
26. **Expected failures never show a traceback.** Every expected failure is a `BundleupError` subclass that the CLI renders. A traceback appears only for unexpected exceptions (exit 3), and then with a "this is a bug" line and an issue link. *Why:* clig: "not printing scary-looking stack traces" for expected errors, plus "provide debug and traceback information, and instructions on how to submit a bug" for unexpected ones. Ruff says "This indicates a bug in Ruff".\[9\]\[25\] *Example:* `error: internal error (this is a bug in bundleup 0.4.0)`, followed by the last frame, a crash-report path and the issue URL. `-v` prints the full traceback.
27. **Suggest corrections for typos in subcommands, choices and preset names, but never auto-run them.** *Why:* clig's "suggest it… but don't force it", and argparse 3.14's `suggest_on_error` does this natively.\[25\]\[39\]\[40\] *Example:* `hint: did you mean `lambda`?`
28. **When a uv subprocess fails, quote its stderr verbatim, indented under bundleup's own one-line explanation.** *Why:* uv's message is usually the precise one, and rewording it loses information. *Example:* `error: uv could not export the lockfile` followed by `  uv: error: Unable to find lockfile at `uv.lock`…`.

### F. Exit codes
29. **Keep a small, documented and tested exit-code table, exposed as a public `bundleup.ExitCode` IntEnum** (pytest's pattern).\[26\] See the table below. *Why:* gh's #9338 shows that wrappers (Homebrew) hard-code these, and Ruff's #11107 shows the cost of exiting 0 on a crash.\[9\]\[23\]
30. **Warnings never change the exit code unless `--strict` is passed, which turns them into exit 1.** *Why:* this follows Ruff's `--exit-zero`/`--exit-non-zero-on-fix` pattern of explicit opt-ins.\[7\] *Example:* `bundleup build --strict` exits 1 on an sdist fallback.

### G. Configuration
31. **Precedence: flags > `BUNDLEUP_*` env vars > `[tool.bundleup]` in the discovered `pyproject.toml` > built-in defaults. A preset expands inside the layer where it was given, and that layer's explicit keys override it.** *Why:* this matches clig's order (flags, then environment, then project config).\[25\] *Example:* `[tool.bundleup] target = "lambda"` plus `--python 3.13` gives the lambda platform with Python 3.13.
32. **Env-var names are `BUNDLEUP_` plus the long flag in SCREAMING_SNAKE (`BUNDLEUP_PYTHON_PLATFORM`). Repeated values are space-separated. Honour `UV_LOCKED`/`UV_FROZEN`, since uv already reads them.** Show the env var in `--help`, uv style. *Why:* uv documents each one (`UV_FROZEN`, "added in 0.4.25"), and clig says "uppercase letters, numbers, and underscores".\[25\]\[41\] *Example:* `--python-platform <PLATFORM>  … [env: BUNDLEUP_PYTHON_PLATFORM=]`.
33. **Don't add user-level or global config files, `.env` reading, or a separate `bundleup.toml` until users ask for one.** Settings that vary per invocation (`--json`, `-q`, `--dry-run`, `--color`) are flag/env only and are rejected in `[tool.bundleup]`. *Why:* clig: per-invocation settings belong in flags, and project-stable settings belong in a version-controlled file.\[25\] uv errors on settings that aren't allowed in a given file (0.5.0, #8550).\[42\] *Example:* `json = true` in `[tool.bundleup]` gives `error: `json` cannot be set in pyproject.toml; pass `--json``.
34. **Unknown keys in `[tool.bundleup]` are errors with a suggestion, not ignored.** *Why:* silently ignoring a typo in a deploy config is a production bug. *Example:* `pythn = "3.12"` gives `hint: did you mean `python`?`

### H. Help and docs
35. **`--help` opens with a one-line purpose, then 3–4 examples, then the most common options first. It ends with a docs URL and a bug-report URL.** Keep top-level help under ~30 lines. *Why:* clig says "Lead with examples", "Display the most common flags… at the start", and to link to web docs.\[25\] *Example:* see the `--help` example below.
36. **Per-flag help shows the default, the allowed values and the `[env: …]` name.** *Why:* uv does this on every flag, so its reference page doubles as config documentation.\[3\]
37. **Generate the web CLI reference (and an optional man page) from the parser in CI, and fail CI if the committed docs drift.** *Why:* a single source of truth. clig recommends web docs plus terminal docs,\[25\] and uv's reference mirrors its `--help` text. *Example:* `python -m bundleup._docs > docs/reference/cli.md`, plus a diff check.
38. **`bundleup targets` is the self-documenting reference for presets. Each preset's docs show its flag expansion.**

### I. Speed you can feel
39. **Budget: `bundleup --version` ≤ 60 ms and `bundleup --help` ≤ 80 ms wall time (median) on a Linux CI runner. `--version`/`--help` must not import `packaging`, start uv, or touch the network or the filesystem beyond the package itself.** *Why:* clig says "Print something to the user in <100ms".\[25\] A third-party benchmark measured bare `python -c pass` at 12.7 ms (Ubuntu) and argparse adding about 19 ms,\[43\]\[44\] so the budget is reachable only with lazy imports. *Example:* a CI test runs `python -X importtime -m bundleup --version` and fails if `packaging`, `subprocess`-launched uv or `json` appear.
40. **Import heavy modules inside the command function that needs them. The `bundleup` package `__init__` re-exports via module `__getattr__`, so `import bundleup` stays cheap.** *Why:* Gregory Szorc's guidance is that import-time work is a major source of startup lag, and that module `__getattr__` (3.7+) allows lazy attributes.\[45\] PEP 810 explicit lazy imports, targeted at Python 3.15, can replace this later.\[46\]

### J. Stability
41. **These are contracts: subcommands, flags, env vars, `[tool.bundleup]` keys, exit codes, JSON schema and diagnostic codes. Human-readable text is not.** Say so in a published versioning policy. *Why:* clig: "Changing output for humans is usually OK… Encourage your users to use `--plain` or `--json` in scripts".\[25\] Arduino CLI and Cosign publish similar policies.\[38\]\[47\]
42. **Follow uv's 0.x scheme (minor = breaking, patch = everything else) until 1.0, then semver.**\[4\] *Why:* users of a uv-adjacent tool already understand it.
43. **Deprecate in three steps. (1) The old flag or key keeps working and prints `warning: `--old` is deprecated; use `--new`` once per run, and a `deprecated-option` diagnostic appears in JSON. (2) After at least two minor releases it becomes an error that says what to use instead. (3) Then it is removed.** Never change what an existing flag means; add a new flag. *Why:* clig: "Keep changes additive… Warn before you make a non-additive change."\[25\] *Example:* `compress = true` → `compression = "deflate"`.

## Part 3 — The style guide: Python library API

44. **The public API is exactly what `bundleup/__init__.py` lists in `__all__`. Everything else lives in underscore modules (`bundleup._resolve`, `bundleup._cli`). Ship `py.typed`.** *Why:* pip shows what happens when there's no boundary, so draw it on day one.\[30\]
45. **Expose two entry functions, `build()` and `check()`, plus `list_targets()`. All options are keyword-only.** *Why:* keyword-only arguments let you add options without breaking callers. pypa/build had to add `build.util` later because `ProjectBuilder` was too low-level.\[34\]
46. **Options are a frozen dataclass mirroring the CLI one-to-one. Results are frozen dataclasses with a `to_json_dict()` that is the `--json` schema.** *Why:* a single schema for CLI and library means no drift.
47. **One exception root, `BundleupError(Exception)`, with `.code` (the diagnostic slug), `.hint` and `.exit_code`.** Subclasses: `ConfigError`, `LockfileError` (→ `LockfileMissingError`, `LockfileOutdatedError`), `ResolutionError`, `NoCompatibleWheelError`, `UvError` (carries `returncode`, `stderr`). Any other exception is a bug.
48. **The library never prints, never calls `sys.exit`, never configures `logging` handlers, and never mutates `sys.stdout`/`os.environ`. Progress goes through an optional callback, and warnings are returned in the result.** *Why:* pip "assumes that it is in sole control of the global state… logging system configuration, or the values of the standard IO streams".\[30\] Don't repeat it.
49. **`build()` reads `[tool.bundleup]` and `BUNDLEUP_*` env vars only if asked (`config="project"` or `"project+env"`; the default is `"project"`).** Library callers shouldn't inherit a CI runner's environment by accident.
50. **Safe to call concurrently for different projects. Document anything that isn't.** pip's "*not* thread safe" is a warning, not a model.\[30\]
51. **Version the API with the same policy as the CLI, and guard it with a test that snapshots `__all__` and every `inspect.signature`.** Accidental breaks then fail CI.
52. **The CLI is a thin layer: `argv → BuildOptions → build() → render(result | error) → ExitCode`.** One `main(argv: list[str] | None = None) -> int` function holds the only exception-to-exit-code mapping. `python -m bundleup` and the console script both call it.

## Example outputs (proposed)

**Successful build** (stderr; stdout empty):
```
$ bundleup build
Resolved 23 packages from uv.lock in 41ms
Bundled myapp 1.4.0 → dist/myapp.pyz (8.2 MiB) in 1.37s
```

**Build with warnings:**
```
$ bundleup build --target lambda
Using target lambda: --python 3.12 --python-platform x86_64-manylinux_2_28 --output dist/myapp-lambda.pyz
Resolved 23 packages from uv.lock in 41ms
warning: `sqlalchemy==2.0.36` has no wheel for x86_64-manylinux_2_28; built it from the source distribution
warning: `compress` in [tool.bundleup] is deprecated; use `compression = "deflate"` (removal in 0.7)
Bundled myapp 1.4.0 → dist/myapp-lambda.pyz (11.9 MiB) in 2.04s with 2 warnings
```

**Error 1: stale lockfile (exit 1)**
```
$ bundleup build --locked
error: `uv.lock` is out of date with `pyproject.toml`, but `--locked` was provided
  pyproject.toml requires `httpx>=0.28`, which is not in uv.lock
hint: run `uv lock`, commit uv.lock, then re-run `bundleup build --locked`
```

**Error 2: no compatible wheel (exit 1)**
```
$ bundleup build --python-platform aarch64-apple-darwin
error: cannot bundle for aarch64-apple-darwin: 2 packages have no compatible wheel
  numpy==2.1.3          wheels: manylinux_2_17_x86_64, win_amd64
  pydantic-core==2.27.1 wheels: manylinux_2_17_x86_64
hint: re-lock with a version that publishes macOS arm64 wheels, or run `bundleup targets` to see supported targets
```

**Error 3: invalid configuration (exit 2)**
```
$ bundleup build
error: invalid [tool.bundleup] in pyproject.toml
  --> pyproject.toml:14:10
   |
14 | target = "lamda"
   |          ^^^^^^^ unknown target
hint: did you mean `lambda`? run `bundleup targets` to list all targets
```

**Internal error (exit 3)**
```
error: internal error: KeyError: 'requires-dist' (this is a bug in bundleup 0.4.0)
  at bundleup/_resolve.py:212 in _wheel_metadata
  crash report: /tmp/bundleup-crash-8f3a.txt
hint: please report it at https://github.com/<org>/bundleup/issues/new (attach the crash report; re-run with -v for the full traceback)
```

**`--json`** (stdout; `schema_version` is the contract):
```json
{
  "schema_version": 1,
  "bundleup_version": "0.4.0",
  "command": "build",
  "status": "success",
  "exit_code": 0,
  "project": {"name": "myapp", "version": "1.4.0", "root": "/home/ana/myapp"},
  "config": {
    "target": "lambda",
    "python": "3.12",
    "python_platforms": ["x86_64-manylinux_2_28"],
    "locked": true,
    "frozen": false,
    "output": "dist/myapp-lambda.pyz",
    "sources": {"target": "flag", "python": "target:lambda", "locked": "env:CI", "output": "target:lambda"}
  },
  "artifact": {"path": "dist/myapp-lambda.pyz", "size_bytes": 12478103, "sha256": "3b1f…"},
  "packages": [
    {"name": "anyio", "version": "4.6.2", "source": "wheel"},
    {"name": "sqlalchemy", "version": "2.0.36", "source": "sdist"}
  ],
  "diagnostics": [
    {"level": "warning", "code": "sdist-build", "package": "sqlalchemy==2.0.36",
     "message": "no wheel for x86_64-manylinux_2_28; built from the source distribution", "hint": null}
  ],
  "timing": {"total_ms": 2040}
}
```
On failure: `"status": "error"`, `"artifact": null`, and the error appears in `diagnostics` with `"level": "error"` and its `code` (e.g. `lock-outdated`).

**`--help`:**
```
$ bundleup --help
Turn a locked Python project into one self-contained file.

Usage: bundleup <COMMAND> [OPTIONS]

Examples:
  bundleup build                       Bundle the project in the current directory
  bundleup build --target lambda       Bundle for AWS Lambda (see `bundleup targets`)
  bundleup build --locked --json       CI: fail if uv.lock is stale; print a JSON report
  bundleup check --python-platform aarch64-apple-darwin

Commands:
  build    Bundle a locked project into one file
  check    Check that a project can be bundled, without writing anything
  targets  List targets and the flags each one expands to

Global options:
  -q, --quiet          Print only warnings and errors (-qq: only errors)
  -v, --verbose        Show step timings (-vv: show uv commands)
      --color <WHEN>   auto, always, never [default: auto] [env: NO_COLOR, FORCE_COLOR]
  -h, --help           Show help (also: bundleup <COMMAND> --help)
  -V, --version        Show version

Docs: https://<docs>/cli  ·  Bugs: https://github.com/<org>/bundleup/issues
```
`bundleup build --help` lists, in this order: `--target`, `--python`, `--python-platform` (repeatable), `-o/--output`, `--locked`, `--frozen`, `--project`, `-n/--dry-run`, `--json`, `--strict`. Each shows `[default: …]` and `[env: BUNDLEUP_…=]`.

## Exit code table

| Code | Name (`bundleup.ExitCode`) | Meaning | Precedent |
|---|---|---|---|
| 0 | `OK` | Success (warnings allowed unless `--strict`) | all |
| 1 | `BUILD_FAILED` | Expected failure caused by the project or environment: stale/missing lock, no compatible wheel, uv failure, `check` found problems, `--strict` warnings | Ruff 1 = violations; pytest 1 = tests failed\[7\]\[26\] |
| 2 | `USAGE_ERROR` | Invalid flags, unknown subcommand/target, invalid `[tool.bundleup]` | argparse's default for usage errors; pytest separates usage (4) from failures\[26\] |
| 3 | `INTERNAL_ERROR` | Uncaught exception = bug in bundleup; prints bug-report instructions | pytest 3 = internal error; Ruff #11107\[9\]\[26\] |
| 130 | `INTERRUPTED` | Ctrl-C (128 + SIGINT) | shell convention; clig: exit "as soon as possible" on INT\[25\] |

Don't add codes per failure type. Scripts and agents should branch on the JSON `code`, which keeps the table small and stable.

## Configuration precedence table

| Rank | Source | Example | Notes |
|---|---|---|---|
| 1 (highest) | Command-line flags (a preset given as a flag expands here; explicit flags beat it) | `--target lambda --python 3.13` | Per-invocation settings (`--json`, `-q`, `--color`, `--dry-run`) exist only here and as env |
| 2 | Environment variables | `BUNDLEUP_PYTHON=3.12`, `BUNDLEUP_LOCKED=1`, plus `UV_LOCKED`/`UV_FROZEN`, `NO_COLOR`, `FORCE_COLOR`, `CI` | `BUNDLEUP_*` wins over `UV_*` when both are set |
| 3 | `[tool.bundleup]` in the nearest `pyproject.toml` | `target = "lambda"`, `python-platforms = [...]` | Unknown keys are errors; a `target` key expands here |
| 4 | Built-in defaults | host platform, `requires-python`/`.python-version`, `dist/<name>.pyz` | Zero-config path |

`bundleup build -n` prints each resolved value with its source, as the `config.sources` field in the JSON example shows.

## Library API outline

```python
# bundleup/__init__.py  — the entire public surface
from __future__ import annotations
import enum, os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Sequence

__all__ = [
    "build", "check", "list_targets",
    "BuildOptions", "BuildResult", "CheckResult", "Target",
    "PackageInfo", "Diagnostic", "ProgressEvent", "ExitCode",
    "BundleupError", "ConfigError", "LockfileError", "LockfileMissingError",
    "LockfileOutdatedError", "ResolutionError", "NoCompatibleWheelError", "UvError",
    "__version__",
]

class ExitCode(enum.IntEnum):
    OK = 0; BUILD_FAILED = 1; USAGE_ERROR = 2; INTERNAL_ERROR = 3; INTERRUPTED = 130

@dataclass(frozen=True, kw_only=True)
class BuildOptions:
    target: str | None = None
    python: str | None = None
    python_platforms: tuple[str, ...] = ()
    output: Path | None = None
    locked: bool = False
    frozen: bool = False
    strict: bool = False

@dataclass(frozen=True)
class Diagnostic:
    level: Literal["error", "warning", "info"]
    code: str                      # stable slug, e.g. "lock-outdated"
    message: str
    hint: str | None = None
    package: str | None = None
    file: Path | None = None
    line: int | None = None

@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str
    source: Literal["wheel", "sdist", "local"]

@dataclass(frozen=True)
class BuildResult:
    artifact: Path
    size_bytes: int
    sha256: str
    options: BuildOptions          # fully resolved
    option_sources: dict[str, str] # "flag" | "env:NAME" | "pyproject" | "target:NAME" | "default"
    packages: tuple[PackageInfo, ...]
    diagnostics: tuple[Diagnostic, ...] = field(default=())
    duration_ms: int = 0
    def to_json_dict(self) -> dict[str, object]: ...   # == CLI --json schema v1

@dataclass(frozen=True)
class CheckResult:
    ok: bool
    options: BuildOptions
    diagnostics: tuple[Diagnostic, ...]
    def to_json_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True)
class Target:
    name: str
    description: str
    expands_to: tuple[str, ...]    # e.g. ("--python", "3.12", "--python-platform", "x86_64-manylinux_2_28")

@dataclass(frozen=True)
class ProgressEvent:
    step: Literal["resolve", "fetch", "build-sdist", "assemble", "write"]
    detail: str
    done: bool

ConfigSource = Literal["none", "project", "project+env"]

def build(
    project: str | os.PathLike[str] = ".",
    *,
    options: BuildOptions | None = None,
    config: ConfigSource = "project",
    on_progress: Callable[[ProgressEvent], None] | None = None,
) -> BuildResult: ...

def check(
    project: str | os.PathLike[str] = ".",
    *,
    options: BuildOptions | None = None,
    config: ConfigSource = "project",
) -> CheckResult: ...

def list_targets() -> Sequence[Target]: ...

class BundleupError(Exception):
    code: str
    hint: str | None
    exit_code: ExitCode            # BUILD_FAILED or USAGE_ERROR
    diagnostics: tuple[Diagnostic, ...]

class ConfigError(BundleupError): ...            # exit 2; carries file/line
class LockfileError(BundleupError): ...
class LockfileMissingError(LockfileError): ...
class LockfileOutdatedError(LockfileError): ...
class ResolutionError(BundleupError): ...
class NoCompatibleWheelError(ResolutionError):
    packages: tuple[PackageInfo, ...]
    platform: str
class UvError(BundleupError):
    returncode: int
    stderr: str
```

The CLI layer (`bundleup/_cli.py`):

```python
def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)                       # argparse; ArgumentParser(..., allow_abbrev=False)
    out = _Renderer.from_env(args)            # TTY/NO_COLOR/--json decisions in one place
    try:
        result = build(args.project, options=_to_options(args), config="project+env",
                       on_progress=out.progress)
    except BundleupError as e:
        out.error(e); return int(e.exit_code)
    except KeyboardInterrupt:
        out.interrupted(); return ExitCode.INTERRUPTED
    except Exception as e:                    # the only place a traceback is produced
        out.crash(e); return ExitCode.INTERNAL_ERROR
    out.success(result)
    return ExitCode.BUILD_FAILED if (args.strict and result.diagnostics) else ExitCode.OK
```

## Part 4 — Implementation in Python

### Framework recommendation: argparse

| | argparse (stdlib) | Click | Typer | Cyclopts |
|---|---|---|---|---|
| Runtime deps | none | none (pallets/click PR #3505 changelog: "Colorama is no longer a dependency and is not used"; first release without it not confirmed) | `rich`, `shellingham` always; vendors Click since 0.26.0\[48\]\[49\]\[50\] | `rich`, `rich-rst`, `attrs`, `docstring-parser`\[51\]\[52\] |
| `--help` time (kevinconka/seascape issue #43: argparse vs click 8.5.0, typer 0.27.2, cyclopts 4.25.3; Py 3.13 macOS, medians) | 44 ms\[43\] | 56 ms\[43\] | 179 ms\[43\] | 198 ms |
| Startup notes | The fastest option | Small overhead | fastapi/typer Discussion #744 (a user, not a maintainer): ">85%" of startup is Rich imports, and the Rich #3399 fixes cut `typer.rich_utils` from ~230 ms to ~70 ms. 2.07 s for hello world on a Raspberry Pi 3 (Typer 0.9.0); Typer PR #1128 lazy-loads Rich | Has lazy *command* loading,\[53\] but still imports Rich for help\[53\] |
| Help quality | Plain. Colour and `suggest_on_error` since 3.14 (`color=True` by default)\[39\]\[40\] | Good, customisable | Rich panels | Rich panels, docstring-driven |
| Testability | Call `main(argv)` and capture streams | `CliRunner` | `CliRunner` | in-process call |
| Maintenance risk | CPython | Pallets, very stable | Fast-moving (vendored Click and dropped Click plug-in support in 0.26)\[50\] | Single maintainer, major versions in quick succession (v4 → v5)\[54\] |

**Recommendation:**
- **Use argparse.** bundleup already pays for `uv` and `packaging`, and its users will often run it through `uvx`, where every extra dependency costs install time.
- **What argparse is missing is cheap to add:**
  - Typo suggestions on Python < 3.14: `difflib.get_close_matches`, about 15 lines.
  - Env-var defaults: a resolver layer you need anyway for precedence and `option_sources`.
  - Help formatting: a custom `HelpFormatter` that adds an `Examples:` epilog and `[env: …]` suffixes.
  - Colour: set `color=` explicitly from your own colour decision, so argparse and bundleup agree. The 3.14 docs note that error messages can contain colour codes when stderr is redirected unless `NO_COLOR`/`PYTHON_COLORS` is set.\[40\]
- **Choose Click only** if you expect many subcommands with shared option groups. It now has no runtime dependencies, and seascape #43 measured it at 12 ms over argparse for `--help` (56 vs 44 ms) and 20 ms for a command (62 vs 42 ms).
- **Avoid Typer and Cyclopts here.** Their main selling point is less boilerplate. That matters little for a CLI with three subcommands, and it costs 100+ ms of startup and four or more transitive dependencies.

### Colour and progress: plain ANSI, not Rich
- **Rich is expensive to import.** Rich PR #3399 measured `rich.console` at 58.7 ms cumulative and `rich.color` at 114.6 ms before that fix.\[55\] Rich has since shipped lazy-loading releases (14.3.4 "Improved import time with lazy loading"; 15.0.0 "The Faster Startup Release"),\[56\]\[57\] but bundleup needs only four colours and one spinner.
- **Write `bundleup/_term.py` (about 80 lines):**
  - Per-stream `isatty()`, `NO_COLOR`/`FORCE_COLOR`/`TERM=dumb`/`--color` resolution.
  - Four styles.
  - An ASCII fallback when `sys.stderr.encoding` isn't UTF-8.
  - A spinner thread that only runs on a TTY, clears its line on exit, and stops on `KeyboardInterrupt`.
- **On Windows,** rely on VT processing in Windows 10+ terminals, the same assumption Click now makes.\[58\]

### Testing CLI behaviour
1. **Snapshot every rendered output.** Run `main(argv)` in-process with captured stdout/stderr and snapshot both streams, using `inline-snapshot` or `syrupy`. Before comparing, replace durations, absolute paths and versions with placeholders, the way cargo's test suite uses `[..]` and `[ERROR]`.\[14\] Cover success, warnings, each `BundleupError` subclass, and the crash path (inject a fault).
2. **Write an exit-code contract test.** A parametrised table maps each scenario to its expected `ExitCode`, run through a real subprocess (`python -m bundleup`), so interpreter-level behaviour (SIGINT → 130, unhandled exception → 3) is covered.
3. **Cover the output-mode matrix.** For each snapshot, run with `NO_COLOR=1`, `FORCE_COLOR=1`, `TERM=dumb`, a non-TTY (subprocess pipes) and a real TTY (`pty.openpty()` on POSIX). Assert there are no escape codes and no spinner frames whenever colour or animation should be off.
4. **Test the JSON contract.** Validate every `--json` output against the checked-in JSON Schema. A schema-diff test fails if a released field is removed or renamed without a `schema_version` bump. Also check that stdout contains exactly one JSON document even when warnings occur.
5. **Test the startup budget.** A subprocess test runs `python -X importtime -m bundleup --version` and fails if forbidden modules are imported. An optional `hyperfine` job tracks the medians.
6. **Test API stability.** Snapshot `bundleup.__all__` and `inspect.signature` of each public callable.
7. **Test docs drift.** Regenerate the CLI reference from the parser and `git diff --exit-code`.

## Caveats
- **Coverage of this pass:** these tools are covered from primary docs and issue trackers: uv, Ruff, cargo, esbuild, gh, pytest, HTTPie, pip, pypa/build, Typer, Rich, Cyclopts and clig.dev. git is covered only through clig.dev's examples. Bun, Deno and pipx were not examined, so no claims are made about them.
- **Startup timings are third-party and environment-specific.** The 44/56/179/198 ms `--help` figures come from a single third-party benchmark (kevinconka/seascape issue #43), which I saw only as a search snippet. Rich's recent lazy-loading releases may have narrowed the Typer/Cyclopts gap. Re-measure on your own CI before treating the budget numbers as final.
- **Some dependency lists are from secondary sources.** Cyclopts' list comes from secondary package indexes (pypistats/pyoven); verify it against its current `pyproject.toml`. I couldn't confirm which Click release first ships without colorama.
- **The cargo JSON stability statement is a maintainer's forum post,** not formal documentation.\[13\]\[59\]
- **Everything labelled as a rule, example output, preset name or schema is my recommendation,** not existing bundleup behaviour. Reconcile it with your ADR.

## Sources

1. [How to use a uv lockfile for reproducible Python environments](https://pydevtools.com/handbook/how-to/how-to-use-a-uv-lockfile-for-reproducible-python-environments/)
2. [Python uv cheat sheet - A code to remember - Copdips.com](https://copdips.com/2025/08/python-uv-cheat-sheet.html)
3. [Commands](https://docs.astral.sh/uv/reference/cli/)
4. [Versioning](https://docs.astral.sh/uv/reference/policies/versioning/)
5. [PYTHONPATH support for \`uv\` Python Package · Issue #5808 · astral-sh/uv](https://github.com/astral-sh/uv/issues/5808)
6. [ruff 0.0.246](https://pypi.org/project/ruff/0.0.246/)
7. [The Ruff Linter - Astral Docs](https://docs.astral.sh/ruff/linter/)
8. [Support for Python 3.6+ · Issue #3826 · astral-sh/ruff](https://github.com/astral-sh/ruff/issues/3826)
9. [Ruff should give a nonzero exit code if file linting panics · Issue #11107 · astral-sh/ruff](https://github.com/astral-sh/ruff/issues/11107)
10. [Using ruff as a Python library · astral-sh/ruff · Discussion #8539](https://github.com/astral-sh/ruff/discussions/8539)
11. [Proposal: Add basic Python API · Issue #8401 · astral-sh/ruff](https://github.com/astral-sh/ruff/issues/8401)
12. [External Tools - The Cargo Book](https://doc.rust-lang.org/cargo/reference/external-tools.html)
13. [How stable is cargo's message-format=json? - Booleshop](https://amp.mpl.co/t/how-stable-is-cargos-message-format-json/3481631)
14. [cargo/tests/testsuite/message\_format.rs at master · rust-lang/cargo](https://github.com/rust-lang/cargo/blob/master/tests/testsuite/message_format.rs)
15. [Saving a specific \`message-format\` to a file, while also producing "normal" output · Issue #14555 · rust-lang/cargo](https://github.com/rust-lang/cargo/issues/14555)
16. [Provide Cargo messages as JSON messages · Issue #8283 · rust-lang/cargo](https://github.com/rust-lang/cargo/issues/8283)
17. [evanw/esbuild v0.12.26 on GitHub](https://newreleases.io/project/github/evanw/esbuild/release/v0.12.26)
18. [CHANGELOG 2020](https://github.com/evanw/esbuild/blob/8c2fdc2966fb3987394c25398a43494ec650d455/CHANGELOG-2020.md)
19. [--metafile doesn't work with --watch · Issue #1357 · evanw/esbuild](https://github.com/evanw/esbuild/issues/1357)
20. [github.com](https://github.com/nusr/excel/pull/5)
21. [gh formatting help](https://cli.github.com/manual/gh_help_formatting)
22. [GitHub Command Line Interface](https://ull-ocw-github-education.github.io/pages/gh.html)
23. [\`gh attestation\` can fail with HTTP 401 without exiting with exitcode 4 · Issue #9338 · cli/cli](https://github.com/cli/cli/issues/9338)
24. [\`gh search prs\` should allow getting unfiltered \`--json\` when no fields are passed; and should imply \`--json\` with no fields when \`--jq\` is used and \`--json\` isn't explicitly set · Issue #10385 · cli/cli](https://github.com/cli/cli/issues/10385)
25. [Command Line Interface Guidelines](https://clig.dev/)
26. [Exit codes - pytest documentation](https://docs.pytest.org/en/stable/reference/exit-codes.html)
27. [Output options - HTTPie 3.2.4 (latest) docs](https://httpie.io/docs/cli/output-options)
28. [Ubuntu Manpage: httpie - CLI, cURL-like tool for humans](https://manpages.ubuntu.com/manpages/focal/man1/http.1.html)
29. [tessl/pypi-httpie@3.2.x - Registry - Tessl](https://tessl.io/registry/tessl/pypi-httpie/3.2.0/files/docs/models.md)
30. [User Guide - pip documentation v26.2.1](https://pip.pypa.io/en/stable/user_guide/)
31. [pip api](https://pypi.org/p/pip-api)
32. [github.com](https://github.com/pypa/pip/issues/5243)
33. [API Documentation - build 1.4.0](https://build.pypa.io/en/stable/api.html)
34. [1.5.0 (2026-04-30) - build - 1.5.0](https://build.pypa.io/en/stable/changelog.html)
35. [build 1.4.0](https://build.pypa.io/en/stable/index.html)
36. [Locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
37. [uv Locked vs Frozen: Reproducible Python CI](https://codehubjournal.com/uv-locked-vs-frozen-python-ci/)
38. [github.com](https://github.com/arduino/arduino-cli/pull/2470.patch)
39. [What's new in Python 3.14 — Python 3.14.8 documentation](https://docs.python.org/3/whatsnew/3.14.html)
40. [argparse — Parser for command-line options, arguments and subcommands — Python 3.14.8 documentation](https://docs.python.org/3/library/argparse.html)
41. [Environment variables](https://docs.astral.sh/uv/reference/environment/)
42. [github.com](https://github.com/astral-sh/uv/releases/tag/0.5.0)
43. [Evaluate a CLI library for seascape/cli.py · Issue #43 · kevinconka/seascape](https://github.com/kevinconka/seascape/issues/43)
44. [\`soup version\` costs 0.41-0.67s on CI runners, and half of it is importing config/schema.py — but deferring one module will not fix it · Issue #780 · MakazhanAlpamys/Soup](https://github.com/MakazhanAlpamys/Soup/issues/780)
45. [Gregory Szorc's Digital Home](https://gregoryszorc.com/blog/2019/01/10/what-i've-learned-about-optimizing-python/)
46. [Say Goodbye to Slow Python Imports: Python 3.15 Lazy Loading Explained](https://algogene.com/community/post/402)
47. [github.com](https://github.com/bobcallaway/cosign/blob/main/VERSIONING.md)
48. [Release Notes - Typer](https://typer.tiangolo.com/release-notes/)
49. [Install Typer - Typer](https://typer.tiangolo.com/tutorial/install/)
50. [typer 0.26.0 on Python PyPI](https://newreleases.io/project/pypi/typer/release/0.26.0)
51. [cyclopts - Oven](https://pyoven.org/package/cyclopts)
52. [cyclopts](https://pypistats.org/packages/cyclopts)
53. [Lazy Loading — cyclopts - Read the Docs](https://cyclopts.readthedocs.io/en/latest/lazy_loading.html)
54. [build(deps): bump the python-dependencies group across 1 directory with 3 updates by dependabot\[bot\] · Pull Request #1050 · overnightworks/songmaker](https://github.com/overnightworks/songmaker/pull/1050)
55. [feat: speedup import time using sys.platform](https://github.com/Textualize/rich/pull/3399)
56. [chore(deps): bump rich from 14.2.0 to 15.0.0 by dependabot\[bot\] · Pull Request #968 · BrianPugh/cyclopts](https://github.com/BrianPugh/cyclopts/pull/968)
57. [Textualize/rich v14.3.4 on GitHub](https://newreleases.io/project/github/Textualize/rich/release/v14.3.4)
58. [remove colorama (#3505) · pallets/click@6a141c3](https://github.com/pallets/click/commit/6a141c3)
59. [How stable is cargo's message-format=json? - The Rust Programming Language Forum](https://users.rust-lang.org/t/how-stable-is-cargos-message-format-json/15662)
