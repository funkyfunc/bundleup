# Synthesis: round 3 (agents) and round 2b (unanchored evolution), 2026-10-04

Reports:
- [round-3-agents-compass.md](round-3-agents-compass.md): the round 3 brief. Thorough, well sourced.
- [round-3-agents-gemini.md](round-3-agents-gemini.md): the round 3 brief. **Truncated**: only the
  executive verdict and the start of Part 1 survived export.
- [round-2b-evolution-compass-unanchored.md](round-2b-evolution-compass-unanchored.md): the round 2
  brief re-run **without** round 1 attached, to check whether round 2's conclusions were anchored.

Key claims were verified by hand; see [verification-notes.md](verification-notes.md).

## Round 3: is "the bundler for agents" authentic?

**Verdict (both reports agree): authentic as a use case, not as a category.** Calling bundling an
agent technology would be "agent-washing" (Gemini's word). The honest lead is the general promise
(one file, plain Python, no install, no network), which is exactly
[ADR-0012](../adr/0012-lead-with-what-it-does.md). Agent sandboxes are the sharpest, most concrete
example, and skills are the one agent format where a bundler adds something no platform provides.

### The documented gap (verified)

- **Claude API Skills run "in a sandboxed container with no network access and no runtime package
  installation"**: Python 3.11, Linux x86_64, pre-installed packages only.
- **The Agent Skills guide (agentskills.io) recommends PEP 723 + `uv run`** for scripts with
  dependencies, which installs at run time and so needs network. The recommended pattern can't
  work on the flagship runtime. A pre-resolved `.pyz` closes exactly that gap.
- claude.ai (egress off), ChatGPT data analysis and Codex's default agent phase are also
  no-network for the code that runs.

### The disproof (also verified)

- **MCP Bundles (MCPB) moved Python to host-side uv.** Its README: traditional Python bundles
  "Cannot portably bundle compiled dependencies (e.g., pydantic, which the MCP Python SDK
  requires)"; it recommends Node, or the newer `uv` server type where the host installs deps.
  Real failure: goodreads-mcp #89, a `.mcpb` that "only runs on Linux x86_64 with CPython 3.11"
  because of vendored compiled wheels.
- **Cloud coding agents** (Codex, Copilot, Cursor, Claude Code cloud) all have a networked setup
  phase. Installing dependencies there is a solved CI problem.
- **Remote MCP servers** avoid local packaging entirely.

### What's genuinely agent-specific

| Feature | Agent-specific? | Why it matters |
|---|---|---|
| **Target profiles for known sandboxes** (e.g. `claude-api` = CPython 3.11, manylinux x86_64, offline) | **Only agents** | Sandboxes publish a fixed interpreter and platform you can't change, so compiled wheels (pydantic, numpy) become shippable. Turns MCPB's "can't bundle pydantic" into a solved problem *for a known target* |
| **Skill output** (`scripts/<tool>.pyz` + a `SKILL.md` stanza + an honest `compatibility` line) | **Only agents** | No platform offers "skill script with dependencies that runs offline" |
| **Compatibility pre-check** (refuse native code that doesn't match the target) | More for agents | Prevents the goodreads-mcp failure; matters wherever build and run machines differ |
| Agent-operable CLI (`--json`, stable exit codes, no prompts) | More for agents | Also good CI ergonomics. agentskills.io's own script-design guidance asks for exactly this |
| Offline guarantee | More for agents | Air-gapped servers need it too, but agent sandboxes are offline by default |
| Manifest with hashes | Equally general | Makes the reviewed artifact the executed one; doesn't address the main agent threat (malicious instructions in `SKILL.md`) |
| MCPB output | Agent-only but **defer** | Competes with MCPB's own `uv` type and hits the compiled-wheel problem |
| Agents as packagers (a skill that teaches agents to bundle) | Hypothesis | **No evidence of demand found.** Validate with users before building |

### The one-sentence answer

> "Agent sandboxes are the most common place you can't install anything (Claude's code-execution
> container has no network, and Codex agents run offline by default), so bundleup turns a skill's
> script and its locked dependencies into one file that runs there with plain `python`."

Use it in docs and talks as the headline example, under the general description.

### What it changes for us

- **Cross-target builds move up.** Milestone 1 builds for the host only. Serving the flagship
  case means building a Linux x86_64 / CPython 3.11 bundle from a Mac. This was already "Near"
  (multi-platform bundles); target profiles make it concrete and testable.
- **Test coverage gap gets more important.** The gauntlet runs on macOS with 3.9 and 3.12. We
  need Linux x86_64 and Python 3.11 runs (CI, since there's no Docker here).
- Proposed as [ADR-0013](../adr/0013-agent-sandboxes-as-headline-use-case.md).

## Round 2b: did round 2 hold up without the anchor?

**Yes.** Run without round 1 attached, Compass reached the same conclusions as round 2, which
means those weren't just echoing the earlier report:
- Winners pair a **headline speedup** with **compatibility** (registry, plugin API, CLI, metadata).
- Python's transitions are gated by **PEPs**; bundling has no standard and no winner.
- Don't inline source (stickytape), don't use a custom importer or config language (PyOxidizer),
  don't overclaim or go quiet (Pipenv). Keep real files on disk; lockfile in, standard formats out.

New and useful:
- **Put a number in the launch post.** Every winner did ("10–100x", "minutes to seconds",
  "46 s to 6 s"). Milestone 1 already has candidates: warm start **29 ms vs pex's 396 ms (~14×)**
  and build **0.25 s vs 1.47 s (~6×)** on gauntlet 03
  ([findings](../findings/2026-10-04-milestone-1.md)).
- **uv has turned bundling requests away** (verified): #13503 (PyInstaller output) closed as *not
  planned*; #5802 labelled *wish*; #12035 (Lambda bundling) was closed by its own author, not
  implemented.
- **Python has no runtime vendor that absorbs tools** (unlike Node absorbing tsx's job). CPython
  absorbs slowly via PEPs, which leaves room for a third-party tool to own a category.
- **Stage big changes** the way Vite 8 did (preview package → beta → default), if we ever swap
  engines.
- A **Lambda zip layout** is a natural output alongside `.pyz` (already in the roadmap).

## Errors and gaps in these reports

- Gemini round 3 is truncated; its surviving verdict agrees with Compass. Its claim that Claude
  Desktop has no Python by default is consistent with the MCPB README (Node ships with it).
- Compass round 3 marks several sandboxes (Devin, Windsurf, Daytona, Modal) unverified and some
  details as third-party (claude.ai on gVisor). Re-check before quoting specs externally.
