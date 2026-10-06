"""Build-time proof that a bundle contains exactly what uv.lock says, byte for byte.

Two links of the hash chain in docs/testing-strategy.md ("What correct means"):

1. lock → bundle: every locked runtime distribution that applies to the target is installed, at
   its locked version, and nothing else is;
2. wheel → bundle: every file a wheel installed (its RECORD, with sha256) is in the payload with
   the same bytes, and the payload holds nothing that didn't come from a wheel except the files
   bundleup adds on purpose (compiled bytecode, a PEP 723 script).

uv already checks downloads against uv.lock's hashes (link 0). These checks guard against
bundleup's own mistakes: a dropped file, a changed byte, an extra or missing package.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# Paths bundleup removes from the install on purpose (see build.SKIP_TOP).
REMOVED_PREFIXES = ("bin/", ".lock")
# Paths bundleup adds on purpose: compiled bytecode, and a PEP 723 script.
ADDED_DIRS = ("__pycache__",)
SCRIPT_DIR = "__bundleup_script__"


@dataclass(frozen=True)
class LockedPackage:
    """A package from uv.lock that applies to the target. `version` is None for local projects."""

    name: str  # canonical, e.g. "charset-normalizer"
    version: str | None


@dataclass(frozen=True)
class InstalledDistribution:
    name: str  # canonical
    version: str
    dist_info: str  # directory name, e.g. "click-8.1.8.dist-info"


def record_hash(data: bytes) -> str:
    """A file's hash in RECORD format: "sha256=" + urlsafe base64 without padding."""
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + digest.decode("ascii")


def locked_packages(pylock: str, environment: dict[str, str]) -> list[LockedPackage]:
    """The packages in a `uv export --format pylock.toml` that apply to this environment."""
    packages = []
    for package in tomllib.loads(pylock).get("packages", []):
        marker = package.get("marker")
        if marker and not Marker(marker).evaluate(environment):
            continue
        packages.append(LockedPackage(canonicalize_name(package["name"]), package.get("version")))
    return packages


def installed_distributions(site: Path) -> list[InstalledDistribution]:
    """Name and version of every distribution installed in `site`, from its METADATA."""
    found = []
    for metadata in sorted(site.glob("*.dist-info/METADATA")):
        fields = _metadata_fields(metadata.read_text(encoding="utf-8", errors="replace"))
        name, version = fields.get("Name", ""), fields.get("Version", "")
        found.append(InstalledDistribution(canonicalize_name(name), version, metadata.parent.name))
    return found


def _metadata_fields(text: str) -> dict[str, str]:
    """The header fields of a METADATA file (it's email-style: headers, blank line, body)."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            break
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields.setdefault(key.strip(), value.strip())
    return fields


def _same_version(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b


def check_lock(locked: list[LockedPackage], installed: list[InstalledDistribution]) -> list[str]:
    """Differences between what uv.lock says and what was installed, as readable lines."""
    problems = []
    by_name: dict[str, list[InstalledDistribution]] = {}
    for dist in installed:
        by_name.setdefault(dist.name, []).append(dist)
    for name, dists in sorted(by_name.items()):
        if len(dists) > 1:
            versions = ", ".join(d.version for d in dists)
            problems.append(f"{name} is installed more than once ({versions})")
    wanted = {p.name: p for p in locked}
    for package in sorted(wanted.values(), key=lambda p: p.name):
        dists = by_name.get(package.name)
        locked_as = f"{package.name}=={package.version}" if package.version else package.name
        if not dists:
            problems.append(f"missing: {locked_as} is locked but not in the bundle")
        elif package.version and not _same_version(dists[0].version, package.version):
            problems.append(f"wrong version: {locked_as} is locked, {dists[0].version} is bundled")
    for name in sorted(set(by_name) - set(wanted)):
        problems.append(f"extra: {name}=={by_name[name][0].version} is bundled but not locked")
    return problems


def _record_entries(text: str) -> Iterable[tuple[str, str]]:
    """(path, hash) for each file a RECORD lists; hash is "" for RECORD itself."""
    for row in csv.reader(io.StringIO(text)):
        if row:
            yield row[0], (row[1] if len(row) > 1 else "")


def _added_on_purpose(path: str) -> bool:
    parts = path.split("/")
    return parts[0] == SCRIPT_DIR or any(part in ADDED_DIRS for part in parts[:-1])


def check_records(site: Path, written: dict[str, str]) -> list[str]:
    """Compare the payload with every RECORD in `site`.

    `written` maps each payload path (POSIX, relative) to the RECORD-style hash of the bytes that
    went into the zip.
    """
    problems = []
    covered: set[str] = set()
    for record in sorted(site.glob("*.dist-info/RECORD")):
        for path, expected in _record_entries(record.read_text(encoding="utf-8")):
            covered.add(path)
            if path.startswith(REMOVED_PREFIXES) or not expected or path.endswith(".pyc"):
                continue  # removed on purpose, RECORD itself, or bytecode bundleup recompiles
            actual = written.get(path)
            if actual is None:
                problems.append(f"missing file: {path} (from {record.parent.name})")
            elif actual != expected:
                problems.append(f"changed file: {path} differs from {record.parent.name}/RECORD")
    for path in sorted(set(written) - covered):
        if not _added_on_purpose(path):
            problems.append(f"extra file: {path} isn't listed in any wheel's RECORD")
    return problems
