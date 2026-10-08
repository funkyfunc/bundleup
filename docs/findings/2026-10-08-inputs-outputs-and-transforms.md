# Inputs, outputs and transformations: what else a Python bundler could be (2026-10-08)

The owner asked, thinking of JavaScript bundlers: should bundleup take more kinds of input,
produce more kinds of output (inline-requirements scripts, one literal `.py` file, wheels, sdists,
Docker images, executables), and transform code the way esbuild or Babel do? This note records the
measurements and the recommendation for each, so none of it is lost. Decided and built on the same
day: more inputs ([ADR-0041](../adr/0041-input-without-a-lock.md)).

## Measurements

The owner's skill (python-pptx, lxml, Pillow, PyMuPDF, xlsxwriter) for macOS arm64, Python 3.12:
one payload, 100 MB unpacked.

| What | Unpacked | Zipped |
|---|---|---|
| Native libraries (`.so`, `.dylib`, bundled libs) | 78.7 MB | 35.1 MB |
| Bytecode (`.pyc`) | 9.1 MB | 2.9 MB |
| Source (`.py`) | 7.4 MB | 1.6 MB |
| C headers and Cython sources (`.h`, `.pyx`, `.pxd`) | 4.3 MB | 0.9 MB |
| Data, dist-info, type stubs | 0.7 MB | 0.4 MB |

`strip -x` on the largest libraries: `_mupdf.so` 13 → 11 MB, `etree.so` 9 → 8 MB, `libmupdf.dylib`
33 → 33 MB (already stripped); on macOS it also invalidates the code signature Apple Silicon
requires. **Size is native code, and native code doesn't shrink.** Every transform below that
removes Python-side files saves at most ~10% of this bundle.

## Inputs

Built (ADR-0041): `pyproject.toml` without a lock, `setup.py` / `setup.cfg`, a folder of modules
with `requirements.txt`, a script with a `requirements.txt` beside it or only standard-library
imports; a fully pinned requirements.txt counts as a lock. Not built, on purpose: `poetry.lock`
and `Pipfile.lock` (export them, or build from `pyproject.toml`; read them directly if users ask),
conda `environment.yml` (not wheels; MISSION rules conda out), a wheel or sdist as input (pex can;
nobody asked).

## Outputs

| Idea | Recommendation | Why |
|---|---|---|
| **One literal `.py` file** (the JS "single file" output) | **Worth building, opt-in** (`--format py`) | A `.py` goes where a `.pyz` can't: places that only accept `.py`, a gist, an agent told to "run this Python file", `python tool.py` in muscle memory. The file would be a short readable header (what's inside, pinned versions, a PEP 723-style block for documentation) plus the bundle as base64 in a string and ~30 lines that unpack it like the loader does. Costs: +33% size (base64), editors struggle with a 100 MB `.py`, so it suits small tools. A truly inlined bundle (every module's source in one file behind an import hook, esbuild-style) works only for pure Python, and 5,000 modules in one file isn't readable either. |
| **Project → script with inline requirements** (PEP 723 as output) | **Not as a separate output; as the header of the `.py` output** | A script whose header lists dependencies is "install at run time" (`uv run`), which needs uv, the network and an index on every machine: the opposite of what bundleup promises. The useful half is the header itself: written on top of the one-file `.py` (pinned, for documentation and tools), it costs nothing and makes the file self-describing. uv already converts the other way (`uv add --script -r`). |
| **Wheel / sdist** | **No** | Those are packages for an installer: `uv build`, Hatch and setuptools make them. bundleup's whole point is no install step; a wheel output would be a worse `uv build`. |
| **Docker / OCI image** | **Later (roadmap)** | A `.pyz` already drops into `python:3.12-slim`. A daemonless image writer (as `ko` and `jib` do for Go and Java: base image + one layer with the bundle) is plausible once someone asks. |
| **Executable with the interpreter inside** | **Investigate deeply (roadmap)** | Node has single executable applications (a blob injected into the `node` binary); Deno and Bun have `compile`. Python has no built-in equivalent. Prior art: PyInstaller (bootloader + archive, unpacks), Nuitka (compiles to C), PyOxidizer (embedded interpreter, imports from memory; largely unmaintained), pex's scie (a small Rust launcher with python-build-standalone and the pex appended; can fetch the interpreter lazily), Cosmopolitan Python (one binary for every OS), PEP 711 (PyBI, draft: interpreters as distributions). bundleup's layered multi-platform `.pyz` plus python-build-standalone plus a tiny launcher is close to a scie; the open questions are signing and notarization on macOS, Windows Defender, and ~30-40 MB of interpreter per platform. For the owner's skill, this is the answer for Windows users without Python. |

## Transformations (what esbuild and Babel do to code)

| Idea | Recommendation | Why |
|---|---|---|
| **Syntax lowering** (run 3.12 syntax on 3.9, like Babel) | **No** | No mature Python tool; bundleup checks the oldest Python instead (ADR-0030), and pure bundles already run on every version their code parses on. |
| **Tree-shaking / pruning** (drop tests, C headers, stubs, unused modules) | **Maybe, as `--strip` of known-dead files only** | Measured above: headers, stubs and tests are ~1 MB of a 40 MB zipped payload. Pruning unused modules needs import tracing that dynamic imports defeat (MISSION: "the lockfile decides what goes in"). |
| **Sourceless bundles** (`.pyc` only) | **No** | Saves 1.6 MB here; breaks tracebacks' source lines and `inspect.getsource`. |
| **Stripping native symbols** | **No** | ~5%, and breaks macOS code signatures. |
| **Build-time constants** (esbuild's `--define`) | **No** | Python has no build step to inline into; an environment variable or a generated module does the same. |
| **Shading** (renaming bundled dependencies into a private namespace, as Java's shade plugin and pip's `vendoring` tool do) | **Investigate for `--format dir`** | The closest Python analogue to a JS bundler's module scoping, and a real problem: two plugins in one host application (Splunk, QGIS, Maya) that need different versions of `requests` collide. Hard in general (compiled extensions, entry points, `importlib.metadata`), which is why few tools try. |

## What this changes

- Roadmap "possible future directions" gains: one-file `.py` output (with a PEP 723 header),
  an executable investigation (a research round first), a daemonless OCI image, shading for
  `dir` output, `--strip` of known-dead files. None is started: the owner decides which, and when.
