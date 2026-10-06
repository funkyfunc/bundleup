# Learnings

Short, dated lessons: facts we discovered, surprises, gotchas. Newest first. Each entry links to
its evidence. If a lesson changes a decision, also write an ADR (see
[ADR-0001](adr/0001-record-decisions-and-learnings.md)).

Format: `- **YYYY-MM-DD** · <area> · <lesson>. Evidence: <link>.`

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
