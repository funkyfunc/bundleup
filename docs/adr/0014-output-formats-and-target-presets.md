# ADR-0014: `.pyz` stays the product; add `dir` and Lambda outputs and printable target presets

- **Status:** Proposed
- **Date:** 2026-10-04
- **Deciders:** proposed by an agent from round 4 research; awaiting the user

## Context

Round 4 mapped who needs self-contained Python programs and what each platform requires
([synthesis](../research/round-4-synthesis.md)). Most strong-fit use cases work with a plain
`.pyz`. Two large audiences can't use a `.pyz` well: AWS Lambda (already unzips the package; only
`/tmp` is writable) and host applications that load plugins from a directory (Splunk, QGIS,
Maya/Houdini, Azure Functions' `.python_packages`). Both currently hand-roll
`pip install --target --platform`.

## Decision

1. **`.pyz` is the product and the default.** First priority is making it honest about its
   target: cross-target builds (`--python`, `--platform`), a cache override (`BUNDLEUP_CACHE`),
   and clear mismatch errors.
2. **Two additional output formats**, written from the same resolved file set:
   - `--format dir`: a vendored directory for host applications;
   - Lambda zip / layer (via the `lambda` preset).
3. **Format and target are separate axes.** `--format` chooses the artifact; `--python` and
   `--platform` choose the target.
4. **Target presets** (`--target lambda`, later others) are named shorthands that expand to
   ordinary flags and **print their expansion**; `bundleup targets` lists them. Presets are a
   general mechanism, so an agent-sandbox preset (ADR-0013) would be one preset among several,
   not a special flag.
5. **No hybrid or uv-dependent default.** A PEP 723 header on a `.pyz` may come later as an
   explicit opt-in, once uv supports it (uv#18662), because `python app.pyz` and `uv run app.pyz`
   would otherwise run different dependency sets.
6. **Out of scope:** standalone executables, container images, Pyodide/WebAssembly, conda-style
   environments, wheelhouses. Non-Python dependencies are detected and warned about, not bundled.

## Consequences

- Cross-target resolution becomes the shared core every output depends on.
- Each extra format is a thin writer, so the maintenance cost stays low; each still needs gauntlet
  coverage.
- Docs can invite Lambda and plugin authors explicitly once the formats land.

## Alternatives considered

- **`.pyz` only.** Simplest, but leaves Lambda and host-app plugin authors with hand-rolled
  commands, and both are large audiences.
- **Many formats** (executables, OCI images, wheelhouses). Rejected: other tools already do these
  well, and feature creep is how PyInstaller and PyOxidizer became hard to maintain.
- **Separate commands per format** (`bundleup lambda`). Rejected in favour of one command with
  orthogonal flags and presets, which keeps one mental model.
