# Reviewing Python as a JavaScript developer

The project's owner is fluent in JavaScript/TypeScript and newer to Python. This guide does two
jobs:
- **for the reviewer:** how to judge Python code (and the agents writing it) using taste you already
  have;
- **for agents writing code:** the style that keeps the code readable to that reviewer. Treat the
  "What good looks like" section as rules.

Most design taste transfers: small functions, clear names, explicit errors, no cleverness. What's
different is vocabulary and a handful of Python-specific traps, listed below.

## Review evidence first, code second

You don't have to read every line to direct the work. For any change, ask for:

1. **Checks:** Ruff, the type checker and the tests pass ([ADR-0015](adr/0015-engineering-tooling.md)).
2. **Gauntlet / benchmark results** if behaviour or speed changed ([ADR-0007](adr/0007-gauntlet-is-the-contract.md)).
3. **An ADR or learnings entry** for any decision or surprise.
4. **A summary written for a JS developer:** what changed, why, and any Python idiom used that
   doesn't exist in JS.

Then spot-check the code against the smell list below.

## Python ↔ TypeScript cheat sheet

| TypeScript / Node | Python | Notes |
|---|---|---|
| `function f(a: string): number` | `def f(a: str) -> int:` | Type hints read almost like TS. They're not enforced at run time; the type checker enforces them |
| `interface Opts { path: string; quiet?: boolean }` | `@dataclass(frozen=True) class Opts: path: Path; quiet: bool = False` | Prefer frozen dataclasses for plain data |
| `f({ output, python, quiet })` (options object) | `f(path, *, output=None, python=None, quiet=False)` | The `*` makes everything after it **keyword-only**: the Python options object |
| `` `hello ${name}` `` | `f"hello {name}"` | f-string |
| `null` / `undefined` | `None` | Compare with `is None`, not `== None` |
| `try { } catch (e) { } finally { }` | `try: … except SomeError as e: … finally: …` | Always catch a *specific* exception |
| `throw new BuildError(msg)` | `raise BuildError(msg)` | Custom errors subclass `Exception` |
| `arr.map(x => x * 2).filter(...)` | `[x * 2 for x in arr if ...]` | List comprehension; use a loop when it gets complicated |
| `Object.entries(obj)` | `obj.items()` | |
| `const { a, b } = obj` / `[a, b] = arr` | `a, b = pair` | Unpacking works on sequences, not dicts |
| `...args`, `{...obj}` | `*args`, `{**obj}` | |
| `await import("./x.js")` (lazy) | `from .x import y` inside a function | Used in `cli.py` so `--help` stays instant |
| `path.join(a, b)` | `Path(a) / b` | Use `pathlib.Path`, not string paths |
| `JSON.parse` / `JSON.stringify` | `json.loads` / `json.dumps` | |
| `process.exit(1)` | `sys.exit(1)`, or return an int from `main()` | |
| `console.error(...)` | `print(..., file=sys.stderr)` | |
| `using` / `try … finally` cleanup | `with open(p) as f:` | Context managers close files and locks automatically |
| `#private` / TS `private` | `_name` | A naming convention only; nothing enforces it |
| `package.json` | `pyproject.toml` | See [python-primer.md](python-primer.md) |

## What good looks like (rules for code in this repo)

- **Type hints on every function signature**, including return types. No bare `Any` without a
  comment explaining why.
- **Data is a frozen dataclass**, not a loose dict or tuple, once it has more than two fields or
  crosses a module boundary.
- **More than two parameters → keyword-only** (`def build(path, *, output=None, ...)`).
- **`pathlib.Path` for every path.**
- **Small functions that do one thing**; side effects (files, subprocesses, network) at the edges,
  logic in plain functions that are easy to test.
- **Specific exceptions**, with messages a user can act on. Never swallow errors silently.
- **No import-time work:** importing a module must not read files, run subprocesses or change
  global state.
- **No cleverness:** no metaprogramming, monkeypatching, deep inheritance or dynamic attribute
  tricks unless an ADR explains why.
- **Loader code (`_loader.py`) is special.** It runs on the user's Python before anything else,
  so it must run on Python 3.9 and *compile* on any Python 3 (to print "this app needs Python X"),
  and its warm path imports nothing beyond `os` and `sys`. That means: `os.path` instead of
  `pathlib`; `%` formatting instead of f-strings; quoted annotations and `# type:` comments for
  variables; typing names imported only under `TYPE_CHECKING = False` (importing `typing` costs
  4–7 ms). `tests/test_bundle.py` checks it parses with Python 3.5's grammar.

## The checks

Ruff (formatter and linter) and pyright (type checker) enforce most of the rules above, configured
in `pyproject.toml` ([ADR-0015](adr/0015-engineering-tooling.md)). Git hooks run them on commit and
the tests on push; CI runs everything on every push.

```bash
uv run ruff format .          # format (like Prettier)
uv run ruff check --fix .     # lint (like ESLint), including "every signature has types" (ANN)
uv run pyright                # type check (like tsc --noEmit)
uv run pytest -q tests        # tests (like vitest/jest)
uvx pre-commit install        # once per clone: run the above as git hooks
```

| JS habit | Here |
|---|---|
| `// eslint-disable-next-line rule` | `# noqa: RULE (why)`, always with a reason |
| `// @ts-expect-error` | `# pyright: ignore[rule]`, always with a reason |
| `"type": "module"` + `tsconfig` targets | `target-version = "py39"` (Ruff) and `pythonVersion = "3.9"` (pyright) |

## Smells to spot in review

| Smell | What it looks like | JS analogy | Fix |
|---|---|---|---|
| Mutable default argument | `def f(items=[]):` | **None in JS.** In Python the default is created once and shared between calls | `items=None`, then `items = items or []` |
| Swallowed errors | `except:` or `except Exception: pass` | an empty `catch {}` | Catch the specific error; handle or re-raise |
| Long positional argument lists | `build(a, b, c, d, e)` | a function taking five positional args | Keyword-only arguments |
| Untyped code | no hints, or `Any` everywhere | `any` everywhere in TS | Add hints; let the type checker check |
| Work at import time | top-level code that reads files or runs commands | side effects at the top of an ES module | Move it into a function |
| String paths | `os.path.join(...)`, `"dir/" + name` | string-concatenated paths | `Path(...) / name` |
| `from x import *` | star imports | `import * as` dumped into globals | Import names explicitly |
| Magic | `__getattr__` tricks, metaclasses, monkeypatching | prototype hacking | Plain functions and classes |
| `== None` | `if x == None:` | `x == null` (loose) | `if x is None:` |
| Unclosed resources | `f = open(p)` without `with` | a stream never closed | `with open(p) as f:` |

## A real example from this repo

`cli.py` calls `build(Path(opts.path), opts.output, opts.python, opts.entry, opts.lock_mode)`:
five positional arguments. A JS reviewer would ask for an options object; the Python answer is
keyword-only arguments: `build(path, output=..., python=..., entry=..., lock_mode=...)`. Your JS
instinct was right.
