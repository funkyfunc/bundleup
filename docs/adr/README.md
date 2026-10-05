# Architecture decision records

Why the project is the way it is. Read this index before changing direction; see
[ADR-0001](0001-record-decisions-and-learnings.md) for how ADRs work here.

**Writing one:** copy [template.md](template.md) to `NNNN-short-title.md` with the next number,
add a row below, and link the evidence. Never rewrite an accepted ADR: supersede it with a new one
and change only the old one's status line.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-decisions-and-learnings.md) | Record decisions as ADRs and lessons in a learnings log | Accepted |
| [0002](0002-target-the-runtime-only-tier.md) | Ship a `.pyz` that needs only Python; no standalone executables | Accepted |
| [0003](0003-compete-on-experience.md) | Compete on experience and speed, not on new capability | Accepted |
| [0004](0004-lockfile-decides-contents.md) | The lockfile decides what goes in; import tracing is for diagnostics only | Accepted |
| [0005](0005-extract-to-cache-by-default.md) | Use the standard importer and extract to a cache by default | Accepted (cache details Proposed) |
| [0006](0006-delegate-to-uv-and-existing-files.md) | Delegate resolution and installation to uv; read the files people already have | Accepted |
| [0007](0007-gauntlet-is-the-contract.md) | The gauntlet is the acceptance test, and claims must be measured | Accepted |
| [0008](0008-prototype-in-python.md) | Build in Python first, with a measured path to Rust | Accepted |
| [0009](0009-name-bundleup.md) | Name the project `bundleup` | Accepted |
| [0010](0010-bundle-format-and-loader.md) | Bundle format, loader and cache layout | Proposed |
| [0011](0011-cli-and-build-pipeline.md) | CLI shape and build pipeline | Proposed |
| [0012](0012-lead-with-what-it-does.md) | Describe bundleup by what it does, with use cases as examples | Accepted |
| [0013](0013-agent-sandboxes-as-headline-use-case.md) | Agent sandboxes as the headline use case, served by target profiles and skill output | Accepted (positioning); features Proposed |
| [0014](0014-output-formats-and-target-presets.md) | `.pyz` stays the product; add `dir` and Lambda outputs and printable target presets | Proposed |
| [0015](0015-engineering-tooling.md) | Enforce code quality with Ruff, a type checker, git hooks and CI | Accepted (direction); tool choices Proposed |
