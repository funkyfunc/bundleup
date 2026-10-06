# Command-line reference

Generated from the parser by `tests/test_cli.py` (rule 34 of the [CLI style guide](cli-style-guide.md)); don't edit by hand. Regenerate with
`UPDATE_SNAPSHOTS=1 uv run pytest -q tests/test_cli.py`.

## `bundleup`

```
usage: bundleup [-h] [-V] <command> ...

Make self-contained Python files: your code and its dependencies in one .pyz that runs with plain `python`.

positional arguments:
  <command>
    build        bundle a project or script into one .pyz

options:
  -h, --help     show this help message and exit
  -V, --version  show program's version number and exit

examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build path/to/script.py  bundle a PEP 723 script and its dependencies
  bundleup build --python 3.9       build for Python 3.9 (a bundle runs on one version)
  bundleup build --json             print the result as JSON on stdout

docs: https://github.com/funkyfunc/bundleup
bugs: https://github.com/funkyfunc/bundleup/issues
```

## `bundleup build`

```
usage: bundleup build [-h] [-o FILE] [--python VERSION] [--entry NAME] [--locked | --frozen]
                      [--json] [-q] [-v] [--color WHEN]
                      [path]

Bundle a project (pyproject.toml + uv.lock) or a PEP 723 script.

positional arguments:
  path                  project directory or .py script (default: .)

options:
  -h, --help            show this help message and exit
  -o FILE, --output FILE
                        output file (default: dist/<name>.pyz) [env: BUNDLEUP_OUTPUT]
  --python VERSION      a version like 3.12, or a path (default: what uv picks for the project)
                        [env: BUNDLEUP_PYTHON]
  --entry NAME          a [project.scripts] name, module:function or module (default: the only
                        script) [env: BUNDLEUP_ENTRY]
  --locked              fail if uv.lock is out of date (as in uv; the default when CI is set)
  --frozen              use uv.lock as is, without checking it (as in uv)
  --json                print one JSON document on stdout
  -q, --quiet           -q: warnings and errors only; -qq: errors
  -v, --verbose         -v: step timings; -vv: commands run
  --color WHEN          auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)

examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build path/to/script.py  bundle a PEP 723 script and its dependencies
  bundleup build --python 3.9       build for Python 3.9 (a bundle runs on one version)
  bundleup build --json             print the result as JSON on stdout

docs: https://github.com/funkyfunc/bundleup
bugs: https://github.com/funkyfunc/bundleup/issues
```
