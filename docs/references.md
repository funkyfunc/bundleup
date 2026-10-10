# Reference projects

Open-source projects that solved problems bundleup also has. **Read them for ideas before writing
code in the same area.** Copy code only from permissive licenses, keep the license notice, and
record what you borrowed in the relevant ADR or in [learnings.md](learnings.md). Paths and
licenses checked 2026-10-04.

## Bundling and runtime (the core)

| Project | Look at | Why | License |
|---|---|---|---|
| [linkedin/shiv](https://github.com/linkedin/shiv) | `src/shiv/bootstrap/__init__.py` | Small, readable loader: extract to a cache, set up `site`. Closest design to ours. Note its lock-file collision bug (shiv#203) | BSD-2-Clause |
| [pex-tool/pex](https://github.com/pex-tool/pex) | `pex/pex_bootstrapper.py`; `--platform` / `--complete-platform` | The correctness bar: interpreter selection, multi-platform bundles, run modes, isolation (`-sE`) | Apache-2.0 |
| [ClericPy/zipapps](https://github.com/ClericPy/zipapps) | `zipapps/main.py` | The only baseline tool that let child processes see the bundle's packages (gauntlet 19) | MIT |
| [pypa/installer](https://github.com/pypa/installer) | `src/installer/_core.py` | Installing a wheel exactly to spec; small, typed, standards-first | MIT |
| [pypa/packaging](https://github.com/pypa/packaging) | `src/packaging/tags.py` | Wheel tags and platform compatibility: the heart of cross-target builds | Apache-2.0 / BSD |
| [astral-sh/uv](https://github.com/astral-sh/uv) docs | `uv pip install --python-platform`, `uv export` | What we delegate to (ADR-0006); how uv resolves for other platforms | MIT / Apache-2.0 |
| [a-scie/jump](https://github.com/a-scie/jump) | `README.md` "Format", `docs/packaging.md`, `jump/src/lift.rs` | The launcher `--format exe` puts at the head of an executable; the manifest and layout rules (ADR-0047) | Apache-2.0 |
| [astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone) | release assets, `install_only_stripped` | The interpreters uv installs and executables carry | MPL-2.0 |
| [Node single executable applications](https://nodejs.org/api/single-executable-applications.html) | the blob injected into a named section | How an executable with an embedded payload stays signable, if bundleup ever needs signing | MIT |

## Pre-ship analysis (`bundleup check`)

| Project | Look at | Why | License |
|---|---|---|---|
| [netromdk/vermin](https://github.com/netromdk/vermin) | `vermin/main.py` | Minimum-Python-version detection | MIT |
| [ronaldoussoren/modulegraph2](https://github.com/ronaldoussoren/modulegraph2) | `modulegraph2/_modulegraph.py` | Import-graph construction | MIT |
| [pyinstaller/pyinstaller-hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib) | the hooks | 15+ years of "this package secretly imports X / needs data file Y". **Check the license before reusing anything** | check |

## CLI and library design

| Project | Look at | Why | License |
|---|---|---|---|
| [clig.dev](https://clig.dev) ([source](https://github.com/cli-guidelines/cli-guidelines)) | the whole guide | Command Line Interface Guidelines: output, errors, flags, config, interactivity | CC-BY-SA-4.0 (quote, don't copy) |
| [astral-sh/uv](https://github.com/astral-sh/uv), [astral-sh/ruff](https://github.com/astral-sh/ruff) | error messages, `--help` output | The experience we want to match: `error:` / `hint:` messages, fast, quiet defaults | MIT / Apache-2.0 |
| [pypa/build](https://github.com/pypa/build) | `src/build/__main__.py` vs `src/build/__init__.py` | A tool that is both a library and a CLI, which the roadmap's Python API needs | MIT |
| [pypa/pipx](https://github.com/pypa/pipx) | `src/pipx/main.py` | A well-liked Python CLI that manages environments for users | MIT |

## Platforms

| Source | Why |
|---|---|
| [AWS Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html), [runtimes](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html) | Size limits, Python runtimes, architectures for the Lambda [recipe](recipes.md) |
| [splunk/splunk-sdk-python](https://github.com/splunk/splunk-sdk-python) README | The `bin/lib` + `--platform` pattern `--format dir` should replace |
| [Blender: Python wheels in extensions](https://docs.blender.org/manual/en/latest/advanced/extensions/python_wheels.html) | How a host app expects per-platform wheels |
| [Agent Skills: using scripts](https://agentskills.io/skill-creation/using-scripts) | Script conventions for agents (no prompts, `--help`, structured output, exit codes) |
| [Claude code execution tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool), [Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) | The Claude API sandbox: Python 3.11, no network, no installs, preinstalled libraries |
| [Gemini code execution](https://ai.google.dev/gemini-api/docs/code-execution) | Fixed library list, no installs, 30 s per run |
| [OpenAI shell tool](https://developers.openai.com/api/docs/guides/tools-shell), [Codex cloud environments](https://developers.openai.com/codex/cloud/environments) | Network off by default with an allowlist; installs in a setup phase |
| [E2B templates](https://e2b.dev/docs/sandbox-template), [Modal images](https://modal.com/docs/guide/images) | Sandboxes built from images; Modal installs from `uv.lock` (`uv_sync`) |
| [MCPB PR #158](https://github.com/modelcontextprotocol/mcpb/pull/158) | Why MCP bundles gained a `uv` runtime: vendored Python broke on version-specific compiled packages |
| [ComfyUI-Docker #170](https://github.com/pixeloven/ComfyUI-Docker/issues/170) | A measured comparison of shipping options; pex scies fail on noexec `/tmp` |
