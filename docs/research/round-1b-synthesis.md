# Synthesis: round 1b (a second run of the round 1 brief), 2026-10-04

Two reports came back, intended as round 3 (agents) but both answer the **round 1 brief**
(landscape, comparisons, esbuild/tsx hypotheses): [round-1b-landscape-compass.md](round-1b-landscape-compass.md)
and [round-1b-landscape-gemini.md](round-1b-landscape-gemini.md). Neither mentions agents, MCP or
skills. **The round 3 brief in [prompts.md](prompts.md) still hasn't been run.**

They are still useful as an independent re-check of round 1, and they were read against what
milestone 1 has since built ([findings](../findings/2026-10-04-milestone-1.md)).

## What's confirmed (now from three or more independent passes)

- **No esbuild equivalent exists**, and pex is the closest tool; shiv is in maintenance mode;
  stickytape, pinliner and tinyBundle are dead.
- **`uv run` + PEP 723 covers most of tsx**; the remaining gaps (watch mode, files inside
  packages, signal handling) are uv-shaped and out of our scope.
- **Native code must be extracted to disk**; in-memory loading is a dead end (PyOxidizer).
- **Function-level tree-shaking is unsound**; module/distribution-level pruning is feasible with
  tracing and allowlists.
- **Contents must come from the requirements/lockfile, with import-following only as an
  optimization on top** (Compass: "follow imports must stay an optimization layered on a correct
  requirement-based bundle"). Matches [ADR-0004](../adr/0004-lockfile-decides-contents.md).
- **Downleveling isn't worth building; a target-version *check* is.** (Gemini disagrees again;
  see below.) Matches the roadmap.
- Both reports independently rank **the bundler we're building as the top opportunity**, with
  "pex's correctness, esbuild's ergonomics and diagnostics" as the differentiator (Compass's
  words). Milestone 1 already measures ahead of pex and shiv on correctness and speed.

## What's new

| Finding | Source | Verified? | What it means for us |
|---|---|---|---|
| Astral (Zanie Blue, 2024-10-08) on uv#7419: bundling is "definitely something we're interested in doing someday. I'm not sure zipapp is the ideal format for us" | Compass | ✅ by hand | The risk that uv ships bundling is real but undated, and uv may not pick `.pyz`. Unchanged strategy: be the engine, stay compatible |
| AWS Lambda's 250 MB unzipped limit (including layers) makes artifact **size** a hard constraint, and no tool shows what's heavy or prunes safely | Both | Widely documented, not re-checked | Raises the value of the **size and contents report** and **opt-in pruning** (roadmap Near). Compass flags demand evidence as thin: validate with users first |
| `zipimport` never writes bytecode caches, so code served from a zip recompiles on every cold start; precompile for the target | Compass | Matches CPython docs | Check that the loader serves cached bytecode (milestone 1 extracts to a cache, so likely fine; confirm) |
| For **end users**, "whatever `python3` exists" is a weak assumption: macOS's `/usr/bin/python3` is only a stub until the Xcode Command Line Tools are installed; Windows has the Store stub | Both | ✅ known behaviour | Our "needs only Python" bet is strongest for developers, servers, CI, Lambda and agents, weakest for non-technical end users. The roadmap's "No Python installed" launcher covers that gap later |
| **modulegraph2** (maintained, Nov 2025) and **vermin** 1.8.0 (Nov 2025) are reusable building blocks for import graphs and minimum-version checks | Compass | Not re-checked | Candidates for `bundleup check` instead of writing our own |
| Hedge against uv's roadmap by also consuming `pylock.toml` / wheels directly | Compass | – | Already in [ADR-0006](../adr/0006-delegate-to-uv-and-existing-files.md) |
| Gemini's design idea: serve pure Python from the zip and extract **only** native extensions, lazily, when imported | Gemini | – | Rejected as a default: the baseline showed run-from-zip breaks `__file__` and frameworks ([ADR-0005](../adr/0005-extract-to-cache-by-default.md)). At most a per-package optimization `check` can prove safe |

## Where the reports disagree with us

- **Gemini ranks a syntax downleveler #2 again** (16/20, "an audience of ~2 million"). Compass
  explains why demand is low: Python deployments choose their interpreter, and downleveling can't
  fix stdlib differences. We keep "check, don't transpile".
- **Gemini recommends Rust** for the bundler. Compass says Python is fine because downloads
  dominate. Milestone 1's measurements agree with Compass; [ADR-0008](../adr/0008-prototype-in-python.md) stands.
- **Both still frame a tsx-style runner as an opportunity.** Out of scope: uv's lane.

## Errors in these reports

See [verification-notes.md](verification-notes.md), "Round 1b".

## Actions

- Run the actual round 3 (agents) brief.
- Roadmap: size report and pruning gain supporting evidence (Lambda); keep them Near.
- Learnings updated (Astral quote verified; the macOS `python3` stub nuance).
