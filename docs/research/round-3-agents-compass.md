# Is "the bundler for the agent era" authentic? Python distribution to AI agents, October 2026

**Partly. There is one specific, documented agent case that a no-install, no-network `.pyz` solves better than the tools the agent ecosystem recommends today. That case is narrower than "the agent era," and bundleup should lead with "Python that runs where you can't install anything," with agent sandboxes as the first named destination.** The case is skills and agent-written scripts that must run in sandboxes with no network or no package installation (Claude API code execution, Claude.ai with egress off, Codex cloud agent phase). The ecosystem's own recommended pattern for those, `uv run` with PEP 723 inline metadata, needs a network on first run. Almost everything else in the agent world (local MCP servers, Claude Code on a laptop, cloud coding agents with setup scripts) already has network-at-install-time solutions, and those platforms have converged on uv rather than on vendored bundles.

## TL;DR
- **Authentic, but as a use case, not a category.** The hard, documented gap is offline agent sandboxes: Claude's API code-execution container has "no internet access, so Claude can't download packages at runtime," and Skills on the API have "no runtime package installation."\[1\] Yet the Agent Skills guide tells authors to declare dependencies with PEP 723 and run `uv run`.\[2\] A pre-resolved single file closes exactly that gap.
- **The disproof is strong elsewhere.** MCPB, the main Python-in-agent packaging format, abandoned vendoring for Python. Its README says traditional bundles "cannot portably bundle compiled dependencies (e.g., pydantic, which the MCP Python SDK requires)," and v0.4 added a `uv` server type where the host installs dependencies.\[3\] Codex, Copilot, Cursor and Claude Code cloud all give you a network-enabled setup phase. A `.pyz` inherits the same compiled-wheel limitation, so it only beats uv where the network is absent *and* the target platform is known.
- **Lead with:** "One file, plain Python, no install, no network." Then the answer to "what do you mean it's for agents?" is: *"Agent sandboxes are the commonest place you can't install anything — Claude's code-execution container has no network and Codex agents run offline by default — so bundleup turns a skill's script and its locked dependencies into one file that runs there with plain `python`."* Build a skill output target and a sandbox target profile; don't build an MCPB target first.

---

## 1. Verdict

**Documented facts that support the agent angle:**
- The Claude API code-execution tool runs Python 3.11 on Linux x86_64 with 5 GiB RAM, 5 GiB disk and 1 CPU. Per the docs, "The container has no internet access, so Claude can't download packages at runtime: only the pre-installed libraries are available."\[1\]
- Anthropic's Agent Skills overview says Skills on the Claude API have "No network access" and "No runtime package installation: Only pre-installed packages are available." On claude.ai, "Depending on user/admin settings, Skills may have full, partial, or no network access."\[4\]
- The agentskills.io guide "Using scripts in skills" recommends self-contained scripts that "declare [their] own dependencies inline" in a PEP 723 block and run via `uv run`, which "creates an isolated environment, installs the declared dependencies, and runs the script."\[2\] The spec's own `compatibility` example is "Requires Python 3.14+ and uv."\[5\] Both assume network plus uv. The documented Claude API sandbox offers neither (Python 3.11, no network).
- Codex cloud: "By default, Codex blocks internet access during the agent phase. Setup scripts still run with internet access."\[6\]

**Documented facts that undercut it:**
- MCPB has moved Python toward host-side `uv` installs. The experimental `uv` server type, added in manifest v0.4 (PR #158, Dec 3, 2025), means the bundle "Must NOT include server/lib/ or server/venv/."\[3\] During review, maintainers asked whether "raw python support may be removed and steer people to uv."\[7\]
- Every cloud coding agent researched gives a networked setup phase: Codex setup scripts, Copilot `copilot-setup-steps.yml` plus a recommended allowlist, Cursor `install` with snapshotted Builds, and Claude Code cloud with "Trusted" access to PyPI by default.\[8\]\[9\]\[10\]\[11\]\[12\]\[13\]\[14\]\[15\] Dependency installation there is a solved, general CI problem.
- A `.pyz` cannot portably carry compiled extensions. That is exactly how vendored Python MCPB bundles fail (see §4). bundleup's offline guarantee is therefore real only for pure-Python closures or for per-target builds.

**Interpretation:** The agent angle is authentic when it names a concrete target: "offline agent sandboxes, starting with skills." It is not authentic as "the bundler for the agent era." That framing implies agents need a new packaging primitive, and most agent surfaces either have network at install time or have standardized on uv. The honest pitch is general ("runs where you don't control the environment"). Agent sandboxes are the sharpest, fastest-growing example, and skills are the one agent format where a bundler adds something no platform currently provides.

---

## 2. Distribution formats (Part 1)

| Format | What ships | How Python deps are expected to ship | Official Python recommendation | What goes wrong |
|---|---|---|---|---|
| **Agent Skills (agentskills.io spec)** | A folder with `SKILL.md` (YAML frontmatter + instructions) plus optional `scripts/`, `references/`, `assets/` | Spec: scripts should "Be self-contained or clearly document dependencies"; "Supported languages depend on the agent implementation" | PEP 723 inline metadata plus `uv run scripts/x.py` (or `pipx run`); one-off tools via `uvx` | Assumes uv and network, which the Claude API sandbox lacks. `compatibility` is free text ("Requires Python 3.14+ and uv"), not machine-checked |
| **Claude skills (claude.ai / API / Claude Code)** | Zip upload on claude.ai, `/v1/skills` upload on the API, directories in `~/.claude/skills/` or `.claude/skills/` for Claude Code; surfaces don't sync | API: pre-installed packages only. Claude Code: "Global package installation discouraged: Skills should only install packages locally" | Same as the spec; no Anthropic-specific bundling format | The same skill behaves differently per surface (network full, partial or none) |
| **Skill package managers (Microsoft APM, skills.sh CLI)** | APM: `apm.yml` manifest plus `apm.lock.yaml` pinning "exact source ref and content hash," deployed into each harness's directory\[16\] | APM manages *context* files (skills, prompts, MCP declarations). It does **not** resolve Python dependencies of skill scripts (docs silent on this) | None | Path mismatches between installers and agents (e.g., `~/.agents/skills/` vs `~/.claude/skills/`, Layer5 blog)\[17\] |
| **Claude Code plugin marketplaces** | `/plugin install x@marketplace` bundles skills, commands, MCP servers | Inherits the skill/MCP model | None specific (not deeply verified here) | — |
| **Local stdio MCP servers (`uvx`/`pipx`/`npx`/Docker)** | Client config with `command` + `args` | Resolved from PyPI at launch by `uvx` | `uvx <package>` is the de facto Python default (dbt, ElevenLabs, Chronulus READMEs)\[18\]\[19\]\[20\] | `spawn uvx ENOENT` when uv is absent or not on the GUI app's PATH; first-run download; needs network\[21\] |
| **Remote MCP servers** | HTTP endpoint | None on the client | — | Sidesteps local packaging entirely, which is the strongest argument against a local-bundle need |
| **MCP Registry (`server.json`)** | Metadata pointing at packages: `registryType` npm, pypi, nuget, oci, mcpb, etc., plus `runtimeHint` (`uvx`, `npx`, `docker`)\[22\]\[23\] | PyPI packages: "currently supports the official PyPI registry (https://pypi.org) only." MCPB artifacts must be hosted on GitHub or GitLab releases\[24\] | `registryType: pypi` + `runtimeHint: uvx`\[25\]\[26\] | Metadata drifts from reality: package not on PyPI (pixeltable PR #11), wrong command so the handshake dies (Archy #462)\[27\]\[28\] |
| **MCP Bundles (`.mcpb`, formerly `.dxt`)** | Zip with `manifest.json`; server types `node`, `python`, `binary`, `uv` | `python`: "All dependencies must be bundled" in `server/lib` or `server/venv`. **`uv` (experimental, v0.4+)**: ships `pyproject.toml`, host installs via uv; "Handles compiled dependencies (pydantic, numpy, etc.)", "No user Python installation required" | README now recommends the `uv` runtime for Python; Node is recommended overall because it ships with Claude Desktop | Vendored `python` bundles break on other OS/Python versions; third-party hosts don't support `uv` yet (Smithery CLI #801); signing exists but verification is buggy (see §5) |
| **Other agent tools** | Gemini CLI extensions, Codex, Cursor, Copilot, Windsurf all consume MCP servers and (per apm/agentskills.io) Agent Skills | Same as MCP/skills | **Not verified in this research:** whether any of these defines its own code-bundle format beyond MCP/skills | — |

**MCPB status (Oct 2026):** The format lives at `modelcontextprotocol/mcpb` and the `@anthropic-ai/mcpb` CLI was at 2.x (2.1.2 cited in Smithery #801).\[29\] The `uv` type is labeled experimental.\[30\] Interpretation: MCPB's answer to Python dependencies is "don't bundle them; let the host run uv." That directly competes with bundleup's premise for desktop MCP.

---

## 3. Execution environments (Part 2)

"Silent" means the official docs I found don't say.

| Environment | OS / CPU | Python | uv / pip | Network | Writable / persistence | Notable |
|---|---|---|---|---|---|---|
| **Claude API code-execution tool** | Linux container, x86_64 | 3.11 | Silent on uv; installs impossible (no network) | **None** ("No outbound network requests permitted") | Workspace dir; container reusable by ID; earlier docs say containers expire 30 days after creation; REPL state persists with `code_execution_20260120`+ | 5 GiB RAM / 5 GiB disk / 1 CPU; 90-second wall-clock limit per Python cell in programmatic tool calling; files returned only from `$OUTPUT_DIR` |
| **Claude API Skills** | Same container | Same | Pre-installed only | None | Same | "No runtime package installation" |
| **Claude Managed Agents environments** | Silent | Silent | `packages` field pre-installs pip packages, "cached across sessions that share the same environment"\[31\] | `limited` (allow-list) or `unrestricted`\[31\] | Cached per environment | A platform-native "save deps for next time" mechanism |
| **Claude.ai file creation / analysis** | Ubuntu/gVisor per third-party probing (not official)\[32\] | Silent | pip from approved sources when egress on | Admin-controlled: off, package managers only, or broader allow-list | Silent | With egress off, "Claude operates with pre-installed packages only, with no internet access"\[33\] |
| **Claude Code (local)** | User's machine (macOS/Linux/Windows) | Whatever's installed | Whatever's installed | User's network; optional sandbox with `network.allowedDomains` | User's FS | Skills "have the same network access as any other program" |
| **Claude Code cloud sessions** | Anthropic-managed VM | Silent in fetched pages | PyPI reachable under Trusted | None / Trusted (default; npm, PyPI, RubyGems, crates.io) / Full / Custom\[12\]\[34\] | Setup script runs before each session | Anthropic-hosted environments can't replace the base image (third-party, replicas.dev); self-hosted environments in beta\[35\] |
| **ChatGPT data analysis** | Silent | Silent | Silent | **None**: "cannot make external web requests or API calls" | "stateful Jupyter notebook environment" | — |
| **OpenAI API Code Interpreter** | "fully sandboxed virtual machine" | Silent | Silent | Silent | Container "expires if it is not used for 20 minutes"; data then "not recoverable" | Memory 1g default; 4g/16g/64g tiers |
| **OpenAI Codex cloud** (docs now labeled "Legacy") | `codex-universal` image; OpenAI's README is silent on the Ubuntu version and says "we only run the linux/amd64 version" | Pinnable runtime versions | Auto-installs pip/poetry/pipenv deps in setup | Setup: open. Agent: **off by default**; on with allow-list (None / Common dependencies / All) and optional GET/HEAD/OPTIONS-only | Container state cached "for up to 12 hours" (OpenAI Codex docs) | Secrets removed before agent phase; setup `export`s don't persist |
| **GitHub Copilot coding (cloud) agent** | Ubuntu x64 by default ("standard GitHub Actions runner"); Windows x64 supported; no macOS | Whatever `ubuntu-latest` has (Copilot docs silent) | Install in `copilot-setup-steps.yml` | Firewall on by default with recommended allowlist; applies only to processes started via the agent's Bash tool | Ephemeral | 59-minute max session; firewall incompatible with self-hosted runners and Windows |
| **Cursor cloud agents** | Ubuntu VM per third parties; custom Dockerfile allowed | Silent | Via `install` command | Configurable per environment (details not fetched) | Builds snapshot **disk only**; "Running processes, shell exports, and in-memory caches stop"\[11\] | `.cursor/environment.json` → personal → team environment resolution; snapshot-not-applied bugs reported\[8\]\[36\] |
| **Devin, Windsurf, Daytona, Modal** | Not verified in this research | — | — | — | — | Don't cite specs for these without checking |
| **E2B** | Firecracker microVM ("default base sandbox template")\[37\]\[38\] | Silent in fetched pages | Silent | **Open by default**; `allow_internet_access=False` to isolate\[39\] | Pause saves filesystem and memory; default timeout 300s; max 24h (Pro) / 1h (Hobby)\[37\]\[40\] | — |
| **Vercel Sandbox** | Since Aug 2026, SDK v3 defaults to Ubuntu `vercel/sandbox/universal`; legacy Amazon Linux 2023 runtimes deprecated\[41\] | `python3.13` legacy runtime image\[42\] | sudo available\[42\] | `allow-all` default; `deny-all` or domain rules, updatable at runtime\[43\]\[44\] | Snapshots; ephemeral | Max session 45 min (Hobby), 24h (Pro), "up from 5 hours" (Vercel pricing docs and changelog) |
| **Cloudflare Sandbox** | Ubuntu 22.04 images (SDK 0.x); new `cloudflare/debian-trixie` system image ships Node 24 only\[45\]\[46\] | 3.11 in `-python` variant\[46\] | pip | Silent in fetched pages | "Sandbox state exists only while the container is active"; sleeps after 10 min idle by default\[47\] | SDK 1.0 is now utilities, not a base class\[45\] |

**Interpretation:** Only three documented environments are truly no-network-for-the-code: Claude API code execution/Skills, ChatGPT data analysis, and Codex's default agent phase. Claude.ai and Claude Code cloud can also be configured that way. These are the only places where bundleup's "no network" property is decisive rather than convenient. And the most important one (Claude API) has a *known, fixed* target: CPython 3.11, Linux x86_64. That makes per-target builds with compiled wheels feasible, which is a genuinely agent-specific opportunity.

---

## 4. Evidence of pain (Part 3)

No source found quantifies failure rates. The items below are individual, verifiable reports, not prevalence data.

**uv not installed / not on PATH (local MCP):**
- MCP discussion #20 (Nov 2024): "Error: spawn uvx ENOENT" on the official sqlite quickstart. A later reply reports the same on Windows with Cowork.\[48\]
- Cline issue #1160: "spawn uvx ENOENT" on Windows 11.\[49\]
- dbt's MCP troubleshooting docs explain the cause as "Your MCP client (like Claude desktop) can't find uvx in its PATH because it starts with a limited environment." ElevenLabs, Chronulus and Databutton docs all carry the same warning, which is effectively a standard "requires uv" note.\[19\]\[20\]\[21\]\[50\]

**Compiled extensions / platform-specific wheels:**
- goodreads-mcp issue #89: the released `.mcpb` "only runs on Linux x86_64 with CPython 3.11" because `pip install --target` vendored compiled modules (e.g., `_pydantic_core.cpython-311-x86_64-linux-gnu.so`).\[51\] The fix PR #99 names four compiled packages in `mcp`'s closure (pydantic-core, rpds-py, cffi, cryptography). It switched to the `uv` type and added a CI check that fails if a multi-platform bundle contains `.so`/`.pyd`/`.dylib`.\[52\]
- The MCPB README itself: "Cannot portably bundle compiled dependencies (e.g., pydantic, which the MCP Python SDK requires)."\[53\]
- dfkunstler/mcp-server-for-oscal PR #6 and ahmedkeewan/service-buddy both chose the `uv` type explicitly because compiled dependencies "can't be portably vendored."\[54\]\[55\]
- MCP python-sdk #1451: install failure on Python 3.14 from an older pydantic-core. #570: `No module named 'pydantic_core._pydantic_core'` on Alpine (musl).\[56\]\[57\]

**Wrong Python version / Windows:**
- The Agent Skills spec's own example pins "Python 3.14+,"\[5\] against a Claude API sandbox that runs 3.11.
- goodreads-mcp also had a Windows bug: `manifest.json` "joins PYTHONPATH with ':' which is not the path-list separator on Windows."\[52\]
- alirezarezvani/claude-skills install guide: Windows consoles "default to a legacy codepage (e.g. cp1252)" that crashes skill tools printing Unicode.\[58\]

**Missing deps / blocked network in skills:**
- The same guide's fix for "Module not found" is "pip install pyyaml," i.e. manual dependency install.\[58\]
- Medium ("Avoid dependency hell for Claude SKILLs"): "When [Claude Code] sees the ModuleNotFoundError, it reasons, and runs pip install … itself," producing "Global environment bloat," "Version conflicts," and "Security concerns from dynamic installs."\[59\]
- sharable.link: skills calling external APIs fail on claude.ai unless the domain allowlist is widened.\[60\]
- OWID docs: under Claude Code cloud's Trusted level, their own hosts are refused, "and the failure looks like an authentication error rather than a network one."\[61\]

**Registry and environment drift:**
- pixeltable PR #11: `server.json` advertised a uvx package "not found in the package registry."\[27\]
- Archy #462: the registry entry runs the wrong command, so "every registry-driven install fails the handshake."\[28\]
- Smithery CLI #801: rejects a valid MCPB `uv` bundle ("Could not determine bundle runtime").\[29\]
- Cursor forum: tools installed in a snapshot give "command not found" inside the actual agent.\[36\]

**What authors do instead (documented):**
- "Requires uv" notes and absolute-path workarounds (dbt, ElevenLabs).\[19\]\[21\]
- Switching MCPB to the `uv` type (goodreads, oscal, service-buddy).\[52\]\[54\]
- Docker sandboxes for skills (Medium post).\[59\]
- Node over Python, because Node "ships with Claude Desktop" (MCPB README).\[62\]
- Zero-dependency Python (e.g., skill-security-audit advertises "Pure Python, zero dependencies").\[63\]
- Per-platform build matrices (proposed and rejected in goodreads #89/#99 as "one asset per platform and Python minor for the user to pick by hand").\[52\]

**Interpretation:** The loudest pain (uvx ENOENT, MCPB compiled wheels) belongs to *desktop MCP*, and the ecosystem is fixing it with host-managed uv, not bundles. The pain bundleup uniquely addresses is quieter: skill scripts with third-party deps in offline sandboxes. There, the only documented alternatives are "use only pre-installed packages" or "avoid dependencies."

---

## 5. Agents as packagers (Part 4) and trust (Part 5)

### Agents as packagers
**Evidence is thin.** I found no primary source documenting agents systematically writing tools they then can't reuse. What exists:
- Agents fix missing dependencies by running `pip install` themselves (Medium post), which works only with network.\[59\]
- Platforms persist *environments*, not *artifacts*: Claude API container reuse and REPL persistence, Managed Agents `packages` cached per environment, Cursor disk snapshots, Codex container caching, E2B pause/resume.\[11\]\[31\]\[40\] None of them offers "save this script plus its locked deps as a portable file."
- Skills are the closest thing to "save this for next time." But a skill's `scripts/` inherits whatever the target sandbox has, and the official advice (`uv run`) assumes network.

**Would a non-interactive CLI plus a teaching skill change anything?** The plausible concrete loop: an agent working in a networked environment (Claude Code locally, Codex setup phase) builds a tool and bundles it with `bundleup --target claude-api` (CPython 3.11, manylinux x86_64). It drops the `.pyz` into a skill's `scripts/` and uploads the skill to the Claude API or claude.ai, where it runs offline. This is plausible and unserved, but **no evidence of demand was found**. Treat it as a hypothesis to validate with users, not a fact.

### Trust and security
**How platforms vet today (documented):**
- Snyk's ToxicSkills scan (Feb 5, 2026) covered 3,984 skills from ClawHub and skills.sh. It found 1,467 (36.82%) with a security issue and confirmed 76 with malicious payloads.\[64\]
- Koi Security researcher Oren Yomtov's audit "ClawHavoc" (Feb 1, 2026) found "341 malicious skills – 335 of them from what appears to be a single campaign" among 2,857 on ClawHub; that campaign delivered Atomic macOS Stealer.
- skills.sh runs three scanners (Gen Agent Trust Hub, Socket, Snyk). ClawHub labels skills CLEAN/SUSPICIOUS/MALICIOUS, but suspicious skills remain installable (The New Stack).\[65\]
- Trail of Bits' June 3, 2026 post "The Sorry State of Skill Distribution" reports: "We recently bypassed ClawHub's malicious skill detector, Cisco's agent skill scanner, and all three of the scanners integrated into skills.sh"; per the Cloud Security Alliance, three of the four bypasses took under an hour to develop.
- APM pins content hashes, scans for hidden Unicode, and "blocks transitive MCP servers unless they are explicitly declared or trusted."\[16\]
- MCPB has `mcpb sign`/`verify` (PKCS#7, detached). Open PR #286 reports `verify` "reports every signed bundle as 'Extension is not signed',"\[66\] and signed bundles reportedly failed to load in Claude Desktop (#278).\[67\]
- Runtime controls: Codex removes secrets before the agent phase;\[68\] Copilot's firewall is on by default;\[69\] Vercel brokers credentials outside the sandbox.\[70\]

**Does "offline, with a manifest of exactly what's inside" help?** Interpretation:
- **It helps with one real concern.** `uv run`/`uvx` resolve dependencies *at execution time*, often unpinned, so the code that runs can differ from what was reviewed. A locked bundle with per-file hashes makes the reviewed artifact the executed artifact, and it works without registry access. That is the same value APM's lockfile provides for context files.
- **It does not address the dominant documented threat.** Malicious instructions in `SKILL.md` and prompt injection are what the ToxicSkills findings center on, and a bundler can't see those.\[71\]
- **It's complementary to sandboxing, not a substitute.** A manifest is useful for reviewers and scanners, but it is a secondary selling point, not a lead.

---

## 6. Agent-specific vs. general (Part 6)

| Candidate feature | Only agents | More for agents | Equally (Lambda/CI/air-gapped) | Reasoning |
|---|---|---|---|---|
| Offline guarantee (no network at run time) | | ✓ | | Air-gapped servers need it too, but documented agent sandboxes are offline *by default* (Claude API, ChatGPT, Codex agent phase) |
| No install step / plain `python` | | | ✓ | The core value everywhere; Lambda and CI want it as much |
| Target profiles for known sandboxes (e.g., CPython 3.11 / manylinux x86_64 for Claude API) | ✓ | | | Only agent sandboxes publish a fixed interpreter/arch you can't change. This makes compiled wheels shippable |
| Skill output format (`scripts/*.pyz` + `SKILL.md` snippet + `compatibility` line) | ✓ | | | No equivalent outside agents |
| MCP-server output (MCPB `python` type with vendored deps) | ✓ | | | Agent-only, but competes with MCPB's own `uv` type and has the compiled-wheel problem |
| Machine-readable output (JSON results, stable exit codes) | | ✓ | | CI wants it too; agents need it to self-correct without human reading |
| Agent-operable CLI (non-interactive, deterministic, no prompts) | | ✓ | | Same as good CI ergonomics; marginally more important for agents |
| Manifest + hashes | | | ✓ | Supply-chain review is general (SBOM-style); agent registries just make it topical |
| Compatibility pre-check (fail if closure has compiled wheels not matching target) | | ✓ | | The exact failure in goodreads #89; matters wherever targets differ, but agent hosts span OSes |
| Sandbox-aware loader (extract native libs to a writable temp dir, tolerate read-only home) | | | ✓ | Read-only FS is classic Lambda; agent sandbox FS rules are mostly undocumented |
| Small start-up time | | | ✓ | Lambda cold starts care at least as much; Claude's 90-second per-cell cap is generous |

**Steelman: "lead with agents."**
- It's the only market where the incumbent recommendation (`uv run` + PEP 723) is documented to be impossible in the flagship runtime (Claude API Skills: no network, no installs).
- Skills are spreading across agents per agentskills.io, and nobody owns "skill scripts with dependencies."
- Sandboxes publish fixed targets, so bundleup can promise "works there" concretely.
- Positioning against a fresh pain beats being "another shiv/pex."

**Steelman: "agents are just one destination."**
- Most agent surfaces have network at setup time, and the MCP world has standardized on uv (MCPB `uv` type, registry `runtimeHint: uvx`).
- Remote MCP servers remove local packaging entirely.
- The compiled-wheel limitation means bundleup can't beat uv for multi-platform desktop MCP.
- Every non-format feature above is equally valuable for Lambda, CI and air-gapped hosts, which are larger, established, and budgeted.
- Prior art already covers the general case: stdlib `zipapp`, shiv (extracts to a cache dir), pex (multi-platform), PyInstaller (bundles the interpreter). These are well-known tool behaviors I did not re-verify for this report. "Agent era" branding invites the question "what's actually different?", and for most surfaces the honest answer is "nothing."

**Conclusion:** The second steelman wins on *positioning*, the first on *wedge*. Lead with the general promise and use agent sandboxes and skills as the headline use case and first-class output target.

---

## 7. Ranked features worth building for the agent case

1. **Sandbox target profiles**, starting with `claude-api` (CPython 3.11, Linux x86_64, offline). They resolve and embed matching compiled wheels, turning the "can't bundle pydantic" problem into a solved one for a known target. This is the single most agent-specific, defensible feature.
2. **Skill output format.** Emit `scripts/<tool>.pyz` plus a ready `SKILL.md` "Available scripts" stanza and an honest `compatibility` line ("Requires Python ≥3.11; no network needed").
3. **Compatibility pre-check.** Refuse, or warn loudly, when the closure contains native code that doesn't match the declared target(s), mirroring goodreads PR #99's CI guard. This prevents the most common documented failure.
4. **Agent-operable CLI.** Non-interactive by default, `--json` output, stable exit codes and actionable error text, plus a companion skill that teaches agents when and how to bundle (build in a networked phase, ship to an offline one).
5. **Manifest with per-file hashes**, emitted as JSON next to the bundle. Cheap, useful to registries and scanners, but secondary.
6. **Native-extension extraction to a writable temp dir**, with documented behavior on read-only home. General value; needed to make item 1 work.
7. **(Defer) MCPB output.** Only for single-platform or offline cases, since MCPB's `uv` type already serves online desktop hosts.

---

## Caveats
- Several sandboxes (Devin, Windsurf, Daytona, Modal) were not verified. Where this report says "silent," that refers to the official pages consulted, not a guarantee that no documentation exists.
- Some environment details come from third parties: Claude.ai gVisor and Claude Code cloud GA on Sept 23, 2026. Treat them as unconfirmed; the Codex image's Ubuntu version is not stated in OpenAI's codex-universal README.
- Fast-moving items to re-check before publishing positioning: MCPB `uv` type moving from experimental to stable (or raw `python` being removed), MCPB signature verification fixes (PR #286), Claude API container specs (tool version `code_execution_20260521` was current at writing), and Vercel's base-image migration.
- No adoption or failure-frequency data exists in the sources found. All pain evidence is anecdotal but primary (issues, PRs, vendor docs).

## 8. Sources
Primary sources are named inline throughout: Anthropic platform and Claude Code docs, agentskills.io specification and scripts guide, modelcontextprotocol/mcpb README, MANIFEST.md, CLI.md and PRs #158/#286, the MCP Registry package-types docs, OpenAI Codex and Code Interpreter docs, OpenAI Help Center, GitHub Copilot docs, Cursor docs, E2B, Vercel and Cloudflare docs, Microsoft APM docs, GitHub issues and PRs cited by repository and number, and the Snyk, Koi Security and Cloud Security Alliance research notes. Link-level citations are attached separately.

## Sources

1. [Code execution tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool)
2. [Using scripts in skills - Agent Skills](https://agentskills.io/skill-creation/using-scripts)
3. [mcpb/MANIFEST.md at main · modelcontextprotocol/mcpb](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)
4. [Agent Skills - Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
5. [Specification - Agent Skills](https://agentskills.io/specification)
6. [Codex Cloud (Legacy): internet access](https://developers.openai.com/codex/cloud/internet-access)
7. [github.com](https://github.com/modelcontextprotocol/mcpb/pull/158)
8. [Cloud Environment Setup](https://cursor.com/docs/cloud-agent/setup)
9. [Cursor cloud agents](https://docs.port.io/workflows/build-workflows/nodes/action-nodes/integration-actions/ai/cursor-cloud-agents/)
10. [Cloud Environment Setup and Cloud Subagents in Agents Window · Cursor](https://cursor.com/changelog/cloud-in-agents-window)
11. [Cloud Agent Builds](https://cursor.com/docs/cloud-agent/builds)
12. [Configure cloud environments - Claude Code Docs](https://code.claude.com/docs/en/cloud-environments)
13. [Use Claude Code on the web - Claude Code Docs](https://translate.google.com/translate?client=srp&hl=es&sl=en&tl=es&u=https%3A%2F%2Fcode.claude.com%2Fdocs%2Fen%2Fclaude-code-on-the-web)
14. [Get started with Claude Code in the cloud - Claude Code Docs](https://code.claude.com/docs/en/web-quickstart)
15. [Use Claude Code in the cloud - Claude Code Docs](https://code.claude.com/docs/en/claude-code-on-the-web)
16. [What is APM?](https://microsoft.github.io/apm/concepts/what-is-apm/)
17. [Claude Code Skills Not Found After npx Install](https://layer5.io/blog/engineering/claude-code-skills-not-found-after-npx-install/)
18. [Integrate Claude with dbt MCP](https://docs.getdbt.com/docs/dbt-ai/integrate-mcp-claude)
19. [Official ElevenLabs MCP Server](https://mcpservers.org/servers/elevenlabs/elevenlabs-mcp)
20. [Official Chronulus AI MCP Server](https://mcpservers.org/servers/ChronulusAI/chronulus-mcp)
21. [MCP troubleshooting](https://docs.getdbt.com/docs/dbt-ai/mcp-troubleshooting)
22. [GitHub - ai-mcpx/mcpx-cli: mcp registry cli · GitHub](https://github.com/ai-mcpx/mcpx-cli)
23. [registry/docs/reference/server-json/generic-server-json.md at main · modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md)
24. [MCP Registry Supported Package Types - Model Context Protocol](https://modelcontextprotocol.io/registry/package-types)
25. [feat(mcp): add MCP Registry server.json and uvx client config (#39) by luongnv89 · Pull Request #116 · Montimage/sec-mcp](https://github.com/Montimage/sec-mcp/pull/116)
26. [feat: registry-ready output for both targets (MCPFO-101) by ricardocvasconcelos · Pull Request #6 · klaridian/klaridian](https://github.com/klaridian/klaridian/pull/6)
27. [Repair main after the manifest change, and make the registry entry honest by pierrebrunelle · Pull Request #11 · pixeltable/mcp-server-pixeltable-developer](https://github.com/pixeltable/mcp-server-pixeltable-developer/pull/11)
28. [mcp registry: every registry-driven install fails the handshake, and the listing is 33 versions stale · Issue #462 · hslee16/Archy](https://github.com/hslee16/Archy/issues/462)
29. [mcp publish: support MCPB server.type "uv" · Issue #801 · arcadeai-labs/smithery-cli](https://github.com/arcadeai-labs/smithery-cli/issues/801)
30. [.mcpb Format - himalaya-mcp](https://data-wise.github.io/himalaya-mcp/reference/mcpb-format-reference/)
31. [Cloud environment setup - Claude Platform Docs](https://platform.claude.com/docs/en/managed-agents/environments)
32. [Exploring CLAUDE.AI’s Code Execution Sandbox: A Fun Dive into Infrastructure and Prompt Injection](https://www.rbtsec.com/blog/exploring-claude-ais-code-execution-sandbox-a-fun-dive-into-infrastructure-and-prompt-injection/)
33. [Create and edit files with Claude](https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude)
34. [Claude Code on the Web: Setup, Sessions, and Auto-Fix](https://fast.io/resources/claude-code-web-interface-guide/)
35. [Claude Code in the Cloud: 5 Ways to Run It (2026) - Replicas](https://replicas.dev/resources/claude-code-in-the-cloud)
36. [Background agent environments don't load snapshot disk state despite snapshot being configured in environment.json - Bug Reports - Cursor - Community Forum](https://forum.cursor.com/t/background-agent-environments-dont-load-snapshot-disk-state-despite-snapshot-being-configured-in-environment-json/136350)
37. [SDK Reference - E2B](https://e2b.dev/docs/sdk-reference/python-sdk/v1.3.2/sandbox_sync)
38. [E2B](https://e2b.dev/)
39. [Internet access - E2B Docs](https://e2b.dev/docs/sandbox/internet-access)
40. [Sandbox persistence - E2B Docs](https://e2b.dev/docs/sandbox/persistence)
41. [Run Docker containers inside Vercel Sandbox - Vercel](https://vercel.com/changelog/run-docker-containers-inside-vercel-sandbox)
42. [vercel/sandbox](https://www.npmjs.com/package/@vercel/sandbox)
43. [Sandbox firewall](https://vercel.com/docs/sandbox/concepts/firewall)
44. [Vercel Sandbox vs CodeSandbox](https://vercel.com/kb/guide/vercel-sandbox-vs-codesandbox)
45. [Cloudflare Containers, rebuilt to scale agent sandboxes](https://blog.cloudflare.com/faster-agent-sandboxes/)
46. [Dockerfile reference](https://developers.cloudflare.com/sandbox/configuration/dockerfile/)
47. [developers.cloudflare.com](https://developers.cloudflare.com/sandbox/concepts/sandboxes)
48. [Error in MCP connection to server sqlite: Error: spawn uvx ENOENT · modelcontextprotocol · Discussion #20](https://github.com/orgs/modelcontextprotocol/discussions/20)
49. [Fail loading mcp server ENOENT error · Issue #1160 · cline ...](https://github.com/cline/cline/issues/1160)
50. [Databutton MCP](https://docs.databutton.com/databutton-mcp-build-tools-for-ai)
51. [The released .mcpb only runs on Linux x86\_64 with CPython 3.11: vendored deps include platform-specific compiled wheels · Issue #89 · Danathar/goodreads-mcp](https://github.com/Danathar/goodreads-mcp/issues/89)
52. [release: ship a bundle that starts on every platform it declares by Danathar · Pull Request #99 · Danathar/goodreads-mcp](https://github.com/Danathar/goodreads-mcp/pull/99)
53. [GitHub - modelcontextprotocol/mcpb: Desktop Extensions: One-click local MCP server installation in desktop apps · GitHub](https://github.com/modelcontextprotocol/mcpb)
54. [build(deps): Bump pydantic-core from 2.46.5 to 2.49.0 in /harness by dependabot\[bot\] · Pull Request #123 · ahmedkeewan/service-buddy](https://github.com/ahmedkeewan/service-buddy/pull/123)
55. [Package the server as an MCP Bundle (.mcpb) by dfkunstler · Pull Request #6 · dfkunstler/mcp-server-for-oscal](https://github.com/dfkunstler/mcp-server-for-oscal/pull/6)
56. [Build failure on Python 3.14 due to outdated pydantic-core dependency · Issue #1451 · modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/issues/1451)
57. [\`ModuleNotFoundError: No module named 'pydantic\_core.\_pydantic\_core'\` when importing from \`mcp.server\` even though \`pydantic-core\` is installed · Issue #570 · modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk/issues/570)
58. [claude-skills/INSTALLATION.md at main · alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills/blob/main/INSTALLATION.md)
59. [Avoid dependency hell for Claude SKILLs](https://medium.com/@michaelyuan_88928/avoid-dependency-hell-for-claude-skills-62658982ebb4)
60. [Fix: Claude Skill Can't Reach External APIs — Network Access Setup](https://sharable.link/blog/fix-claude-skill-network-access)
61. [Claude Code on the web - OWID's Technical Documentation](https://docs.owid.io/projects/etl/guides/data-work/claude-code-web/)
62. [MCPB Files (.mcpb): Format Reference, Manifest, and Examples](https://www.mcpbundles.com/docs/concepts/mcpb-files)
63. [GitHub - smartchainark/skill-security-audit: Detect malicious patterns in AI Agent skills. 13 detectors based on SlowMist ClawHub threat intelligence. Pure Python, zero dependencies. · GitHub](https://github.com/smartchainark/skill-security-audit)
64. [Snyk Finds Prompt Injection in 36%, 1467 Malicious Payloads in a ToxicSkills Study of Agent Skills Supply Chain Compromise](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/)
65. [What a security audit of 22,511 AI coding skills found lurking in the code - The New Stack](https://thenewstack.io/ai-agent-skills-security/)
66. [Verify signed MCPB bundles by jstar0 · Pull Request #286 · modelcontextprotocol/mcpb](https://github.com/modelcontextprotocol/mcpb/pull/286)
67. [fix(mcpb): signed bundles declare the signature as the zip comment by tp322d · Pull Request #22 · tp322d/lastping-app](https://github.com/tp322d/lastping-app/pull/22)
68. [Codex Cloud (Legacy)](https://developers.openai.com/codex/cloud/environments)
69. [customizing or disabling the firewall for copilot coding agent](https://docs.github.com/en/copilot/how-tos/agents/copilot-coding-agent/customizing-or-disabling-the-firewall-for-copilot-coding-agent)
70. [Sandbox - Vercel](https://vercel.com/sandbox)
71. [Agent Context Poisoning: SKILL.md and the New AI Supply Chain Attack Surface](https://labs.cloudsecurityalliance.org/research/csa-research-note-skill-md-agent-context-poisoning-20260506/)
