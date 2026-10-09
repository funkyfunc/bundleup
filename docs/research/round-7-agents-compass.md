# Python Packaging When Agents Write and Run the Code: A Sceptical Assessment (October 2026)

The evidence says AI agents are changing who writes Python and where it runs, not what Python needs in order to run. The "it won't run elsewhere" problem is getting more common, not going away. But much of the fix already exists in uv, PEP 723, lockfiles, container images and platform templates, so a new tool's opening is narrow. It lies in verification and translation across targets ("will this run *there*?"), not in another packaging format.

## TL;DR
- **Agents author a large and growing share of code, and it travels badly.** Agent pull requests number in the hundreds of thousands. Model-written code still names packages that don't exist 4.62% (Claude Haiku 4.5) to 6.10% (GPT-5.4-mini) of the time on 2026 frontier models, across 199,845 prompts (arXiv 2605.17062). Claude Code co-authored commits leaked secrets at 3.2% against a 1.5% baseline in 2025. Agents themselves fail often at setting up environments: 6.69% success on EnvBench-Python, and 34–62% on SetupBench.
- **Platforms fragment the target, rather than making packaging irrelevant.** Claude's API sandbox and Gemini's code execution allow no installs and no network. Codex installs only during setup. E2B and Modal build from images or templates. MCP bundles use a uv runtime. Each one needs a different shape of "bring your dependencies", so code that runs in one place often fails in another.
- **What a tool should do:** be the verifier and translator. One declared environment (PEP 723 or `pyproject.toml` plus a lockfile) gets checked against named targets before shipping, with machine-readable results. Don't compete with uv on resolving or installing, or with Docker on isolation; that gap is small. Confidence: medium.

## Key Findings

| # | Finding | Label | Confidence |
|---|---|---|---|
| 1 | Agent-authored code is now a large share of new code at major firms and on GitHub | [evidence] for volume; company percentages are self-reported | High |
| 2 | Agent code has specific portability faults: hallucinated packages, secrets, assumed environments | [evidence] | High |
| 3 | Agents are poor at building environments from scratch, and good when environments are prebuilt | [evidence] | Medium-high |
| 4 | Sandboxes split into "no installs" and "bring an image or template" models, with no common input format | [evidence] | High |
| 5 | llms.txt has no measured benefit for search crawlers; its main real consumer is coding agents fetching docs | [evidence] | Medium |
| 6 | uv and PEP 723 already cover most "share a single script" needs where uv is installed and the network is available | [evidence] + [inference] | Medium-high |

## Part 1: Agents as authors

### How much code agents write
- **GitHub (Octoverse 2025, Oct 2025):** TypeScript overtook Python in August 2025 as the most-used language on GitHub by monthly contributors. Python remained #2, with 9,261,587 contributors. GitHub calls Python "AI's default glue."\[1\]\[2\] It reports "nearly 80% of new developers used Copilot within their first week" (Octoverse 2025, Oct 28, 2025). GitHub's own Octoverse post says the coding agent created "1+ million pull requests" between May and September 2025. [evidence, vendor-reported] GitHub claims typed languages make agent output more reliable; that is [inference/vendor framing], not a measured result.\[3\]
- **AIDev dataset (Li et al., 2025–2026):** 932,791 agent-authored pull requests across 116,211 repositories, from Codex, Devin, Copilot, Cursor and Claude Code, up to August 1, 2025.\[4\]\[5\] A curated subset of 33,596 PRs comes from 2,807 repositories with 100+ stars, dominated by Codex (21,799).\[6\] [evidence] Merge rates for fix PRs ranged from 81.6% (Codex) to 42.9% (Devin), and 46.41% of fixes from Copilot, Devin, Cursor and Claude were rejected (arXiv 2602.00164; arXiv 2606.13468).\[7\]\[8\] [evidence]
- **Anthropic Economic Index:** 79% of Claude Code conversations were classed as "automation", against 49% on Claude.ai (software-development report, 2025). Software-development tasks were judged successful 61% of the time, against 78% for personal tasks (January 2026 report).\[9\]\[10\] [evidence, vendor-published and model-classified]
- **Google:** Sundar Pichai said in April 2025 (Q1 earnings call) that the share of checked-in code that "involves people accepting AI-suggested solutions" was "well over 30%".\[11\] That is acceptance of AI suggestions, not code written autonomously by agents. The earlier figure was "more than a quarter" (October 2024).\[12\] In his own Google blog post for Cloud Next '26 (Apr 22, 2026), Pichai wrote that "75% of all new code at Google is now AI-generated and approved by engineers, up from 50% last fall." [evidence of the statement; the number is self-reported]
- **Microsoft:** Satya Nadella said at LlamaCon (April 29, 2025) that "maybe 20%, 30%" of code in Microsoft repos was "written by software". He hedged it to "some of our projects", and there is no official transcript.\[13\] [evidence of the statement; the number is self-reported]

**Interpretation [inference]:** Nobody has a defensible global figure for "share of new Python written by agents". What is measurable is a steep rise: GitGuardian counted Claude Code co-authored commits going from 22 in January 2025 to 2.16 million in December 2025.\[14\] That count only covers commits that carry the co-author tag.\[15\]

### What agent code looks like, and what breaks elsewhere
| Failure mode | Evidence | Source and date |
|---|---|---|
| Hallucinated or missing packages | 19.7% of recommended packages were hallucinated across 16 models: about 5.2% for commercial models, 21.7% for open-source. 205,474 unique fake names\[16\]\[17\] | Spracklen et al., USENIX Security 2025 |
| Still true in 2026 | 4.62% (Claude Haiku 4.5) to 6.10% (GPT-5.4-mini) on 199,845 prompts across 5 frontier models. The spread between models has narrowed, but 127 fake names are invented identically by all 5 models, and 53 of them "remain registrable by an attacker" | arXiv 2605.17062, 2026 |
| Secrets | Claude Code co-authored commits leaked secrets at 3.2%, against a 1.5% baseline. 24,008 unique secrets in public MCP config files, 2,117 of them valid. 28.65M new secrets found on public GitHub in 2025 (+34% year on year)\[18\]\[19\] | GitGuardian State of Secrets Sprawl, Mar 17, 2026\[20\] [evidence from a security vendor; its incentives favour alarm] |
| Larger change sets | Claude Code commits have about 2× the lines of human-only commits\[21\] | GitGuardian 2026 |
| Redundant code | Agent PRs contain more redundant code than human PRs\[22\] | Huang et al. 2026, as cited in arXiv 2607.21832 |
| Assumed environment | Agents call bare `python` when only Pixi is available; "kept trying to run python directly"\[23\] | Eric J. Ma blog, Oct 4, 2025\[23\] |

**PEP 723 and lockfiles:** I found no published count of PEP 723 adoption, and none of agent-written code specifically. [unverified] Qualitative evidence is strong. A python.org Discourse thread, "In Praise of PEP 723", calls it "a huge success".\[24\] Agent toolkits now require PEP 723 headers on standalone scripts (e.g. topij/agentic-dev-kit issue #942, 2026).\[25\] Agent sandboxes are being asked to accept PEP 723 as a "declared environment" (LightconeResearch/lightcone-cli issue #244).\[26\] One gap remains: `uv run python script.py` silently ignores inline metadata (leynos/agent-helper-scripts issue #180).\[27\] [evidence] I found no study comparing how often agent and human code includes tests or lockfiles. [unverified]

## Part 2: Agents as operators

### What agents struggle with
- **Setting up environments from scratch is hard.** On EnvBench (JetBrains, ICLR 2025 DL4C), the best approach (a Bash agent on GPT-4o) set up only 6.69% of 329 Python repos, against 29.47% of JVM repos.\[28\] Python was the harder ecosystem.\[29\] [evidence; older models] On SetupBench (arXiv 2507.09063, July 2025), OpenHands succeeded 34.4–62.4% of the time, with the weakest results on repo setup and local databases.\[30\] [evidence]
- **Terminal-Bench 2.0 (ICLR 2026):** the failure taxonomy includes "missing CLI utility dependency", "dependency resolution unsatisfied" and DNS failures.\[31\]\[32\] Secondary summaries put "command not found / missing executable" at about 24% of command failures.\[33\] [evidence; secondary percentage] The benchmark itself rotted. Terminal-Bench 2.1 (tbench.ai, May 6, 2026) fixed 28 of 89 tasks. Its maintainers wrote that 2.0 "pinned pre-built Docker images for reproducibility, but internet access introduces external dependencies," and found nine tasks where those dependencies changed. The fixes raised scores by up to 12.1 points. Benchmark authors with pinned Docker images still couldn't freeze the internet. [evidence] This is the most important single data point for a portability tool.
- **Network policy:** Codex Cloud runs setup scripts with internet access but turns internet off for the agent phase by default. Its docs' advice for "Agent cannot install packages" is to move installs into setup.\[34\] [evidence, OpenAI docs, 2026]
- **Tool output and prompts:** I found no issue in uv, pip, Poetry, pixi or conda about interactive prompts hanging agents or ANSI/progress output polluting agent context. [unverified; absence of evidence] Related evidence: uv issue #13901 (June 2025) requested an llms.txt because "most LLMs struggle with commands like uv".\[35\] uv issue #19677 asks `uv init` to generate agent instruction files, because assistants "frequently mismanage project environments".\[36\] [evidence]

### What tool authors do to be "agent-friendly", and whether it helps
- **llms.txt:** no measurable benefit for search or answer crawlers. Ahrefs found 97% of llms.txt files got zero requests (June 2026, 137,000 domains).\[37\] OtterlyAI saw 84 of 62.1K AI-bot hits go to llms.txt (about 0.1%).\[38\] SE Ranking's citation model got *better* when llms.txt was removed (about 300,000 domains).\[39\] [evidence from SEO vendors, which is the relevant population] One nuance from Ahrefs' May 2026 logs (published Jun 15, 2026): the Claude Code indexer made 3.52% of llms.txt requests. That is more than ClaudeBot (0.8%) or OAI-SearchBot (0.74%), though behind SEO audit tools (21.7%) and GPTBot (4.51%). Documentation for coding agents is a real, if small, use. [evidence, secondary]
- **AGENTS.md / CLAUDE.md:** widely adopted as a convention, but I found no controlled measurement of their effect. [unverified]
- **Machine-readable output and stable exit codes:** plausible and cheap, but I found no benchmark isolating their effect on agent success. [inference]

## Part 3: People and platforms consuming agents' output

### People
The evidence here is thinner than I wanted. Reddit and Stack Overflow searches turned up no usable threads. [gap flagged] What I found:
- OpenAI Developer Community: "I had ChatGPT write a simple Python script…", followed by "ModuleNotFoundError: No module named 'openai'" (probably late 2024).\[40\]\[41\]
- Cursor user, "Vibe Coding 101" (noenthuda Substack, undated): "I just can't wrap my head around things like virtual environments."\[42\]
- Scheduling: a Microsoft Q&A user's script "runs manually" but Task Scheduler returns 0x1 (Aug 28, 2023; no AI involved, but it is the classic failure).\[43\]
- PyInstaller ModuleNotFoundError when turning a script into an .exe for others (GitHub Community discussion #145834, Nov 2024).\[44\]

**[inference]** The recurring problems are old ones: wrong interpreter, missing packages, venv confusion, scheduler environments differing from the user's shell, and sharing with people who have no Python at all. Agents mostly add volume: more people now hold scripts they didn't write and can't debug. People want "double-click to run" and "send this to a colleague". MCPB's "zero configuration" pitch is aimed at exactly this. [vendor marketing]

### Platforms (as of the dates shown)
| Platform | Python | Runtime installs | Network | Limits | How dependencies get in | Date |
|---|---|---|---|---|---|---|
| Claude API code execution | 3.11(.12) | No | None | 5 GiB RAM, 5 GiB disk, 1 CPU | Preinstalled stack only (pandas, numpy, scipy, sklearn, docx/pptx/pdf libraries) | Anthropic docs, 2026\[45\]\[46\]\[47\]\[48\]\[49\] |
| Claude Agent Skills (API) | Same container | No | None | Third-party guides cite 8 skills per request and 30 MB per skill [unverified in primary docs] | Bundle files in the skill; rely on preinstalled packages | Anthropic docs, 2026 |
| Claude Skills (claude.ai / Claude Code) | Host | Yes | claude.ai: admin-set allowlist; Claude Code: full network | — | Local installs; docs discourage global installs | Anthropic docs, 2026 |
| Claude Managed Agents environments | Configurable | Yes, via `packages` field, cached | `limited` (allowlist) or `unrestricted` | — | Package list in environment config | Anthropic docs, 2026 |
| OpenAI Codex Cloud | universal image, pinnable runtimes | Setup phase only by default | Agent phase off by default; limited or unrestricted optional | Container cache up to 12 h | Setup script; auto-detects pip/poetry/pipenv | OpenAI docs, 2026\[50\]\[51\]\[52\] |
| Gemini API code execution | Python only | No ("You can't install your own libraries") | None | 30 s per run; up to 5 retries | Fixed list (numpy, pandas, sklearn, tensorflow…) | Google docs, 2026\[53\] |
| E2B | Template-defined | Yes (pip in sandbox) | Allowed | Hobby: 1 h continuous, 20 concurrent; Pro ($150/mo): 24 h; builds ≤1 h, 10–20 GiB disk | Templates (base image + pipInstall/aptInstall), snapshotted | E2B docs, 2026\[54\]\[55\]\[56\] |
| Modal | 3.10–3.14 (3.9 dropped Dec 2025) | Image-build time | Allowed | — | `uv_pip_install`, `uv_sync` from uv.lock, registry images | Modal docs/changelog, 2025–26\[57\]\[58\] |
| MCP bundles (.mcpb) | Host-provided via uv | Host installs at first run | Needs internet at first install | — | `server.type: "uv"` with pyproject.toml (manifest 0.4, added Dec 2025, "experimental"); or vendored `lib/` | MCPB PR #158; ToolUniverse docs\[59\]\[60\]\[61\] |

I did not verify the following. Daytona, Vercel Sandbox, Cloudflare Python Workers/Pyodide, Colab/Kaggle, Databricks, GitHub Actions, Lambda and Cloud Run were outside my search budget. Treat them as uncovered, not as checked.

**What users ask for [evidence]:**
- **MCPB uv runtime:** it exists because vendored Python bundles broke. Pydantic's compiled core "requires the exact python version" the bundle was built with (MCPB PR #158).\[61\]
- **Registries lag the spec:** Smithery's CLI rejects valid `uv`-type bundles (smithery-cli issues #801, #823, 2026).\[62\]\[63\]
- **Skill authors keep hitting the gap between surfaces:** a skill that runs `pip install` "works in Claude Code and fails here" in the API, according to third-party guides.\[48\]

## Part 4: The paradigm shift

| Candidate shift | Evidence for | Who benefits | What would have to be true | What would make it fail | Verdict |
|---|---|---|---|---|---|
| **Environments, not apps, are what travels** | Modal `uv_sync`, E2B templates, Codex setup scripts, Claude `packages` field, MCPB uv type all ship a description of the environment | Platforms, agents | Lockfiles reproduce across OS and architecture; registries stay reachable | Air-gapped sandboxes; dependency drift (Terminal-Bench 2.1) | Believe — medium-high |
| **Ephemeral, run-once code** | 79% automation in Claude Code; sandboxes with 30 s to 24 h lifetimes; Gemini/Claude run-and-discard | Analysts, chat users | Cheap and fast cold starts; the preinstalled stack covers the task | Users keep and schedule scripts (Task Scheduler, cron) | Partly — most such code never needs packaging; the code that survives does |
| **Sandboxes make local packaging irrelevant** | Many no-install sandboxes with rich preinstalled stacks | Vendors | The preinstalled set covers the long tail | Long-tail packages, private code, local data, compliance, offline machines | Don't believe — low |
| **Standard formats agents produce and verify** | PEP 723, PEP 751 pylock.toml, uv.lock, MCPB manifest, SKILL.md; agent toolkits enforce PEP 723 | Everyone | Platforms accept the standard formats directly | Every platform keeps its own format (Skills vs Codex vs E2B) | Believe in the formats; doubt platforms converging on them — medium |
| **Pre-ship "will it run there?" checks** | Hallucination rates around 5%; secret leaks 2× baseline; Codex/Claude/Gemini install rules differ; agents fail at setup | Agents, receivers, platforms | Target profiles are published and machine-readable | Platforms change quarterly; checks drift | Believe — medium; the clearest gap |
| **Supply-chain gating at install time** (not on your list) | Slopsquatting attack surface; 205k hallucinated names | Security teams | Registries/indexes expose "exists, age, popularity" signals | Package hallucination falls below about 1% | Believe — medium |
| **Secrets separated from code** (not on your list) | GitGuardian MCP-config data | Platforms | Standard secret-injection conventions | — | Believe — medium |

**The case against (strong):**
- uv already does most of the job. It installs Python itself, resolves PEP 723 scripts on the fly, and supports `uv lock --script` and `uv run --locked`.\[64\]
- Docker/OCI already serves as the universal format sandboxes consume: E2B templates, Modal registry images, Codex's published `codex-universal` image.
- Agents can be told "add PEP 723 metadata" or "write a Dockerfile", and toolkits already enforce this.
- Sandboxes with preinstalled scientific stacks handle the run-once analysis case completely.
- Agents improve at iterative repair. SetupBench's best score of 62.4% sits far above EnvBench's 6.69% with older models.\[28\]\[30\]

So a large share of the "it won't run elsewhere" problem may be solved by agents using uv by default. [inference] What these tools don't cover:
- No-network targets, where uv can't fetch anything.
- Non-technical recipients with no uv installed.
- Checking against a target *before* the target fails.
- Cross-platform compiled wheels (the pydantic case).

## Part 5: What a tool should offer

Capabilities are ranked by the evidence of need found above.

| Rank | Capability | For | Evidence of need | Already provided by | Gap size |
|---|---|---|---|---|---|
| 1 | Check against target profiles: "this script needs X, which Claude API, Gemini or Codex agent-phase lacks" | Agent, platform | Fragmented sandbox rules; Skills that fail between surfaces | Nothing general; partial: `mcpb validate`, `uv run --locked` | **Large** |
| 2 | Check that every dependency exists and is legitimate (anti-slopsquatting) | Agent | 4.6–6.1% hallucination (2026) | Partial: Socket/Snyk-style scanners [not researched] | Medium |
| 3 | Offline/air-gapped bundle: pre-resolved wheels per platform | Platform, receiver | No-network sandboxes; MCPB pydantic problem | pex, shiv, `uv` wheel caches, PyInstaller, Docker | Small-medium |
| 4 | Secret detection and separation before shipping | Agent | 3.2% vs 1.5% leak rate | GitGuardian, gitleaks | Small |
| 5 | One-command run for non-technical receivers | Receiver | Forum anecdotes (thin) | uv shebang scripts, PyInstaller, PyApp, MCPB | Small-medium |
| 6 | Turn one declared environment into each platform's format (E2B template, Modal image, Codex setup, Dockerfile) | Agent, platform | Every platform has its own format | Modal `uv_sync`; manual elsewhere | Medium |
| 7 | Machine-readable output, stable exit codes, no prompts | Agent | Plausible; unmeasured | uv mostly does this | Small |
| 8 | Docs written for models (llms.txt) | Agent | No measured benefit | Cheap to add | Negligible |

## Caveats
- **Vendor bias:** Company percentages (Google, Microsoft, GitHub, Anthropic) are self-reported and defined differently. GitGuardian and the llms.txt studies come from vendors with incentives.
- **Fast-moving and possibly outdated:** Benchmark models age fast (EnvBench used GPT-4o). Platform limits change quarterly; re-check them before building.
- **Not verified:** PEP 723 adoption counts; how often agents write tests or lockfiles compared with humans; forum evidence on receivers; several platforms, including Daytona and Vercel.

## One-page summary

| Shift | Do I believe it? | Confidence | What a tool should do |
|---|---|---|---|
| The environment description (PEP 723/pyproject + lock) becomes what travels | Yes | High | Treat it as the single input; never invent a new manifest |
| Pre-ship checks that code will run on a named target | Yes, and the biggest gap | Medium | Ship machine-readable target profiles (Claude API, Gemini, Codex, E2B, Modal, MCPB, Lambda) and a JSON verdict an agent can act on |
| Supply-chain checks on agent-chosen dependencies | Yes | Medium | Check that packages exist, their age and their reputation during the check |
| Run-once code dominates | Partly | Medium | Ignore it: preinstalled sandboxes serve it. Focus on code that survives to be shared or scheduled |
| Sandboxes make local packaging irrelevant | No | Low that it happens | Support no-network targets with pre-resolved, platform-specific wheel bundles |
| Platforms converge on one format | No, not within 2–3 years | Low-medium | Translate one environment into each platform's format; this is the durable value |
| Agent-friendly CLI and llms.txt drive adoption | Hygiene only | Medium | Do it cheaply: `--json`, no prompts, stable exit codes. Don't market it |
| uv, Docker and agents already cover most of it | Largely yes | Medium-high | Build on uv rather than against it; the defensible product is verification and translation, not resolution or isolation |

## Sources

1. [TypeScript Tops GitHub Octoverse as AI Era Reshapes Language Choices -- Visual Studio Magazine](https://visualstudiomagazine.com/articles/2025/10/31/typescript-tops-github-octoverse-as-ai-era-reshapes-language-choices.aspx)
2. [Octoverse: A new developer joins GitHub every second as AI leads TypeScript to #1 - The GitHub Blog](https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/)
3. [How AI is reshaping developer choice (and Octoverse data proves it) - The GitHub Blog](https://github.blog/ai-and-ml/generative-ai/how-ai-is-reshaping-developer-choice-and-octoverse-data-proves-it/)
4. [Agentic Software Engineering: Foundational Pillars and a Research Roadmap](https://arxiv.org/pdf/2509.06216)
5. [Paper page - AIDev: Studying AI Coding Agents on GitHub](https://huggingface.co/papers/2602.09185)
6. [Security in the Age of AI Teammates: An Empirical Study of Agentic Pull Requests on GitHub](https://arxiv.org/pdf/2601.00477)
7. [Understanding the Rejection of Fixes Generated by Agentic Pull Requests - Insights from the AIDev Dataset](https://arxiv.org/html/2606.13468)
8. [Why Are AI Agent–Involved Pull Requests (Fix-Related) Remain Unmerged? An Empirical Study](https://arxiv.org/html/2602.00164v1)
9. [Economic Index report: Economic primitives \\ Anthropic](https://www.anthropic.com/research/anthropic-economic-index-january-2026-report)
10. [Societal ImpactsEconomic Research](https://anthropic.com/research/impact-software-development)
11. [2025-q1-earnings-transcript.pdf](https://s206.q4cdn.com/479360582/files/doc_financials/2025/q1/2025-q1-earnings-transcript.pdf)
12. [Alphabet CEO says more than a quarter of new code at Google is AI-generated](https://www.techradar.com/pro/alphabet-ceo-says-more-than-a-quarter-of-new-code-at-google-is-ai-generated)
13. [‘Developers will need to adapt’: Microsoft CEO Satya Nadella joins Google’s Sundar Pichai in revealing the scale of AI-generated code at the tech giants](https://www.itpro.com/software/development/developers-will-need-to-adapt-microsoft-ceo-satya-nadella-joins-googles-sundar-pichai-in-revealing-the-scale-of-ai-generated-code-at-the-tech-giants-and-its-a-stark-warning-for-software-developers)
14. [The state of secrets sprawl in 2026: Key findings from GitGuardian's report](https://passwork.pro/blog/the-state-of-secrets-sprawl-in-2026/)
15. [AI Code Leaked 29M Secrets in 2025: GitGuardian](https://tfir.io/ai-code-secret-sprawl-gitguardian/)
16. [\[2605.17062\] The Range Shrinks, the Threat Remains: Re-evaluating LLM Package Hallucinations on the 2026 Frontier-Model Cohort](https://arxiv.org/abs/2605.17062)
17. [GitHub - Spracks/PackageHallucination: Code and data for the USENIX 2025 paper "We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code Generating LLMs" · GitHub](https://github.com/Spracks/PackageHallucination)
18. [The State of Secrets Sprawl 2026: AI-Service Leaks Surge 81% and 29M Secrets Hit Public GitHub - DEV Community](https://dev.to/gitguardian/the-state-of-secrets-sprawl-2026-ai-service-leaks-surge-81-and-29m-secrets-hit-public-github-2bgj)
19. [The State of Secrets Sprawl 2026: AI-Service Leaks Surge 81% and 29M Secrets Hit Public GitHub](https://daily.dev/posts/the-state-of-secrets-sprawl-2026-ai-service-leaks-surge-81-and-29m-secrets-hit-public-github-9jppqgnjt)
20. [AI Is Fueling Secrets Sprawl. GitGuardian Reports an 81% Surge of AI-Service Leaks as 29M Secrets Hit Public GitHub](https://blog.gitguardian.com/the-state-of-secrets-sprawl-2026-pr/)
21. [The State of Secrets Sprawl 2026](https://nhimg.org/the-state-of-secrets-sprawl-2026)
22. [How Do AI Coding Agents Contribute to Software Development? an Empirical Study of Agentic Pull Requests](https://arxiv.org/html/2607.21832v1)
23. [How to teach your coding agent with AGENTS.md](https://ericmjl.github.io/blog/2025/10/4/how-to-teach-your-coding-agent-with-agentsmd/)
24. [In Praise of PEP 723 - User Feedback - Discussions on Python.org](https://discuss.python.org/t/in-praise-of-pep-723/84039)
25. [Triage entry points need standalone PEP 723 metadata for adopter uv invocation · Issue #942 · topij/agentic-dev-kit](https://github.com/topij/agentic-dev-kit/issues/942)
26. [Sandbox blocks uv run for PEP 723 scripts: can inline script metadata count as a declared environment? · Issue #244 · LightconeResearch/lightcone-cli](https://github.com/LightconeResearch/lightcone-cli/issues/244)
27. [Correct uv script metadata guidance for direct execution · Issue #180 · leynos/agent-helper-scripts](https://github.com/leynos/agent-helper-scripts/issues/180)
28. [ICLR EnvBench: A Benchmark for Automated Environment Setup](https://iclr.cc/virtual/2025/34818)
29. [EnvBench: A Benchmark for Automated Environment Setup — Lacuna](https://lacuna.tiptreesystems.com/work/envbench-a-benchmark-for-automated-environment-setup/wrk_3a5ceb6bac405880dd74a5369bb29682)
30. [SetupBench: Assessing Software Engineering Agents' ...](https://arxiv.org/pdf/2507.09063)
31. [Published as a conference paper at ICLR 2026 TERMINAL-BENCH: BENCHMARKING](https://proceedings.iclr.cc/paper_files/paper/2026/file/444a3737adaee10d86ad2ef5f74468e6-Paper-Conference.pdf)
32. [(PDF) Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces](https://www.researchgate.net/publication/399931917_Terminal-Bench_Benchmarking_Agents_on_Hard_Realistic_Tasks_in_Command_Line_Interfaces)
33. [Terminal-Bench 2.0: AI Agent Benchmark](https://www.emergentmind.com/topics/terminal-bench-2-0)
34. [Cloud Environment Tips](https://developertoolkit.ai/en/codex/tips-tricks/cloud-workflows/)
35. [Generate an llms-text file to improve the experience of working with AI agents and UV. · Issue #13901 · astral-sh/uv](https://github.com/astral-sh/uv/issues/13901)
36. [Feature Request: \`uv init\` should generate LLM/AI assistant configuration to guide correct environment and command usage (similar to \`bun init\`) · Issue #19677 · astral-sh/uv](https://github.com/astral-sh/uv/issues/19677)
37. [LLMs.txt Tracking Study and Live Dashboard](https://originality.ai/blog/llms-txt-tracking-study)
38. [llms.txt and AI Visibility: Results from OtterlyAI's GEO Study](https://otterly.ai/blog/the-llms-txt-experiment/)
39. [llms.txt for AI Crawlers](https://www.profitbyclix.com/blog/llms-txt-for-ai-crawlers/)
40. [Import openai module not found error in simple chatbot script - Plugins / Actions builders - OpenAI Developer Community](https://community.openai.com/t/import-openai-module-not-found-error-in-simple-chatbot-script/329000)
41. [For the new Canvas Run command, how/where does ChatGPT install necessary Python libraries? - Community - OpenAI Developer Community](https://community.openai.com/t/for-the-new-canvas-run-command-how-where-does-chatgpt-install-necessary-python-libraries/1050475)
42. [Vibe Coding 101](https://noenthuda.substack.com/p/vibe-coding-101)
43. [How to fix (0x1) error in task scheduler that runs a python script?](<https://learn.microsoft.com/en-us/answers/questions/1353553/how-to-fix-(0x1)-error-in-task-scheduler-that-runs>)
44. [Solution](https://github.com/orgs/community/discussions/145834)
45. [Code execution tool - Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool)
46. [Code execution tool - Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool?vid=99)
47. [Agent Skills - Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
48. [Claude Skills on claude.ai and the Claude API (2026) — AgentsCamp](https://agentscamp.com/guides/skills/claude-skills-on-claude-ai-and-api)
49. [Cloud environment setup - Claude Platform Docs](https://platform.claude.com/docs/en/managed-agents/environments)
50. [Codex Cloud (Legacy)](https://developers.openai.com/codex/cloud/environments)
51. [Codex Cloud vs Codex Local: When to Run in the Cloud](https://codex.danielvaughan.com/2026/03/27/codex-cloud-vs-local-when-to-run-in-cloud/)
52. [How to Run OpenAI Codex in the Cloud (2026) - Replicas.dev](https://replicas.dev/resources/codex-in-the-cloud)
53. [Code execution](https://ai.google.dev/gemini-api/docs/code-execution)
54. [E2B](https://mastra.ai/integrations/sandboxes/e2b)
55. [Quickstart - E2B Docs](https://e2b.dev/docs/sandbox-template)
56. [Billing & limits - E2B Docs](https://www.e2b.dev/docs/sandbox/rate-limits)
57. [Images](https://modal.com/docs/guide/images)
58. [Changelog](https://modal.com/docs/reference/changelog)
59. [MCP Bundle - ToolUniverse Documentation](https://zitniklab.hms.harvard.edu/ToolUniverse/guide/building_ai_scientists/mcpb_introduction.html)
60. [MCPB Files (.mcpb): Format Reference, Manifest, and Examples](https://www.mcpbundles.com/docs/concepts/mcpb-files)
61. [github.com](https://github.com/modelcontextprotocol/mcpb/pull/158)
62. [mcp publish: an MCPB bundle with server.type "uv" (manifest 0.4) is rejected · Issue #823 · arcadeai-labs/smithery-cli](https://github.com/arcadeai-labs/smithery-cli/issues/823)
63. [mcp publish: support MCPB server.type "uv" · Issue #801 · arcadeai-labs/smithery-cli](https://github.com/arcadeai-labs/smithery-cli/issues/801)
64. [What is PEP 723?](https://pydevtools.com/handbook/explanation/what-is-pep-723/)
