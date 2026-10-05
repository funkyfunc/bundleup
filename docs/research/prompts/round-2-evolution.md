# Round 2: how tools evolved, and what to learn

**Copy only the fenced block below into the research tool.**

Produced `round-2-evolution-compass.md` and `round-2-evolution-gemini.md`. The round-1 compass
report was attached as context.

````markdown
# Research brief: How developer tools replaced each other in Python, JavaScript and other ecosystems, and what Python's next tools should learn from that

## Context
I'm an experienced JavaScript/TypeScript developer planning to build Python developer tools, probably starting with an esbuild-style bundler. I already have a snapshot of today's Python toolchain (attached / summarized below), so **don't re-describe current tools**. This research is about *how the tools evolved*: why each generation replaced the last, what users are still unhappy with, and which ideas from other ecosystems Python should adopt.

[Paste or attach the earlier report here]

## Part 1: How each JavaScript tool category evolved
Cover bundlers (Browserify → webpack → Rollup → Parcel → esbuild → Vite → Rspack/Rolldown/Turbopack), package managers (npm → Yarn → pnpm → Bun), runners (ts-node → tsx → Node's built-in type stripping) and linters/formatters (JSHint → ESLint → Prettier → Biome/oxc).
For each transition, answer:
- **Complaint:** what frustration with the old tool drove the change? Cite contemporary sources: launch posts, Hacker News threads, maintainers' explanations.
- **Approach:** what did the new tool do differently?
- **Compatibility:** what did it stay compatible with to make switching easy (config formats, APIs, plugins)?
- **Speed of change:** how fast did adoption happen, and what accelerated it?
- **Survival:** what happened to the old tool? Did it die, find a niche, or get absorbed?

## Part 2: How each Python tool category evolved
Answer the same questions for: installers and environments (easy_install → pip → virtualenv/venv → pip-tools → Pipenv → Poetry → PDM/Hatch → uv), build systems (distutils → setuptools → PEP 517 backends), freezers (py2exe → cx_Freeze → PyInstaller → PyOxidizer → PyApp/scie), bundlers (pex → zipapp/PEP 441 → shiv → ?), linters/formatters (pylint/flake8/Black → Ruff), and type checkers.
Also explain which standards (PEPs) made each transition possible, and which transitions stalled waiting for a standard.

## Part 3: What Python users are still unhappy with today
List the unresolved complaints about current tools, including uv, with evidence: GitHub issues sorted by reactions, discuss.python.org threads, survey data, Hacker News and Reddit threads from 2025–2026. For each complaint, say who has it and whether anyone is working on a fix.

## Part 4: What other ecosystems do best
Look at Go, Rust/Cargo, Zig, Julia (Pkg, BinaryBuilder/JLL), Elixir (Mix releases), Java (fat JARs, Shade, JBang, GraalVM), .NET (dotnet watch, trimming, file-based apps), Deno, Bun, Dart and Swift PM.
For each, pick the 1–3 things it does *best in class*. For each one, explain:
- the mechanism behind it;
- whether Python could adopt it, and what stands in the way (runtime semantics, standards, culture);
- whether anyone has tried it in Python, and what happened.

## Part 5: Lessons
Using Parts 1–4, write:
1. **Patterns in how new tools win:** what consistently made a new tool win (speed, compatibility, zero config, bundling several tools into one, standards), with examples from both ecosystems, and patterns in how tools lost.
2. **Ranked list of ideas worth bringing to Python:** each with value, feasibility and the main obstacle.
3. **Implications for a Python bundler:** what it should be compatible with, what complaint it should lead with, and what mistakes from earlier tools (stickytape, PyOxidizer, Pipenv) to avoid.

## Rules
- Prefer primary sources: launch blog posts, maintainers' writing, PEPs, GitHub issues. Cite every non-trivial claim with a link.
- Clearly separate documented history from your interpretation of it.
- Don't make up adoption numbers or audience sizes. If there's no data, say so.
- Skip beginner explanations.
````
