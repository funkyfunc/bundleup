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
    check        report what won't survive bundling, without writing a bundle
    verify       check a bundle against its manifest
    cache        list or clean up unpacked bundles

options:
  -h, --help     show this help message and exit
  -V, --version  show program's version number and exit

examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build path/to/script.py  bundle a PEP 723 script and its dependencies
  bundleup build --python 3.9       build with Python 3.9 (pure Python runs on 3.9 and newer)
  bundleup check                    report what won't survive bundling, and package sizes
  bundleup verify dist/app.pyz      check a bundle (and its unpacked copy) against its manifest

docs: https://github.com/funkyfunc/bundleup
bugs: https://github.com/funkyfunc/bundleup/issues
```

## `bundleup build`

```
usage: bundleup build [options] [path]

Bundle a project, a folder of modules or a script; locked or not.

positional arguments:
  path                  project directory or .py script (default: .)

options:
  -h, --help            show this help message and exit
  -o FILE, --output FILE
                        output file (default: dist/<name>.pyz) [env: BUNDLEUP_OUTPUT]
  --format FORMAT       pyz (default), py (one .py), exe (experimental), dir, lambda (Lambda .zip)
  --python VERSION      a version (3.12) or a path; repeatable; default: uv's [env: BUNDLEUP_PYTHON]
  --entry NAME          a script name, module:function, module or python [env: BUNDLEUP_ENTRY]
  --against FILE        a destination described in a TOML file (docs/targets/)
  --python-platform OS  an OS/CPU, uv's names (linux); repeatable [env: BUNDLEUP_PYTHON_PLATFORM]
  --locked              fail if the lock is out of date (as in uv; the default when there is one)
  --frozen              bundle the lock as it is, without checking it (as in uv)
  --strict              warnings fail too (errors always do)
  --max-size SIZE       fail if the output is bigger (30MB) [env: BUNDLEUP_MAX_SIZE]
  --split SIZE          no file bigger: a .pyz + parts folder (100MB) [env: BUNDLEUP_SPLIT]
  --smoke [ARGS]        run it once, fresh home, no network (default args: --help)
  --json                print one JSON document on stdout
  -q, --quiet           -q: warnings and errors only; -qq: errors
  -v, --verbose         -v: step timings; -vv: commands run
  --color WHEN          auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)

examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build --python-platform linux --python-platform windows   one .pyz for both
```

## `bundleup check`

```
usage: bundleup check [options] [path]

Install and compile like `build`, then report what won't work in a bundle and how big each package is. Every build runs the same checks.

positional arguments:
  path                  project directory or .py script (default: .)

options:
  -h, --help            show this help message and exit
  --format FORMAT       pyz (default), py (one .py), exe (experimental), dir, lambda (Lambda .zip)
  --python VERSION      a version (3.12) or a path; repeatable; default: uv's [env: BUNDLEUP_PYTHON]
  --entry NAME          a script name, module:function, module or python [env: BUNDLEUP_ENTRY]
  --against FILE        a destination described in a TOML file (docs/targets/)
  --python-platform OS  an OS/CPU, uv's names (linux); repeatable [env: BUNDLEUP_PYTHON_PLATFORM]
  --locked              fail if the lock is out of date (as in uv; the default when there is one)
  --frozen              bundle the lock as it is, without checking it (as in uv)
  --strict              warnings fail too (errors always do)
  --also-platform OS    also check, from the lock alone, that every package has a wheel there
  --matrix              show which OS, CPU and Python versions the lock's wheels cover
  --audit               ask PyPI about the locked packages: vulnerabilities, yanked, brand-new
  --json                print one JSON document on stdout
  -q, --quiet           -q: warnings and errors only; -qq: errors
  -v, --verbose         -v: every package's size; -vv: commands run
  --color WHEN          auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)

examples:
  bundleup check --audit --also-platform windows   also ask PyPI, and check Windows wheels

docs: https://github.com/funkyfunc/bundleup
```

## `bundleup verify`

```
usage: bundleup verify [-h] [--json] [-q] [-v] [--color WHEN] bundle

Check a bundle, and its unpacked copy on this machine, against its manifest.

positional arguments:
  bundle         the .pyz to check

options:
  -h, --help     show this help message and exit
  --json         print one JSON document on stdout
  -q, --quiet    -q: warnings and errors only; -qq: errors
  -v, --verbose  -v: show the traceback if bundleup crashes
  --color WHEN   auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)
```

## `bundleup cache`

```
usage: bundleup cache [-h] <command> ...

Bundles unpack once into a cache on the machine that runs them. List those copies, or remove the ones not used lately.

positional arguments:
  <command>
    list      show unpacked bundles, their size and when each was last used
    clean     remove unpacked bundles not used lately

options:
  -h, --help  show this help message and exit
```

## `bundleup cache list`

```
usage: bundleup cache list [-h] [--json] [-q] [-v] [--color WHEN]

options:
  -h, --help     show this help message and exit
  --json         print one JSON document on stdout
  -q, --quiet    -q: warnings and errors only; -qq: errors
  -v, --verbose  -v: show the traceback if bundleup crashes
  --color WHEN   auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)
```

## `bundleup cache clean`

```
usage: bundleup cache clean [-h] [--older-than DAYS] [--build] [-n] [--json] [-q] [-v]
                            [--color WHEN]

Remove unpacked bundles not used for --older-than days, plus leftovers of interrupted unpacks. A bundle that's removed unpacks again on its next run.

options:
  -h, --help         show this help message and exit
  --older-than DAYS  remove copies not used for this many days (default: 30; 0 removes all)
  --build            also clear the build cache (compiled bytecode)
  -n, --dry-run      show what would be removed
  --json             print one JSON document on stdout
  -q, --quiet        -q: warnings and errors only; -qq: errors
  -v, --verbose      -v: list each path removed
  --color WHEN       auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)
```
