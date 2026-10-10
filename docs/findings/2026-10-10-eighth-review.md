# Findings 2026-10-10: the eighth independent review, and what was done about it

Run by a fresh subagent with [the review brief](review-brief.md), on the commit that fixed the
[seventh review](2026-10-10-seventh-review.md)'s findings (07e7618), before its CI had finished.
Condensed, with the working agent's verdict on each point. The reviewer ran the tests (225),
ruff and pyright (clean), built gauntlet 03, 07 and 21 as `.pyz`, `.py` and executables, ran
them on 3.12, 3.13 and Apple's 3.9 with and without `PYTHONDONTWRITEBYTECODE`, simulated a noexec
cache, and planted folders for `bundleup cache`. Verdict up front: the core is still good; the fix
commit brought two regressions of its own; "the reviews are now mostly finding bugs in their own
fixes"; run the pilot and release.

## Findings and verdicts

| # | Finding | Verdict | Done |
|---|---|---|---|
| 5.1 | ADR-0048 (an explicit `BUNDLEUP_CACHE` is the only cache) broke the noexec fallback: the gauntlet's `noexec-cache` condition pointed `BUNDLEUP_CACHE` at a noexec mount and would fail on Linux; `--smoke` on a host with a noexec `/tmp` would fail native builds; the message said "set BUNDLEUP_CACHE" when it was set | Agree; CI confirmed it (all 28 failures on Linux were `noexec-cache`) | ADR-0048 kept. The gauntlet condition now models the real case (noexec temp folder, read-only home: the bundle must fall back to the folder beside it); `--smoke` uses bundleup's build cache when the temp folder is noexec; the message names `BUNDLEUP_CACHE` and noexec when it's set. Tested |
| 5.2 | `_bytecode_for_here` compiled the whole payload up front: 4.7 s instead of 0.9 to use one module of 3,339, on every start where the cache is fresh | Agree | Replaced: at exit, only the payload modules this run imported get bytecode for the running interpreter, at `__spec__.cached` (honours `-O` and `sys.pycache_prefix`); stops at the first failed write. Tested on Apple's 3.9 |
| 5.3 | `cache_roots` compared an absolute path with `_roots("")`'s relative one, so `cache list/clean` acted on `./.bundleup` | Agree, a regression from 07e7618 | Fixed; tested |
| 5.4 | An explicit `BUNDLEUP_CACHE` skips the ownership check the shared roots get | Disagree | Set by the user, on purpose; a group-shared cluster cache is a legitimate choice |
| 5.5 | The outer-artifact class of bug is structural: `build()` derives its result from `Prepared` and patches it for executables | Agree, deferred | Each writer returning its own description is the right refactor; not before another output needs it |
| 5.6 | Executables depend on the installed uv's list of Python patch releases, so two machines can build different files | Agree, kept | The trade the seventh review asked for (security fixes arrive); the result reports the patch version. Raised with the owner |
| §1 | `check --also-platform` says "no problems found" without naming the other platforms; no JSON field | Agree | The summary names them; `also_platforms` in the JSON (schema updated) |
| §4 | A recipe to warm the cache when building an image, now that `BUNDLEUP_CACHE` is authoritative | Agree | Added to the container recipe (untested in CI, says so) |
| §6 | The new bytecode test only checks a marker; nothing tests `cache_roots` against `./.bundleup`; noexec is Linux-only and the agent works on macOS | Agree | Both tests added; the noexec path is CI's (Linux) |
| rec. 6 | Gate pushes on a Linux run | Agree it's needed | The agent can't run Linux here; this commit's breakage was found by CI after the push. The owner's call: a branch with CI before merging, or a Linux machine |
| rec. 7-9 | Pilot, release; demote `--against` and `--audit`; freeze `py` and `exe` | The owner's call | Raised in the report |
| §6 | ADRs "accepted by an agent under a blanket request" | Agree it weakens the status | ADR-0045 to 0048 say "design not yet reviewed by the owner"; the report asks for that review |

## What it means

Two of three regressions came from changing a fallback (the cache order) without listing who
relied on it: the gauntlet, `--smoke` and `bundleup cache` all did. Before changing a fallback,
grep for every caller of it.
