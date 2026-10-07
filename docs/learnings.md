# Learnings

Short, dated lessons: facts we discovered, surprises, gotchas. Newest first. Each entry links to
its evidence. If a lesson changes a decision, also write an ADR (see
[ADR-0001](adr/0001-record-decisions-and-learnings.md)).

Format: `- **YYYY-MM-DD** · <area> · <lesson>. Evidence: <link>.`

- **2026-10-07** · process · `git checkout -- .` discards every uncommitted change in the tree,
  with no undo (a stash only helps if made first). An agent ran it while tidying and lost an hour
  of fixes, redone from its own record. Commit to a working branch as soon as a fix passes, and
  merge to `main` only when CI is green (the second review also found red commits on `main`).
  Evidence: [second review](findings/2026-10-07-second-review.md).
- **2026-10-07** · security · A cache directory next to a bundle must get the same ownership check
  as a shared temp directory: a bundle in `/tmp` or on a team drive otherwise runs a copy another
  user planted beside it. Internal environment variables need their own prefix: the runtime's
  `BUNDLEUP_PYTHON` doubled as `--python`'s default and broke bundleup inside bundles. Evidence:
  [second review](findings/2026-10-07-second-review.md).
- **2026-10-07** · benchmarks · Against pex's fastest path (`--venv-repository` from a uv-synced
  venv, `--venv prepend`), bundleup's build lead shrinks to 1.1-2.4× (uv does most of the work for
  both); its start-up lead stays (warm = venv, first run 2.3-15× faster). pex can't subset uv's
  `pylock.toml` (no dependency metadata) and refuses `--python` with some `--venv-repository`
  venvs. Evidence: [findings](findings/2026-10-07-speed-vs-pex-best.md).
- **2026-10-07** · platforms · uv's platform names map to wheel levels (`uv help pip install`):
  `x86_64-unknown-linux-gnu` is `manylinux_2_28`, macOS targets 13.0 unless
  `MACOSX_DEPLOYMENT_TARGET` says otherwise; uv offers manylinux 2_17, 2_28 and 2_31-2_40 only.
  `packaging.tags.cpython_tags`/`compatible_tags`/`mac_platforms` give the exact tag set for a
  target, so wheel coverage can be decided from a pylock's wheel filenames. Evidence:
  [ADR-0031](adr/0031-wheel-coverage-from-the-lock.md).
- **2026-10-07** · runtime · uv's universal lock forks per Python version (gauntlet 03 gets other
  package versions on 3.9; Django 4.2 vs 5 in gauntlet 21), so "does a pure bundle run on 3.X?"
  is answered by evaluating the pylock markers for 3.X and comparing the selection, plus every
  package's `Requires-Python`. A bundle's unchecked-hash `.pyc` files for one version sit next to
  ones other versions compile on first import; nothing conflicts. Evidence:
  [ADR-0030](adr/0030-pure-python-bundles-run-on-a-range.md).
- **2026-10-07** · runtime · A `sitecustomize.py` reached through `PYTHONPATH` runs in every
  Python a program starts, so it can decide per interpreter: compare `sys.prefix`, version and ABI
  flags with the parent's and only then activate the bundle, then import the `sitecustomize` it
  shadows (`importlib.machinery.PathFinder.find_spec` on the rest of `sys.path`). The old
  `PYTHONPATH`-to-the-payload approach made unrelated Pythons import the bundle's packages.
  Evidence: [ADR-0027](adr/0027-children-see-the-bundle-only-from-its-own-python.md).
- **2026-10-07** · ecosystem · Some wheels built on Windows write `RECORD` paths with backslashes
  (ormsgpack 1.12.2); pip and uv install them, so a strict checker must normalise `\\` to `/`.
  Found by the first scheduled smoke run (langchain on Windows). `uv export` on a project without
  `uv.lock` writes one; `uv export --script` never writes a script lock. Pillow 12 publishes no
  wheels below `manylinux_2_27`, so a `manylinux_2_17` target can't use it. Evidence:
  [review findings](findings/2026-10-07-independent-review.md).
- **2026-10-07** · process · An independent, adversarial review found real bugs the gauntlet and
  CI missed (a leak into other Pythons, a broken preset, a silently written lockfile) and docs
  that oversold the code. Worth repeating before releases; the prompt is in the findings.
  Evidence: [review findings](findings/2026-10-07-independent-review.md).
- **2026-10-06** · testing · A real test suite can run *from* a bundle: make a throwaway project
  depending on the package, pytest and the test deps, bundle it with `--entry pytest:console_main`,
  and run it from a clone with a `src/` layout (so the clone can't shadow the package) and
  `--import-mode=importlib`. Read pytest's summary line by pattern: other output can follow it.
  Lambda's runtime interface emulator image runs locally in Docker, so Lambda zips can be tested
  in CI; there a `python -c` child finds the function's packages via the working directory
  (`/var/task`). Evidence: [findings](findings/2026-10-06-formats-checks-and-suites.md).
- **2026-10-06** · ecosystem · uv 0.12 installs a `pylock.toml` directly, without a preview
  flag, but refuses it alongside other requirements ("Cannot specify additional requirements
  alongside a `pylock.toml` file") and rejects one with no `packages` array. `pip lock`'s output
  lists the project itself as a directory entry, and bundles fine. Evidence:
  [ADR-0026](adr/0026-pylock-toml-input.md).
- **2026-10-06** · platforms · AWS Lambda runs Python 3.10/3.11 on Amazon Linux 2 (glibc 2.26)
  and 3.12+ on Amazon Linux 2023 (glibc 2.34); both CPUs everywhere; 3.15 in preview. uv's
  `--python-platform` has no `manylinux_2_26`, so AL2 targets use `manylinux_2_17`. Anthropic's
  code execution sandbox is Python 3.11 on Linux x86_64 with no network; its glibc isn't
  documented. Evidence: [ADR-0025](adr/0025-dir-and-lambda-formats-and-presets.md).
- **2026-10-05** · build · `compileall` with `quiet=2` skips files that don't compile without a
  word, so a bundle built for 3.9 from code with a `match` statement built fine and crashed on
  import. The build now treats "a `.py` with no `.pyc` after compiling" as a candidate and asks
  the target interpreter why (`bundleup check`, ADR-0024). Across gauntlet 03, 10, 13-15 and 20-23
  on 3.9 and 3.12 (torch, sympy, Django, boto3) no dependency file failed, so the check is quiet
  in practice. Evidence: [ADR-0024](adr/0024-check-command-and-build-analysis.md).
- **2026-10-05** · runtime · Python runs `.pth` files only in site directories, never in
  `PYTHONPATH` or `sys.path.insert` entries, so a bundler must process them itself. Without that,
  setuptools' distutils shim and pywin32's directories are missing. pex, shiv and a plain zipapp
  all fail; some old namespace-package `.pth` lines read `sitedir` from their caller's frame, so
  the loader's function keeps that name. Evidence: gauntlet
  [23-pth-files](../gauntlet/projects/23-pth-files/gauntlet.toml),
  [ADR-0023](adr/0023-payload-behaves-like-site-packages.md).
- **2026-10-05** · runtime · Some wheels are mostly a program: ruff's (and uv's, ninja's, cmake's)
  binary is a wheel *script*, installed to `bin/` (`Scripts/` on Windows), and the Python wrapper
  finds it next to the packages when installed with `--target`. bundleup dropped all of `bin/` as
  console-script launchers, so `find_ruff_bin()` failed; now only each distribution's own
  entry-point launchers are dropped. pex and zipapps fail the same way; shiv passes. Evidence:
  gauntlet [22-wheel-executables](../gauntlet/projects/22-wheel-executables/gauntlet.toml).
- **2026-10-05** · tooling · This repo's Actions token can't open pull requests: the repo setting
  "Allow GitHub Actions to create and approve pull requests" is off
  (`gh api repos/funkyfunc/bundleup/actions/permissions/workflow` shows
  `can_approve_pull_request_reviews: false`). The weekly summary job pushes a branch and falls back
  to an issue with a "open a pull request" link. Evidence: [weekly.yml](../.github/workflows/weekly.yml).
- **2026-10-05** · runtime · A PEP 420 namespace package (directories without `__init__.py`) loses to
  a *regular* package of the same name anywhere later on `sys.path`: Python keeps scanning after
  a namespace portion and takes the first regular package. So with `BUNDLEUP_INHERIT_PATH=1` a stale
  `pip install --user` copy can shadow a bundle's namespace package despite the bundle coming
  first; the default isolation (ADR-0021) prevents it. Found by the `user-site-conflict` condition
  on gauntlet 08 in CI. Evidence: [gauntlet/run_bundlers.py](../gauntlet/run_bundlers.py).
- **2026-10-05** · testing · A test that picked "the first directory entry" in the cache broke
  once the unpack lock added `.lock-*` files beside the unpacked copies (and passed on macOS by
  directory-order luck). Select cache entries by their name pattern. Evidence:
  `tests/test_verify_command.py`.
- **2026-10-05** · runtime · Without a lock, 16 simultaneous first runs of the NumPy bundle each
  unpacked a full copy (3.2 s wall, 28 s CPU; correct thanks to the atomic rename, but wasteful). A
  best-effort lock file in the cache root (flock / msvcrt, released by the OS if the holder dies,
  120 s timeout) makes one process unpack while the rest wait: 0.55 s wall, 1.1 s CPU. Evidence:
  `src/bundleup/_loader.py` `_lock()`; measured with two bundles built from consecutive commits.
- **2026-10-05** · build · `zipfile.writestr(ZipInfo, ...)` ignores the archive's `compresslevel`, so
  "level 1" payloads were really level 6. `pathlib.Path.relative_to()` costs ~60 µs a call (over a
  second for 18,000 files); use `os.walk` strings in hot loops. Set literals make `.pyc` bytes
  depend on the hash seed: compile with `PYTHONHASHSEED=0` for reproducible builds. Evidence:
  [findings](findings/2026-10-05-faster-builds.md).
- **2026-10-05** · cross-target · `uv pip install --target --python-platform X` installs another
  platform's wheels from any machine, and builds pure-Python sdists fine. A compiled sdist is
  built for *this* machine: uv itself rejects the result ("not compatible with the target"), and
  bundleup also checks every wheel tag against the target. Bytecode only depends on the Python
  version, so a local interpreter of the target version compiles it. Evidence:
  [`_platforms.py`](../src/bundleup/_platforms.py), `tests/test_platforms.py`.
- **2026-10-05** · testing · A corpus oracle that compares raw output flags programs that print
  their install path (`--version` "from …/site-packages"), list things in set order (twine), or
  differ only in traceback frames (the loader's vs a console-script launcher's). The first corpus
  run filed six such false positives (#1-#6); normalise those, and pin `PYTHONHASHSEED`. Evidence:
  [gauntlet/corpus.py](../gauntlet/corpus.py).
- **2026-10-05** · testing · The 100 most-downloaded PyPI packages (incl. pandas, scipy, pyarrow,
  grpcio, cryptography) bundle and match a normal install on Linux x64/arm64, macOS and Windows with
  no failures. Breadth beyond that and real program runs are the next risk. Evidence:
  [findings](findings/2026-10-05-ci-and-correctness.md).
- **2026-10-05** · testing · argparse's error wording changes even between patch releases
  (`(choose from 'build')` vs `(choose from build)` across 3.12.x), so CLI snapshots must only
  contain bundleup's own words. A corruption test that flipped a byte at a fixed offset landed in
  the loader, not the payload, and showed `verify` wasn't checking the loader: target bytes by zip
  offsets, and hash everything that runs. Evidence: [tests/test_verify_command.py](../tests/test_verify_command.py).
- **2026-10-05** · cli · `uv export --locked` refuses a PEP 723 script that has no lockfile, so
  "CI implies `--locked`" must only apply when a lockfile exists. argparse's help layout and error
  wording change between Python versions (3.13: `-o, --output FILE`), so help snapshots are pinned
  to the dev Python (`.python-version`). An `-X importtime` test caught `difflib` (a top-level
  import) on the `--version` path. Evidence: [tests/test_cli.py](../tests/test_cli.py).
- **2026-10-05** · ecosystem · Runtime hooks inside bundles are normal: shiv bundles read 10
  `SHIV_*` variables and pex ~30 `PEX_*` (incl. `PEX_TOOLS`); neither has a verify mode. bundleup
  verifies with a command (`bundleup verify`) instead, keeping the loader minimal. Evidence: the
  baseline's built bundles (`_bootstrap/environment.py`, `.bootstrap/pex/variables.py`).
- **2026-10-05** · runtime · A wheel's data files (the `.data/data/` scheme, e.g. sympy's
  `share/man/man1/isympy.1`) go to `<venv>/share/...` in a venv but to the payload root with
  `--target` (uv and pip alike), where `share/` even imports as a namespace package. Harmless for man
  pages; an app that looks for its data under `sys.prefix` won't find it in a bundle. Found by the
  `matches-venv` condition on gauntlet 21; candidate for its own gauntlet project if a real package
  depends on it. Evidence: [gauntlet/snapshot.py](../gauntlet/snapshot.py).
- **2026-10-05** · platforms · First runs on CI: every gauntlet project passed on Linux x64 and
  arm64 (3.9/3.11/3.12) and Windows x64 (3.11/3.12) with no code changes, including the hostile
  conditions each platform supports. Windows can't block network for a process (recorded per
  result) and ignores read-only on directories (those conditions are skipped there). Evidence: CI
  artifacts of the first green run; [gauntlet README](../gauntlet/README.md) "CI".
- **2026-10-05** · tooling · `astral-sh/setup-uv` publishes exact version tags only (`v10.2.0`), not
  a floating `v10`; `actions/checkout` and `actions/upload-artifact` do have `v7`. Evidence:
  `.github/workflows/ci.yml`.
- **2026-10-05** · tooling · `uv export --format pylock.toml` gives each locked package's name,
  version, marker and wheel hashes, which is what a lock-vs-bundle check needs. But
  `uv pip install -r pylock.toml` is a preview feature and resolves local directories relative to
  the file, so installs keep using the requirements format. Evidence: `src/bundleup/build.py`
  `export()`.
- **2026-10-05** · testing · Inside a project, `uv python find 3.12` returns the project's own
  `.venv` even with `--managed-python --no-project`; only running it from outside the repo (and
  without `VIRTUAL_ENV`) finds a plain interpreter. Since milestone 1 the harness had run "3.12"
  bundles on the repo venv, whose `packaging`/`pygments` could have masked a package missing from a
  bundle. Fixed (the harness now refuses venvs); a clean re-run passed all 21 projects and every
  hostile condition, so no result changed. Evidence: `gauntlet/run_bundlers.py` `python_path()`.
- **2026-10-05** · process · Other sessions edit this repo concurrently: a `git add -A` commit swept
  in someone else's in-progress ADR and roadmap edits (undone before pushing). Stage explicit paths,
  and re-read docs from disk before relying on them. Evidence: CLAUDE.md "Working rules".
- **2026-10-04** · runtime · Importing `typing` costs 6.7 ms on macOS's Python 3.9 and 3.9 ms on
  3.12, more than the loader's whole margin over a venv. pyright honours a module-level
  `TYPE_CHECKING = False` (no import), so the loader is fully typed for free with quoted annotations
  and `# type:` comments. Evidence: `python -X importtime -c "import typing"`; `src/bundleup/_loader.py`.
- **2026-10-04** · tooling · Ruff doesn't read `# type:` comments, so names used only there look
  unused (F401) and need an explained `noqa`. Variable annotations (`x: int = 1`) are Python 3.6+
  syntax even in a function body. `ast.parse(src, feature_version=(3, 5))` checks a file against an
  older grammar. Evidence: `tests/test_bundle.py::test_loader_parses_on_any_python_3`.
- **2026-10-04** · tooling · pre-commit hooks without `stages` run at every installed stage, so
  commit-time checks also re-run on push unless pinned to `stages: [pre-commit]`. Ruff skips
  excluded paths passed explicitly by a hook only with `force-exclude = true`. Evidence:
  `.pre-commit-config.yaml`.
- **2026-10-04** · tooling · The `pyright` PyPI wrapper ships the matching pyright release in the
  wheel (so `uv.lock` pins it), but needs Node.js: it uses `node` from `PATH`, otherwise downloads
  one with nodeenv at run time. The `nodejs` extra brings Node in as a wheel instead, which is why
  the dev group uses `pyright[nodejs]`. Evidence: the package's README (PyPI `pyright` 1.1.414).
- **2026-10-04** · testing · The gauntlet proves bundles *run and behave*; nothing yet proves a
  bundle contains *exactly* the locked files. Planned: lock-vs-bundle check, wheel `RECORD` hash
  verification, differential test against a `uv sync` venv, a top-PyPI import smoke test. Evidence:
  [roadmap](roadmap.md) "Next up" item 4.
- **2026-10-04** · research · Deep-research tools don't always receive attachments (round 5's
  Compass report didn't); check the report's own "assumptions" section before trusting
  project-specific details. Evidence: [round 5 synthesis](research/round-5-synthesis.md).
- **2026-10-04** · platforms · AWS Lambda: only `/tmp` is writable, the handler is
  `module.function`, and Lambda already unzips the package, so a `.pyz` would re-extract on every
  cold start. A native Lambda zip is the right output. Limits: 50 MB zipped / 250 MB unzipped incl.
  layers. Evidence: [verification notes](research/verification-notes.md).
- **2026-10-04** · platforms · Host applications (Splunk, Blender, QGIS) want a vendored directory
  or wheels built for *their* Python and platform, not a zipapp. Evidence:
  [round 4 synthesis](research/round-4-synthesis.md).
- **2026-10-04** · platforms · Some platforms now build from `uv.lock` themselves (Vercel; Cloud Run
  from Python 3.14), so bundleup adds little there. Evidence:
  [round 4 synthesis](research/round-4-synthesis.md).
- **2026-10-04** · design · A `.pyz` carrying a PEP 723 header would run different dependency sets
  under `python` (locked wheels) and `uv run` (fresh resolve). Never make that the default.
  Evidence: [round 4 synthesis](research/round-4-synthesis.md).
- **2026-10-04** · agents · Claude API Skills have no network and no runtime installs (Python 3.11,
  Linux x86_64), but the Agent Skills guide recommends PEP 723 + `uv run`, which needs network. That
  contradiction is bundleup's clearest agent use case. Evidence:
  [round 3 synthesis](research/round-3-and-2b-synthesis.md).
- **2026-10-04** · agents · MCPB (MCP Bundles) gave up vendoring Python: compiled deps like
  pydantic can't be bundled portably, so it added a host-side `uv` server type. A `.pyz` has the
  same limit unless the target platform is known in advance. Evidence:
  [verification notes](research/verification-notes.md).
- **2026-10-04** · ecosystem · uv has turned bundling requests away: #13503 closed as not planned,
  #5802 labelled wish; #12035 (Lambda) was closed by its own author, not implemented. Evidence:
  [verification notes](research/verification-notes.md).
- **2026-10-04** · research · Re-running round 2 without round 1 attached reached the same
  conclusions, so they weren't an artifact of anchoring. Evidence:
  [round 3/2b synthesis](research/round-3-and-2b-synthesis.md).
- **2026-10-04** · ecosystem · Astral on bundling (uv#7419, 2024-10-08): "definitely something we're
  interested in doing someday. I'm not sure zipapp is the ideal format for us." Still open,
  labelled `wish`. Evidence: [verification notes](research/verification-notes.md).
- **2026-10-04** · environment · macOS's `/usr/bin/python3` is a stub until the Xcode Command Line
  Tools are installed; with them it's Python 3.9.6. "Use whatever python3 exists" is solid for
  developers, servers, CI, Lambda and agents, weak for non-technical end users. Evidence:
  [round 1b synthesis](research/round-1b-synthesis.md).
- **2026-10-04** · positioning · Lead with what bundleup literally does (self-contained Python
  files); use cases are examples, never the definition, so nobody concludes "not for me".
  Evidence: [ADR-0012](adr/0012-lead-with-what-it-does.md).
- **2026-10-04** · research · Check which brief is pasted before running a deep-research job: the
  "round 3" run re-used the round 1 brief. Evidence: [round 1b synthesis](research/round-1b-synthesis.md).
- **2026-10-04** · build · On a large pure-Python project (21: 44 MB of source) bundleup's build is
  no faster than pex (5.2 vs 5.5 s): zip 3.1 s and bytecode compile 1.3 s dominate; uv's install is
  0.2 s. zlib releases the GIL, so threads cut compression 2–5×; compiling must be done by the
  target Python, so the fix there is caching per wheel, not another language. Evidence:
  [large project](findings/2026-10-04-large-project-and-rust.md).
- **2026-10-04** · analyzer · Just `ast.parse` + walking every node takes 5.2 s for 21 and 10.5 s
  for PyTorch's 98 MB of source in one process (0.8 s / 1.6 s on 8 processes): a pure-Python
  scanner sits at ADR-0008's Rust trigger before doing any analysis. Evidence:
  [large project](findings/2026-10-04-large-project-and-rust.md#experiment-2-what-would-the-analyzers-scan-cost).
- **2026-10-04** · ecosystem · Django finds its translation catalogs through its package directory,
  so it fails inside a zip (*"No translation files found for default language en"*) with zipapps
  and plain zipapp. Evidence: gauntlet 21.
- **2026-10-04** · environment · `/usr/bin/python3` on macOS is an `xcrun` shim: ~5 ms slower to
  start than the interpreter it launches (16.5 vs 11 ms for `-c pass`). A venv's console script
  skips it; `python3 app.pyz` can't. Compare start-up with the same binary. Evidence:
  [milestone 1](findings/2026-10-04-milestone-1.md#speed).
- **2026-10-04** · build · For PyTorch (21,942 files, 190 MB bundle), single-threaded zip
  compression is 11.3 s of a 14.5 s build: the next build-speed bottleneck, fixable with threads
  (zlib releases the GIL) rather than Rust. Evidence:
  [milestone 1](findings/2026-10-04-milestone-1.md#build-steps).
- **2026-10-04** · runtime · Running a `.pyz` makes `zipimport` parse the whole zip directory on
  every start: ~1.5–2 µs per entry, so a 20,000-file bundle adds 27 ms (3.12) to 43 ms (3.9) to every
  run. A two-entry outer zip with a stored inner payload makes warm start independent of size.
  Evidence: [milestone 1](findings/2026-10-04-milestone-1.md#why-two-zips).
- **2026-10-04** · environment · macOS's `/usr/bin/python3` sets `sys.pycache_prefix` to
  `~/Library/Caches/com.apple.python`: it ignores every `__pycache__` directory, and its standard
  library ships no `.pyc`, so a fresh `HOME` compiles the stdlib on the first run of *any* program
  (~130 ms for click's imports). Precompiled `.pyc` must be placed under the prefix to be used.
  Evidence: [milestone 1](findings/2026-10-04-milestone-1.md#macos-system-python).
- **2026-10-04** · tooling · uv caches what it learns about a real interpreter but re-runs a shim
  like `/usr/bin/python3` on every `uv pip install --python` (+120 ms); resolve `sys.executable`
  first. Importing `platform` costs ~30 ms on Apple's Python. Evidence:
  [milestone 1](findings/2026-10-04-milestone-1.md).
- **2026-10-04** · tooling · `compileall` with `workers=0` is slower than one process for small
  trees on macOS (workers are spawned interpreters): 317 ms vs 125 ms for 03 on 3.9; worth it from
  a few hundred files. `compileall` embeds the source path in each `.pyc` unless given `ddir`,
  which breaks reproducible builds. Evidence: [milestone 1](findings/2026-10-04-milestone-1.md).
- **2026-10-04** · tooling · `uv pip install -r` resolves relative paths in the requirements file
  against the working directory, not the file's location; `uv export --no-editable` emits the
  project and workspace members as `.`/`./packages/x`. `uv python find` can't combine a version
  request with `--script`. Evidence: [ADR-0011](adr/0011-cli-and-build-pipeline.md).
- **2026-10-04** · tooling · zlib level 1 deflates NumPy's 33 MB install 2.5× faster than level 6
  (183 vs 463 ms) for 14% more size; decompression time is the same. Evidence:
  [milestone 1](findings/2026-10-04-milestone-1.md).
- **2026-10-04** · measurement · The baseline's speed table (59 ms venv, 106 ms shiv) isn't
  reproducible from `run_bundlers.py`, which runs six builds in parallel; its method wasn't
  recorded. Re-measured sequentially with `gauntlet/bench.py`: the venv floor for 03 is ~31 ms on
  3.12. Compare tools from the same run, not across sessions. Evidence:
  [milestone 1](findings/2026-10-04-milestone-1.md).
- **2026-10-04** · environment · The development machine's shell sets `PYTHONDONTWRITEBYTECODE=1`.
  The gauntlet scripts pass a clean environment, so results aren't affected, but ad-hoc timings in
  the shell are.

- **2026-10-03** · naming · Names built on "zip" read as "this makes zip files"; name the experience
  (ready to run), not the container format. Evidence: [ADR-0009](adr/0009-name-bundleup.md).
- **2026-10-03** · naming · `bundle`/`bundler` are Ruby commands preinstalled on macOS
  (`/usr/bin/bundle`); `packer` is HashiCorp's; `pack` is Cloud Native Buildpacks' CLI. Check
  command clashes, not just PyPI. Evidence: [ADR-0009](adr/0009-name-bundleup.md).
- **2026-10-03** · naming · PyPI `pack` is an empty placeholder (0.0.1, no files, Paul J. Davis):
  likely eligible for PEP 541 transfer, but transfers take months (owner contacted, ~6-week wait,
  small review team). Evidence: [PEP 541](https://peps.python.org/pep-0541/).
- **2026-10-03** · prior art · Abandoned attempts at the same idea exist on PyPI: `carryon` (0.1.3,
  Nov 2024: "Pack your Python script with its dependencies", appends a zip to the script) and
  `carton` (2016: "make self-extracting virtualenvs"). More evidence of demand and of nobody
  sticking with it.
- **2026-10-03** · tools · pex is the correctness bar: it passed every applicable gauntlet project
  except child processes (19), and every hostile condition. Evidence:
  [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · pex adds ~210 ms to every start by default (273 ms vs 59 ms for an
  installed venv). `--venv --sh-boot` gets 32 ms, but an `--sh-boot` pex runs the first `python3`
  on `PATH`, and on macOS that's 3.9, so a 3.12 pex fails with a confusing "no cp39
  distributions" error. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · On Python 3.9, pex resolves with a vendored pip 20.3.4 and its legacy
  resolver: builds take ~12 s vs ~2 s on 3.12. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · shiv always extracts to `~/.shiv` with no fallback; every bundle fails
  when `HOME` isn't writable. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · zipapps deletes all `.dist-info` by default (`--rm-patterns`), breaking
  `importlib.metadata` and entry points; it unpacks native code into `./zipapps_cache` in the
  *working directory*, so it fails from read-only directories and races on simultaneous first runs.
  Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · tools · A naive `pip --target` + `zipapp` bundle silently loses compiled
  accelerators (PyYAML's LibYAML, mypyc'd charset-normalizer) and falls back to pure Python with
  no warning. Evidence: gauntlet project 10 in the [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · runtime · Child interpreters started with `sys.executable` don't inherit a
  bundle's `sys.path`; only zipapps handles this (via the environment). Evidence: gauntlet 19.
- **2026-10-03** · runtime · Extract-everything tools avoid `__file__`, metadata *and* native
  failures; run-from-zip tools fail more on files/metadata than on native code. Answers the
  research's open question. Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · ecosystem · Every tool refused the 3.12-only project on 3.9 only because pip
  checked `requires-python`; none inspects the code, and none gave a plain-language message.
  Evidence: [baseline](findings/2026-10-03-baseline.md).
- **2026-10-03** · ecosystem · python-pptx reads its default template via `__file__` (zip-unsafe);
  pytz tries `__file__` and falls back to `importlib.resources`; docopt 0.6.2 ships only an sdist.
  Evidence: gauntlet projects 05, 14, 18.
- **2026-10-03** · environment · macOS's `/usr/bin/python3` is 3.9.6 (Command Line Tools), a
  realistic "user's Python" target.
- **2026-10-03** · environment · `sandbox-exec -p '(version 1)(allow default)(deny network*)'`
  blocks network for a process on macOS; used by the harness to prove bundles need no network.
- **2026-10-03** · environment · No Docker on the development machine; Linux/cross-platform runs
  need CI or another host.
- **2026-10-03** · tooling · `uv export --script file.py` exports a PEP 723 script's resolved
  dependencies as requirements.
- **2026-10-03** · research · The "gemini" research reports hallucinate and recycle sources (round 2
  cites round 1 as its main source). Trust the "compass" reports, and verify anything decisive.
  Evidence: [verification notes](research/verification-notes.md).
- **2026-10-03** · research · uv's `uv bundle` request (#5802) is labelled "wish – Not on the
  immediate roadmap"; the `uv run --watch` PR (#12847) was closed unmerged. Evidence:
  [verification notes](research/verification-notes.md).
