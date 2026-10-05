# Round 3: is there an authentic agent-specific angle?

**Copy only the fenced block below into the research tool.**

Run 2026-10-04 (reports: `round-3-*`). Written to test whether "the bundler for agents" is honest positioning or
just a label on a general tool. Attach `MISSION.md`, `docs/vision.md` and `docs/roadmap.md` as
context.

````markdown
# Research brief: How Python code gets distributed to and run by AI agents, and whether that needs anything a general-purpose bundler doesn't already provide

## Context
I'm building bundleup, a tool that turns a locked Python project into one `.pyz` file that runs on
plain Python with no install step and no network (attached: mission, vision, roadmap). Its value is
general: it helps anywhere you don't control the environment (serverless, CI, locked-down servers,
other people's machines). I'm considering positioning it as "the bundler for the agent era", but I
want to know whether that's **authentic**. If someone asks "what do you mean it's for agents?", I
need a concrete answer, or I should drop the angle.

**Be skeptical. Try to disprove the agent angle as hard as you try to support it.** "There's
nothing agent-specific here; position it generally" is a perfectly good conclusion.

## Part 1: How agent extensions that contain code are distributed today
For each, describe the format, how bundled code and its dependencies are expected to be shipped,
what the docs recommend for Python specifically, and what goes wrong:
- Agent Skills (the agentskills.io spec; Claude Code / Claude.ai skills; skill package managers
  such as apm; plugin marketplaces)
- MCP servers: local stdio servers launched via `uvx`/`pipx`/`npx`/Docker, remote servers, the
  MCP registry, and MCP Bundles (`.mcpb`, formerly Desktop Extensions `.dxt`). Verify the current
  status of MCPB and exactly how it handles Python dependencies
- Plugins/extensions for other agent tools (OpenAI Codex, Cursor, GitHub Copilot agents, Gemini
  CLI, Windsurf, etc.) where they can run local code

## Part 2: Where agent-run code actually executes
For each environment, list: OS/CPU, Python version(s) available, whether uv/pip are present,
network policy (none / allow-list / open), writable directories, preinstalled packages, whether
state persists between runs, and anything unusual (read-only home, no compiler, time limits):
- Claude API code-execution tool; Claude.ai file creation / analysis container; Claude Code on
  the user's machine and in cloud/remote sessions
- ChatGPT's code execution (data analysis); OpenAI Codex cloud tasks
- GitHub Copilot coding agent; Cursor background agents; Devin or similar
- General agent sandboxes: E2B, Modal, Daytona, Vercel Sandbox, Cloudflare containers
Cite official docs. Where documentation is silent, say so instead of guessing.

## Part 3: Evidence of the pain
Find concrete reports (GitHub issues, forum threads, docs warnings, blog posts) of Python skills,
MCP servers or agent tools failing because of: missing dependencies, uv not installed, blocked
network, wrong Python version, Windows, compiled extensions, or first-run install delays. Also:
what do authors do today instead (vendoring, rewriting in Node, Docker, "requires uv" notes,
avoiding dependencies altogether)? Quantify only where real data exists.

## Part 4: Agents as the ones doing the packaging
Is there evidence that agents write small tools they then can't easily ship or reuse? How do
agent platforms handle "save this script and its dependencies so it runs next time"? Would a
non-interactive, predictable bundling CLI (plus a skill that teaches agents to use it) change
anything?

## Part 5: Trust and security
How do agent platforms vet third-party skills and MCP servers today (signing, provenance, review,
sandboxing)? Does "runs offline, with a manifest of exactly what's inside" help with any real
concern, or is it irrelevant next to sandboxing?

## Part 6: Agent-specific versus general
Build a table of every candidate feature (offline guarantee, no-install, machine-readable output,
manifest/hashes, skill output format, MCP-server output format, agent-operable CLI, sandbox-aware
loader, small start-up time, etc.). For each, mark whether it matters **only** for agents,
**more** for agents, or **equally** for Lambda/CI/air-gapped servers. Steelman both positions:
"bundleup should lead with agents" and "agents are just one destination".

## Output
1. Verdict (half a page): is agent-first positioning authentic? If yes, write the one-sentence
   answer to "what do you mean it's for agents?". If no, say what to lead with instead.
2. Distribution formats (Part 1) as a table
3. Execution environments (Part 2) as a matrix
4. Evidence of pain (Part 3), with links
5. Agents as packagers (Part 4) and trust (Part 5)
6. The agent-specific vs. general table (Part 6)
7. Ranked list of features worth building for the agent case, if any
8. Sources

## Rules
- Prefer primary sources: official docs, specs, GitHub issues, maintainer posts. Cite every
  non-trivial claim with a link and date anything that changes quickly.
- Separate documented facts from your interpretation.
- Don't invent numbers or adoption figures. If there's no data, say so.
- Skip beginner explanations.
````
