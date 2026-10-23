"""Wheel coverage from the lock alone (ADR-0031): which locked packages have no wheel for a target
platform, without installing anything. A lock lists every file of every locked version, so this
takes milliseconds and works for any number of targets.

Used before a cross-platform install (a precise error instead of uv's "built wheel is not
compatible"), and by `bundleup check --python-platform`, which checks other targets too.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, replace
from typing import Any

from packaging.markers import InvalidMarker, Marker, UndefinedEnvironmentName
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


@dataclass(frozen=True)
class _ParsedPackage:
    name: str
    version: str | None
    marker: Marker | None
    from_source: bool
    tags: tuple[frozenset[Tag], ...]


def _wheel_tags(package: Package) -> list[frozenset[Tag]]:
    found = []
    wheels = package.get("wheels", [])
    if not isinstance(wheels, list):
        return found
    for wheel in wheels:
        if not isinstance(wheel, dict):
            continue
        raw_url = str(wheel.get("url") or wheel.get("path") or "")
        fallback = raw_url.split("?", 1)[0].split("#", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
        name = str(wheel.get("name") or fallback)
        try:
            found.append(parse_wheel_filename(name)[3])
        except InvalidWheelFilename:
            continue
    return found


@functools.lru_cache(maxsize=8)
def _parsed_packages(pylock: str) -> tuple[_ParsedPackage, ...]:
    raw_packages = tomllib.loads(pylock).get("packages", [])
    if not isinstance(raw_packages, list):
        return ()
    parsed = []
    for package in raw_packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            continue
        raw_marker = package.get("marker")
        marker: Marker | None = None
        if isinstance(raw_marker, str):
            try:
                marker = Marker(raw_marker)
            except InvalidMarker:
                marker = None
        from_source = any(key in package for key in ("directory", "vcs", "archive"))
        version = package.get("version")
        parsed.append(
            _ParsedPackage(
                canonicalize_name(package["name"]),
                version if isinstance(version, str) else None,
                marker,
                from_source,
                tuple(_wheel_tags(package)),
            )
        )
    return tuple(parsed)


def gaps(
    pylock: str,
    platform: Platform,
    python: tuple[int, int],
    *,
    abiflags: str = "",
) -> list[Gap]:
    """Every locked package that applies to this target and has no wheel it can install."""
    supported = platform.supported_tags(python, abiflags=abiflags)
    environment: dict[str, Any] = {
        "extra": "",
        "extras": set(),
        "dependency_groups": set(),
        **platform.markers(python_full_version=f"{python[0]}.{python[1]}.0"),
    }
    grouped: dict[str, list[_ParsedPackage]] = {}
    for pkg in _parsed_packages(pylock):
        if pkg.marker is not None:
            try:
                if not pkg.marker.evaluate(environment):
                    continue
            except UndefinedEnvironmentName:
                continue
        grouped.setdefault(pkg.name, []).append(pkg)
    found = []
    for name, entries in grouped.items():
        if any(e.from_source for e in entries):
            continue  # a local project or a URL: built here from source
        tags = [t for e in entries for t in e.tags]
        if tags and (
            any(t & supported for t in tags)
            or any(
                platform.accepts(str(tag), python=python, abiflags=abiflags)
                for t in tags
                for tag in t
            )
        ):
            continue
        every = sorted({tag.platform for t in tags for tag in t})
        words = TAG_OS[platform.sys_platform]  # the same OS's wheels are the useful ones to show
        available = [p for p in every if any(w in p for w in words)] or every
        version = next((e.version for e in entries if e.version), None)
        found.append(
            Gap(
                name,
                version,
                platform.name,
                python,
                tuple(available),
                source_only=not tags,
            )
        )
    return found


def suggestion(
    found: list[Gap], platform: Platform, pylock: str, *, abiflags: str = ""
) -> str | None:
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
        still = {g.package for g in gaps(pylock, candidate, hard[0].python, abiflags=abiflags)}
        if not any(g.package in still for g in hard):
            return candidate.name
    return None


MACOS_LEVELS = [(14, 0), (15, 0), (26, 0)]  # newer deployment targets wheels commonly need


def macos_suggestion(
    found: list[Gap], platform: Platform, pylock: str, *, abiflags: str = ""
) -> tuple[int, int] | None:
    """A newer macOS deployment target under which every gap has a wheel, if one exists. uv takes
    macOS 13 unless MACOSX_DEPLOYMENT_TARGET says otherwise, so a wheel for macOS 14 looked
    missing even on the Mac building it, and nothing said why (twelfth review)."""
    hard = [g for g in found if not g.source_only]
    if not hard or platform.sys_platform != "darwin":
        return None
    for level in MACOS_LEVELS:
        if platform.level and level <= platform.level:
            continue
        candidate = replace(platform, level=level)
        still = {g.package for g in gaps(pylock, candidate, hard[0].python, abiflags=abiflags)}
        if not any(g.package in still for g in hard):
            return level
    return None


def describe(gap: Gap) -> str:
    """'pillow 12.3.0: wheels for manylinux_2_28_x86_64, macosx_11_0_arm64, ...'."""
    name = f"{gap.package} {gap.version}" if gap.version else gap.package
    if gap.source_only:
        return f"{name}: no wheels, only source"
    shown = ", ".join(gap.available[:6]) + (" ..." if len(gap.available) > 6 else "")
    return f"{name}: wheels only for {shown}"


def diagnostics(
    found: list[Gap], platform: Platform, pylock: str, *, abiflags: str = ""
) -> list[Diagnostic]:
    """Errors for packages that can't be bundled for `platform`; warnings for source-only ones
    (fine if they're pure Python, which only a build can tell)."""
    diags = []
    better = suggestion(found, platform, pylock, abiflags=abiflags)
    newer_macos = macos_suggestion(found, platform, pylock, abiflags=abiflags)
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
            if better:
                hint = f"{better} would work, if the target's C library is new enough"
            elif newer_macos:
                version = f"{newer_macos[0]}.{newer_macos[1]}"
                hint = (
                    f"MACOSX_DEPLOYMENT_TARGET={version} would work: build with it set, and the "
                    f"bundle needs macOS {version} or newer"
                )
            else:
                hint = "pin a version that publishes a wheel for it, or build on the target"
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


# The platforms `check --matrix` shows, with short labels, and the Python versions it considers.
MATRIX_PLATFORMS = {
    "x86_64-unknown-linux-gnu": "Linux x86_64",
    "aarch64-unknown-linux-gnu": "Linux arm64",
    "x86_64-unknown-linux-musl": "Linux x86_64 musl",
    "aarch64-apple-darwin": "macOS arm64",
    "x86_64-apple-darwin": "macOS x86_64",
    "x86_64-pc-windows-msvc": "Windows x86_64",
    "aarch64-pc-windows-msvc": "Windows arm64",
}
MATRIX_PYTHONS = [(3, minor) for minor in range(9, 15)]


@dataclass(frozen=True)
class MatrixCell:
    """One platform and Python version: the locked packages without a wheel there."""

    platform: str  # uv's name
    label: str
    python: tuple[int, int]
    missing: tuple[str, ...]  # packages with wheels, none for this cell (can't be bundled)
    source_only: tuple[str, ...]  # packages with no wheels at all (built here: fine if pure)

    @property
    def ok(self) -> bool:
        return not self.missing

    def to_json_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "python": f"{self.python[0]}.{self.python[1]}",
            "ok": self.ok,
            "missing": list(self.missing),
            "source_only": list(self.source_only),
        }


def matrix(pylock: str, pythons: list[tuple[int, int]]) -> list[MatrixCell]:
    """Where the locked packages can be bundled: every platform in MATRIX_PLATFORMS for every
    Python in `pythons`, from the lock alone (ADR-0031)."""
    cells = []
    for name, label in MATRIX_PLATFORMS.items():
        platform = parse(name)
        for python in pythons:
            found = gaps(pylock, platform, python)
            cells.append(
                MatrixCell(
                    name,
                    label,
                    python,
                    tuple(g.package for g in found if not g.source_only),
                    tuple(g.package for g in found if g.source_only),
                )
            )
    return cells
