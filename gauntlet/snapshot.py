"""Describe the packages installed in one directory, as JSON, for the gauntlet's `matches-venv`
condition: run once against a normal install (a `uv sync` venv) and once against a bundle's
extracted payload; the two must match.

Runs on the *target* Python (3.9+), so it uses nothing newer:
    <venv>/bin/python snapshot.py <its site-packages>       # a normal install, as Python runs it
    python -S snapshot.py <extracted payload> --as-bundle   # a bundle, as bundleup's loader runs it

The loader puts the payload on sys.path after the standard library and processes its `.pth`
files as site.py does (ADR-0023), so the bundle side uses `site.addsitedir`, the reference for
both.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import sys

# Top-level names that are never importable on their own, in either environment.
NOT_MODULES = {"__pycache__", "bin", "Scripts", "..", ""}


CODE_SUFFIXES = (".py", ".so", ".pyd")


def top_level_names(dist: md.Distribution) -> set[str]:
    """Top-level modules and packages a distribution installed, from its RECORD.

    Only names with code under them count: a wheel's data files (e.g. sympy's `share/man/...`)
    sit at the root of a `--target` install, but they aren't modules.
    """
    names = set()
    for file in dist.files or []:
        first = file.parts[0] if file.parts else ""
        if first.endswith((".dist-info", ".data")) or first in NOT_MODULES:
            continue
        if not file.name.endswith(CODE_SUFFIXES):
            continue
        names.add(first.split(".")[0] if len(file.parts) == 1 else first)
    return names


def snapshot(site: str, *, as_bundle: bool) -> dict[str, object]:
    if as_bundle:
        import site as site_module  # importable under -S; -S only skips running it

        site_module.addsitedir(site)  # appended after the standard library, .pth files run
    dists = sorted(md.distributions(path=[site]), key=lambda d: d.metadata["Name"].lower())
    names: set[str] = set()
    for dist in dists:
        names |= top_level_names(dist)
    imports = {}
    for name in sorted(names):
        try:
            importlib.import_module(name)
            imports[name] = "ok"
        except BaseException as e:  # record any failure, including SystemExit
            imports[name] = type(e).__name__
    return {
        "distributions": [
            [dist.metadata["Name"].lower().replace("_", "-"), dist.version] for dist in dists
        ],
        "entry_points": sorted(
            [ep.group, ep.name, ep.value] for dist in dists for ep in dist.entry_points
        ),
        "imports": imports,
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(sys.argv[1], as_bundle="--as-bundle" in sys.argv), sort_keys=True))
