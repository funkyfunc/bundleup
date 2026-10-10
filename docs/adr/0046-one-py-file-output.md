# ADR-0046: `--format py`: the bundle as one plain-text `.py` file

- **Status:** Accepted (the owner, 2026-10-09: "let's do the one file output"; kept on purpose
  after rounds 6 and 7, roadmap item 24)
- **Date:** 2026-10-09
- **Deciders:** the owner (the output), an agent (the design)
- **Refines:** [ADR-0002](0002-target-the-runtime-only-tier.md) (which ruled out a `.py` that
  *inlines* all code; this one carries the bundle as data instead)

## Context

A `.py` goes where a `.pyz` can't: places that take only `.py` files or only text (a gist, an
upload form, a chat, an agent told to "run this Python file"), and `python tool.py` is what
people type. ADR-0002 rejected inlining every module's source into one file (stickytape-style:
it breaks native code, data files and metadata), and rounds 6 and 7 argue against that too
(uv #12035). The owner kept the idea of one file that *carries* the bundle
([note](../findings/2026-10-08-inputs-outputs-and-transforms.md)).

Python compiles a whole script before running any of it, so whatever data the file holds is read
on every start. Measured on an M-series Mac, Python 3.12 (2026-10-09): base64 in comment lines
costs about 1.7 ms per MB, the same in a string literal twice that.

## Decision

- `--format py` (`format = "py"`) writes `dist/<name>.py`: plain ASCII text with
  1. a shebang and a `# /// bundleup` block (PEP 723's syntax, not its `script` type) naming the
     project, version, bundleup version, where it runs, the entry and every bundled package
     pinned, so people and tools can read what's inside; nothing installs from it, because uv and
     other runners only act on `script` blocks;
  2. two sentences on how to run and check it;
  3. bundleup's loader, unchanged except `EMBEDDED = True`;
  4. what a `.pyz` would carry (the payloads or layers, and the manifest) as a zip in base64,
     one `#`-prefixed line per 76 characters, between two marker lines.
- The loader behaves as in a `.pyz`: the same checks, cache, entry points, `--entry python`,
  several platforms, re-runs with a matching Python. On the first run it decodes the data,
  skipping non-base64 characters (so Windows line endings don't matter), and refuses a cut or
  edited file with a message before trying any cache folder. It takes the file's own folder off
  `sys.path`, so files beside it can't shadow its packages (a `.pyz`'s folder isn't on it either).
- `bundleup verify tool.py` checks the code before the data (the manifest records its hash) and
  every file in the data. `--smoke` runs it. `--split` is for `.pyz` only.

## Consequences

- One text file with no install step that works wherever a `.pyz` would.
- A third bigger than the `.pyz` (base64), and every start reads the whole file: +3 ms for a
  small tool (the loader is compiled on each run, a `.pyz` carries it compiled), +38 ms for the
  21 MB skill fixture (a warm start of 50 ms against 11 ms). Recommended for small tools; the
  recipe says so. First runs are slower by the decoding (180 ms against 122 ms for the fixture).
- Editors cope badly with a multi-megabyte `.py`; the readable part is the top.
- The gauntlet runs every project and hostile condition as a `.py` too (`--tool bundleup-py`).

## Alternatives considered

- **Inlining every module behind an import hook** (stickytape, esbuild-style): rejected again
  (ADR-0002): native code, data files and `importlib.metadata` don't survive, and it isn't
  readable either at thousands of modules.
- **A `# /// script` header with the pinned dependencies.** `uv run tool.py` would then install
  everything from the network before running a file that already carries it, and a lock's
  per-platform packages need markers that one `dependencies` list doesn't say well.
- **The data in a string literal.** Twice the start cost, and a copy in memory on every run.
- **A `.py` that is also a zip** (Python runs a zip with any name). Not text, so it fails exactly
  where this format is needed.

## Evidence

- [tests/test_py_format.py](../../tests/test_py_format.py): plain ASCII, the header, runs,
  verifies, files beside it don't shadow, Windows line endings run, a cut file is refused
  without a traceback, `--entry python` with two platforms.
- Gauntlet `--tool bundleup-py` (local and CI): every project and condition.
- Start-time measurements: this ADR's context; [learnings](../learnings.md), 2026-10-09.
