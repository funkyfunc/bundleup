# Findings 2026-10-07: the second independent review, and what was done about it

After the fixes from the [first review](2026-10-07-independent-review.md) (ADRs 0027-0032), the
owner asked for two more adversarial passes. A fresh agent reviewed the repo read-only at
`5f503d4` with the same prompt (in the first review's findings). Its report, condensed, and the
working agent's verdict on each point.

## What it found working

Warm start about 6 ms over bare `python -c pass`; the pex comparison now fair; one-sentence
errors for wrong Python, platform, libc and macOS; `check --also-platform` precise (0.84 s on
gauntlet 14); the claude-api fix; the child-process design (ADR-0027) "clever and tested"; the
`_build.py` split adequate.

## Findings and verdicts

| # | Finding (reproduced by the reviewer) | Verdict | Done |
|---|---|---|---|
| 1 | A stale `uv.lock` is silently re-locked and rewritten outside CI, contradicting ADR-0028 | Agree | `--locked` by default when a lock exists ([ADR-0033](../adr/0033-a-stale-lock-is-an-error.md)) |
| 2 | The cache next to a bundle (`.bundleup/`) was trusted without an ownership check: a copy planted beside a bundle in `/tmp` printed "HIJACKED" | Agree: a local code-execution path | Trusted only if private, like the temp root; regression test |
| 3 | The runtime set `BUNDLEUP_PYTHON`, also `--python`'s variable: bundleup failed inside any bundled program | Agree | Runtime variables are `BUNDLEUP_RUNTIME_*`; test that none collides |
| 4 | The range check (ADR-0030) passed silently when the oldest Python wasn't installed (the usual CI case); a failure fell back to the target only | Agree | Every version below the target is checked, with its own interpreter or with `ast.parse(feature_version=)`; the range starts at the oldest that passes ([ADR-0035](../adr/0035-check-older-pythons-syntax-without-their-interpreters.md)). A warning (noisy in CI) and installing interpreters (broke a running Python on Windows) were tried and dropped |
| 5 | Pure bundles were tied to one OS: losing to shiv for mixed-OS colleagues | Agree, the most valuable item | Any OS when the lock agrees ([ADR-0034](../adr/0034-pure-python-bundles-run-on-any-os.md)); also fixed CPU markers being ignored |
| 6 | The vision's lead example (python-pptx via `--target claude-api`) is preinstalled in the API sandbox; no Skills size check | Agree | Example fixed (the founding case is a user's machine); claude-api warns over the 30 MB Skills limit (checked in Anthropic's docs) |
| 7 | Support packages a target already provides | Partly: excluding locked packages and trusting the sandbox's versions breaks "the lock decides" | Deferred; the recipe explains when bundleup isn't needed |
| 8 | Three fix commits went to `main` red | Agree | Work now goes on a branch, merged when CI is green |
| 9 | Tests wrote to the developer's cache (57 leftovers) | Agree | `BUNDLEUP_CACHE` points at a temp directory in tests |
| 10 | ADRs 0027-0032 "Accepted" with designs nobody reviewed | Fair | Their Deciders lines now say the owner approved the fixes, not the designs; new ADRs are Proposed |
| 11 | `tomllib` boilerplate in 5 modules; Lambda zip not written atomically; stale help text | Agree | One `_toml` module; temp file + rename; help fixed |
| 12 | CLAUDE.md "Current state" still a changelog (152 lines) | Disagree: it was cut to 27 lines in this session; the reviewer may have counted the whole file | – |
| 13 | `pyproject.toml` at 0.0.1 while the CHANGELOG says 0.1.0 is unreleased | Disagree: the bump is a release step ([releasing.md](../releasing.md)) | – |
| 14 | Docs (10k lines) outweigh code (5k); ADRs for routine fixes | Partly: kept the process (the owner's), but new ADRs only for behaviour changes | – |

## Process note

While working on these fixes the agent ran `git checkout -- .` by mistake and discarded its
uncommitted work; it redid every edit from the record and re-ran the tests. Since then each fix is
committed to the working branch as soon as it passes. See [learnings](../learnings.md).
