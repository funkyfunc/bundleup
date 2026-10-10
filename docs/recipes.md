# Recipes

How to build for a destination with ordinary flags. bundleup has no named targets
([ADR-0039](adr/0039-recipes-instead-of-target-presets.md)): each recipe says which Python,
platform, format and size limit the destination needs, so you can see and change every choice.
CI builds gauntlet 14 (python-pptx, lxml, Pillow) with each recipe marked *CI*, from a Mac and
from Linux.

## A skill installed on people's machines (Claude Code, agent package managers) *(CI)*

A skill's scripts fail with `ModuleNotFoundError` on a machine that doesn't have their packages,
and installing them on first use needs pip, a package index and the network. Instead, ship the
packages in one file next to the scripts and run every script through it
([ADR-0040](adr/0040-entry-python-runs-any-script.md)):

```
my-skill/
  SKILL.md
  pyproject.toml        # [project] dependencies = ["python-pptx", "pymupdf", ...], then `uv lock`
  uv.lock
  scripts/
    deck_edit.py        # plain scripts the agent can read
    check_setup.py
    deps.pyz            # built below
```

```bash
bundleup build my-skill --entry python -o my-skill/scripts/deps.pyz \
  --python 3.12 \
  --python-platform aarch64-apple-darwin --python-platform x86_64-apple-darwin \
  --python-platform x86_64-pc-windows-msvc --python-platform x86_64-manylinux_2_28
```

(or keep the settings in the project, so `bundleup build my-skill -o my-skill/scripts/deps.pyz` is
enough:

```toml
[tool.bundleup]
entry = "python"
python = "3.12"
python-platform = ["aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-pc-windows-msvc",
                   "x86_64-manylinux_2_28"]
```

) and in SKILL.md: `python3 scripts/deps.pyz scripts/deck_edit.py ...` (`python` on Windows). The
scripts' own helper modules import as usual (the script's folder comes first on `sys.path`), and
a script that starts another one from that folder with `sys.executable` shares the bundle. Every
build reads the scripts' imports and warns (`undeclared-import`) about any the bundle doesn't
provide, so a missing dependency shows up before your users find it.

- **Which Pythons:** packages with compiled code (lxml, Pillow) have a build per Python version,
  so list the versions your users have. A bundle started with another version re-runs itself
  with a matching Python if one is installed (`python3.X`, or a plain `python3`/`python` of the
  right version, such as Apple's `/usr/bin/python3`; ADR-0036); otherwise it names the versions
  it needs.
  `bundleup check --matrix` shows which platforms and versions the lock's wheels cover.
- **Size:** each file is stored once across platforms and versions, but compiled packages differ
  per platform. Measured 2026-10-07 for python-pptx, lxml, Pillow, PyMuPDF, xlsxwriter and
  pywin32 on the four platforms above: 144 MiB for one Python, 230 MiB for three, 314 MiB for
  five; PyMuPDF is about half (without it, python-pptx and pywin32 for the same four platforms
  make 55 MiB: the `skill` CI job builds that, then runs the scripts on Linux, Windows and macOS).
  Over 100 MB, bundleup warns (`large-bundle`): GitHub refuses such files. **Add `--split 100MB`**
  (or `split = "100MB"` under `[tool.bundleup]`): a bundle that doesn't fit becomes a small
  `deps.pyz` and a `deps.pyz.parts/` folder beside it, no file over 100 MB, so no Git LFS
  ([ADR-0045](adr/0045-split-a-bundle-into-parts.md)). Commit both; SKILL.md's command doesn't
  change. A missing or mismatched part is refused by name. CI builds the skill with `--split 20MB`
  and runs it on all three OSes.
- **Python must be installed** for a `.pyz`. macOS has one (Apple's 3.9, if the developer tools
  are installed); many Windows machines don't, and `python` there may be the Microsoft Store
  placeholder, which isn't Python. For those, ship executables that bring their own Python
  (below, "A machine without Python"): one per platform, and SKILL.md names the one to run.
- **No network, no index, no install step** on the user's machine; the first run unpacks into a
  cache (a second or two for this size), later runs start like an installed venv. When a new
  version of the skill unpacks, copies of older versions unused for 30 days are removed
  (macOS and Linux), so updates don't pile up.

## A Claude API Skill or code execution script *(CI)*

Claude API Skills and code execution run in a sandbox with Python 3.11 on Linux x86_64, **no
network and no package installs** (Anthropic's code execution docs). A skill script that imports
anything outside the standard library and the preinstalled libraries can't run there, and the
`uv run` the Agent Skills guide recommends needs the network. A bundle carries its dependencies:

```bash
bundleup build tool.py --against docs/targets/claude-api.toml -o my-skill/scripts/tool.pyz
```

[`docs/targets/claude-api.toml`](targets/claude-api.toml) describes the sandbox, with its source
and the date it was checked ([ADR-0044](adr/0044-destinations-as-data-files.md)); it stands for:

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
bundleup build --against docs/targets/aws-lambda-python3.13-x86_64.toml --entry app:handler
bundleup build --against docs/targets/aws-lambda-python3.13-arm64.toml   # Graviton
bundleup build handler.py --format lambda --python 3.12 --python-platform x86_64-manylinux_2_34
```

The [target files](targets/) stand for `--format lambda --python 3.13 --python-platform
x86_64-manylinux_2_34` (or `aarch64-…`); for another runtime, copy one or pass the flags.

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

## A container, or a sandbox built from an image *(Docker: CI)*

A `.pyz` is one file, so an image only needs a Python of the version it was built for:

```dockerfile
FROM python:3.12-slim
COPY dist/app.pyz /app/app.pyz
ENTRYPOINT ["python", "/app/app.pyz"]
```

Build the bundle for the image's platform (`--python 3.12 --python-platform
x86_64-manylinux_2_28`, or `aarch64-…`). On first start it unpacks into the user's cache; in a
read-only container give it a writable place, and if the bundle has compiled code, one where
code can run: `docker run --read-only --tmpfs /tmp:exec …`. Docker's plain `--tmpfs` is mounted
noexec, and a bundle with compiled code refuses it with that reason rather than failing on import.
Tested in CI: a bundle with a compiled extension runs in `python:3.12-slim` as is, read-only
with `/tmp:exec`, and refuses clearly with a noexec `/tmp` (job `docker`).

The same file goes into sandboxes built from images (not yet tested there):

- **E2B:** use the Dockerfile above as the template's `e2b.Dockerfile`, then run
  `python /app/app.pyz` in the sandbox.
- **Modal:** `modal.Image.debian_slim(python_version="3.12").add_local_file("dist/app.pyz",
  "/app/app.pyz")`, then run `python /app/app.pyz` in a Sandbox or Function.
- **A setup script** (Codex cloud and the like): copy the `.pyz` into the repository; nothing to
  install, so it also works in the phase without network.

## Coming from pip, requirements.txt or setup.py

bundleup takes Python projects as they are ([ADR-0041](adr/0041-input-without-a-lock.md)); you
don't need uv to use it (installing bundleup installs its own).

| You have | Run | What happens |
|---|---|---|
| A `pyproject.toml` you install with `pip install .` | `bundleup build` | Builds; warns `unlocked` |
| A legacy `setup.py` / `setup.cfg` project | `bundleup build` | Builds; warns `unlocked` |
| A folder with `main.py`, other modules and a `requirements.txt` | `bundleup build myapp/` | The folder's files go in as they are (not `.venv`, caches or `build/`); runs `__main__.py`, `main.py` or `app.py`, or `--entry server.py` |
| A script with a `requirements.txt` beside it | `bundleup build tool.py` | Builds; warns `unlocked` unless every version is pinned |
| A script that needs only the standard library | `bundleup build tool.py` | Builds; a script importing an undeclared package is refused, naming it |
| A `pylock.toml` from `pip lock .` (pip 25.1+) | `bundleup build` | Builds from the lock |

Without a lock, the versions are resolved when you build (for every platform at once, in a
temporary folder: nothing is written into your project), and the bundle's manifest records exactly
what went in. Two builds a week apart can still differ, which is what the `unlocked` warning
says. To make builds repeatable, lock once:

- `uv lock` (or `pip lock .`) in a project;
- a `requirements.txt` that pins every package it needs (`uv pip compile requirements.in -o
  requirements.txt --generate-hashes`, or `pip freeze > requirements.txt`) counts as a lock; with
  `--hash` on every line, uv also checks the hashes;
- `uv add --script tool.py <packages>` and `uv lock --script tool.py` for a single script.

`--strict` fails on the warning; `--locked` refuses anything that isn't locked.
`poetry.lock` and `Pipfile.lock` aren't read: export them (`poetry export --with-hashes -o
requirements.txt`, `pipenv requirements --hash > requirements.txt`) or build from
`pyproject.toml`.

## Behind a company index or proxy

bundleup installs exactly the files the lock names, from the index they were locked from, and
checks their hashes; a same-named package on PyPI is never used. So the index matters when you
lock (`uv lock`, your command), not when you build. The bundle itself never uses the network.

uv reads **uv's configuration, not pip's**: a `pip.conf` that points pip at an Artifactory is
ignored. Set the same URL once for uv, in `~/.config/uv/uv.toml` (Windows:
`%APPDATA%\uv\uv.toml`) or a project's `pyproject.toml` as `[[tool.uv.index]]`:

```toml
[[index]]
url = "https://artifactory.example.com/api/pypi/pypi/simple"  # pip.conf's index-url
default = true
```

or `UV_DEFAULT_INDEX=<url>` in the environment. bundleup passes its environment to uv, so these
work too:

- **Proxy:** `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY`.
- **A proxy that inspects TLS** (a company certificate): `UV_NATIVE_TLS=1` uses the system's
  certificate store, or `SSL_CERT_FILE=<bundle.pem>`.
- **Credentials:** `~/.netrc`, keyring, or `UV_INDEX_<NAME>_USERNAME` / `_PASSWORD` for a named
  index. A lock never stores them. (Not yet tested against an index that needs a login.)
- **Python downloads:** to check the oldest Python a pure-Python bundle supports, bundleup may
  download that Python (into its own cache, from GitHub); `UV_PYTHON_INSTALL_MIRROR` points it
  at a mirror. If the download fails, the build still works and says the range is approximate.

Tested: a script locked against a private index (a flat folder) builds and runs from it
(`tests/test_index.py`).

## A machine without Python *(CI)*

Build an executable that carries its own interpreter, one per OS and CPU, from any machine
([ADR-0047](adr/0047-standalone-executables.md)):

```bash
bundleup build --format exe --python 3.12 --python-platform x86_64-pc-windows-msvc -o dist/tool.exe
bundleup build --format exe --python 3.12 --python-platform aarch64-apple-darwin -o dist/tool-macos
bundleup build --format exe --python 3.12 --python-platform x86_64-manylinux_2_28 -o dist/tool-linux
```

The first build downloads a small launcher (scie-jump, checked against a pinned hash) and the
interpreter for that platform (through uv), once each. Run it as `dist/tool.exe ARGS`; with
`--entry python` it runs scripts as `python` would (`dist/tool.exe scripts/deck_edit.py`).

- **Size:** the interpreter adds 22-35 MB (the skill fixture: 49 MB for macOS, 50 for Windows,
  57 for Linux, against 16 MB as a `.pyz`). Warm starts equal the `.pyz`'s; the first run unpacks
  the interpreter too (4.5 s for the fixture on a Mac).
- **Unsigned.** Files delivered by git or a package manager run as they are. On macOS a file
  downloaded in a browser is quarantined, and Gatekeeper warns about an unsigned executable;
  these can't be signed (data appended to a Mach-O isn't covered by a signature). Windows
  antivirus may look twice at an unknown `.exe`. Where Python exists, a `.pyz` avoids all this.
- CI builds the skill fixture as three executables on a Mac and runs each on Linux, Windows and
  macOS with no Python on `PATH`.

## One `.py` file: a gist, an upload, a chat *(gauntlet)*

Where only a `.py` (or only text) is accepted, write the bundle as one plain-text Python file
([ADR-0046](adr/0046-one-py-file-output.md)):

```bash
bundleup build tool.py --format py -o dist/tool.py
python3 dist/tool.py --help
```

The top of the file says what's inside (each package and version, where it runs) in a
`# /// bundleup` block, which nothing installs from; the loader follows, then the packages as
base64 comment lines. It runs like the `.pyz` (any flag that works for a `.pyz` works, apart from
`--split`), and `bundleup verify dist/tool.py` checks it. **Best for small tools:** it's a third
bigger than the `.pyz`, and Python reads the whole file on every start, about 2 ms per MB (a
small tool starts 3 ms slower than its `.pyz`; a 21 MB one 38 ms slower). Every gauntlet project
also runs as a `.py` (`--tool bundleup-py`).

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
bundleup check --audit --strict               # also fail on vulnerable or brand-new dependencies
bundleup build --smoke "--version"            # build, then run it once offline in a fresh home
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
