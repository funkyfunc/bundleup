# Python packaging, explained for JavaScript developers

A tour of how Python finds, installs and ships code, mapped to things a Node developer already
knows. Most of Python's packaging tools and complexity follow from one difference in how the two
languages find imported code, so we start there.

## 1. The root difference: where imports come from

**Node** resolves imports relative to the file. `require("lodash")` walks up from the current
file's folder looking for `node_modules/lodash`. Every project carries its own dependencies, and
two packages can even depend on different versions of the same library: npm nests them.

**Python** has one search list per interpreter, called `sys.path`. `import requests` checks a fixed
list of directories in order and takes the first match. There's no walking up from the file. For
third-party packages that list normally points to a single folder called **`site-packages`**,
which belongs to the Python installation:

```
Node:   ./node_modules → ../node_modules → ../../node_modules …   (per project)
Python: [script's folder, stdlib, …/python3.12/site-packages]     (per interpreter)
```

So `site-packages` is like a single global `node_modules` that every project using that Python
shares.

Three consequences:
- **Only one version of each package can be installed per interpreter.** If project A needs
  `requests` 2.28 and project B needs 2.32, they can't share the same `site-packages`.
- **Dependency resolution is harder than in npm.** npm can install two versions and nest them.
  Python's installer has to find *one* version of every package that satisfies everybody. When no
  such set exists, you get the famous "dependency hell".
- **Python needed a way to give each project its own `site-packages`.** That's what virtual
  environments are.

## 2. Virtual environments: a per-project `node_modules`

A virtual environment (venv) is just a folder, usually `.venv/`, containing:
- a `pyvenv.cfg` file pointing to a real Python installation;
- its **own** empty `site-packages`;
- a `bin/python` launcher that, when started, uses that private `site-packages` instead of the
  global one;
- `bin/` entries for any command-line tools your dependencies install.

"Activating" a venv (`source .venv/bin/activate`) only puts `.venv/bin` first on your `PATH`, so
typing `python` picks the venv's Python. Nothing magical happens.

The purpose is to recreate what Node gives you for free: dependencies isolated per project. With
modern tools you rarely activate anything. `uv run app.py` finds or creates the project's `.venv`
and runs inside it, much like `npm run` uses the local `node_modules/.bin`.

**Why you can't just `pip install` globally anymore:** installing into the system Python can break
OS tools that depend on it. Modern Linux distros and Homebrew Python mark themselves "externally
managed" (PEP 668), and `pip install` refuses with an error. That pushes everyone toward venvs.

## 3. There are many Pythons on one machine

Node users mostly have one Node, maybe switched with nvm. Python users often have several without
realising it. A typical Mac has:
- `/usr/bin/python3`: Apple's copy (3.9.6 with current Command Line Tools), installed with the Xcode Command Line
  Tools. Don't install things into it.
- Homebrew's Python, python.org installers, and/or Pythons downloaded by uv or pyenv.

The version matters more than in Node, because compiled packages are built for a specific Python
version (section 5). Tools that manage versions: **pyenv** (like nvm; compiles Python from source)
and **`uv python`** (downloads prebuilt Pythons from python-build-standalone, which is much
faster).

## 4. Packages: names and formats

**The name you install isn't always the name you import.** npm has nothing like this:

| Install with | Import as |
|---|---|
| `pip install Pillow` | `import PIL` |
| `pip install python-pptx` | `import pptx` |
| `pip install pyyaml` | `import yaml` |

The install name is the **distribution** (what's on PyPI, Python's npm registry). The import name
is the **package** inside it. One distribution can contain several import names, and several
distributions can share one (namespace packages).

**Two package formats:**
- **sdist** (source distribution): a tarball of source code. Installing it may mean *running a
  build*, including compiling C code, which needs a compiler on the user's machine. Old projects
  ran arbitrary code via `setup.py` here.
- **wheel** (`.whl`): a prebuilt zip that just gets unpacked into `site-packages`. Fast, and no
  code runs during install. Almost everything ships wheels now.

The wheel's filename tells you what it runs on:

```
numpy-2.1.0-cp312-cp312-macosx_14_0_arm64.whl
      │      │     │     └─ platform: macOS 14+, Apple Silicon
      │      │     └─ ABI: compiled against CPython 3.12
      │      └─ Python: CPython 3.12
      └─ version
requests-2.32.3-py3-none-any.whl     ← pure Python: any Python 3, any platform
```

A pure-Python wheel is like a normal npm package. A tagged wheel is like esbuild's
`@esbuild/darwin-arm64` platform packages, except the Python version is also part of the matrix.

## 5. Native code is everywhere, which is the big difference from npm

In npm, compiled addons are fairly rare. In Python they're **everywhere**, because Python is slow
and hands heavy work to C, C++ or Rust: NumPy, pandas, pydantic, cryptography, lxml, Pillow,
PyTorch. This is why:
- popular packages publish **dozens of wheels per release**: macOS/Linux/Windows × Intel/ARM ×
  each Python version;
- Linux has the **manylinux** standard so one wheel works across distros (it targets an old enough
  glibc), and **musllinux** for Alpine;
- **abi3** (the "stable ABI") lets a package publish one wheel per platform that works on all
  Python versions. It's roughly Python's version of Node-API, but only some packages use it;
- compiled code can't be loaded from inside a zip file, which is the core problem for any bundler.

## 6. Project files: `pyproject.toml` ≈ `package.json`

```toml
[project]
name = "my-app"
version = "0.1.0"
requires-python = ">=3.10"          # like "engines"
dependencies = ["requests>=2.31"]   # like "dependencies"

[project.scripts]
my-app = "my_app.cli:main"          # like "bin"

[build-system]                      # no npm equivalent (see below)
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Differences from npm:
- **There's a build step to publish.** npm publishes your folder. Python packages are *built* into
  a wheel by a **build backend** (hatchling, setuptools, flit, maturin for Rust…), chosen in
  `[build-system]`.
- **No `"scripts"` task runner.** Running `npm run test` style tasks has no standard equivalent.
  People use Makefiles, `just`, or add-on tools.
- **`requirements.txt`** is the older, simpler format: a plain list of packages, often with exact
  versions. You'll still see it everywhere.
- **Lockfiles came late.** For years the closest thing was `pip freeze > requirements.txt`. Today
  there's `uv.lock`, `poetry.lock`, and a new official standard, `pylock.toml` (PEP 751, 2025).
  All of them play the role of `package-lock.json`.

## 7. The tools, mapped to JS

| JS | Python | Notes |
|---|---|---|
| npm install | **pip** | Only installs. Doesn't manage venvs or lockfiles |
| *(automatic)* | **venv** / virtualenv | Creates the per-project environment |
| npm / yarn (whole workflow) | **Poetry**, **PDM**, **Hatch** | All-in-one project managers from the 2018–2023 era |
| `npm i -g`, `npx` | **pipx** | Installs or runs CLI tools, each in its own isolated venv |
| nvm | **pyenv** | Manages Python versions |
| **Bun** (does everything, fast) | **uv** | Written in Rust. Replaces pip, venv, pip-tools, pipx and pyenv. `uvx` ≈ `npx`. `uv run` runs things inside the project's venv |
| Prettier + ESLint | **Ruff** | Same company as uv (Astral) |
| tsc | **mypy**, **pyright**, **ty** | Type checkers. Python type hints are built into the language and ignored at runtime |
| — | **conda** / **pixi** | A separate world, popular in data science, that also packages non-Python things (CUDA, C libraries, even R) |

The history in short: pip got installs right, then a decade of tools tried to fix the surrounding
workflow. uv (2024) unified it and became the default very quickly.

## 8. Running code

- `python app.py` runs a file. Its own folder goes first on `sys.path`.
- `python -m my_app.cli` runs a module **by import name**, from the current folder.

The two behave differently. Running a file that sits inside a package with
`python path/to/file.py` breaks its relative imports ("attempted relative import with no known
parent package"); `-m` doesn't. There's no Node equivalent. JS developers trip on this constantly.

- **Console scripts:** `[project.scripts]` entries become small executables in `.venv/bin/` at
  install time, like npm `bin` links.
- **PEP 723 scripts:** a comment block at the top of a single file declaring its dependencies.
  `uv run script.py` sets up a cached environment and runs it. This is the closest thing to "just
  run a file with dependencies".

## 9. Shipping Python to someone else

- **Libraries:** publish wheels to PyPI. This works well.
- **Servers:** usually a **Docker container**. The Python environment (right interpreter, compiled
  wheels, system C libraries, right glibc) is fragile enough that people ship the whole operating
  system with it. A Node server often ships a bundle or `node_modules` instead.
- **CLI tools for developers:** `pipx install` / `uv tool install`, which assumes the user has
  those tools.
- **Desktop apps or non-developers:** freezers such as PyInstaller and Nuitka produce an executable
  that includes Python. That brings platform builds, code signing and antivirus issues.
- **"One file, needs only Python":** zipapp, shiv and pex. That's the tier with no good default,
  the way esbuild became the default for Node. See [MISSION.md](../MISSION.md).

The rest of the ecosystem's quirks explain why that last tier is hard: one `site-packages` per
interpreter, native code everywhere, wheels tagged per platform and Python version, packages that
read files via `__file__`, and users with an unpredictable Python. Each project in the
[gauntlet](../gauntlet/README.md) tests one of those.
