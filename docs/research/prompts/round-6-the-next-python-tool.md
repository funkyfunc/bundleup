# Round 6: the next tool for shipping Python, seen through the JavaScript ecosystem's history

Written 2026-10-08 at the owner's request. Run it in a deep-research tool. **Attach nothing**: the
point is an outside view, not a check of bundleup's own story (round 2b found that attaching our
documents anchors the answer). Round 2 ([report](../round-2-evolution-compass.md)) already covered
how tools replaced each other; this round uses that history as a lens on what comes next.

**Copy only the fenced block below into the research tool.**

````markdown
# Research brief: What will be the next widely adopted tool for shipping Python, judged by the lessons of the JavaScript tooling ecosystem?

## Context
I'm building a developer tool in the Python packaging and distribution space, and I want an
outside, evidence-based view of where the real opportunities are, not validation of any idea I
already have. Please don't try to guess or favour my tool; evaluate the space on its merits.
"Shipping" here means getting Python code to run somewhere other than the machine it was written
on: a colleague's laptop, a server, a container, a serverless function, a CI job, a sandbox, an
end user's desktop.

## Part 1: The lessons of the JavaScript ecosystem (the lens)
Distil, in at most two pages, what made each of these JavaScript tools win, stall or fade, and
what the general lessons are: Browserify, webpack, Rollup, Parcel, esbuild, Vite, SWC, tsup and
tsdown, Bun, Turbopack and Rspack, plus npm, Yarn and pnpm. For each, name the specific reason
with evidence (a capability nobody else had, a speed step change, owning one job, zero
configuration, being embedded in other tools, a workflow insight, backing by a company), and what
it replaced and why. Then state the lessons as a short list of rules of the form "tools win when
... ; tools stall when ...", each tied to at least two examples. Include the failures and the tools
that lost despite being good.

## Part 2: Python today, through that lens
Map the current Python tools for building, packaging, distributing and running code onto those
lessons: uv and uvx, pip and pipx, Poetry, PDM, Hatch, conda and pixi, pex, shiv, zipapp,
PyInstaller, Nuitka, PyOxidizer, PyApp, conda-pack, Briefcase, scie and science, python-build-
standalone, Docker-based workflows, and the standards (PEP 723 inline script metadata, PEP 751
pylock.toml, PEP 711, PEP 668). For each: what job it owns, which lesson explains its position, how
active it is (releases and commits in the last 12 months), and what it can't do. Say which tool
today plays the role esbuild or Vite played, if any, and which roles are empty.

## Part 3: What people complain about and ask for (evidence, not opinion)
Collect concrete evidence of unmet needs in shipping Python, from the last 24 months:
- **Issue trackers:** the most-reacted open feature requests and long-running issues about
  bundling, single-file distribution, offline installs, cross-platform builds, startup time and
  "works on my machine" in the repositories of uv, pip, pex, PyInstaller, Nuitka, Poetry, Hatch,
  conda and pixi. Give the issue number, title, link, reaction or comment count, and status.
- **Discussion:** recurring complaints on discuss.python.org (Packaging category), Hacker News,
  Reddit (r/Python, r/learnpython, r/devops, r/MachineLearning), Stack Overflow, Mastodon and X.
  Quote short phrases (under 15 words each) with links and dates; give counts or scores where
  available.
- **Surveys:** what the Python Developers Survey and similar surveys say about packaging and
  deployment pain.
Group the evidence into themes, rank the themes by how much evidence supports them, and for each
say who feels it (beginners, data scientists, web developers, ops, enterprise teams, tool authors)
and how they work around it today.

## Part 4: What could come next
Using Parts 1 to 3, describe the three to five most plausible "next things" in shipping Python:
a tool, a standard, or a workflow. For each: the job it would own, which JavaScript lesson it
follows, the evidence of demand from Part 3, who could build it (including the risk that uv,
Astral or another incumbent ships it first), and what would make it fail. Be explicit about which
of these are well supported by evidence and which are speculation. Also name ideas that sound
promising but the evidence argues against.

## Requirements
- Cite sources with links and dates; prefer primary sources (issue trackers, release notes,
  official docs, the people who built the tools). Mark anything you couldn't verify.
- Separate evidence from your own inference throughout.
- Don't pad: tables are welcome; a short, well-supported report beats a long one.
- End with a one-page summary: the lessons, the biggest gaps, and the top candidates for what comes
  next, each with a confidence level.
````
