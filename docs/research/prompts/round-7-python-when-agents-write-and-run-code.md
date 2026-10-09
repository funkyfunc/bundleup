# Round 7: Python when agents write, run and consume the code

Written 2026-10-08 at the owner's request. Run it in a deep-research tool. **Attach nothing**, as for
round 6. Round 3 ([report](../round-3-agents-compass.md)) looked at agent sandboxes and skills as
distribution targets; this round asks the broader question: what shifts when AI agents become
the main authors, operators and users of Python code.

**Copy only the fenced block below into the research tool.**

````markdown
# Research brief: What changes for writing, packaging and running Python when AI agents write and run most of the code?

## Context
I'm building a developer tool for getting Python code to run on machines other than the one it was
written on. I want to understand the paradigm shift the current wave of AI coding agents may cause,
so I don't build for the last era. Please don't try to guess or favour my tool; evaluate the shift
on its merits, including the possibility that it makes tools like mine less relevant.

## Part 1: Agents as authors
How much new Python is now written by AI agents (Claude Code, Codex, Cursor, Copilot, Devin and
others) or by people prompting them? What does that code look like compared with code people
write: dependencies, use of single scripts versus projects, use of PEP 723 inline script metadata,
lockfiles, tests? What goes wrong when it has to run elsewhere (missing packages, wrong Python,
platform-specific code, hard-coded paths, secrets)? Use studies, vendor reports, benchmark papers
and public issue reports; give numbers with sources.

## Part 2: Agents as operators
Agents now install packages, run builds, and execute code in sandboxes and on users' machines.
What do they struggle with in today's Python tooling (error messages, interactive prompts,
network access, virtual environments, long installs, inconsistent output), with evidence from
agent vendors' docs, bug reports and benchmarks? What do tool authors already do to be
"agent-friendly" (machine-readable output, stable exit codes, non-interactive modes, docs written
for models such as llms.txt), and does it measurably help?

## Part 3: People and platforms consuming agents' output
- **People:** someone receives a script or tool an agent wrote and wants to run it, share it with a
  colleague, or schedule it. What do they do today, what breaks, and what would they want? Look at
  forums, social media and support communities (quote short phrases under 15 words, with links).
- **Platforms:** agent skills and plugin systems (Claude Agent Skills, agent package managers,
  MCP servers), code-execution sandboxes (Claude, OpenAI, Google, E2B, Modal, Daytona), notebook
  and data platforms, CI and serverless. For each: what Python they offer, whether packages can be
  installed, network access, size limits, how third-party code with dependencies gets in, and what
  their docs and issue trackers say users ask for. Give dates; these change fast.

## Part 4: The paradigm shift
Based on Parts 1 to 3, what are the plausible shifts in how Python gets packaged and shipped over
the next two to three years? Consider at least: environments as the unit that travels instead of
apps; ephemeral, disposable code that is run once; sandboxes that make local packaging irrelevant;
standard formats agents can produce and verify; checks that tell an agent before it ships that
code won't run somewhere else; and anything the evidence suggests that isn't on this list. For
each: the evidence for it, who benefits, what would have to be true, and what would make it fail.
Include the case against: reasons the current tools (uv, Docker, sandboxes with preinstalled
packages) may already be enough.

## Part 5: What a tool should offer in that world
What should a tool that gets Python code running elsewhere offer to (a) an agent that wrote the
code, (b) the person who receives the agent's output, and (c) a platform that hosts it? Rank the
capabilities by evidence of need, and say which ones existing tools already provide.

## Requirements
- Cite sources with links and dates; prefer primary sources (vendor documentation, issue
  trackers, papers, the people building these systems). Mark anything you couldn't verify, and
  anything that is vendor marketing rather than evidence.
- Separate evidence from inference throughout; this topic attracts hype, so be sceptical.
- Tables are welcome; a short, well-supported report beats a long one.
- End with a one-page summary: the shifts you believe in, the ones you don't, and what a tool in
  this space should do about each, with confidence levels.
````
