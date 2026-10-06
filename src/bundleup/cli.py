"""Command-line entry point: `bundleup [path]` builds dist/<name>.pyz."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__

DESCRIPTION = """\
Bundle a locked Python project (pyproject.toml + uv.lock) or a PEP 723 script into one
.pyz that runs on plain Python with no install step.

examples:
  bundleup                       bundle the project in this directory -> dist/<name>.pyz
  bundleup path/to/script.py     bundle a single-file script and its inline dependencies
  bundleup --python 3.9          build for Python 3.9 (bundles are tied to one Python version)
"""


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bundleup",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "path", nargs="?", default=".", help="project directory or .py script (default: .)"
    )
    p.add_argument(
        "-o", "--output", type=Path, help="output file (default: dist/<name>.pyz next to the input)"
    )
    p.add_argument(
        "-p",
        "--python",
        help="Python to build for: a version like 3.12 or a path "
        "(default: the one uv picks for the project)",
    )
    p.add_argument(
        "-e",
        "--entry",
        help="what to run: a [project.scripts] name, module:function, or module "
        "(default: the project's only script)",
    )
    lock = p.add_mutually_exclusive_group()
    lock.add_argument(
        "--locked",
        dest="lock_mode",
        action="store_const",
        const="locked",
        help="fail if uv.lock is out of date (as in uv)",
    )
    lock.add_argument(
        "--frozen",
        dest="lock_mode",
        action="store_const",
        const="frozen",
        help="use uv.lock as is, without checking it (as in uv)",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="print nothing on success")
    p.add_argument("-V", "--version", action="version", version=f"bundleup {__version__}")
    return p


def size(n: int) -> str:
    """A byte count for people: 884.8 KB, 9.5 MB."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return ""


def main(argv: list[str] | None = None) -> int:
    opts = parser().parse_args(argv)
    from .build import BuildError, build  # deferred so --help and --version stay instant

    start = time.perf_counter()
    try:
        result = build(
            Path(opts.path),
            output=opts.output,
            python=opts.python,
            entry=opts.entry,
            lock_mode=opts.lock_mode,
        )
    except BuildError as e:
        print(f"bundleup: error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    if not opts.quiet:
        elapsed = time.perf_counter() - start
        shown = str(result.output)
        try:
            rel = os.path.relpath(result.output)
            shown = shown if rel.startswith("..") else rel
        except ValueError:  # different drive on Windows
            pass
        target = result.target.describe(result.native)
        noun = "package" if result.packages == 1 else "packages"
        print(f"\n  {shown}  {size(result.size)}\n  {target} · {result.packages} {noun}\n")
        print(f"Done in {elapsed * 1000:.0f}ms")
        if os.environ.get("BUNDLEUP_TIMINGS"):
            print("  " + "  ".join(f"{k} {v * 1000:.0f}ms" for k, v in result.timings.items()))
    return 0
