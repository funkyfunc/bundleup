# Recipes

Short, tested-where-noted ways to use bundleup for a destination. Each uses only ordinary
commands; `bundleup targets` shows what a preset stands for.

## A Claude Skill script with dependencies

Claude API Skills and code execution run in a sandbox with Python 3.11 on Linux x86_64, **no
network and no package installs** (Anthropic's code execution docs). A skill script that imports
anything outside the standard library and the preinstalled libraries can't run there, and the
`uv run` the Agent Skills guide recommends needs the network. A bundle carries its dependencies:

```bash
bundleup build tool.py --target claude-api -o my-skill/scripts/tool.pyz
```

`--target claude-api` builds for CPython 3.11 on `x86_64-manylinux_2_17` (the most compatible
Linux level; the sandbox's exact glibc isn't documented), so compiled packages such as pydantic
or numpy get Linux wheels even when you build on a Mac. Then in `my-skill/SKILL.md`
([format](https://agentskills.io/specification)):

```markdown
---
name: my-skill
description: What the skill does and when to use it.
compatibility: Runs scripts/tool.pyz with Python 3.11 on Linux x86_64; needs no network.
---

Run `python scripts/tool.pyz --help` to see the options, then ...
```

Check it before shipping: `bundleup check tool.py --target claude-api --strict`. Not yet tested in
the real sandbox (it needs an API account); the target's Python and platform are the documented
ones, and CI runs the same kind of cross build (macOS → Linux) on every push.

## An AWS Lambda function

```bash
bundleup build --target lambda --entry app:handler       # dist/<name>-lambda.zip, x86_64
bundleup build --target lambda-arm64 --python 3.12         # Graviton, Python 3.12
bundleup build handler.py --target lambda                  # a single PEP 723 script
```

The zip has your code and its dependencies at the top, as Lambda expects, with bytecode
precompiled for the runtime (Lambda's `/var/task` is read-only). Set the function's runtime to
the Python shown (`python3.13` by default) and its handler to the one printed
(`handler app.handler`; for a script `handler.py`, `handler.<function>`). bundleup refuses a
function over Lambda's 250 MB unzipped limit and warns over the 50 MB direct-upload limit.
Tested in CI: every gauntlet project except the `.pth` one (below) runs inside AWS's own Lambda
image on x86_64 and arm64.

Known limits: Lambda doesn't run `.pth` files from `/var/task` (bundleup warns,
`pth-not-run`), and has no `/dev/shm`, so `multiprocessing.Pool` and `Queue` don't work there
(an AWS limitation; the emulator CI uses has it, so this isn't tested).

## A host application that loads packages from a directory

Splunk apps (`bin/lib`), QGIS and Maya plugins, Azure Functions' `.python_packages`: build a
plain directory for the host's Python and platform.

```bash
bundleup build --format dir --python 3.9 --python-platform x86_64-manylinux_2_17 -o my_app/bin/lib
```

Running `bundleup build` again replaces a directory it wrote before; it refuses to replace
anything else. Tested on every push: each gauntlet project runs with only that directory on
`PYTHONPATH`, on Linux, macOS and Windows.

## CI: fail on anything that won't survive bundling

```bash
bundleup check --strict --json > check.json   # exit 1 on any error or warning
bundleup build --locked                       # CI implies --locked when there's a lockfile
bundleup verify dist/app.pyz                  # the bundle matches its manifest
```

Diagnostics have stable codes (`syntax-error`, `data-files`, `pth-not-run`, `lambda-too-big`,
...); branch on `code`, not on the message. Schemas: [docs/schema/](schema/).

## Many machines starting the same bundle (HPC, shared filesystems)

A bundle unpacks once per machine into a cache. Point the cache at fast local storage, and clean
it up later:

```bash
BUNDLEUP_CACHE=/local/scratch/$USER python app.pyz
bundleup cache clean --older-than 7
```

Simultaneous first runs on one machine unpack once (16 at once: 0.55 s instead of 3.2 s).
