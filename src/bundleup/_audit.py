"""`bundleup check --audit`: supply-chain checks on the locked packages, from PyPI (rounds 6 and
7: agents choose dependencies; models name packages that don't exist about 5% of the time, and
pick versions with known vulnerabilities in a third to a half of tasks).

For each locked package from pypi.org: known vulnerabilities of the locked version (PyPI's own
data, from OSV), whether it was yanked, and whether the project itself is brand new (first
published under NEW_PROJECT_DAYS ago, where typosquats and hallucinated names get registered).
Opt-in, because it needs the network; packages from other indexes aren't checked. A failure to
reach PyPI is one warning, never an error.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Container
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from packaging.utils import canonicalize_name

from . import _toml as tomllib
from ._errors import Diagnostic

PYPI = "https://pypi.org/pypi"
NEW_PROJECT_DAYS = 90
TIMEOUT = 15.0  # seconds per request


@dataclass(frozen=True)
class Locked:
    name: str
    version: str


def from_pypi(pylock_text: str, selected: Container[str]) -> list[Locked]:
    """The locked packages (those in `selected`, canonical names) that come from pypi.org."""
    found = []
    for package in tomllib.loads(pylock_text).get("packages", []):
        name, version = str(package.get("name", "")), package.get("version")
        index = str(package.get("index", ""))
        urls = [
            str(f.get("url", "")) for f in [*package.get("wheels", []), package.get("sdist") or {}]
        ]
        on_pypi = "pypi.org" in index or any("files.pythonhosted.org" in u for u in urls)
        if version and on_pypi and canonicalize_name(name) in selected:
            found.append(Locked(name, str(version)))
    return found


def audit(packages: list[Locked], *, now: datetime | None = None) -> list[Diagnostic]:
    """Check every package against PyPI, a few at a time."""
    now = now or datetime.now(timezone.utc)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda p: _check(p, now), packages))
    diags = [d for found, _failed in results for d in found]
    failed = [p.name for (_found, unreachable), p in zip(results, packages) if unreachable]
    if failed:
        diags.append(
            Diagnostic(
                "audit-incomplete",
                "warning",
                f"couldn't reach PyPI for {len(failed)} of {len(packages)} packages "
                f"({', '.join(failed[:5])}{', ...' if len(failed) > 5 else ''}), "
                "so they weren't audited",
                hint="check the network or proxy (HTTPS_PROXY), then run it again",
            )
        )
    return diags


def _check(package: Locked, now: datetime) -> tuple[list[Diagnostic], bool]:
    """(findings, whether PyPI couldn't be reached)."""
    try:
        release = _get(f"{PYPI}/{package.name}/{package.version}/json")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [_missing(package)], False
        return [], True
    except (OSError, ValueError):
        return [], True
    found = _vulnerabilities(package, release.get("vulnerabilities") or [])
    files = release.get("urls") or []
    if files and all(f.get("yanked") for f in files):
        reason = next((f.get("yanked_reason") for f in files if f.get("yanked_reason")), None)
        found.append(
            Diagnostic(
                "yanked",
                "warning",
                f"{package.name} {package.version} was yanked from PyPI"
                + (f": {reason}" if reason else ""),
                hint="lock another version (uv lock --upgrade-package NAME)",
                package=package.name,
            )
        )
    # A brand-new project has only recent releases; only then is the whole history fetched.
    uploaded = _oldest_upload(files)
    if uploaded and (now - uploaded).days < NEW_PROJECT_DAYS:
        try:
            project = _get(f"{PYPI}/{package.name}/json")
        except (OSError, ValueError):
            return found, True
        first = _oldest_upload([f for files in project.get("releases", {}).values() for f in files])
        if first and (now - first).days < NEW_PROJECT_DAYS:
            found.append(
                Diagnostic(
                    "new-project",
                    "warning",
                    f"{package.name} was first published on PyPI {(now - first).days} days ago",
                    hint="new projects are where typosquats and names models invent get "
                    "registered: check it's the package you meant",
                    package=package.name,
                )
            )
    return found, False


def _vulnerabilities(package: Locked, found: list[dict[str, Any]]) -> list[Diagnostic]:  # Any: JSON
    known = [v for v in found if not v.get("withdrawn")]
    if not known:
        return []
    ids = [str(v.get("id")) for v in known]
    fixed = sorted(
        {str(x) for v in known for x in (v.get("fixed_in") or [])},
        key=_version_key,
    )
    return [
        Diagnostic(
            "vulnerable",
            "warning",
            f"{package.name} {package.version} has {len(known)} known "
            f"{'vulnerability' if len(known) == 1 else 'vulnerabilities'}: {', '.join(ids[:5])}"
            + (", ..." if len(ids) > 5 else ""),
            hint=f"fixed in {fixed[-1]}; lock a newer version (uv lock --upgrade-package "
            f"{package.name})"
            if fixed
            else "no fixed version is listed; see https://osv.dev",
            package=package.name,
        )
    ]


def _missing(package: Locked) -> Diagnostic:
    return Diagnostic(
        "not-on-pypi",
        "warning",
        f"{package.name} {package.version} is locked from PyPI but PyPI doesn't have it now",
        hint="it may have been removed; check the name, and lock again",
        package=package.name,
    )


def _get(url: str) -> dict[str, Any]:  # Any: JSON
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # fixed https URL
        return json.loads(response.read())


def _oldest_upload(files: list[dict[str, Any]]) -> datetime | None:  # Any: JSON
    times = [str(f["upload_time_iso_8601"]) for f in files if f.get("upload_time_iso_8601")]
    if not times:
        return None
    return min(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times)


def _version_key(version: str) -> tuple[int, ...] | tuple[()]:
    from packaging.version import InvalidVersion, Version

    try:
        return Version(version).release
    except InvalidVersion:
        return ()
