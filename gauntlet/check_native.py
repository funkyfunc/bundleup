"""Run every gauntlet project the normal way (installed with uv), to prove the projects work.

This is the control group: a project that fails here is a broken test, not a bundler failure.

Usage:
    uv run gauntlet/check_native.py                    # all projects, default Pythons
    uv run gauntlet/check_native.py 05 13              # only projects whose id starts with these
    uv run gauntlet/check_native.py --python 3.9 --heavy
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.specifiers import SpecifierSet

PROJECTS = Path(__file__).parent / "projects"
DEFAULT_PYTHONS = ["3.9", "3.10", "3.12"]


def load(project: Path) -> dict:
    meta = tomllib.loads((project / "gauntlet.toml").read_text())
    if "script" in meta:
        header = (project / meta["script"]).read_text()
        requires = header.split("requires-python = ", 1)[1].split("\n", 1)[0].strip('"')
    else:
        requires = tomllib.loads((project / "pyproject.toml").read_text())["project"][
            "requires-python"
        ]
    meta["requires_python"] = requires
    return meta


def command(project: Path, meta: dict, python: str) -> list[str]:
    args = meta.get("args", [])
    if "script" in meta:
        return ["uv", "run", "--quiet", "--python", python, "--script", meta["script"], *args]
    script_name = next(
        iter(tomllib.loads((project / "pyproject.toml").read_text())["project"]["scripts"])
    )
    return ["uv", "run", "--quiet", "--frozen", "--python", python, script_name, *args]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", help="project id prefixes to run")
    parser.add_argument("--python", action="append", help="Python versions (repeatable)")
    parser.add_argument("--heavy", action="store_true", help="include projects marked heavy")
    opts = parser.parse_args()

    pythons = opts.python or DEFAULT_PYTHONS
    failures = 0
    for project in sorted(p for p in PROJECTS.iterdir() if (p / "gauntlet.toml").exists()):
        meta = load(project)
        if opts.only and not any(meta["id"].startswith(o) for o in opts.only):
            continue
        if meta.get("heavy") and not opts.heavy:
            print(f"SKIP  {meta['id']:<32} heavy")
            continue
        for py in pythons:
            if py not in SpecifierSet(meta["requires_python"]):
                print(f"SKIP  {meta['id']:<32} py{py} (requires {meta['requires_python']})")
                continue
            result = subprocess.run(
                command(project, meta, py), cwd=project, capture_output=True, text=True
            )
            ok = result.returncode == 0 and f"GAUNTLET OK {meta['id']}" in result.stdout
            print(f"{'PASS' if ok else 'FAIL'}  {meta['id']:<32} py{py}")
            if not ok:
                failures += 1
                print(
                    "      "
                    + (result.stderr or result.stdout).strip().replace("\n", "\n      ")[-1500:]
                )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
