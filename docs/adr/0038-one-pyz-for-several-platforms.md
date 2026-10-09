# ADR-0038: One `.pyz` can carry a payload per platform and Python version

- **Status:** Accepted (the owner, 2026-10-08)
- **Date:** 2026-10-07
- **Deciders:** the owner (the feature), an agent (the design)
- **Amends:** [ADR-0010](0010-bundle-format-and-loader.md) (one payload per bundle)

## Context

A bundle with compiled dependencies runs on one OS, CPU and Python version. The project's
founding example (a skill script using python-pptx, which needs lxml and Pillow) therefore needed
one file per platform, while pex can build one artifact for several. The third review called this
the most important missing feature.

## Decision

- **`--python` and `--python-platform` repeat** (lists in `[tool.bundleup]`); a `.pyz` gets a
  payload for every combination, e.g. `--python 3.11 --python 3.12 --python-platform linux
  --python-platform macos --python-platform windows` makes up to six.
- Each payload is built exactly as a single bundle is (install, compile, check, verify against
  the lock and RECORD). A combination an earlier **pure-Python payload already serves** (its
  range covers the version, and it runs on any OS, or on this OS with any CPU) isn't built again.
- **Each file is stored once** (changed 2026-10-07, after measuring the founding use case): files
  are grouped by the set of payloads that contain them (same path, contents and executable bit),
  and each group is one `layer-<hash>.zip` member. Pure-Python packages land in a layer every
  payload shares, a stable-ABI (abi3) extension in one per platform. A payload is its list of
  layers, unpacked in order into one directory, named after the layers' hashes.
- The loader gets a `PAYLOADS` table and uses
  the **first payload that fits the machine** (OS, CPU, interpreter build, C library, macOS
  version, then Python version). A payload for this platform but another Python version makes the
  bundle re-run itself with a Python any fitting payload allows (ADR-0036); nothing for this
  platform is one sentence naming every target.
- The manifest lists each layer (hash, size, files) and each payload (its layers, cache
  directory, target, packages); `bundleup verify` checks every layer once, and this machine's
  unpacked copy. A single-payload bundle is
  unchanged (`payload.zip`, the same manifest).
- A Python version that isn't installed is fetched into bundleup's private directory
  (ADR-0035's mechanism), so a multi-version build needs no setup.
- `dir` and `lambda` outputs stay single-target; `check` looks at one target (`--matrix` covers
  the rest).

## Consequences

- The founding example, built on a Mac for macOS, Linux and Windows on Python 3.11 and 3.12: one
  84 MiB file in 7.7 s, running on 3.11 and 3.12 here, and re-running itself under Apple's 3.9.
  CI builds the gauntlet on macOS for three platforms in one bundle and runs it on Linux, Windows
  and macOS.
- Size grows with each payload, but only by what differs. The owner's skill (python-pptx, lxml,
  Pillow, PyMuPDF, xlsxwriter, pywin32) for macOS arm64 and x86_64, Windows and Linux: 144 MiB
  for one Python (157 MiB with whole payloads), 230 MiB for three (469), 314 MiB for five (783).
  PyMuPDF alone is ~22 MB compressed per platform; lxml and Pillow publish one build per Python
  version, so each extra version still adds ~17 MB per platform.
- Tests: `tests/test_multi.py`, `tests/test_bundle.py::test_the_loader_picks_the_payload_that_fits`.
