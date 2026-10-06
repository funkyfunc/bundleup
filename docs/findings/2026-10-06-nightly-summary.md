# Nightly runs: 2026-09-29 to 2026-10-06

Written by the weekly job ([`weekly.yml`](../../.github/workflows/weekly.yml) running [`weekly_summary.py`](../../gauntlet/weekly_summary.py)) from the results each nightly run attached on GitHub. Add a line of analysis when merging if anything changed.

## Smoke test (most-downloaded PyPI packages)

| Night | OS | Pass | Skipped | Failed |
|---|---|---|---|---|
| [2026-10-06 02:05](https://github.com/funkyfunc/bundleup/actions/runs/37402458784) | macos-15 | 100 | 0 | 0 |
| [2026-10-06 02:05](https://github.com/funkyfunc/bundleup/actions/runs/37402458784) | ubuntu-24.04 | 100 | 0 | 0 |
| [2026-10-06 02:05](https://github.com/funkyfunc/bundleup/actions/runs/37402458784) | ubuntu-24.04-arm | 100 | 0 | 0 |
| [2026-10-06 02:05](https://github.com/funkyfunc/bundleup/actions/runs/37402458784) | windows-2025 | 100 | 0 | 0 |

No smoke failures this week.

## Corpus (real programs, installed vs bundled)

| Night | OS | Pass | Skipped | Failed |
|---|---|---|---|---|
| [2026-10-06 02:18](https://github.com/funkyfunc/bundleup/actions/runs/37403482367) | macos-15 | 18 | 0 | 4 |
| [2026-10-06 02:18](https://github.com/funkyfunc/bundleup/actions/runs/37403482367) | ubuntu-24.04 | 18 | 0 | 4 |
| [2026-10-06 02:18](https://github.com/funkyfunc/bundleup/actions/runs/37403482367) | ubuntu-24.04-arm | 19 | 0 | 3 |
| [2026-10-06 02:18](https://github.com/funkyfunc/bundleup/actions/runs/37403482367) | windows-2025 | 16 | 0 | 6 |
| [2026-10-06 02:25](https://github.com/funkyfunc/bundleup/actions/runs/37404054537) | macos-15 | 22 | 0 | 0 |
| [2026-10-06 02:25](https://github.com/funkyfunc/bundleup/actions/runs/37404054537) | ubuntu-24.04 | 22 | 0 | 0 |
| [2026-10-06 02:25](https://github.com/funkyfunc/bundleup/actions/runs/37404054537) | ubuntu-24.04-arm | 22 | 0 | 0 |
| [2026-10-06 02:25](https://github.com/funkyfunc/bundleup/actions/runs/37404054537) | windows-2025 | 22 | 0 | 0 |

Failures (corpus):

| Name | OS | Nights failed | Last night | Detail |
|---|---|---|---|---|
| awscli | windows-2025 | 1 (2026-10-06 02:18) | pass | FileNotFoundError(2, 'The system cannot find the file specified', None, 2, None) |
| cookiecutter | macos-15 | 1 (2026-10-06 02:18) | pass | output: `cookiecutter --version` stdout differs: 'Cookiecutter 2.7.1 from <ENV>/lib/python3.12/site-packages (Python 3.12.15 (main, Oct  3 2026, 00:54:33) [Clang 22.1.3 ])' vs 'Cookiecutter 2.7.1 from |
| cookiecutter | ubuntu-24.04 | 1 (2026-10-06 02:18) | pass | output: `cookiecutter --version` stdout differs: 'Cookiecutter 2.7.1 from <ENV>/lib/python3.12/site-packages (Python 3.12.15 (main, Oct  3 2026, 01:03:07) [Clang 22.1.3 ])' vs 'Cookiecutter 2.7.1 from |
| cookiecutter | ubuntu-24.04-arm | 1 (2026-10-06 02:18) | pass | output: `cookiecutter --version` stdout differs: 'Cookiecutter 2.7.1 from <ENV>/lib/python3.12/site-packages (Python 3.12.15 (main, Oct  3 2026, 01:05:12) [Clang 22.1.3 ])' vs 'Cookiecutter 2.7.1 from |
| cookiecutter | windows-2025 | 1 (2026-10-06 02:18) | pass | output: `cookiecutter --version` stdout differs: 'Cookiecutter 2.7.1 from <ENV>/Lib/site-packages (Python 3.12.15 (main, Oct  3 2026, 01:05:37) [MSC v.1944 64 bit (AMD64)])' vs 'Cookiecutter 2.7.1 fro |
| mkdocs | macos-15 | 1 (2026-10-06 02:18) | pass | output: `mkdocs --version` stdout differs: 'mkdocs, version 1.6.1 from <ENV>/lib/python3.12/site-packages/mkdocs (Python 3.12)' vs 'mkdocs, version 1.6.1 from <HOME>/Library/Caches/bundleup/corpus-mkd |
| mkdocs | ubuntu-24.04 | 1 (2026-10-06 02:18) | pass | output: `mkdocs --version` stdout differs: 'mkdocs, version 1.6.1 from <ENV>/lib/python3.12/site-packages/mkdocs (Python 3.12)' vs 'mkdocs, version 1.6.1 from <HOME>/.cache/bundleup/corpus-mkdocs-b970 |
| mkdocs | ubuntu-24.04-arm | 1 (2026-10-06 02:18) | pass | output: `mkdocs --version` stdout differs: 'mkdocs, version 1.6.1 from <ENV>/lib/python3.12/site-packages/mkdocs (Python 3.12)' vs 'mkdocs, version 1.6.1 from <HOME>/.cache/bundleup/corpus-mkdocs-64c8 |
| mkdocs | windows-2025 | 1 (2026-10-06 02:18) | pass | output: `mkdocs --version` stdout differs: 'mkdocs, version 1.6.1 from <ENV>/Lib/site-packages/mkdocs (Python 3.12)' vs 'mkdocs, version 1.6.1 from <HOME>/AppData/Local/bundleup/Cache/corpus-mkdocs-18 |
| rich-cli | windows-2025 | 1 (2026-10-06 02:18) | pass | output: `rich --help` stderr differs: '  File "rich/__main__.py", line 10, in <module>' vs '  File "__main__.py", line 301, in <module>' |
| tox | macos-15 | 1 (2026-10-06 02:18) | pass | output: `tox --version` stdout differs: '4.64.9 from <ENV>/lib/python3.12/site-packages/tox/__init__.py' vs '4.64.9 from <HOME>/Library/Caches/bundleup/corpus-tox-9542c837427fb9ed/tox/__init__.py' |
| tox | ubuntu-24.04 | 1 (2026-10-06 02:18) | pass | output: `tox --version` stdout differs: '4.64.9 from <ENV>/lib/python3.12/site-packages/tox/__init__.py' vs '4.64.9 from <HOME>/.cache/bundleup/corpus-tox-96295a75dfdb061b/tox/__init__.py' |
| tox | ubuntu-24.04-arm | 1 (2026-10-06 02:18) | pass | output: `tox --version` stdout differs: '4.64.9 from <ENV>/lib/python3.12/site-packages/tox/__init__.py' vs '4.64.9 from <HOME>/.cache/bundleup/corpus-tox-812e321c484f56b7/tox/__init__.py' |
| tox | windows-2025 | 1 (2026-10-06 02:18) | pass | output: `tox --version` stdout differs: '4.64.9 from <ENV>/Lib/site-packages/tox/__init__.py' vs '4.64.9 from <HOME>/AppData/Local/bundleup/Cache/corpus-tox-52ea79992196db6a/tox/__init__.py' |
| twine | macos-15 | 1 (2026-10-06 02:18) | pass | output: `twine --help` stdout differs: 'usage: twine [-h] [--version] [--no-color] {register,check,upload}' vs 'usage: twine [-h] [--version] [--no-color] {register,upload,check}' |
| twine | ubuntu-24.04 | 1 (2026-10-06 02:18) | pass | output: `twine --help` stdout differs: 'usage: twine [-h] [--version] [--no-color] {check,register,upload}' vs 'usage: twine [-h] [--version] [--no-color] {check,upload,register}' |
| twine | windows-2025 | 1 (2026-10-06 02:18) | pass | output: `twine --help` stdout differs: 'usage: twine [-h] [--version] [--no-color] {check,upload,register}' vs 'usage: twine [-h] [--version] [--no-color] {register,upload,check}' |

## Open `corpus-failure` issues

None.
