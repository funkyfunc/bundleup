"""The payload: the installed tree, its entry point, bytecode, and the checks against the lock."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from . import _bytecode, _check, _platforms, _verify, _zipwriter
from ._errors import (
    ISSUES_URL,
    BundleMismatchError,
    BundleupError,
    Diagnostic,
    EntryPointError,
    NoCompatibleWheelError,
    UsageError,
)
from ._python import Portability, PythonRange, Target
from ._source import Source
from ._steps import Progress, run
from ._text import listing
from ._uv import console_scripts, launchers


class Entry(NamedTuple):
    """What a bundle runs. A plain tuple in the loader's config and the manifest."""

    kind: Literal["call", "module", "script"]
    target: str  # the module, or the script's path inside the payload
    attr: str = ""  # the function, for "call"

    def __str__(self) -> str:
        """ "module:function", "module", or the script's path."""
        return f"{self.target}:{self.attr}" if self.kind == "call" else self.target


def resolve_entry(source: Source, site: Path, *, entry: str | None, script: str | None) -> Entry:
    """What the loader runs: --entry, the project's console script, or the script itself."""
    if script:
        if entry:
            raise UsageError(
                "--entry is for projects; a script bundle runs the script",
                hint="drop --entry",
            )
        return Entry("script", script)
    scripts = console_scripts(site, source.name)
    if entry is None:
        if len(scripts) == 1:
            entry = next(iter(scripts.values()))
        elif canonicalize_name(source.name) in scripts:
            entry = scripts[canonicalize_name(source.name)]
        elif not scripts:
            raise EntryPointError(
                f"{source.name} defines no [project.scripts], so bundleup doesn't know what to run",
                hint="add one to pyproject.toml, or pass --entry module:function",
            )
        else:
            raise EntryPointError(
                f"{source.name} defines several commands ({', '.join(sorted(scripts))})",
                hint=f"pick one: --entry {sorted(scripts)[0]}",
            )
    elif entry in scripts:
        entry = scripts[entry]
    module, _, attr = entry.partition(":")
    attr = attr.split("[")[0].strip()  # drop legacy "extras" syntax: "mod:func [extra]"
    return Entry("call", module.strip(), attr) if attr else Entry("module", module.strip())


def check_wheel_platforms(site: Path, target: Target) -> None:
    """For another platform, every installed wheel must be built for it. uv builds source-only
    packages on this machine, so a compiled one would otherwise ship this machine's binaries."""
    platform = target.python_platform
    if platform is None:
        return
    wrong = []
    for dist_info in sorted(site.glob("*.dist-info")):
        tags = _platforms.wheel_tags(dist_info)
        if tags and not any(platform.accepts(tag) for tag in tags):
            wrong.append(f"{dist_info.name.removesuffix('.dist-info')}: {', '.join(tags)}")
    if wrong:
        raise NoCompatibleWheelError(
            f"{len(wrong)} package(s) have no build for {platform.name}",
            detail="\n".join(wrong),
            hint="these were probably built from source on this machine; build on the target "
            "platform, or pin versions that publish wheels for it",
        )


def inspect_site(site: Path) -> tuple[int, bool]:
    """(number of distributions, whether any of them is platform-specific)."""
    tags = [_platforms.wheel_tags(dist_info) for dist_info in site.glob("*.dist-info")]
    return len(tags), any(_platforms.is_native(t) for t in tags)


def runtime_needs(site: Path) -> _platforms.RuntimeNeeds:
    """What a machine needs to run the native wheels in `site` (checked by the loader)."""
    return _platforms.runtime_needs(
        _platforms.wheel_tags(dist_info) for dist_info in site.glob("*.dist-info")
    )


# Set literals are stored in .pyc files in hash order, and string hashes are randomised per process,
# so compiling twice can give different bytes. A fixed seed keeps builds reproducible.
COMPILE_ENV = {**os.environ, "PYTHONHASHSEED": "0"}


def precompile(target: Target, site: Path, *, progress: Progress, checked: bool = False) -> None:
    """Compile everything with the target's interpreter, reusing cached bytecode (_bytecode)."""

    def compile_with(cmd: list[str]) -> None:
        run(cmd, what="compiling bytecode", progress=progress, error=BundleupError, env=COMPILE_ENV)

    identity = (
        f"{_bytecode.FORMAT}-{target.implementation}-{target.full_version}-{target.cache_tag}"
    )
    _bytecode.precompile(
        site,
        python=target.executable,
        python_identity=identity,
        cache_tag=target.cache_tag,
        run=compile_with,
        checked=checked,
    )


def write_payload(site: Path, payload: Path) -> tuple[str, dict[str, str]]:
    """Zip the installed tree reproducibly, compressing on several threads.

    Returns the archive's sha256, and each zipped file's RECORD-style hash, for the integrity
    check and the manifest.
    """
    members = [
        _zipwriter.Member(rel, Path(path).read_bytes, os.stat(path).st_mode)
        for rel, path in _bytecode.walk_files(site)
    ]
    workers = min(8, os.cpu_count() or 1)
    # Level 6 (zlib's default): with compression spread over threads it costs ~5% more time than
    # level 1 on a large tree and saves ~8-13% of the size (findings 2026-10-05-faster-builds).
    return _zipwriter.write_zip(
        payload, members, level=6, workers=workers, hasher=_verify.record_hash
    )


def verify_payload(
    site: Path, *, pylock: Path, target: Target, written: dict[str, str], script: str | None
) -> list[_verify.LockedPackage]:
    """Fail the build if the payload doesn't match uv.lock and the wheels' RECORD files exactly.

    Returns the locked packages that apply to the target, for the manifest.
    """
    locked = _verify.locked_packages(pylock.read_text(encoding="utf-8"), target.markers)
    problems = _verify.check_lock(locked, _verify.installed_distributions(site))
    problems += _verify.check_records(
        site, written, removed=launchers(site), added=[script] if script else []
    )
    if problems:
        raise BundleMismatchError(
            "the bundle wouldn't match uv.lock exactly, so it wasn't written",
            detail=listing(problems),
            hint=f"this is a bug in bundleup; please report it: {ISSUES_URL}",
        )
    return locked


def pth_files(site: Path) -> list[str]:
    """The payload's .pth files, which the loader processes like a venv's site-packages: sorted,
    hidden ones skipped, as site.py does."""
    return sorted(p.name for p in site.glob("*.pth") if not p.name.startswith("."))


# The range a pure-Python bundle can claim (ADR-0030): from the oldest Python bundles are tested on;
# lock markers are evaluated up to NEWEST_KNOWN, and a range still open there stays open.
OLDEST = (3, 9)
NEWEST_KNOWN = (3, 20)


# One of each OS and CPU bundleup builds for: a pure bundle runs on all of them if the lock
# selects the same packages for each (ADR-0034).
SURVEY = [
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc",
    "aarch64-pc-windows-msvc",
]


def portability(pylock: Path, *, target: Target, pythons: PythonRange, native: bool) -> Portability:
    """Whether a pure-Python payload runs on any OS and any CPU: the lock's markers, evaluated
    for each OS and CPU and every Python in the range, select exactly the packages bundled.
    `colorama; sys_platform == "win32"` ties a bundle to its OS; a CPU marker to its CPU."""
    if native:
        return Portability()
    lock = pylock.read_text(encoding="utf-8")
    selected = set(_verify.locked_packages(lock, target.markers))
    newest = pythons.max or NEWEST_KNOWN
    versions = {target.full_version} | {f"3.{m}.0" for m in range(pythons.min[1], newest[1] + 1)}

    def same(name: str) -> bool:
        platform = _platforms.parse(name)
        return all(
            set(_verify.locked_packages(lock, platform.markers(python_full_version=v))) == selected
            for v in versions
        )

    results = {name: same(name) for name in SURVEY}
    any_os = all(results.values())
    own = [n for n in SURVEY if _platforms.parse(n).sys_platform == target.platform]
    return Portability(any_os=any_os, any_cpu=any_os or all(results[n] for n in own))


def python_range(
    site: Path, *, pylock: Path, target: Target, source: Source, native: bool
) -> PythonRange:
    """The minor versions this payload runs on: the target's only, if anything is compiled;
    otherwise every neighbouring version for which the lock selects the same packages and the
    project and every package allow that Python."""
    here = target.version
    if native:
        return PythonRange(here, here)
    lock = pylock.read_text(encoding="utf-8")
    selected = set(_verify.locked_packages(lock, target.markers))
    texts = [source.requires_python or ""]
    texts += [d.requires_python for d in _verify.installed_distributions(site)]
    specs = []
    for text in texts:
        try:
            specs.append(SpecifierSet(text))
        except InvalidSpecifier:
            continue  # unreadable metadata: the installer accepted it, so does this

    def same(minor: int) -> bool:
        full = f"3.{minor}.0"
        if not all(spec.contains(full, prereleases=True) for spec in specs):
            return False
        environment = {
            **target.markers,
            "python_version": f"3.{minor}",
            "python_full_version": full,
            "implementation_version": full,
        }
        return set(_verify.locked_packages(lock, environment)) == selected

    low = here[1]
    while low - 1 >= OLDEST[1] and same(low - 1):
        low -= 1
    high = here[1]
    while high + 1 <= NEWEST_KNOWN[1] and same(high + 1):
        high += 1
    return PythonRange((3, low), None if high == NEWEST_KNOWN[1] else (3, high))


@dataclass(frozen=True)
class Prepared:
    """A project installed and compiled in a staging directory, and what the analysis found."""

    source: Source
    target: Target
    site: Path
    pylock: Path
    script: str | None  # where a PEP 723 script is in the payload
    entry: Entry | None  # None only for `dir` and `lambda`, where it's optional
    packages: int
    native: bool
    version: str | None
    diagnostics: list[Diagnostic]
    sizes: list[_check.PackageSize]
    pythons: PythonRange  # the minor versions the bundle runs on (ADR-0030)
    reach: Portability  # whether it runs on any OS and CPU (ADR-0034)
