"""Wheel coverage from the lock alone (ADR-0031): which locked packages have no wheel for a target
platform, without installing anything. A lock lists every file of every locked version, so this
takes milliseconds and works for any number of targets.

Used before a cross-platform install (a precise error instead of uv's "built wheel is not
compatible"), and by `bundleup check --also-platform`, which checks other targets too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packaging.markers import Marker
from packaging.tags import Tag
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

from . import _toml as tomllib
from ._errors import Diagnostic
from ._platforms import TAG_OS, Platform, parse

Package = dict[str, Any]  # one [[packages]] entry of a pylock.toml; Any: TOML values

# The manylinux levels uv can target (`uv help pip install`), for suggestions.
UV_MANYLINUX = [(2, 17), (2, 28), *[(2, m) for m in range(31, 41)]]


@dataclass(frozen=True)
class Gap:
    """A locked package with no wheel for a target."""

    package: str  # canonical name
    version: str | None
    platform: str  # uv's name for the target
    python: tuple[int, int]
    available: tuple[str, ...]  # the platform tags its wheels do have, sorted
    source_only: bool  # no wheels at all: uv builds it from source, which works if it's pure


def _wheel_tags(package: Package) -> list[frozenset[Tag]]:
    found = []
    for wheel in package.get("wheels", []):
        name = (
            wheel.get("name") or str(wheel.get("url") or wheel.get("path") or "").rsplit("/", 1)[-1]
        )
        try:
            found.append(parse_wheel_filename(name)[3])
        except InvalidWheelFilename:
            continue
    return found


def gaps(pylock: str, platform: Platform, python: tuple[int, int]) -> list[Gap]:
    """Every locked package that applies to this target and has no wheel it can install."""
    supported = platform.supported_tags(python)
    environment = platform.markers(python_full_version=f"{python[0]}.{python[1]}.0")
    found = []
    for package in tomllib.loads(pylock).get("packages", []):
        marker = package.get("marker")
        if marker and not Marker(marker).evaluate(environment):
            continue
        if any(key in package for key in ("directory", "vcs", "archive")):
            continue  # a local project or a URL: built here from source
        tags = _wheel_tags(package)
        if tags and any(t & supported for t in tags):
            continue
        every = sorted({tag.platform for t in tags for tag in t})
        words = TAG_OS[platform.sys_platform]  # the same OS's wheels are the useful ones to show
        available = [p for p in every if any(w in p for w in words)] or every
        found.append(
            Gap(
                canonicalize_name(package["name"]),
                package.get("version"),
                platform.name,
                python,
                tuple(available),
                source_only=not tags,
            )
        )
    return found


def suggestion(found: list[Gap], platform: Platform, pylock: str) -> str | None:
    """A platform name for the same OS and CPU under which every gap has a wheel, if one exists
    (on Linux: a newer manylinux level), else None."""
    hard = [g for g in found if not g.source_only]
    if not hard or platform.sys_platform != "linux" or platform.musl:
        return None
    current = platform.level or (2, 28)
    for level in UV_MANYLINUX:
        if level <= current:
            continue
        candidate = parse(f"{platform.arch}-manylinux_{level[0]}_{level[1]}")
        still = {g.package for g in gaps(pylock, candidate, hard[0].python)}
        if not any(g.package in still for g in hard):
            return candidate.name
    return None


def describe(gap: Gap) -> str:
    """'pillow 12.3.0: wheels for manylinux_2_28_x86_64, macosx_11_0_arm64, ...'."""
    name = f"{gap.package} {gap.version}" if gap.version else gap.package
    if gap.source_only:
        return f"{name}: no wheels, only source"
    shown = ", ".join(gap.available[:6]) + (" ..." if len(gap.available) > 6 else "")
    return f"{name}: wheels only for {shown}"


def diagnostics(found: list[Gap], platform: Platform, pylock: str) -> list[Diagnostic]:
    """Errors for packages that can't be bundled for `platform`; warnings for source-only ones
    (fine if they're pure Python, which only a build can tell)."""
    diags = []
    better = suggestion(found, platform, pylock)
    python = f"Python {found[0].python[0]}.{found[0].python[1]}" if found else ""
    for gap in found:
        if gap.source_only:
            diags.append(
                Diagnostic(
                    "source-only",
                    "warning",
                    f"{describe(gap)}; for {platform.name} it's built from source on this "
                    "machine, which only works if it's pure Python",
                    hint="check it with a build for that platform (bundleup build "
                    f"--python-platform {platform.name})",
                    package=gap.package,
                )
            )
        else:
            hint = (
                f"{better} would work, if the target's C library is new enough"
                if better
                else "pin a version that publishes a wheel for it, or build on the target"
            )
            diags.append(
                Diagnostic(
                    "no-wheel",
                    "error",
                    f"no wheel of {gap.package} for {platform.name} ({python}): {describe(gap)}",
                    hint=hint,
                    package=gap.package,
                )
            )
    return diags
