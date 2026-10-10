# ADR-0045: `--split SIZE` writes a big bundle as a small `.pyz` and a folder of parts

- **Status:** Accepted (the owner, 2026-10-09: "let's tackle bundle splitting, maybe that's just
  something you can pass in an argument")
- **Date:** 2026-10-09
- **Deciders:** the owner (an opt-in flag), an agent (the design)
- **Refines:** [ADR-0038](0038-one-pyz-for-several-platforms.md) (layers)

## Context

The founding skill (python-pptx, lxml, Pillow, PyMuPDF, xlsxwriter) for four platforms is one
144 MiB `.pyz`. GitHub refuses files over 100 MB, so a repository, or a skill an agent package
manager installs from one, can't hold it without Git LFS, and LFS support in those tools is
unverified ([fifth review](../findings/2026-10-08-fifth-review.md), Rec. 5; roadmap item 22).
Since ADR-0038 a bundle is already made of layers (zips unpacked in order), so the bytes can live
in several files without a new format.

## Decision

- `--split SIZE` on `build` (`BuildOptions(split=...)`, `split = "100MB"` in `[tool.bundleup]`,
  `BUNDLEUP_SPLIT`): no file the build writes is bigger than SIZE.
- A bundle that fits in one file of SIZE is written as usual. One that doesn't becomes
  `app.pyz`, holding only the loader and the manifest, and a folder `app.pyz.parts/` beside it
  holding the layers as `layer-<hash>.zip` files. A layer bigger than SIZE is cut into several,
  between files (each part is an ordinary zip); a single file that is bigger compressed than SIZE
  is an error that names it.
- The loader finds the folder by the name it was built with, next to wherever the `.pyz` is (so
  renaming the `.pyz` works), and checks each part's sha256 before unpacking: a missing part or
  one from another build is refused with a message saying to copy the `.pyz` and its folder
  together, and nothing is unpacked under the bundle's name.
- `bundleup verify` checks the parts against the manifest (`"parts"` in a version 2 manifest).
  The build result has `parts` (the folder) and counts it in `size_bytes`.
- A build without `--split`, or one that fits, removes a parts folder an earlier `--split` build
  left beside the output; a folder there holding anything else is left alone, or, when the build
  needs it, refused.
- Only for `.pyz` output. The `large-bundle` warning's hint suggests `--split 100MB`, and
  `--split` turns that warning off (the size is then a choice).

## Consequences

- The founding skill can ship through git with no LFS: `scripts/deps.pyz` plus
  `scripts/deps.pyz.parts/`, each file under the limit. The command the skill's instructions give
  doesn't change.
- Two things to copy instead of one; the loader's message covers the common mistake (copying
  only the `.pyz`). Parts are content-addressed, so a stale part can't be mixed in silently.
- The cold start hashes each part before unpacking it (a few hundred MB/s); warm starts are
  unchanged.
- Not split by platform: a macOS user still receives the Windows parts. Fetching only one
  platform's parts would need a download step, which a bundle never has.

## Alternatives considered

- **One `.pyz` per platform with a small launcher choosing among them.** Each file is still one
  platform's whole payload, which may itself be over the limit, and it's a second loader to keep.
- **Cutting the `.pyz` into byte ranges (`app.pyz.001`, `.002`).** Python can't run a cut zip,
  so it would need a separate launcher; parts as zips need nothing new in the loader's reading.
- **Split by default over 100 MB.** The owner asked for an option; a single file is simpler to
  hand around whenever it fits the place it goes.

## Evidence

- [tests/test_split.py](../../tests/test_split.py): parts under the size, runs, verifies, refuses
  a missing or foreign part by name, removes a stale folder, keeps a folder it didn't write.
- CI `skill` / `skill-run`: the skill built for four platforms with `--split 20MB` on macOS and
  run on Linux, Windows and macOS.
- GitHub's limit: docs.github.com, "About large files on GitHub" (files over 100 MiB are blocked).
