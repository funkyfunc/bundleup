# Rounds 6 and 7: what they mean for bundleup (2026-10-09)

Four Compass reports, two runs of each brief, written without any bundleup documents attached:
[round 6](round-6-next-tool-compass.md) and [6b](round-6b-next-tool-compass.md) (the next tool
for shipping Python, through the JavaScript ecosystem's history), [round 7](round-7-agents-compass.md)
and [7b](round-7b-agents-compass.md) (what changes when agents write and run the code). The two
runs of each brief reached the same conclusions independently, which raises confidence, though
both runs used the same tool.

**Reliability.** High on structure and on primary sources the reports quote (issue trackers,
vendor docs, release notes). Weaker on: GitHub reaction counts (both round 6 runs couldn't
retrieve them, so their ranking of complaints is qualitative); Reddit and X (not searched in any
run); and the many 2026 arXiv preprints round 7 cites, which aren't peer-reviewed and which we
haven't checked.

## The short version

1. **The empty seat in Python is "project → artifact that runs elsewhere".** uv is Python's
   esbuild plus Vite for installing and environments; nothing plays that role for the last mile.
   The best-evidenced unmet needs are a self-contained executable (uv #5802, open since August
   2024, labelled "Not on the immediate roadmap") and **offline, portable environments** (uv
   #11746 "`uv layout`", #13587, #15519, #16519; Poetry #2184). bundleup sits in exactly this
   seat.
2. **The biggest risk is uv (now part of OpenAI) shipping it.** Both round 6 runs: high
   confidence the job gets done in the next two years, low confidence an independent tool wins
   the *executable* version. The lesson from JavaScript (npm absorbed Yarn's lockfile) is that a
   challenger survives only with a structural advantage, or by owning a job the incumbent won't.
3. **What an independent tool can own:** the portable, offline environment artifact (medium
   chance a non-incumbent wins), and **verification**: "will this run *there*?" (round 7 runs
   rank it the biggest gap, and nobody provides it).
4. **Agents make the problem bigger, not different.** Agent code mostly works where it was
   written; what breaks elsewhere is the environment. One study: only 68.3% of agent-built
   projects ran from a clean environment, and the packages needed at run time were 13.5× those
   declared (arXiv 2512.22387). Model-written code still names packages that don't exist about 5%
   of the time (arXiv 2605.17062).
5. **The sceptical report lists what uv, Docker and sandboxes don't cover:** no-network targets,
   recipients without uv, checking against a target before it fails, and cross-platform compiled
   wheels. Those four are bundleup's capabilities today.

## What it confirms we already do

| The reports call for | bundleup today |
|---|---|
| Build on uv and python-build-standalone; don't compete with them (round 6, rule "win by being embedded or building on the engine") | Built on uv from the start (ADR-0006, ADR-0011) |
| Use the standard formats; never invent a lock format | Reads `uv.lock`, `pylock.toml`, PEP 723 (ADR-0026, ADR-0041) |
| Offline, portable environment artifact | The `.pyz`, multi-platform layers (ADR-0038), `--entry python` as one environment for a folder of scripts (ADR-0040) |
| Clean-room verification, "rank 1" capability in round 7b | `--smoke` (ADR-0042), the gauntlet's hostile conditions |
| Catch undeclared dependencies (the 13.5× gap) | `undeclared-import` on every build |
| Agent-operable CLI: no prompts, JSON, exit codes | Already the CLI style guide; "hygiene, not a moat" per both round 7 runs |
| Zero configuration for one job (tsup's lesson) | One command, `[tool.bundleup]` when needed |

## What it argues against

- **A single `.py` file that inlines dependencies** ("tree-shaking"): both round 6 runs, citing
  uv #12035 (closed: dynamic imports defeat it). Roadmap item 24 isn't inlining (it embeds the
  bundle as data), and the reports neither support nor argue against that; the owner wants to
  keep it (2026-10-09).
- **Another installer, resolver or lockfile format**: uv has won that (round 6, both runs).
- **Cross-compiled native executables** and Cosmopolitan builds: requests closed for years in
  PyInstaller and Nuitka; no C extensions in Cosmopolitan.
- **llms.txt and AGENTS.md as differentiators**: no measured benefit (round 7, both runs).
- **"Sandboxes make packaging irrelevant"**: both round 7 runs disbelieve it; sandboxes split
  into "nothing installable" (Claude API, Gemini) and "bring an image" (E2B, Modal), with no
  common input format.

## New ideas worth considering (none started; the owner decides)

1. **Check against a described target environment** (round 7: "target profiles", ranked the
   largest gap by 7 and third by 7b). Not presets that set build flags, which ADR-0039 removed,
   but data describing a destination: its Python, platform, network, and the packages it already
   has (the Claude API sandbox's fixed list, Gemini's, Lambda's), so `check` can say "this needs
   X, which that sandbox lacks and can't install". It fits "capabilities over named targets" if
   profiles are data files anyone can write, with a few published as recipes. Would need an ADR.
2. **Supply-chain checks on dependencies** (round 7, both runs; medium): flag a dependency that
   is very new, rarely downloaded, or a known hallucinated name, before it's bundled. Agents pick
   dependencies; a bundler that ships them to other machines is a natural place to check.
3. **Hardened environments**: pex scies fail where `/tmp` is mounted noexec (ComfyUI-Docker #170,
   Oct 2026). bundleup unpacks into the user's cache, with a temporary folder as the fallback;
   worth a gauntlet condition for a noexec cache.
4. **MCP bundles**: MCPB added a `uv` server type because vendored Python bundles broke on
   pydantic's exact-version compiled core (MCPB PR #158). A multi-version `.pyz` solves that case
   offline; the roadmap's deferred "MCP servers" row deserves another look after the skill pilot.
5. **Translate one environment into each platform's format** (Modal image, E2B template, Codex
   setup script, Dockerfile) (round 7b, medium gap): a possible future output, not now.

## What it changes in the plan

Nothing in the order. It strengthens it: under 100 MB per file (roadmap 22), Windows without
Python (23), and the pilot (25) are the wedge round 6 describes; `--smoke` and `undeclared-import`
are the verification round 7 describes. The new ideas above go on the roadmap's "possible future
directions", not "Next up".
