# Findings 2026-10-10: the seventh independent review, and what was done about it

Run by a fresh subagent with [the review brief](review-brief.md), after `--split`, `--format py`
and `--format exe` (2026-10-09). Condensed, with the working agent's verdict on each point. The
reviewer ran the tests (223), ruff and pyright (clean), built gauntlet 03 as `.pyz`, `.py` and
executables (cross-built too), ran them on Apple's 3.9, 3.12 and 3.13, and checked reproducibility.
Verdict up front: "the core is still good"; the three new outputs "were shipped faster than they
were finished", each with a bug reproducible in minutes; the top documents contradict ADR-0047;
the scope freeze has become "a policy of yes", with a release and a pilot still open.

## Findings and verdicts

| # | Finding | Verdict | Done |
|---|---|---|---|
| 5.1 | An executable is described, smoke-tested and size-checked as its inner `.pyz`: a cross-built Windows `.exe` was run by `--smoke` on macOS (exit 126); the JSON said "any OS, 3.10+"; `large-bundle` measured the `.pyz` and suggested `--split` | Agree, reproduced | Reported as what it carries (its OS and CPU, the one Python, the interpreter's patch version); `--smoke` skips a foreign executable with `smoke-skipped`; the size warning measures the executable, with its own hint. Tested |
| 5.2 | A `.py` piped to Python (`curl ... \| python3 -`): a traceback on a cold cache, and on the wrong Python an exit 0 that did nothing (the re-run got an empty stdin) | Agree, reproduced both | The loader refuses first, in one sentence: save it as a file. Also when there's no `__file__` at all. Tested |
| 5.3 | Range bundles under `PYTHONDONTWRITEBYTECODE` compile on every start off the build's version (85 ms instead of 27 on the founding Mac case) | Agree | Under that variable, on another version, the payload is compiled once for the running interpreter and marked (one stat on the warm path; nothing in a read-only cache). `verify` ignores the mark. Tested |
| 5.4 | The executable's interpreter cache keys on the minor version: the first patch release downloaded is used forever, unchecked; a failed stdlib compile is ignored and cached | Agree | Each build asks uv for the newest patch it can download and uses (or fetches) that one; offline, the newest kept. A failed compile is an error (the stdlib compiles cleanly: checked) |
| 5.5 | `host_platform()` uses bundleup's own CPU, not the target interpreter's; an unguarded `confstr` | Agree | Taken from the target interpreter; `confstr` guarded |
| 5.6 | `BUNDLEUP_CACHE` isn't authoritative: a copy in the user cache wins, defeating the HPC recipe | Agree, reproduced (it hid bug 5.2 here too) | [ADR-0048](../adr/0048-an-explicit-cache-is-the-only-cache.md): when set, it's the only folder. Tested |
| 5.7 | `--split` part sizes are estimated, never checked; ADR-0045 ignores git history growth | Agree | Written parts are checked against the size; the skill recipe says rebuilds accumulate in git (ten rebuilds of 144 MiB pass GitHub's 1 GB recommendation) |
| 5.8 | The `.py` header pins the project as `name==None` | Agree | Name only when there's no version |
| 5.9 | `_parts()` reads each part twice (hash, then unpack) | Disagree | Cold path only; hashing before unpacking is the point (nothing unpacked under the bundle's name from a bad part) |
| 5.10 | `_loader.py` (862 lines, three modes) needs a data-source abstraction before a fourth | Agree, deferred | No fourth mode is planned; split it when one is |
| §4 | Warn on `.py` bundles over ~5 MB | Agree | `slow-start` warning from 10 MB (+18 ms a start), with the estimate; `--strict` fails before writing |
| §4, rec. 8 | Mark `--format exe` experimental until a clean Windows VM run passes (GitHub's runners have Python, the VC++ runtime and Defender exclusions) | Agree | "experimental" in `--help`, the README and the recipe. A clean-VM run needs the owner (no Windows here) |
| rec. 6, §1 | MISSION, vision and README contradict ADR-0047 and don't mention the new outputs | Agree | All three updated: unsigned executables and the `.py` built, signed executables and inlining still not |
| §4 | Byte-reproducibility can regress silently | Agree | CI builds the split skill twice and the macOS executable twice and compares bytes |
| §4, rec. 10 | `--against` is presets as data; its files ship only in a checkout; `network`/`installs` change nothing | Partly | The files are examples to copy (ADR-0044); shipping them by name would bring named targets back (ADR-0039). The owner's call |
| rec. 7, §1 | Release 0.1 and run the pilot before any new input or output; the freeze is "a policy of yes" | Agree on the substance | The owner's call (roadmap 25, 37); raised in the report |
| rec. 9 | 6 of the last 25 CI runs on main were red (Linux/Windows failures from a macOS-only gate) | Agree | No Linux or Docker here; the remedy is CI before merging, which the owner chose against (work on main). Raised |
| §6 | 176k words of docs against 37k of code; ADR per detail | Partly | ADRs are written for public behaviour only; research is background. The owner's call on pruning |

## What it means

The new outputs had the same class of bug: an outer artifact reported, tested or sized as the
`.pyz` inside it. When one output wraps another, every report (target, smoke, size) has to be
about the outer one; the tests now check that for executables.
