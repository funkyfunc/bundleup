# Twelfth review: using it as a user would — 2026-10-22

The owner asked for a hands-on review: use bundleup a lot, become an expert, say what to change
or fix. Unlike reviews one to eleven, which mostly read code, this one **used the released
`bundleup 0.2.1` from PyPI** (`uvx --from bundleup==0.2.1`) on new projects: a PEP 723 script, a
`uv init --package` CLI, a requirements folder, a uv workspace, the founding skill. It also
looked at the uncommitted ADR-0052 work in the working tree. One agent did the hands-on runs;
three helper agents hammered the runtime, the outputs, and the uncommitted diff. Every **High**
item below was reproduced at least twice. Line numbers are for commit `04c6ee2`, whose code is
0.2.1's.

## Verdict

The engine is good, and the speed and error-message claims hold up. Builds take 1–2 s and warm
rebuilds about 1 s, against 8–10 s for a warm default pex. Warm starts take 17–90 ms, about the
same as a venv; pex takes 530 ms or more. Repeated builds are byte-identical. `check -v` is
excellent. The library API is clean. The local gauntlet passed 409 of 410 runs (the other was the
expected refusal), and the committed tests passed (251).

What breaks is the **contract a bundle states about itself**: which Pythons it runs on, and that
starting it works. Those failures sit on ordinary paths that code reading missed:

- downloading a Python;
- a backport dependency behind a marker;
- deleting a cached copy;
- building with macOS's own Python.

The **founding use case doesn't work with default settings in 0.2.1.** A fresh `uv init` skill gets
`requires-python = ">=3.13"`, and almost every real dependency set includes compiled code
(`requests` → `charset-normalizer`, `pyyaml`, `pydantic`). So the default bundle runs only on the
build machine's Python. Apple's 3.9 refuses it, and nothing at build time says so. The recipe as
written (`--python 3.12`) fails immediately on a fresh `uv init` project. On a machine without
3.12 it hangs for 5 minutes (bug 1).

I'd use bundleup today for internal CLIs where the Python version is known, Lambda zips, Docker,
and pinned-Python sandboxes (the Claude API). I wouldn't yet hand a bundle to arbitrary Mac users,
which is the founding case.

## Bugs in the released 0.2.1, worst first

| # | Severity | What happens | Where | Checked by |
|---|---|---|---|---|
| 1 | High | Any build that has to download a Python hangs until uv gives up waiting (~300 s), then fails with "couldn't find Python 3.X" (see below) | `_python.py:357-404` | me (lock test), helper |
| 2 | High | A script with `tomli; python_version < '3.11'` (or another backport behind a marker) claims "Python 3.10+" and crashes on 3.10 with `ModuleNotFoundError: tomli`. Same with or without a lock, in 0.2.1 and the working tree (see below) | `_payload.py:882` | me |
| 3 | High | Start-up hangs silently for 120 s if a cached copy is deleted while another instance runs (see below) | `_loader.py:797-836`, `:1249` | me (15 s+), helper (120 s) |
| 4 | High | `cache clean` running alongside starts crashes about 5% of them (`ModuleNotFoundError` partway through imports). A fix was tried and passed 300/300 (see below) | `_loader.py:1279-1284`, `:857-858` | helper |
| 5 | Med-High | If the `.pyz` is replaced while a start waits on bug 3, the new bundle's payload is unpacked under the old bundle's hash and is used from then on; only `verify` notices | `_loader.py:714` | helper |
| 6 | Medium | Builds with macOS's own Python (`--python 3.9`) ship **0** `.pyc` files (259 with 3.13). The bytecode goes to `~/Library/Caches/com.apple.python` and stays there, because Apple's Python sets a `pycache_prefix` unless `-E`/`-I` is passed. Fix: add `-X pycache_prefix=` (checked: it gives `None`) | `_bytecode.py:232` | me |
| 7 | Medium | An active virtualenv (`VIRTUAL_ENV`) decides the build's Python. A locked script then fails with uv's raw "incompatible with pylock's requires-python" or "lock is out of date"; re-locking doesn't help | `_uv.py` export/install calls | me |
| 8 | Medium | macOS cross-targets assume macOS 13.0. A wheel needing 14.0 (onnxruntime, now pulled in by PyMuPDF 2.0) is "missing" for `--python-platform macos` on the very Mac that builds it, and no hint mentions `MACOSX_DEPLOYMENT_TARGET` | `_platforms.py:209-229`, `_coverage.py:153-206` | helper |
| 9 | Medium | `-o` into a read-only folder ends with "bundleup crashed … this is a bug", exit 3 | output writer | me |
| 10 | Medium | A first run interrupted by Ctrl-C or a kill leaves a `.tmp-*` folder (170 MB in a test). The loader's `_prune` never removes them, and `cache list` doesn't show them | `_loader.py:576-626`, `:875-885` | helper |
| 11 | Low-Med | Cross-building a native package that has only a source release fails with "a package has no wheel", without naming the package. The hint (`check --python-platform`) fails the same way, and `check --matrix` shows it as ok | `_uv.py` install, `_coverage.py` | helper |
| 12 | Low | Ctrl-C exits 1, not 130, on 3.9–3.12 when the bundle compiles at exit (a CPython `atexit` bug); `BUNDLEUP_CACHE=~/x` or a relative path makes a cache in the working directory; `-m missing_module` prints a 15-line loader traceback; user tracebacks start with 2–6 loader frames | `_loader.py:914-919`, `:452-454`, `:1085` | helper |

**Bug 1, the download hang.** `_install_lock` locks `<pythons_dir>/.lock`, then runs
`uv python install` with `UV_PYTHON_INSTALL_DIR=<pythons_dir>`, and uv locks that same file. So
the child waits on its parent until uv's timeout. Checked directly: with the lock held, uv was
still waiting after 25 s; without it, the install took 3.4 s. This breaks ADR-0035 and every
recipe that uses `--python 3.X` on a machine that lacks that version. Fix: lock a different file
name.

**Bug 2, backports behind a marker.** The range check never reads the exported lock's top-level
`requires-python`. `uv lock --script` stamps that as `>=<the build machine's Python>`, so the lock
holds no `tomli` at all. Fix: add the lock's `requires-python` to `texts`.

**Bug 3, the silent hang.** Every running copy holds a shared lock on `.lock-<DIRNAME>`, and the
unpack step waits for an exclusive lock on the same file. The loader can't tell "running" from
"unpacking". `verify`'s own hint ("delete the folder; it unpacks again") triggers it. Fix: a
separate unpack lock.

**Bug 4, `cache clean` races.** The main block ignores the result of the last `_hold()`, and
`_extract` returns an existing folder without a lock. The fix that was tried, `while not _hold(...):
_site = _extract()`, passed 300 of 300 runs.

The gauntlet missed 1, 2, 3 and 6 because CI preinstalls every Python, no gauntlet script has a
backport behind a marker, no condition deletes a cached copy while the bundle runs, and the 3.9
runs check behaviour, not whether `.pyc` files exist.

### Fixed (2026-10-22, on the owner's go-ahead)

Every fix has a test that fails without it and passes with it (checked by reverting each). The
first commit holds bugs 1, 3 and 4; the second the rest, with the ADR-0052 work.

| Bug | Fix | Test |
|---|---|---|
| 1 | `_install_lock` locks `<folder>.lock` beside uv's install folder. A real download took 6 s | `test_inputs.py::test_downloading_a_python_leaves_uvs_own_lock_free` |
| 2 | `_verify.lock_requires_python()` bounds every range (`python_range`, forks, merges, `check`). Unlocked scripts and requirements that name no `requires-python` are resolved from 3.9, falling back to the target's version if nothing resolves that low | `test_portability.py::test_the_range_stays_within_the_pythons_the_lock_was_resolved_for`, `test_inputs.py::test_an_unlocked_script_that_names_no_python_is_resolved_for_every_one` |
| 3 | The loader's unpack lock is its own `.unpack-<DIRNAME>` file; `cache clean` removes stale ones no unpack holds | `test_cache.py::test_a_copy_deleted_while_in_use_unpacks_again_at_once` |
| 4 | `_extract_and_hold()` retries until the copy is held, up to `LOCK_TIMEOUT`. Race script: 80/300 crashes before, 0/300 after | `test_cache.py::test_a_start_waits_while_clean_removes_its_copy` |
| 5 | The loader carries each member's CRC-32 and refuses a file that no longer matches ("was replaced ... Run it again") | `test_bundle.py::test_a_bundle_replaced_while_it_starts_is_not_unpacked_under_its_name` |
| 6 | `-X pycache_prefix=` when compiling a payload (and an executable's stdlib) | `test_bundle.py::test_a_bundle_built_with_macos_own_python_carries_its_bytecode` |
| 7 | A locked script that names no `requires-python` is built with the Python its lock was made for, and `uv export` gets that interpreter | `test_inputs.py::test_a_locked_script_that_names_no_python_is_built_with_the_one_it_was_locked_for` |
| 8 | A newer `MACOSX_DEPLOYMENT_TARGET` that covers the gap is suggested | `test_coverage.py::test_a_wheel_for_a_newer_macos_names_the_setting_that_reaches_it` |
| 9 | The output folder is test-written before zipping: a plain error | `test_inputs.py::test_an_output_folder_that_cant_be_written_is_a_plain_error` |
| 10 | Ctrl-C during the first unpack removes it and exits 130; the next unpack removes `.tmp-` folders of dead processes | `test_bundle.py::test_an_unpack_abandoned_by_a_killed_run_is_removed` |
| 11 | The package is named from uv's message; the hint no longer points at `check` | `test_coverage.py::test_a_package_built_from_source_for_another_platform_is_named` |
| 12 | Ctrl-C exits 130 (imports before the atexit handler); `~` in `BUNDLEUP_CACHE`; `-m missing` is one line | `test_bundle.py::test_ctrl_c_exits_as_an_interrupted_python_does`, `..._a_tilde_in_bundleup_cache_means_home`, `..._a_missing_module_is_one_line_as_python_says_it` |

Also fixed: the build says when `requires-python` is what limits the bundle (the narrow-range
gap below); syntax errors point at their column and the hint leads with "fix it"; `-e .` in a
folder app's requirements.txt is explained; `--python` below 3.9 says why.

**Left as they are:** user tracebacks still start with loader frames; a relative `BUNDLEUP_CACHE`
still means the working directory; `check --matrix` can show a package as covered when only old
Pythons' wheels exist; the other gaps in the next section.

## UX and product gaps (not bugs, but they decide whether the founding case works)

- **Nothing says why a bundle's range is narrow.** "Python 3.13 on macOS arm64" doesn't say it's
  because of `requires-python` (stamped by `uv init`) or which compiled package forced it. A
  one-line note with the fix ("lower requires-python and re-lock to reach macOS's 3.9", or
  "`--python 3.9`") would prevent the most common failure in the founding case. The
  `--python 3.9` error hint only suggests `--python 3.13`, never lowering `requires-python`.
- **An unguarded top-level import in your own code that nothing provides is only a warning,** and
  the bundle then crashes on every run. For the project's own entry code, consider making it an
  error unless `--external` covers it.
- **With several `[project.scripts]`, the first is picked silently.** The summary should name
  the entry it chose.
- **The recipe's numbers are stale.** PyMuPDF 2.0 now pulls in onnxruntime, numpy and networkx:
  the skill is 329 MiB for four platforms on one Python, against the 144 MiB in the recipe.
- **The JSON schemas are too loose to catch much.** `payloads[]` items are just `object`, and
  check, verify and cache never use `additionalProperties`.
- **Warm rebuilds aren't "instant"** (`docs/vision.md`): the 119 MiB skill rezips for 4 s even when
  the output is byte-identical.

## The uncommitted ADR-0052 work

Merging per-version extension binaries works mechanically. numpy, lxml, Pillow, pydantic,
greenlet, cryptography and charset-normalizer bundles ran on 3.9–3.13, picked the right package
version for each Python, and `verify` passed. Warm start is unchanged. A pydantic CLI that 0.2.1
locks to 3.13 runs on 3.9–3.13 with the WIP.

**Don't commit it as it stands.** It bundles four policy changes, and three of them produce
bundles that claim a Python they crash on:

1. **Fork payloads skip every code check.** `_build.py:1179-1200` returns early for `fork_of`,
   so code with `match` gets a "3.9" payload and raises `SyntaxError` there.
2. **An explicit `requires-python` is silently overridden on virtual projects.** `_source.py:45`
   and `_payload.py:899` turn `>=3.13` into `>=3.10`; code calling `itertools.batched` then fails
   on 3.10 and 3.11. The ADR's "AST/stdlib checks still enforce real bounds" doesn't hold for
   attribute-level APIs.
3. **`_widen_virtual_pylock` ships versions the user never locked** (`_uv.py:567-688`): numpy
   2.2.6 and 2.4.6, when the lock has only 2.5.4. In one run it shipped 2.5.3 on the main Python
   and saved that in the export cache. It can need the network. This contradicts ADR-0004 and
   ADR-0033.
4. **A missing interpreter falls back to the build machine's Python** (`_python.py:166-197`). One
   result was labelled "Python 3.14" with no `.pyc` files; `cache_tag` is set to the requested
   version, which hides it from the guards.

5. **It breaks a gauntlet project that 0.2.1 passes.** `11-native-abi3` with
   `--python /usr/bin/python3` fails: "cryptography==50.0.2 is locked, 47.0.0 is bundled".
   `_uv.py:1080` now adds `--python-version 3.9` to every `uv pip install`, and uv reads that as
   3.9.0. The lock forks at `python_full_version <= '3.9'`, so the install picks the 3.9.0 package
   while the check uses the real 3.9.6. It fails the same way with this review's fixes reverted.
   **Fixed (uncommitted):** the install passes `target.full_version`. Test:
   `test_pylock.py::test_a_lock_forked_on_the_full_python_version_installs_this_versions_side`,
   which fails on the old line with gauntlet 11's error. Gauntlet 11 now builds, runs and verifies
   on `/usr/bin/python3`. The binary merge's own `--python-version 3.X` is unchanged: those
   payloads are for other minor versions. The local gauntlet on the fixed tree passes 417 of 418
   runs; the remaining one is 17's expected refusal on 3.9.

**All five are fixed** (2026-10-22): see the table above and ADR-0052's amended text. Fork
payloads run `_check.fork_range` (syntax for that version, standard library); `requires-python`
is used as written, with a note when it limits the bundle; the re-lock is gone; a missing
interpreter is an error; binaries merge only for `.pyz`/`.py`, and only version-tagged files.
Tests: `test_check.py::test_a_payload_for_other_pythons_claims_only_those_its_code_runs_on`,
`test_pylock.py::test_a_payload_for_older_pythons_is_built_only_where_the_code_runs`,
`test_multi.py::test_merging_another_versions_wheel_takes_only_its_own_extensions`,
`test_formats.py::test_only_a_bundle_with_a_loader_carries_extensions_for_several_pythons`.

**Cost.** Bundles get 3–4× bigger (5 → 15 MiB for a pydantic CLI; 18 → 75 MiB for numpy + lxml)
and cold builds about 10× slower. Merging also happens for `--format zip`/`dir`, whose host runs
one Python.

**Suggested split:**

1. Land the binary merge, for `.pyz` and `.py` only, with the syntax and stdlib checks run for
   each fork's Python.
2. Fix bug 2 above.
3. Replace the relaxation, the re-lock and the interpreter fallback with loud warnings and the
   exact fix.
4. Add an end-to-end test that builds a native project and runs it on every installed Python.
   All the WIP's tests are unit-level, which is why these passed.

The ADR-0052 text also overstates: it says a zero-flag build runs on "3.9/3.10–3.14 out of the
box". CLAUDE.md's "Current state" already lists `--python-platform all` and ADR-0052 as working,
though they're uncommitted and 0.2.1 rejects `all`.

## Code, tests and process

- **Size.** 12.7k lines of source, 7.4k of tests and 13.5k of docs, in under three weeks. The
  longest functions are 150–170 lines (`_config.apply`, `_build.build`, `_build._prepare`,
  `_uv.export`, `_outputs.write_pyz`). That's readable enough. Today's bugs are in core
  plumbing, not in the formats, so the formats aren't the risk; the core contract is.
- **About 2,800 of `tests/test_config.py`'s 3,393 lines are mega-tests named after review passes**:
  `test_phase4_deep_reasoning_audit_regressions` is 553 lines, `test_systems_correctness_audit_regressions`
  525. They're in the wrong file, the first failing assertion hides the rest, the name says
  nothing about the behaviour, and many monkeypatch private functions. Split them into
  behaviour-named tests next to the code they cover.
- **Eleven code-reading reviews mostly found edge cases; using it found the main-path bugs.**
  Today's important bugs came from ordinary use, and ADR-0052 itself came from the first real
  skill build (playwright). Roadmap item 25, a pilot with colleagues, is worth more than a
  thirteenth review.

## Recommendations, by impact

1. **Fix the download hang** (bug 1): one file name, and it unblocks every `--python 3.X` recipe.
2. **Make every claimed Python true.** Include the lock's `requires-python` in the range (bug 2).
   Add a gauntlet project with marker-gated backports in a script with no `requires-python`. Run
   each bundle on every installed Python in its claimed range.
3. **Fix the loader's locking** (bugs 3–5): a separate unpack lock, honour `_hold()`'s result,
   and check the payload's identity before unpacking.
4. **Split the ADR-0052 work as above** before committing it; keep the binary merge, drop the
   silent overrides.
5. **Explain a narrow range at build time**, naming the cause (`requires-python` or a compiled
   package) and the fix. It's the founding case's first failure.
6. **`-X pycache_prefix=` when compiling** (bug 6), and run build-side uv commands without the
   caller's `VIRTUAL_ENV` (bug 7).
7. **Turn the crash on a read-only `-o` into a plain error** (bug 9), and have the loader remove
   stale `.tmp-*` folders (bug 10).
8. **Run the pilot (roadmap 25) before the next review pass.**
9. **Restructure `tests/test_config.py`,** and add multi-Python end-to-end tests.
10. **Keep formats frozen;** spend effort on the range contract and the founding recipe, and
    update the recipe's sizes for PyMuPDF 2.0.

The lessons are in [learnings](../learnings.md) under 2026-10-22.
