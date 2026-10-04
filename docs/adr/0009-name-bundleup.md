# ADR-0009: Name the project `bundleup`

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** the user

## Context

The project needed a name for the command, the PyPI distribution and the GitHub repo. About 150
candidates were considered across several angles: compression and binding (bale, cinch, truss),
packing (pack, packz, packout), sealing and preserving (ziplock, zipseal, hermetic, sachet),
travel and logistics (tote, kitbag, docket), and packed meals (tiffin, bento, takeout, boxlunch).
Most short English words are taken on PyPI.

Criteria that emerged:
- **Evoke the experience, not the file format.** A `.pyz` is technically a zip, but users get
  "something ready to run". Names built on "zip" (ziplock, zipup) made the user think the tool
  just creates zip files.
- **Clear to a developer on first sight**, and searchable.
- **Don't pigeonhole.** Every plausible future direction ([roadmap](../roadmap.md)) is bundling
  for some destination: `.pyz`, executables, containers, serverless, the browser, other languages.
  No "py", no "zip".
- Free on PyPI, and no clash with an existing command.

## Decision

The project, command and distribution are named **`bundleup`**. Repo:
https://github.com/funkyfunc/bundleup.

Personality lives in the docs and messages rather than the name: the "packed meal / to go" voice
from the runner-up names (e.g. "your app, packed to go", "ready to serve").

## Consequences

- "Bundler" is the name of the tool category in both JS (esbuild, webpack) and Python
  (PyInstaller "bundles"), so people searching for a Python bundler find us by name.
- Eight letters to type. Acceptable for a tool run in build scripts and CI; a short alias can be
  added later without renaming.
- The name stays accurate if bundleup grows beyond `.pyz` or beyond Python.
- Not yet published on PyPI; free as of 2026-10-03. Publish once there's a working release.

## Alternatives considered

| Name | Why not |
|---|---|
| `bundle` | Taken on PyPI (2012), and `bundle`/`bundler` are Ruby's commands, preinstalled on macOS |
| `takeout` | Most fun, but needs explaining, doesn't work as a verb, and Google Takeout owns the word in tech |
| `boxup` | Short and fine, but vague; "box" is overloaded (Vagrant, sandboxes) |
| `ziplock`, `zipup`, `packz` | Suggest the tool only makes zip files; tied to one format |
| `pack` | Empty placeholder on PyPI (reclaimable via PEP 541, slowly); clashes with Buildpacks' `pack` command; "python pack" searches return `struct.pack` |
| `packer` | HashiCorp Packer |
| `packout` | Good, but less clear than "bundle"; Milwaukee Tool's PACKOUT brand |
| `tiffin`, `boxlunch`, `sachet` | Charming, but need explaining to many audiences |
| `bale`, `cinch`, `prep` | Rejected by the user (`prep` also reads as data preprocessing in Python) |
| `mise`, `bento`, `pallet`, `cargo`, `flatpack` | Collide with mise, BentoML, the Pallets org (Flask), Rust, Flatpak |

## Evidence

- PyPI availability checks run 2026-10-03 (`https://pypi.org/pypi/<name>/json`).
- [docs/roadmap.md](../roadmap.md) for the future directions the name had to cover.
