# Architecture decision records

Why the project is the way it is. Read this index before changing direction; see
[ADR-0001](0001-record-decisions-and-learnings.md) for how ADRs work here.

**Writing one:** copy [template.md](template.md) to `NNNN-short-title.md` with the next number,
add a row below, and link the evidence. Never rewrite an accepted ADR: supersede it with a new one
and change only the old one's status line.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-decisions-and-learnings.md) | Record decisions as ADRs and lessons in a learnings log | Accepted |
| [0002](0002-target-the-runtime-only-tier.md) | Ship a `.pyz` that needs only Python; no standalone executables | Accepted (the `.py` point refined by 0046; executables superseded by 0047) |
| [0003](0003-compete-on-experience.md) | Compete on experience and speed, not on new capability | Accepted |
| [0004](0004-lockfile-decides-contents.md) | The lockfile decides what goes in; import tracing is for diagnostics only | Accepted; refined by 0041 |
| [0005](0005-extract-to-cache-by-default.md) | Use the standard importer and extract to a cache by default | Accepted |
| [0006](0006-delegate-to-uv-and-existing-files.md) | Delegate resolution and installation to uv; read the files people already have | Accepted |
| [0007](0007-gauntlet-is-the-contract.md) | The gauntlet is the acceptance test, and claims must be measured | Accepted |
| [0008](0008-prototype-in-python.md) | Build in Python first, with a measured path to Rust | Accepted |
| [0009](0009-name-bundleup.md) | Name the project `bundleup` | Accepted |
| [0010](0010-bundle-format-and-loader.md) | Bundle format, loader and cache layout | Accepted (compression level superseded by 0020; child processes by 0027; one Python version, for pure-Python bundles, by 0030; an explicit `BUNDLEUP_CACHE` by 0048) |
| [0011](0011-cli-and-build-pipeline.md) | CLI shape and build pipeline | Accepted (pipeline); CLI superseded by 0016 |
| [0012](0012-lead-with-what-it-does.md) | Describe bundleup by what it does, with use cases as examples | Accepted |
| [0013](0013-agent-sandboxes-as-headline-use-case.md) | Agent sandboxes as the headline use case, served by target profiles and skill output | Accepted (positioning); features Proposed |
| [0014](0014-output-formats-and-target-presets.md) | `.pyz` stays the product; add `dir` and Lambda outputs and printable target presets | Accepted; presets superseded by 0039 |
| [0015](0015-engineering-tooling.md) | Enforce code quality with Ruff, a type checker, git hooks and CI | Accepted |
| [0016](0016-cli-and-api-conventions.md) | CLI and Python API follow the style guide | Accepted (verbs) |
| [0017](0017-platform-matrix-and-corpus-testing.md) | Free platform matrix on GitHub Actions, plus nightly corpus testing with AI triage | Accepted (agent triage deferred) |
| [0018](0018-package-layout-and-lazy-api.md) | Private modules, and a public API that loads lazily | Accepted |
| [0019](0019-manifest-and-verify-command.md) | Every bundle carries a manifest; `bundleup verify` checks it | Accepted |
| [0020](0020-parallel-zip-and-bytecode-cache.md) | Compress the payload in parallel at level 6; cache compiled bytecode per wheel | Accepted |
| [0021](0021-isolate-from-machine-packages.md) | Bundles don't see the machine's own packages, unless asked to | Accepted (children amended by 0027) |
| [0022](0022-cache-command.md) | Unpacked bundles are cleaned up by a command, never by bundles themselves | Accepted |
| [0023](0023-payload-behaves-like-site-packages.md) | The payload behaves like a venv's site-packages: wheel executables stay, `.pth` files run | Accepted |
| [0024](0024-check-command-and-build-analysis.md) | `bundleup check` reports what won't survive bundling, and every build runs it | Accepted |
| [0025](0025-dir-and-lambda-formats-and-presets.md) | How `--format dir`, `--format lambda` and target presets work | Accepted; presets superseded by 0039 |
| [0026](0026-pylock-toml-input.md) | A project's `pylock.toml` is used when it has no `uv.lock` | Accepted |
| [0027](0027-children-see-the-bundle-only-from-its-own-python.md) | Child processes see the bundle only when they run the bundle's own Python | Accepted (amended by 0037) |
| [0028](0028-a-project-needs-a-lockfile.md) | A project needs a lockfile; bundleup never writes one into it | Accepted; first decision superseded by 0041 |
| [0029](0029-start-up-checks-c-library-and-macos-version.md) | Bundles check the C library and macOS version at start-up | Accepted |
| [0030](0030-pure-python-bundles-run-on-a-range.md) | A pure-Python bundle runs on every Python version its lock allows | Accepted (shebang superseded by 0036) |
| [0031](0031-wheel-coverage-from-the-lock.md) | Wheel coverage is checked from the lock, before installing, for any number of targets | Accepted |
| [0032](0032-tool-bundleup-configuration.md) | Project settings live in `[tool.bundleup]` | Accepted |
| [0033](0033-a-stale-lock-is-an-error.md) | A stale lock is an error by default; bundleup never rewrites it | Accepted |
| [0034](0034-pure-python-bundles-run-on-any-os.md) | A pure-Python bundle runs on any OS when the lock selects the same packages everywhere | Accepted |
| [0035](0035-check-older-pythons-syntax-without-their-interpreters.md) | A range's oldest Python is checked with a real interpreter, installed privately if needed | Accepted |
| [0036](0036-wrong-python-reruns-and-a-platform-matrix.md) | A plain `python3` shebang and a re-run with a matching Python; `check --matrix`; in-use copies are kept | Accepted |
| [0037](0037-children-activate-only-for-bundle-code.md) | A child process activates the bundle only when it runs the bundle's code | Accepted |
| [0038](0038-one-pyz-for-several-platforms.md) | One `.pyz` can carry a payload per platform and Python version | Accepted |
| [0039](0039-recipes-instead-of-target-presets.md) | Recipes and capabilities (`--max-size`) instead of named target presets | Accepted |
| [0040](0040-entry-python-runs-any-script.md) | `--entry python`: a bundle that runs the scripts it's given | Accepted |
| [0041](0041-input-without-a-lock.md) | Input without a lock builds, resolved at build time, with a warning | Accepted |
| [0042](0042-smoke-runs-the-bundle-once.md) | `--smoke` runs the finished bundle once before shipping | Accepted |
| [0043](0043-check-audit-asks-pypi-about-the-lock.md) | `check --audit` asks PyPI about the locked packages | Accepted |
| [0044](0044-destinations-as-data-files.md) | Destinations described as data files (`--against FILE`) | Accepted |
| [0045](0045-split-a-bundle-into-parts.md) | `--split SIZE`: a big bundle as a small `.pyz` and a folder of parts | Accepted |
| [0046](0046-one-py-file-output.md) | `--format py`: the bundle as one plain-text `.py` file | Accepted |
| [0047](0047-standalone-executables.md) | `--format exe`: a standalone executable that brings its own Python | Accepted |
| [0048](0048-an-explicit-cache-is-the-only-cache.md) | An explicit `BUNDLEUP_CACHE` is the only cache folder | Accepted |
