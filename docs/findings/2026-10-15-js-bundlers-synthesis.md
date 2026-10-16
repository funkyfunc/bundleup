# Design & architecture synthesis: six JavaScript bundlers across eras

Date: 2026-10-15

We studied six reference JavaScript bundlers cloned into `docs/references/` — `esbuild`, `rollup`,
`parcel`, `@vercel/ncc`, `tsup`, and `rolldown` — alongside `bundleup`'s own codebase (`src/bundleup/`)
and design documents.

---

## 1. Why each one won its era

| Bundler | Era | Mental model | The ecosystem friction it killed |
|---|---|---|---|
| **Rollup** | 2015+ | **An ES module scope-hoisting compiler.** Every ES module's top-level declarations are renamed only on collision and concatenated into a single flat scope (`Bundle.ts` → `Chunk.ts`), with a fixed-point liveness pass (`include()`) walking AST `Node.hasEffects(context)` from entry exports. | Browserify and Webpack 1 wrapped every module in a closure (`function(module, exports, __webpack_require__)`) and shipped runtime loader boilerplate in every library. Rollup made libraries smaller and faster *because* they were bundled, and normalized multi-format output (`esm`, `cjs`, `iife`, `umd`) plus the universal `{ resolveId, load, transform, renderChunk, generateBundle }` plugin lifecycle (`src/utils/PluginDriver.ts`). |
| **Parcel** | 2017+ | **A content-addressed, multi-type asset compiler driven by existing project files.** Point it at `index.html`, `src/index.ts`, or `package.json`; it reads `main`, `module`, `bin`, `exports`, and `engines` (`packages/core/core/src/projectPath.ts`) to infer entry points, output paths, and target environments automatically. | Webpack config fatigue (200-line `webpack.config.js` files with `babel-loader`, `css-loader`, `file-loader` just to start a project). Parcel proved that **the project metadata you already wrote *is* the bundler config**, and raised the bar on human diagnostics with structured `Diagnostic` objects (`packages/core/diagnostic/src/diagnostic.js`). |
| **`@vercel/ncc`** | 2018+ | **`gcc` for Node.js.** *"Compile a Node.js module into a single file, together with all its dependencies, gcc-style."* Built specifically for shipping CLIs, serverless functions, and GitHub Actions without `node_modules`. | Server/CLI JS tooling treated `node_modules` as sacred because backend packages use `fs.readFileSync(path.join(__dirname, 'data.bin'))`, dynamic `require()`, and native `.node` C++ addons (`binding.gyp`). `ncc` combined Webpack with `@vercel/webpack-asset-relocator-loader` (`src/index.js`) to statically analyze AST paths, emit companion assets/native addons alongside `index.js`, rewrite `__dirname`/`process.dlopen` references, and preserve executable `#!` shebangs and `chmod 0o755`. |
| **esbuild** | 2020+ | **A parallel native compiler with a sealed, batteries-included two-phase pipeline.** Written in Go (`internal/bundler/bundler.go` + `internal/linker/linker.go`), parsing TS/JS/JSX/CSS/JSON natively with zero plugin calls on the hot path and an integer-indexed symbol table (`ast.Ref{OuterIndex, InnerIndex}`). | Bundling took 10–60 seconds, making build steps feel like batch jobs. By making bundling 10–100× faster (milliseconds), `esbuild` turned bundling into an instant, reflex-speed operation, while setting the gold standard for CLI flag orthogonality (`pkg/cli/cli_impl.go`) and self-teaching error notes (`internal/logger/`). |
| **tsup** | 2021+ | **Opinionated zero-config package/CLI workflow built on `esbuild`.** Reads `package.json` (`src/index.ts`, `src/esbuild/external.ts`), auto-externalizes `dependencies`/`peerDependencies` for libraries while bundling `devDependencies`, injects CJS/ESM interoperability shims (`__dirname`/`import.meta.url` in `assets/cjs_shims.js`, `assets/esm_shims.js`), and makes output executable whenever a `#!` shebang is present (`src/plugins/shebang.ts`). | `esbuild` is a low-level primitive: it doesn't read `package.json`, doesn't emit `.d.ts` declarations, and makes you wire up `external` and CJS/ESM shims yourself. `tsup` wrapped `esbuild`'s speed in `package.json`-aware defaults so `tsup src/cli.ts` just works. |
| **Rolldown** | 2024+ | **Rust speed + esbuild's 2-phase Scan/Link architecture (`crates/rolldown/src/stages/`) + Rollup's plugin and chunking model, built on Oxc.** | Vite's dual-bundler split (`esbuild` in dev, `rollup` in prod) caused subtle behavior drift, and JS-to-Go plugin serialization in `esbuild` bottlenecked complex builds. Rolldown folds first-class `esbuild` features (`platform`, `tsconfig`, `inject`, `define`, `external`) into core Rust so common builds need zero JS plugins. |

---

## 2. API & CLI design taste

### How they keep the 90% case zero-config and the 10% case composable
1. **Orthogonal, flat primitives instead of named target profiles:**
   - Look at `esbuild/pkg/api/api.go` (`BuildOptions`) and `esbuild/pkg/cli/cli_impl.go` (`parseOptionsImpl`): every option falls into one of four orthogonal axes:
     1. **Input**: entry points (`app.js`), `stdin`
     2. **Environment**: `--platform=browser|node|neutral`, `--target=es2020,node18`
     3. **Boundaries**: `--bundle`, `--external:pkg`, `--packages=bundle|external`
     4. **Output**: `--format=iife|cjs|esm`, `--outfile=...` / `--outdir=...`, `--splitting`, `--metafile`
   - Neither `esbuild`, `tsup`, nor `ncc` ships named "presets" like `--preset=aws-lambda` or `--preset=cloudflare`. Instead, each deployment environment is a 2–3 flag combination of those orthogonal axes. `bundleup`'s ADR-0039 (`--format`, `--python-platform`, `--max-size`, `--split` instead of named presets) is already aligned with this philosophy.
2. ** CLI and programmatic API are 1:1 mirrors:**
   - `esbuild`'s `BuildOptions` struct in `pkg/api/api.go` is the exact target of `pkg/cli/cli_impl.go`. Every CLI flag maps deterministically to a field on `BuildOptions`, and `BuildResult` returns structured `{ Errors, Warnings, OutputFiles, Metafile }`.
   - `bundleup`'s `BuildOptions` dataclass (`src/bundleup/_options.py`) and `main(argv) -> BuildOptions -> build()` (`src/bundleup/_cli.py`) follow this exact 1:1 design.
3. **Ergonomic list flags (both repeatable and comma-separated):**
   - `esbuild` (`--target=es2020,chrome58,node18`), `tsup` (`--format cjs,esm --external a,b`), and `rollup` accept **both** repeated flags and comma-separated values. When passing flags in CI matrices or environment variables (`BUNDLEUP_PYTHON_PLATFORM=linux,windows`), comma-separated lists remove friction without adding surface area.
4. **Smart muscle-memory flag hints (`esbuild/pkg/cli/cli_impl.go`):**
   - Instead of generic `unrecognized arguments`, `esbuild` checks a table of common cross-tool mistakes and explains the exact translation (`--platform` → `--python-platform`, `--outfile` → `-o` / `--output`, etc.).
5. **Size summaries & "Why is this in my bundle?" (`ncc/src/cli.js`, `esbuild/internal/bundler/bundler.go`):**
   - `ncc` prints per-asset sizes (`42kB  dist/index.js`) and total build time.
   - `esbuild`'s `PrintSummaryTable` aligns output paths and sizes, dims directory prefixes, bolds filenames and sizes, and with `--metafile` / `--analyze` shows a tree of what contributed to the bundle size and the **import chain** (`required_by`) that pulled each dependency in.

### How their diagnostics teach the user how to fix the problem
Across `esbuild/internal/logger/logger.go`, `parcel/packages/core/diagnostic/src/diagnostic.js`, and `rolldown/crates/rolldown_error/`:
Every diagnostic has **four structural parts**:
1. **Severity + stable code/title**: `error [code]: message`
2. **Primary source location + code frame**: `path/to/file.py:14:8` with the offending source line and a `^` underline pointing at the token:
   ```text
   14 | import yaml
      | ^
   ```
3. **Secondary notes / causal chain (`Notes` / ` origins`)**: e.g., *"Required by `rich` → `pygments`"*, or *"The target environment was set to Python 3.9 here"*.
4. **Actionable fix hint (`Suggestion` / `hints`)**: Concrete copy-pasteable command or flag (e.g., *"Run `uv add pyyaml`, or pass `--external pyyaml` to use the host's copy"*).

---

## 3. How they work under the hood

### Pipeline separation: Scan/Resolve vs. Link/Emit
- **`esbuild` (`internal/bundler/bundler.go` & `internal/linker/linker.go`) and `rolldown` (`crates/rolldown/src/stages/`)** strictly separate:
  1. **Scan / Resolve stage**: Parallel traversal of inputs, dependency resolution, AST parsing, and per-module metadata extraction (cachable per input file/package).
  2. **Link / Emit stage**: Cross-module validation, symbol/import verification, bytecode/code generation, and archive assembly.
- **`@vercel/ncc` (`src/index.js`)** shows how to handle backend/CLI realities that pure frontend bundlers ignore:
  - **Native addons (`.node`) and dynamic `fs.readFileSync(__dirname, ...)`**: `ncc` uses static evaluation to discover files read relative to `__dirname` and native binaries loaded via `bindings` / `node-gyp-build` / `process.dlopen`, emits them into the output directory, and rewrites the paths.
  - **`bundleup`'s architectural advantage over `ncc`**: Because Python's `zipimport` cannot load `.so`/`.pyd` C extensions or satisfy `open( Path(__file__).parent / "template.pptx" )` (gauntlet 05, 10, 14, 21, 22, 23), `bundleup` (ADR-0005, ADR-0010, ADR-0023) extracts a two-entry outer `.pyz` with a stored inner payload into a content-addressed cache directory (`<cache>/<name>-<hash12>/site`), runs `.pth` files, preserves wheel helper binaries (`bin/`), and sets `PYTHONPATH` to a selective `sitecustomize.py` (ADR-0027, ADR-0037). This gives `bundleup` **100% native extension and `__file__` fidelity without fragile AST path rewriting**, while `bundleup check` (`_imports.py`) still performs static AST scanning to warn about build-time hazards (`undeclared-import`, `dynamic-import`, `syntax-error`, `python-range`, `stdlib-range`).

---

## 4. What `bundleup` already nails — and what we are stealing and implementing

### Where `bundleup` already matches or beats the best JS bundlers
- **Zero-config from existing files (Parcel / tsup style)**: `bundleup build` reads `pyproject.toml` + `uv.lock`, `pylock.toml`, `requirements.txt`, or a PEP 723 script (`# /// script`), infers the entry point (`[project.scripts]`, `__main__.py`, single `.py` file), and outputs `dist/<name>.pyz`.
- **Orthogonal flags instead of preset soup (`esbuild` style)**: `--format pyz|py|exe|dir|zip`, `--python`, `--python-platform`, `--max-size`, `--split`, `--smoke`.
- **Two-zip runtime architecture**: Outer `.pyz` has only 2 entries (`__main__.py` and `payload.zip` stored uncompressed), keeping `zipimport` directory parsing O(1) (~0 ms) on warm starts regardless of whether the bundle has 10 files or 20,000 files (PyTorch).

### Concrete improvements stolen from `esbuild`, `tsup`, `ncc`, `parcel`, and `rolldown` (implemented now)

1. **`--external PKG` (`BuildOptions.external`, `BUNDLEUP_EXTERNAL`, `[tool.bundleup] external`) — from `esbuild`, `tsup`, `ncc`, `rollup`:**
   - Every major bundler has `--external`. In Python, the #1 reason bundles fail `--max-size` (AWS Lambda layers with `boto3`/`botocore`, Databricks/Snowflake/SageMaker containers with `torch`/`numpy`/`pyarrow`, Blender/QGIS plugins, or system packages like `gi`/`apt`) is that the target host *already provides* specific heavy packages.
   - Passing `--external boto3` (or `external = ["boto3"]` in `[tool.bundleup]`):
     - Prunes the external package *and its exclusive transitive dependencies* from `uv export` (`--prune <pkg>`) and strips it from `pylock.toml` before wheel coverage and installation.
     - Suppresses `undeclared-import` false positives for modules provided by external packages.
     - Sets `EXTERNAL = True` in the `.pyz` loader so the bundle keeps its own `site` first on `sys.path` while inheriting the host Python's `site-packages` after it (`BUNDLEUP_INHERIT_PATH=1`), allowing the bundled code to import `--external` packages from the host at runtime.
2. **Comma-separated list flags (`--python 3.11,3.12`, `--python-platform linux,windows`, `--external boto3,botocore`) — from `esbuild` & `tsup`:**
   - Repeatable flags remain supported, and comma-separated values now work seamlessly across CLI flags, `BUNDLEUP_*` environment variables, and `BuildOptions`.
3. **Self-teaching CLI errors for muscle-memory flags and bare paths — from `esbuild/pkg/cli/cli_impl.go`:**
   - Typing `bundleup app.py` or `bundleup .` hints: `did you mean \`bundleup build app.py\`?`
   - Typing `bundleup dist/app.pyz` hints: `to run it: \`python3 dist/app.pyz\`; to check its integrity: \`bundleup verify dist/app.pyz\``
   - Common flags from `esbuild`, `pex`, `pyinstaller`, and `uv` (`--platform`, `--target`, `--outfile`, `--outdir`, `--entrypoint`, `--main`, `--externals`, `--onefile`, `--analyze`, `--metafile`) give an exact translation hint instead of a generic error.
4. **Source code frames (`line | code` + `^`) on diagnostics and config errors — from `esbuild/internal/logger/` & `parcel/packages/core/diagnostic/`:**
   - `syntax-error`, `python-range`, `undeclared-import`, and `[tool.bundleup]` configuration errors now include the exact line number and an inline source snippet with a `^` pointer in `detail` (rendered in terminal output and included in `--json`).
5. **Dependency chain (`required_by`) and percentage size breakdown in `bundleup check -v` — from `esbuild --analyze` & `ncc`:**
   - `PackageSize` in `bundleup check` now computes `required_by: tuple[str, ...]` by walking `Requires-Dist` metadata from the project root (`BFS` shortest dependency path).
   - `bundleup check -v` displays each package's share of total unpacked size (`42.1%`) and, for transitive dependencies, shows *why* it's in the bundle (`via rich → pygments`).
6. **Lock-keyed `uv export` build cache — from `parcel` & `esbuild` incremental caching:**
   - On warm builds when `uv.lock` (or `<script>.lock`) and `pyproject.toml` haven't changed, `bundleup` caches the exported `pylock.toml` in `<cache>/exports/<sha256>.toml` (cleared by `bundleup cache clean --build`), skipping the `uv export` subprocess on repeated builds and `bundleup check` runs.
