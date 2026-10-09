# Python When Agents Write and Run the Code: What Actually Changes for Packaging and Shipping (October 2026)

The main change is that the environment is now the thing that breaks, not the code. Agent-written Python usually works on the machine it was written on. It fails elsewhere because the dependencies it needs were never fully written down. A December 2025 study found that only 68.3% of agent-built projects ran in a clean environment, and that the dependencies needed at runtime were on average 13.5 times the ones the agent had declared.\[1\] The tools that matter most will be the ones that capture, check and replay environments for machines and for the people who receive the code. Agents are already good at writing the code itself, and current tools (uv, PEP 723, container images, sandbox templates) already cover much of the remaining need.

## TL;DR

- **Authorship has shifted, but measurements disagree.** A classifier-based study in *Science* (January 2026) estimates AI wrote about 29% of US Python functions by the end of 2024. Developers' own estimates in mid-2026 are much higher, and Anthropic says 70–90% of its own code is AI-written. Agent code rarely adds new dependencies, and usually pins versions when it does. Its main portability failure is undeclared or drifting environments, plus hallucinated packages at about 5–6% per frontier model.
- **Agents struggle most with operating environments, not writing code.** On EnvBench, the best agent fully set up only 6.69% of Python repositories, against 29.47% for JVM ones. The failures that recur in issue trackers are interactive prompts that hang, sandbox network rules that block PyPI, and proxy or certificate problems. "Agent-friendly" documentation (llms.txt, AGENTS.md) has weak or mixed measured benefit. Non-interactive modes and machine-readable output have better, though mostly anecdotal, support.
- **The shifts I believe in:** environments as the thing that travels (locked, cross-platform, verifiable), pre-flight checks that tell you code "will run there", and building against what a sandbox already has installed. **The shifts I doubt:** sandboxes making local packaging irrelevant, and llms.txt-style docs as a moat. A tool should verify and translate between environments that uv, Docker and sandbox templates already define, not compete with them.

## Key Findings

| Claim | Evidence | Strength |
|---|---|---|
| A large and growing share of Python is AI-written | *Science* classifier study: 29% of US Python functions by end-2024; 22.2–28.7% of 128,018 GitHub projects show coding-agent traces (Feb 2026)\[2\] | Strong, but the figures disagree by method |
| Agent code under-declares its environment | 68.3% of projects run out of the box; 13.5× more runtime dependencies than declared (arXiv 2512.22387);\[1\] dependency sets for the same task overlap as little as 7% (arXiv 2610.00425)\[3\] | Strong (preprints) |
| Agents rarely add dependencies to existing projects, but pin versions when they do | 2.8% of Python agent PRs add dependencies; 82.5% of those specify a version (MSR '26)\[4\] | Strong |
| Package hallucination persists | 4.62–6.10% across five 2026 frontier models; Python worse than JS (arXiv 2605.17062)\[5\] | Strong, but measured without agent tool use |
| Environment setup is the weakest agent skill | EnvBench Python 6.69%;\[6\] SetupBench 34.4–62.4%\[7\] | Strong |
| llms.txt or AGENTS.md measurably help | No general improvement in task success; over 20% higher inference cost (arXiv 2602.11988 v3) | Weak or negative |
| Sandboxes are converging on "preinstalled + optional allowlisted network" | Claude API, Gemini: no package installation;\[8\]\[9\] OpenAI: network off by default, allowlist option;\[10\] E2B/Modal: custom images\[11\]\[12\] | Strong (vendor docs, October 2026) |

## Part 1: Agents as Authors

### How much Python is AI-written

- **Independent measurement.** Daniotti, Wachs, Feng and Neffke (*Science*, published 22 January 2026) trained a classifier on more than 30 million GitHub commits by 160,097 developers. Their headline: "AI writes an estimated 29% of Python functions in the US, a shrinking lead over other countries", measured as of the end of 2024. They also estimate it raised quarterly output by 3.6%. This is the best-founded number available, but it predates the agent wave of 2025–26.
- **Repository-level adoption.** "Agentic Much?" (arXiv 2601.18341) finds that 22.20–28.66% of 128,018 GitHub projects showed traces of coding-agent use by 21 February 2026. Most of the uptake happened between March and October 2025.\[2\]
- **Self-reports and vendor claims (treat as upper bounds).** Fortune reported on 29 January 2026 that an Anthropic spokesperson put company-wide AI-written code at 70–90%; Claude Code's creator, Boris Cherny, says 100% of his own code.\[13\] A JetBrains Research survey of more than 15,000 developers (May–July 2026; Mikhail Bogdanov, JetBrains Research blog, August 2026) has developers estimating that about 47% of their code is fully written by agents and about 38% with some AI help. The widely repeated "41% of all code is AI" has no primary source that I could find.\[14\]

**Inference:** for code that is meant to travel (scripts, tools, internal utilities), the agent-written share is probably well above the 29% repository average. Those artefacts are exactly the ones people prompt for. No study measures this directly.

### What agent code looks like

- **Dependencies in existing projects.** Twist and Zhang (MSR '26, arXiv 2512.11589) studied 26,760 agent PRs from the AIDev dataset, 7,190 of them in Python. Only 2.8% of Python PRs added new dependencies, and 82.5% of those specified a version. Across all languages the figures were 1.3% and 75.0%. The authors note this is far better than plain LLM chat, where versions came up in about 9% of library-related interactions. Agents did, however, use a broad range of libraries: 948 distinct external Python libraries.\[4\]
- **Dependencies in new projects (where portability is decided).** Vangala, Adibifar, Gehani and Malik (arXiv 2512.22387, December 2025, revised March 2026) had Claude Code, Codex and Gemini build 300 projects. They then ran each one in a clean environment with only the declared dependencies.\[1\]
  - Only 68.3% ran out of the box: 89.2% for Python and 44.0% for Java.\[1\]
  - The dependencies actually needed at runtime averaged 13.5 times the declared ones.\[1\]
  - A follow-up (arXiv 2610.00425, 30 September 2026) found that two runs of the same task can share as little as 7% of their declared dependencies.\[3\]
- **Versions and deprecated APIs.**
  - PinTrace (arXiv 2605.06279, May 2026) tested 10 LLMs on 1,000 Python tasks. When writing manifests, models pinned versions only 6.45–59.19% of the time. They chose versions with known CVEs in 36.70–55.70% of tasks. Static compatibility was 19.70–63.20%, and installation failure was the main cause,\[15\] because models favour older versions.\[16\]
  - Ashik et al. (arXiv 2604.09515, April 2026) found that only 42.55% of generated code ran against evolved library APIs. That rose to 66.36% when the model was given structured documentation.\[17\]
  - Majdoub et al. (arXiv 2610.00622, September 2026) report that 84% of generated files contain at least one library-related error.\[18\]
- **Hallucinated packages.**
  - Spracklen et al. (USENIX Security 2025) measured rates of at least 5.2% for commercial models and 21.7% for open-source models.\[5\]
  - A 2026 replication (Churilov, arXiv 2605.17062, run 22–28 April 2026) measured 4.62% (Claude Haiku 4.5) to 6.10% (GPT-5.4-mini). Python was 2.73–4.13 points worse than JavaScript.\[5\]
  - 127 names were hallucinated by all five models, and 41 of those PyPI names were still registrable after PyPI's defences. The top example was `aws-cdk` instead of `aws-cdk-lib`.\[5\]
  - Two caveats. The study excluded agentic configurations, where retrieval may remove the problem.\[5\] A separate paper (arXiv 2608.22652) argues that earlier Python rates were inflated by misclassified standard-library modules.\[19\]
- **Tests.** In 4,882 agent PRs, 4,350 of them Python, agents included test changes in only 49.6% of PRs that changed code under test (arXiv 2607.18057, ICSME 2026).\[20\]
- **PEP 723 and single scripts.** I found **no quantitative study** of how often agents emit PEP 723 inline metadata or lockfiles. The evidence is anecdotal and mixed:
  - Simon Willison (Hacker News, July 2025): "Claude 4 actually knows about this trick".\[21\]
  - Another HN user (June 2025): "claude sonnet typically forgets about uv script syntax".\[22\]
  - Practitioners are now writing agent skills that tell models "Do not write inline metadata blocks by hand" and to use `uv add --script` instead (mathspp, "uv skills for coding agents").\[23\]
  - Agent-oriented repositories are starting to require PEP 723 headers: agentic-dev-kit issue #942 asks for "standalone PEP 723 metadata for adopter uv invocation".\[24\]
- **Secrets.** Peng et al. (arXiv 2607.12089, July 2026) found hard-coded credentials in 79.1% of the snippets where the check applied, and standard static scanners caught only 44 of the 651. The judging was done by an LLM, on small open models and security-themed prompts,\[25\] so treat this as an upper bound. A separate study of agent skills (arXiv 2604.03070) found that 73.5% of credential leaks came from print or console logging.\[26\]
- **Hard-coded paths and platform-specific code: unverified.** I found no study that quantifies these for LLM-generated Python. arXiv 2609.25531 (September 2026) studies cross-OS portability issues in Python projects and LLMs' "limited ability" to fix them,\[27\] but I could not extract its numbers.

**What this means:** agent code fails to travel mainly through environment drift: imports that work only because something happened to be installed, nondeterministic dependency choices, and stale versions. Writing the code is not the weak point. This favours tools that derive and verify the environment from the code and from execution traces, rather than trusting the manifest the agent declared.

## Part 2: Agents as Operators

### What they struggle with

- **Environment setup is the hardest category.**
  - EnvBench (JetBrains Research, ICLR 2025 DL4C workshop): the best approach fully configured 6.69% of 329 Python repositories (22 of 329), against 29.47% of JVM ones. Expert-written scripts reached 66.7%.\[28\]\[29\]
  - SetupBench (arXiv 2507.09063): OpenHands succeeded on 34.4–62.4% of tasks, with Claude 4 the best at 62.4%.\[7\]
  - Terminal-Bench 2.0 (ICLR 2026): frontier agents resolve under 65% of tasks. Its failure taxonomy includes "Non-standard CLI semantics / interactive default".\[30\]\[31\]
  - These Python results come from 2025-era models. Newer agents are likely better, but I found no 2026 rerun of EnvBench.
- **Interactive prompts and hangs.**
  - Gemini CLI issue #21052: sub-agents "hang indefinitely" on prompts. The only workaround is to "heavily prompt" the agent to use non-interactive flags.\[32\]
  - GitHub Copilot community discussion #161238: the agent fails to detect that long-running build or test commands have finished.\[33\]
  - Tool authors are filing their own issues to add a flag for every prompt (for example arcane #282 and AgentBehaviorBench #12, which asks for `--yes`).\[34\]\[35\]
- **Network and sandbox friction.**
  - Claude Code's sandbox runtime denies network access by default, and child processes inherit environment variables, "including any secrets", unless these are scrubbed (Claude Code docs, accessed October 2026).\[36\]\[37\]
  - Issue #94758 on anthropics/claude-code (Claude Code 2.1.236 and 2.1.270): with an enterprise gateway, `allowedDomains` is ignored and pypi.org stays blocked. Users "work around it by running commands outside the sandbox".\[38\]
  - code-mower issue #769: pip fails certificate validation inside the macOS Claude Code sandbox. The same install works outside it.\[39\]
  - An independent experiment (claudecodecamp) found that pip, uv and requests respect proxy environment variables but Node's `fetch` does not.\[40\] Whether a tool works in a sandbox therefore depends on its HTTP client.
  - LightconeResearch/lightcone-cli issue #244: a research sandbox blocked `uv run` for PEP 723 scripts as "not part of the declared environment".\[41\]
- **Virtual environments and IDEs.** HN users report that Cursor "often gets confused because the dependencies are not installed" (June 2025), and that PyCharm cannot run PEP 723 scripts through uv (March 2025).\[22\]\[42\]

### What "agent-friendly" tooling does, and whether it helps

- **Non-interactive modes.** ForgeCode's blog ("Benchmarks Don't Matter — Until They Do") reports its TermBench score rose from about 25% to about 38% after one change that bundled a strict non-interactive mode with tool-call naming and micro-evals. The gain therefore can't be credited to non-interactive mode alone. This is a vendor blog and self-reported, but the direction matches the issue trackers.
- **Context files (AGENTS.md / CLAUDE.md).** The evidence is mixed to negative:
  - Gloaguen et al. (ETH Zurich, arXiv 2602.11988, February 2026; v3 29 September 2026): context files "do not generally improve task success rates". This holds for both LLM-generated and developer-committed files, and they raise inference cost by over 20% on average. Agents follow the files literally: tools named in them get used far more often.\[43\]\[44\]
  - A JAWs 2026 study found that AGENTS.md files cut runtime by 28.6% and output tokens by 16.6%.\[43\]\[45\]
  - A two-agent ablation (arXiv 2607.27250) finds no correctness benefit, bounded at under 10–15 points.\[46\]\[47\]
- **llms.txt.** In Ahrefs' study of 137,210 domains (15 June 2026), 97% of published llms.txt files got no requests in May 2026. Per secondary coverage, only about 1,100 saw any traffic at all. Its one bright spot is coding agents: per a secondary summary, Claude Code fetched llms.txt more than any AI retrieval bot, and agents fetch it "when directed".\[48\]\[49\] There is no measured effect on task success.
- **Machine-readable output and stable exit codes.** I found no controlled study. EnvBench notes that agents without error feedback "commonly produce erroneous" setup scripts,\[28\] which indirectly supports clear, parseable errors.

**What this means:** the agent-friendly features with real evidence are about *control flow*: no prompts, bounded runtime, clear exit status and errors that can be acted on. Documentation written for models is cheap but unproven. Do not build a moat on it.

## Part 3: People and Platforms Consuming Agents' Output

### People

The evidence here is thin. I could not access Reddit, so this section relies on Hacker News and blogs.
- **What they do.** Someone asks an agent for a script with inline dependencies and runs it with `uv run`. Typical reports: "I now habitually vibe-code little scripts that I can immediately run" (HN, June 2025), and "I used this to share a script with the team and it just worked" (Paul's Programming Notes, March 2026).\[22\]\[50\]
- **What breaks.**
  - The recipient needs uv: the "self-contained" claim "depends on `uv` being installed" (HN, March 2025).\[51\]
  - uv can be unavailable on some platforms. One user says uv "won't build" on an older Raspberry Pi setup, so they wrote their own fallback.\[52\]
  - Some people write polyglot shebangs that fall back to `python3` for colleagues who don't have uv (HN thread "Go away Python", December 2025).\[52\]
  - Editors and debuggers don't understand script environments.\[42\]\[51\]\[53\]
  - Lockfiles are optional: PEP 723 resolution is "deferred" unless you run `uv lock --script`.\[50\]\[54\]
- **What they want (inferred).** One-command running with no installation step, something a non-developer can double-click or schedule, and confidence that it will behave the same next month.

### Platforms (documentation accessed October 2026 unless noted)

| Platform | Python and packages | Install at runtime? | Network | Limits | How third-party code with dependencies gets in |
|---|---|---|---|---|---|
| Claude API code execution tool | Python and Bash; preinstalled data libraries\[55\] | No | "Completely disabled"\[56\] | Workspace directory only\[56\] | Pre-installed only; upload files |
| Claude Agent Skills (API) | Same container | "No runtime package installation"\[9\] | None | — | Skill bundles (instructions and scripts) that must use preinstalled packages; on Claude Code, skills have full local network\[9\] |
| Claude.ai (consumer) | gVisor container (third-party analysis)\[57\] | Varies by admin settings | "Full, partial, or no" by setting\[9\] | — | Varies |
| OpenAI hosted containers / shell tool | Container with pip available\[10\] | Yes, if network allowed | Off by default; `network_policy` allowlist\[10\] | `memory_limit` such as "4g"\[58\] | Install inside the container when network is enabled |
| ChatGPT containers | Bash, pip and npm (since about January 2026)\[59\] | Yes, via an internal package proxy\[59\] | Packages only (`caas_packages_only`)\[59\] | — | pip/npm through the proxy (Simon Willison, 26 January 2026)\[59\] |
| OpenAI Codex cloud | "universal" image; pinnable runtimes\[60\] | In setup scripts\[60\] | Setup has internet; agent phase off by default\[60\] | — | Setup scripts\[60\] |
| Gemini API code execution | Python only; fixed list (numpy, pandas, scikit-learn, tensorflow and others)\[8\] | "You can't install your own libraries"\[8\] | None | 30 s per execution (Google, Gemini 2.0 post)\[61\] | Not possible |
| E2B | Custom templates (base image, commands, start command snapshot)\[12\] | Yes | Configurable (`allow_internet_access`)\[62\] | Build: 8 vCPU / 8 GiB / 10 GiB disk on Hobby; sandbox default 300 s, 1 h maximum on Hobby\[12\]\[62\]\[63\] | Build a template |
| Modal Sandboxes / Notebooks | Debian slim; same minor Python as local by default\[11\] | Yes (`uv_pip_install`, `uv_sync` from uv.lock; `%uv pip install`)\[64\]\[65\] | Yes | — | Image definitions in Python; registry images\[66\] |
| Daytona, Databricks/Colab, CI, serverless | **Not verified in this research** | — | — | — | — |

**Pattern:** the hosted model-provider sandboxes (Anthropic, Google) freeze the environment and remove the network. OpenAI moved toward a proxy for packages only. Developer sandboxes (E2B, Modal) use container images and increasingly accept uv lockfiles directly (Modal's `uv_sync`). The common request across issue trackers is the same: let my declared environment in, safely.

## Part 4: Plausible Shifts (2026–2029)

| Shift | Evidence for | Who benefits | What must be true | What would make it fail | My view |
|---|---|---|---|---|---|
| **1. Environments, not apps, are what travels** | 13.5× declared-vs-runtime gap; Modal `uv_sync`; E2B templates; PEP 723 + `uv lock --script` | Recipients, platforms | Lockfiles that are cross-platform and include the interpreter; a way to capture an environment from a working run | Platforms keep proprietary image formats | **Believe (high)** |
| **2. Ephemeral, run-once code** | Hosted code tools run snippets that never get saved; "vibe-code little scripts" | Users of chat tools | Startup and installs fast enough (uv caching) | Valuable scripts become recurring jobs that need to be scheduled and shared, which brings packaging back | **Partly believe (medium).** One-off code exists, but the scripts people value tend to get kept and re-run |
| **3. Sandboxes make local packaging irrelevant** | Many runs happen in sandboxes; Claude/Gemini preinstalled sets | Vendors | Sandboxes accept arbitrary dependencies | Network-off sandboxes *can't* install; corporate users need local or on-prem runs; GPU, data-locality and cost needs | **Don't believe (medium-high).** It moves packaging into image building rather than removing it |
| **4. Standard formats agents produce and verify** | PEP 723; pylock.toml (PEP 751 — not verified here); agents pin 75–82% when they add dependencies | Everyone | Agents emit the format reliably (anecdotes are mixed) and tools validate it | A split between uv-specific and standard formats | **Believe (medium)** |
| **5. Pre-ship "will it run there?" checks** | 68.3% out-of-box rate; 42.55% executability across API versions; hallucinated packages | Agents (closing the feedback loop), recipients | Fast clean-room runs; target-environment descriptions such as "Claude API sandbox" or "Windows + Python 3.11" | Checks too slow or too noisy for agent loops | **Believe (high)**. This has the best evidence-to-supply gap |
| **6. (Emerging) Building against what the sandbox already has** | Gemini and Claude publish fixed library lists; skills must use preinstalled packages | Skill and plugin authors | Machine-readable target manifests | Vendors change the lists without notice | **Believe (medium)** |
| **7. (Emerging) Supply-chain gating at install time** | 41 registrable universally hallucinated PyPI names; CVE-version picks in 36–56% of tasks; dependency-steering attacks via malicious skills (arXiv 2605.09594)\[67\] | Platforms, enterprises | Registry metadata (age, downloads, known-hallucination lists) available to the installer | False positives annoy users | **Believe (medium-high)** |

**The case against new tooling.** uv already covers fast resolution, managed Python downloads, PEP 723 scripts, script lockfiles and `uv tool install`.\[50\]\[68\] Docker and sandbox templates already move whole environments. Hosted sandboxes already work around portability by giving everyone the same preinstalled image. The 89.2% Python out-of-box rate in arXiv 2512.22387 is far better than Java's 44.0%, so the Python problem may be small enough for current tools plus better prompts. Agents improve quickly too: hallucination spread across models narrowed about eleven-fold between 2024 and 2026.\[5\] If uv becomes ubiquitous, much of the case for a separate "make it run elsewhere" tool collapses into "use uv correctly". The only primary adoption figure I found is old: uv was 4.8% of PyPI downloads against pip's 87.5% in March–September 2024 (PEP 777 appendix).\[69\] Later and higher figures are secondary, so ubiquity is not yet established.

## Part 5: What a Tool Should Offer

Ranked by the evidence of need.

| Rank | Capability | For | Evidence of need | Already provided by |
|---|---|---|---|---|
| 1 | **Clean-room verification:** run the code in a fresh, target-like environment and report missing imports or packages as structured output | Agent | 68.3% out-of-box; 13.5× dependency gap; EnvBench's feedback finding | Partly: `uv run --isolated`, Docker, E2B/Modal. There is no packaged "check against target X" |
| 2 | **Inferring the environment from code and runs:** turn imports and a successful run into a pinned PEP 723 block or lock | Agent, person | 7% dependency agreement; manifest pinning 6–59% | Partly: `uv add --script`, `uv lock --script`; no import-to-package mapping that is safe from hallucinated names |
| 3 | **Target profiles:** machine-readable descriptions of sandboxes (Claude API, Gemini, OpenAI, Windows/macOS/Linux, Python versions) and checks against them | Agent, platform | Fixed library lists, network-off sandboxes, Python 3.x drift | **No one, as far as I found** |
| 4 | **Install-time supply-chain checks:** flag non-existent, very new or known-hallucinated names and CVE versions before installing | Agent, platform | 4.6–6.1% hallucination; 41 registrable names; 36–56% CVE versions | Partly: Socket, pip-audit, PyPI prohibited names |
| 5 | **Non-interactive by default, JSON output, stable exit codes, bounded installs** | Agent | Gemini CLI #21052, Copilot #161238, Terminal-Bench taxonomy | uv is mostly non-interactive; not universal |
| 6 | **Recipient experience:** a single artefact or command that runs without the recipient installing uv, can be scheduled, and reports clear errors | Person | HN reports above | Partly: uv, PyInstaller, shiv/zipapps |
| 7 | **Platform ingestion:** accept PEP 723 or uv.lock as input to build a sandbox image, with network allowlisting for registries | Platform | lightcone #244, Claude Code #94758, Modal `uv_sync` | Modal (uv.lock), E2B (templates) |
| 8 | **Secret and path linting before shipping** | Agent, person | 79.1% hard-coded credentials (upper bound); path data unverified | Partly: gitleaks/SAST (low recall per arXiv 2607.12089) |
| 9 | llms.txt / agent docs | Agent | Weak | Cheap to add; not a differentiator |

## Caveats

- Many cited papers are 2026 arXiv preprints and not yet peer-reviewed. Several measure models without agent tool use (hallucination, PinTrace), where agents with retrieval and execution may do better.
- "AI-written share" figures are not comparable: classifier estimates, self-reports and vendor claims measure different things. Vendor statements (Anthropic's 70–90%, ForgeCode's benchmark gains) are claims, not independent evidence.
- **Not verified in this research:** Daytona, Colab and Databricks, CI and serverless limits, pylock.toml/PEP 751 status, current uv share of PyPI, the quantitative prevalence of hard-coded paths or platform-specific code, and how often agents emit PEP 723. Reddit and support forums were not accessible; the "people" evidence comes from Hacker News and blogs, and is thin.
- Platform facts change monthly. Treat the table as a snapshot from October 2026.

## One-Page Summary

**Bottom line:** agents moved the bottleneck from writing code to stating and checking its environment. Build for verification and translation between environments, not for another packaging format.

| Shift | Verdict | Confidence | What a tool should do |
|---|---|---|---|
| Environments are what travels | Believe | High | Produce and consume standard artefacts (PEP 723, uv.lock, container images); never invent a new lock format |
| Pre-ship "will it run there?" checks | Believe | High | Make clean-room runs against named target profiles fast, with JSON output; this is the clearest unmet need |
| Building against a sandbox's preinstalled set | Believe | Medium | Maintain machine-readable target profiles for the major sandboxes; warn when code needs packages the target lacks |
| Supply-chain gating at install | Believe | Medium-high | Check names, age and CVEs before installing; block known hallucinated names |
| Standard formats agents emit | Believe | Medium | Give agents a command that writes metadata, not a spec to hand-write |
| Agent-operable CLIs (no prompts, exit codes, JSON) | Believe | Medium (mostly anecdotal) | Ship this as a baseline, not a feature |
| Ephemeral run-once code | Partly | Medium | Make "promote a one-off to a scheduled or shared job" a single step |
| Sandboxes make local packaging irrelevant | Don't believe | Medium-high | Treat sandboxes as one more target; packaging moves into image building |
| llms.txt / AGENTS.md as a differentiator | Don't believe | Medium | Publish them cheaply; don't invest |
| Current tools (uv + Docker + sandbox templates) are enough | Partly true | Medium | Build on them; differentiate only on verification, target profiles and the recipient experience. If uv becomes universal and agents learn to write PEP 723 reliably, the remaining gap is mostly verification |

## Sources

1. [AI-Generated Code Is Not Reproducible (Yet): An Empirical Study of Dependency Gaps in LLM-Based Coding Agents](https://arxiv.org/abs/2512.22387)
2. [Agentic Much? Adoption of Coding Agents on GitHub](https://arxiv.org/pdf/2601.18341)
3. [Code That Works, Environments That Don't: Measuring Environment Reproducibility in AI-Generated Software](https://arxiv.org/abs/2610.00425)
4. [A Study of Library Usage in Agent-Authored Pull Requests](https://arxiv.org/html/2512.11589v2)
5. [The Range Shrinks, the Threat Remains: Re-evaluating LLM Package Hallucinations on the 2026 Frontier-Model Cohort](https://arxiv.org/pdf/2605.17062)
6. [EnvBench: A Benchmark for Automated Environment Setup](https://www.alphaxiv.org/abs/2503.14443)
7. [SetupBench: Assessing Software Engineering Agents' ...](https://arxiv.org/pdf/2507.09063)
8. [Code execution](https://ai.google.dev/gemini-api/docs/code-execution)
9. [Agent Skills - Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
10. [Shell](https://developers.openai.com/api/docs/guides/tools-shell)
11. [Images](https://modal.com/docs/guide/images)
12. [Quickstart - E2B Docs](https://e2b.dev/docs/sandbox-template)
13. [Top engineers at Anthropic, OpenAI say AI now writes 100% of their code—with big implications for the future of software development jobs](https://fortune.com/2026/01/29/100-percent-of-code-at-anthropic-and-openai-is-now-ai-written-boris-cherny-roon/)
14. [AI coding statistics 2026: adoption, trust and security, with sources · Cyborb](https://cyborb.ai/blog/ai-coding-statistics-2026)
15. [Correct Code, Vulnerable Dependencies: A Large Scale Measurement Study of LLM-Specified Library Versions](https://arxiv.org/abs/2605.06279)
16. [Correct Code, Vulnerable Dependencies: A Large Scale Measurement Study of LLM-Specified Library Versions](https://arxiv.org/html/2605.06279)
17. [When LLMs Lag Behind: Knowledge Conflicts from Evolving APIs in Code Generation](https://arxiv.org/abs/2604.09515)
18. [Understanding and Mitigating Library-Related Issues in LLM-Generated Code](https://arxiv.org/abs/2610.00622)
19. [\[2608.22652\] Evaluating Inference-Time Defenses Against Package Hallucination in LLM-Generated Code](https://arxiv.org/abs/2608.22652)
20. [\[2607.18057\] Test Coverage Analysis of Agentic Pull Requests](https://arxiv.org/abs/2607.18057)
21. [Uv: Running a script with dependencies](https://news.ycombinator.com/item?id=44641521)
22. [I adore the uv add \<mydependencies\> --script mycoolscript.py And then shoving #!...](https://news.ycombinator.com/item?id=44358181)
23. [uv skills for coding agents](https://mathspp.com/blog/uv-skills)
24. [Triage entry points need standalone PEP 723 metadata for adopter uv invocation · Issue #942 · topij/agentic-dev-kit](https://github.com/topij/agentic-dev-kit/issues/942)
25. [Cross-Cutting Security Analysis of LLM-Generated Code via Metamorphic Testing and Association Rule Mining](https://arxiv.org/pdf/2607.12089)
26. [Credential Leakage in LLM Agent Skills: A Large-Scale Empirical Study](https://arxiv.org/html/2604.03070v1)
27. [An Empirical Analysis of Cross-OS Portability Issues in Python Projects](https://arxiv.org/pdf/2609.25531)
28. [envbench:abenchmark for automated environment setup](https://arxiv.org/pdf/2503.14443)
29. [EnvBench: A Benchmark for AutomatedEnvironment Setup](https://arxiv.org/html/2503.14443)
30. [Published as a conference paper at ICLR 2026 TERMINAL-BENCH: BENCHMARKING](https://proceedings.iclr.cc/paper_files/paper/2026/file/444a3737adaee10d86ad2ef5f74468e6-Paper-Conference.pdf)
31. [(PDF) Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces](https://www.researchgate.net/publication/399931917_Terminal-Bench_Benchmarking_Agents_on_Hard_Realistic_Tasks_in_Command_Line_Interfaces)
32. [Regression: Sub-agents hang indefinitely on interactive terminal prompts in v0.32.0 · Issue #21052 · google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli/issues/21052)
33. [Copilot does not detect terminal command has completed or is not getting terminal output · community · Discussion #161238](https://github.com/orgs/community/discussions/161238)
34. [Interactive CLI prompts should be drivable from AI coding harnesses without dropping to a terminal · Issue #282 · codemagicianhq/arcane](https://github.com/codemagicianhq/arcane/issues/282)
35. [\[cli\] run blocks on interactive confirmation with no way to skip it · Issue #12 · DefuzeX-AI/AgentBehaviorBench](https://github.com/DefuzeX-AI/AgentBehaviorBench/issues/12)
36. [Choose a sandbox environment - Claude Code Docs](https://code.claude.com/docs/en/sandbox-environments)
37. [Configure the sandboxed Bash tool - Claude Code Docs](https://code.claude.com/docs/en/sandboxing)
38. [Claude Desktop 3p + custom gateway (\`ANTHROPIC\_BASE\_URL\`): sandbox network pinned to gateway + api.anthropic.com, \`sandbox.network.allowedDomains\` ignored even after full app restart · Issue #94758 · anthropics/claude-code](https://github.com/anthropics/claude-code/issues/94758)
39. [Campaign: handle Claude macOS sandbox certificate validation safely · Issue #769 · codemower-ai/code-mower](https://github.com/codemower-ai/code-mower/issues/769)
40. [Claude Code Sandbox: How /sandbox Works (and What It Doesn't Protect)](https://www.claudecodecamp.com/p/claude-code-sandboxing-how-sandbox-works-and-what-it-doesn-t-protect)
41. [Sandbox blocks uv run for PEP 723 scripts: can inline script metadata count as a declared environment? · Issue #244 · LightconeResearch/lightcone-cli](https://github.com/LightconeResearch/lightcone-cli/issues/244)
42. [Using uv and PEP 723 for Self-Contained Python Scripts](https://news.ycombinator.com/item?id=43500124)
43. [Probe-and-Refine Tuning of Repository Guidance for Coding Agents](https://arxiv.org/pdf/2606.20512)
44. [What AGENTS.md Actually Does to Your Coding Agent](https://agentic-academy.ai/posts/agents-md-context-files-evaluation/)
45. [When AGENTS.md Backfires: What a New Study Says About Context Files and Coding Agents](https://notchrisgroves.com/when-agents-md-backfires/)
46. [Do Context Files Help Coding Agents?A Two-Agent Ablation Study on Real Repositories](https://arxiv.org/html/2607.27250)
47. [Do Context Files Help Coding Agents? A Two-Agent Ablation Study on Real Repositories](https://arxiv.org/pdf/2607.27250)
48. [We Analyzed 137K Sites: 97% of llms.txt Files Never Get Read](https://ahrefs.com/blog/llmstxt-study/)
49. [Does llms.txt Actually Work? What the Evidence Shows](https://www.marqeable.com/blog/does-llms-txt-work/)
50. [Python - Inline Script Dependencies With PEP 723 · Paul's Programming Notes](https://www.paulsprogrammingnotes.com/2026/03/pep-723-inline-script-metadata.html)
51. [Self-contained Python scripts with uv](https://news.ycombinator.com/item?id=43519669)
52. [Go away Python](https://news.ycombinator.com/item?id=46431028)
53. [The "declaring script dependencies" thing is incredibly useful: https://docs.ast...](https://news.ycombinator.com/item?id=44641746)
54. [A very well written article! I admire the analysis done by the author regarding ...](https://news.ycombinator.com/item?id=43097006)
55. [Claude's Code Execution Tool - Running Python and Bash in the API](https://team400.ai/blog/2026-04-claude-code-execution-tool-api-guide)
56. [Code execution tool - Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool)
57. [Exploring CLAUDE.AI’s Code Execution Sandbox: A Fun Dive into Infrastructure and Prompt Injection](https://www.rbtsec.com/blog/exploring-claude-ais-code-execution-sandbox-a-fun-dive-into-infrastructure-and-prompt-injection/)
58. [Code Interpreter](https://developers.openai.com/api/docs/guides/tools-code-interpreter)
59. [ChatGPT Containers can now run bash, pip/npm install packages, and download files](https://simonwillison.net/2026/Jan/26/chatgpt-containers/)
60. [Codex Cloud (Legacy)](https://developers.openai.com/codex/cloud/environments)
61. [Gemini 2.0 Deep Dive: Code Execution - Google Developers Blog](https://developers.googleblog.com/gemini-20-deep-dive-code-execution/)
62. [E2B Sandbox](https://pydantic.dev/docs/ai/harness/e2b-sandbox/)
63. [SDK Reference - E2B](https://e2b.dev/docs/sdk-reference/python-sdk/v1.3.2/sandbox_sync)
64. [Modal Notebooks](https://modal.com/docs/guide/notebooks)
65. [How to run uv on Modal](https://pydevtools.com/handbook/how-to/how-to-run-uv-on-modal/)
66. [Using existing images](https://modal.com/docs/guide/existing-images)
67. [Trust Me, Import This: Dependency Steering Attacks via Malicious Agent Skills](https://arxiv.org/pdf/2605.09594)
68. [Stop Fighting Your Python Setup in 2026: Use uv](https://iampraveen.medium.com/stop-fighting-your-python-setup-in-2026-use-uv-2ca0f54bd083)
69. [Appendix: Analysis of Installer Usage on PyPI | peps.python.org](https://peps.python.org/pep-0777/appendix-pypi-download-analysis/)
