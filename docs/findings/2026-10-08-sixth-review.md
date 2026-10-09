# Findings 2026-10-08: the sixth independent review, and what was done about it

Run by a separate agent the owner started (not by the working agent), after the fifth review's
fixes. Condensed, with the working agent's verdict on each point. The reviewer built gauntlet 03
in 0.18 s and 14 in 0.69 s, ran the bundles on Apple's 3.9 and on 3.12, verified them, and ran
the checks (192 tests, ruff, pyright clean). Verdict up front: "the core works and is fast",
"a good UX layer over uv plus a careful loader", not yet what the docs describe; usable today for
pure-Python internal CLIs and Lambda zips from a uv.lock; not yet for the founding skill (the
100 MB problem) or for colleagues.

## Findings and verdicts

| # | Finding | Verdict | Done |
|---|---|---|---|
| §1 | "24 projects pass in CI": 23 do, `20-heavy-ml` never runs (CI doesn't pass `--heavy`) | Agree, verified | CLAUDE.md says 23 in CI and why |
| §1 | Nightlies "open issues": suites file none; all three green together only on 10-08; CI results aren't committed | Agree, verified | CLAUDE.md says which file issues, that results live in run artifacts, and since when they're green |
| §1 | 15 commits on main cancelled mid-run | Agree | Already fixed earlier the same day (no cancelling on main) |
| §7 | Weekly summary listed as a Monday job (paused since 10-07); gauntlet README's "last run" 10-03; Next up numbered 22-26, 19; MISSION's acquisition claim unverified | Agree, verified | Fixed; the claim now cites its source (round 1 research, news reports) |
| §2 | `verify` checks against a manifest in the same zip: corruption, not tampering | Agree | README says "corruption; not a signature". ADR-0019 is accepted, so its wording stays, read with this |
| §2 | "The most defensible part" oversells a ~440-line check | Agree | Roadmap reworded |
| 5.3 | Pruning unlinks the lock file a starting process may have just opened | Agree (rare) | The lock file stays; `cache clean` removes stale ones |
| 5.4 | Hand-maintained stdlib tables stop at 3.14; `NOT_RUN` skips every `src/` | Agree | A test fails on a Python newer than the tables; the scan skips the project's own packages at any depth instead of `src` |
| 5 (rec. 5) | `large-bundle` changes behaviour by where the output lands | Agree | Fires wherever the bundle is written (reverting the fourth review's suggestion: a predictable rule beats a clever one) |
| 5.1 | A plain build can download an interpreter (ADR-0035, Proposed) | Partly | It respects `UV_PYTHON_DOWNLOADS=never` and offline mode, like uv's own default; whether it should be opt-in is the owner's call: roadmap 29 |
| 5.2 | Children are handled by PYTHONPATH and sitecustomize injection with a heuristic; compare with a venv in the cache | Agree it deserves a decision | Roadmap 28 (the owner's call, then one ADR) rather than more patches |
| 5.2 | The isolation keeps the user's own `PYTHONPATH`, which can shadow bundled packages | Partly | That's how a venv behaves too (PYTHONPATH comes first); documented behaviour, kept |
| 5.3 | The wrong-Python path probes unversioned `python3`/`python` and runs a different interpreter silently | Disagree for now | The fifth review reproduced the founding case failing on a typical Mac without it; ADR-0036 (Proposed) is where the owner decides |
| §4, rec. 4-5 | Pull ADR-0041 back (no folder apps, setup.py, loose requirements); remove `looks_secret` | Disagree | The owner asked for these inputs on 2026-10-08; `looks_secret` is a narrow warning, matching whole words, under `.gitignore`. Raised with the owner |
| rec. 8 | `--smoke`: run the finished bundle once in a fresh HOME without network | Agree it's the missing check | Roadmap 27, Proposed (it runs the author's program, so opt-in) |
| rec. 10 | Run tests plus three gauntlet OSes per push, the full matrix nightly | Plausible | The owner's call: roadmap 30 |
| rec. 1, 7, 9 | Release 0.1 and get users; freeze new ADRs until the Proposed ones are reviewed, archive `docs/research/`; decide the skill size shape first | Agree on users and the size shape (roadmap 22, 25); the rest is the owner's | Raised with the owner |
| §6 | The macOS CI image is assumed to keep `/usr/bin/python3` at 3.9; help snapshots run on 3.12 only; the smoke test follows the live top-200 | Noted | Real but cheap to notice when they break; not changed |
| §5 | 1.4 GB in the owner's cache after five days | Noted | Development builds; `bundleup cache clean` |
