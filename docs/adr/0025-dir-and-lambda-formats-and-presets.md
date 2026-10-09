# ADR-0025: How `--format dir`, `--format lambda` and target presets work

- **Status:** Accepted (the owner, 2026-10-08); the presets part superseded by [ADR-0039](0039-recipes-instead-of-target-presets.md)
- **Date:** 2026-10-06
- **Deciders:** an agent, while the user was away (roadmap item 11); needs the user's confirmation

## Context

[ADR-0014](0014-output-formats-and-target-presets.md) (accepted) chose the shape: `.pyz` stays
the default, a `dir` output and a Lambda output are added, format and target are separate axes,
and presets expand to ordinary flags and print the expansion. This ADR records the details
decided while building it.

## Decision

- **`--format pyz|dir|lambda`**, all written from the same installed, compiled, checked and
  verified file set (lockfile and RECORD checks included):
  - `dir`: the payload as a plain directory (default `dist/<name>/`) plus
    `bundleup-manifest.json`, for hosts that put a directory on `sys.path`. It replaces an
    earlier bundleup output atomically and refuses to replace any other non-empty directory.
  - `lambda`: an AWS Lambda function `.zip` (default `dist/<name>-lambda.zip`): packages and the
    project at the top, bytecode precompiled for the runtime (Lambda's `/var/task` is
    read-only), `bundleup-manifest.json` alongside. Errors when the function would exceed
    Lambda's 250 MB unzipped limit (`lambda-too-big`, before writing); warns over 50 MB zipped
    (`lambda-upload-size`: upload through S3).
  - In both, a PEP 723 script goes at the top as a module (`fn.py`, handler `fn.handler`), and
    `--entry` is optional: the host decides what runs. A console script is never taken as the
    entry (it's a CLI, not a handler), so the printed Lambda handler is only the one passed with
    `--entry module:function` (changed 2026-10-07 after the review).
  - Bytecode in both is **checked-hash**: someone may edit the files in place (Lambda's console
    editor, a plugin folder), and Python then ignores a stale `.pyc` (a `.pyz` keeps
    unchecked-hash: its files never change). `--strict` checks the Lambda upload size before
    writing, so an earlier zip stays untouched. Both warn (`pth-not-run`) when the payload
    has `.pth` files, which only bundleup's loader runs.
- **Presets (`--target NAME`, `bundleup targets`, `bundleup.list_targets()`):**
  - `lambda` / `lambda-arm64`: `--format lambda --python 3.13`, platform from the Python
    version: `manylinux_2_34` for 3.12+ (Amazon Linux 2023), `manylinux_2_17` for 3.10-3.11
    (Amazon Linux 2, glibc 2.26; uv has no `manylinux_2_26`). A Python Lambda doesn't run
    (e.g. 3.9) is a usage error. 3.13 rather than 3.14: same support window (June 2029), wider
    wheel coverage. ([AWS's runtime table](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html),
    checked 2026-10-06.)
  - `claude-api`: `--format pyz --python 3.11 --python-platform x86_64-manylinux_2_28`, from
    Anthropic's code execution docs (Python 3.11, Linux x86_64, no network). The sandbox's glibc
    isn't documented. (First set to the more cautious `manylinux_2_17`, which broke gauntlet 14:
    Pillow 12 publishes only 2_27/2_28 wheels. Changed 2026-10-07 after the
    [independent review](../findings/2026-10-07-independent-review.md); CI now builds gauntlet
    14 with every preset.) This is the first feature of
    [ADR-0013](0013-agent-sandboxes-as-headline-use-case.md), whose features are still Proposed.
  - Explicit flags win over a preset's values; the expansion is printed to stderr
    (`Using target lambda: --format lambda --python 3.13 --python-platform …`) and `BUNDLEUP_TARGET`
    sets a default.
- **Tests:** `gauntlet/formats.py` runs every project as a `dir` (only `PYTHONPATH`) on Linux,
  Windows and macOS, and as a Lambda zip inside AWS's own image (`public.ecr.aws/lambda/python`)
  through its runtime interface emulator on x86_64 and arm64 (CI job `formats`).

## Consequences

- Lambda users get a zip that runs as is, without hand-rolled `pip install --target --platform`.
- Without the loader, `dir` and Lambda outputs don't isolate from the host's packages, don't run
  `.pth` files (gauntlet 23; the check warns), and don't set up child processes. In CI on
  2026-10-06 every other gauntlet project passed in AWS's Lambda image on x86_64 and arm64,
  including 19 (a child `python -c` finds the packages through the working directory,
  `/var/task`) and 16 (multiprocessing). The emulator has `/dev/shm`; real Lambda doesn't, so
  `multiprocessing.Pool` and `Queue` still fail there (an AWS limitation, untested here).
- Not done: Lambda layers (`python/` prefix), `verify` for `dir`/Lambda outputs, a `splunk`
  preset. Each is small once someone needs it.

## Alternatives considered

- **Lambda zip as a `.pyz` inside a zip:** Lambda already unzips; the loader would extract again
  on every cold start ([round 4](../research/round-4-synthesis.md)).
- **Default to the newest Lambda Python (3.14):** fewer wheels today for the same support window.
- **Download missing Pythons automatically for presets:** the build compiles bytecode with a
  local interpreter of the target version; the error says `uv python install 3.13`. Automatic
  downloads would be a behaviour change for every build, left for a separate decision.
