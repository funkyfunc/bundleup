# Recipes

How to build for a destination with ordinary flags. bundleup has no named targets
([ADR-0039](adr/0039-recipes-instead-of-target-presets.md)): each recipe says which Python,
platform, format and size limit the destination needs, so you can see and change every choice.
CI builds gauntlet 14 (python-pptx, lxml, Pillow) with each recipe marked *CI*, from a Mac and
from Linux.

## A Claude API Skill or code execution script *(CI)*

Claude API Skills and code execution run in a sandbox with Python 3.11 on Linux x86_64, **no
network and no package installs** (Anthropic's code execution docs). A skill script that imports
anything outside the standard library and the preinstalled libraries can't run there, and the
`uv run` the Agent Skills guide recommends needs the network. A bundle carries its dependencies:

```bash
bundleup build tool.py --python 3.11 --python-platform x86_64-manylinux_2_28 --max-size 30MB \
  -o my-skill/scripts/tool.pyz
```

- `--python 3.11 --python-platform x86_64-manylinux_2_28`: the sandbox's Python and platform.
  Its exact glibc isn't documented; 2.28 (2018) is the oldest level that many packages, Pillow 12
  among them, still publish wheels for.
- `--max-size 30MB`: a Skill must stay under 30 MB uncompressed; over it, nothing is written.

Then in `my-skill/SKILL.md` ([format](https://agentskills.io/specification)):

```markdown
---
name: my-skill
description: What the skill does and when to use it.
compatibility: Runs scripts/tool.pyz with Python 3.11 on Linux x86_64; needs no network.
---

Run `python scripts/tool.pyz --help` to see the options, then ...
```

The sandbox already has many libraries installed (pandas, numpy, pillow, python-pptx and more,
per Anthropic's docs). If your script only needs those, you don't need bundleup there; a bundle
always carries its own locked versions, which costs space.

Check it before shipping: `bundleup check tool.py --python 3.11 --python-platform
x86_64-manylinux_2_28 --strict`. If a package has no wheel for the sandbox, the error names the
platforms it does have wheels for. Not yet tested in the real sandbox (it needs an API account).

## An AWS Lambda function *(CI)*

```bash
bundleup build --format lambda --python 3.13 --python-platform x86_64-manylinux_2_34 --entry app:handler
bundleup build --format lambda --python 3.13 --python-platform aarch64-manylinux_2_34  # Graviton
bundleup build handler.py --format lambda --python 3.13 --python-platform x86_64-manylinux_2_34
```

Pick the platform from the function's runtime
([AWS's table](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html), checked
2026-10-06):

| Runtime | OS | `--python-platform` |
|---|---|---|
| `python3.12` and newer | Amazon Linux 2023 (glibc 2.34) | `x86_64-manylinux_2_34` or `aarch64-manylinux_2_34` |
| `python3.10`, `python3.11` | Amazon Linux 2 (glibc 2.26) | `x86_64-manylinux_2_17` or `aarch64-manylinux_2_17` |

uv has no `manylinux_2_26`, so the older runtimes use 2_17, and packages that stopped publishing
2_17 wheels (Pillow 12) can't be built for them; `bundleup check` says so. A `--format lambda`
build of compiled packages for macOS or Windows is an error (`lambda-not-linux`).

The zip has your code and its dependencies at the top, as Lambda expects, with bytecode
precompiled for the runtime (Lambda's `/var/task` is read-only). Set the function's runtime to
the Python you built for and its handler to `module.function`: bundleup prints it when you pass
`--entry app:handler` (`handler app.handler`); for a script `handler.py`, it's
`handler.<function>`. Bytecode is hash-checked, so edits made in Lambda's console editor apply.
bundleup refuses a function over Lambda's 250 MB unzipped limit and warns over the 50 MB
direct-upload limit. Tested in CI: every gauntlet project except the `.pth` one (below) runs
inside AWS's own Lambda image on x86_64 and arm64.

Known limits: Lambda doesn't run `.pth` files from `/var/task` (bundleup warns,
`pth-not-run`), and has no `/dev/shm`, so `multiprocessing.Pool` and `Queue` don't work there
(an AWS limitation; the emulator CI uses has it, so this isn't tested).

## Will it build for other platforms?

`bundleup check --also-platform windows --also-platform linux --also-platform macos` reads the
lock and lists every package without a wheel for each platform, in milliseconds, without building
anything. On Linux it also says which manylinux level would work.

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
