# Findings 2026-10-07: the third independent review, and what was done about it

The last of three adversarial passes the owner asked for, by a fresh agent at `f76f973`, with the
same prompt. Condensed, with the working agent's verdict on each point.

## What it found working

Builds of gauntlet 03 in 0.49 s; warm start 20 ms (equal to a venv); one-sentence errors for
Python, OS, CPU and libc mismatches; the lock analysis ("3.10+ on any OS; 3.9 pinned to macOS",
correct once the lock is read); `verify` on bundle and cache; CI running any-OS bundles on other
OSes and Lambda zips in AWS's image ("real evidence"); most earlier fixes adequate.

## Findings and verdicts

| # | Finding (reproduced by the reviewer) | Verdict | Done |
|---|---|---|---|
| 5.1 | A tool installed with the same Python that runs a bundle (Docker with `pip install awscli`) lost its packages when the bundle started it | Agree, high: ADR-0027 keyed on the interpreter alone | Children activate only for bundle code: `-c`, `-m` of a bundled module, a script in the payload ([ADR-0037](../adr/0037-children-activate-only-for-bundle-code.md)) |
| 5.2 | `ast.parse(feature_version=)` accepts PEP 701 f-strings: "3.10+" for code 3.11 can't parse | Agree | The oldest version is checked with a real interpreter, installed into bundleup's own directory if missing ([ADR-0035](../adr/0035-check-older-pythons-syntax-without-their-interpreters.md)); `ast` is the fallback, with a warning |
| 5.3 | `#!/usr/bin/env python3.9` fails on a stock Mac | Agree | Plain `python3` shebang; a wrong Python re-runs the bundle with a matching one on `PATH` ([ADR-0036](../adr/0036-wrong-python-reruns-and-a-platform-matrix.md)) |
| 5.4 | Darwin 25 read as macOS 16 (it's 26) | Agree: wrong on this Mac | Fixed, tested |
| 5.5 | 32-bit Python on 64-bit Windows read as AMD64 | Agree | CPU from the interpreter's build string, tested |
| 5.6 | `cache clean` could remove a copy a long-running program used; tmpfiles can age files out of `/tmp` | Agree with the first | Shared in-use lock, `in_use` in the report. The second is documented: checking every file on every start costs too much |
| 5.7 | Duplicated identity logic, repeated TOML parsing, positional `Prepared(...)`, `FileNotFoundError` escaping, duplicated build/check setup | Agree | All fixed |
| 5.7 | `.bundleup` trust check is POSIX-only; `PYTHONDONTWRITEBYTECODE` makes range bundles recompile on other versions | Real, low | Documented below |
| Rec. 2 | A multi-platform `.pyz` (or fan-out plus dispatcher): the founding case has compiled dependencies | Agree it matters most; it's new scope the same review says to freeze | Deferred as the top roadmap item; `check --matrix` added instead (Rec. 7) |
| Rec. 8 | Freeze formats, presets and nightly automation; ADRs only for public behaviour, reviewed by the owner | Agree | Working rule in CLAUDE.md |
| Rec. 9 | Cache compressed zip members per wheel for faster warm rebuilds | Plausible, unmeasured | Roadmap |
| §1 | vision's before/after promises "just works" for python-pptx, which is compiled | Agree | Vision corrected: one bundle per platform for compiled code; `--matrix` shows where |

## Known limitations, written down

- On Windows, the cache next to a bundle is trusted without an ownership check (ACLs aren't
  checked); use a user-owned directory for bundles on shared Windows drives.
- With `PYTHONDONTWRITEBYTECODE=1`, a pure bundle run on a Python other than the one it was built
  with compiles its modules on every start (about 30 ms more on gauntlet 03).
- A bundle unpacked into `/tmp` (no `HOME`) can be damaged by tmpfiles' age-based cleanup; set
  `BUNDLEUP_CACHE` for long-lived services.
