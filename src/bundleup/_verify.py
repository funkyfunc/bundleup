"""Proof that a bundle contains exactly what uv.lock says, byte for byte: at build time, and later
with `bundleup verify`.

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
import functools
import hashlib
import io
import json
import os
import tempfile
import zipfile
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packaging.markers import Marker
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from . import _loader
from . import _toml as tomllib
from ._errors import NotABundleError

# Paths bundleup removes from the install on purpose (see build.SKIP_TOP); console-script
# launchers are removed too, and passed to check_records.
REMOVED_PREFIXES = (".lock",)
# Where installers put scripts and executables (`Scripts` on Windows).
SCRIPT_DIRS = ("bin", "Scripts")
# Paths bundleup adds on purpose: compiled bytecode, and a PEP 723 script.
ADDED_DIRS = ("__pycache__",)
SCRIPT_DIR = "__bundleup_script__"
RUNTIME_DIR = "__bundleup__"  # the payload's runtime files (ADR-0027)


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
    requires_python: str = ""  # its Requires-Python, "" if it states none


def record_hash(data: bytes) -> str:
    """A file's hash in RECORD format: "sha256=" + urlsafe base64 without padding."""
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + digest.decode("ascii")


@functools.lru_cache(maxsize=8)
def _lock_packages(pylock: str) -> tuple[tuple[str, str | None, str | None], ...]:
    """(name, version, marker) of every package in a pylock.toml, parsed once per text: the range
    and portability checks evaluate one lock for dozens of environments."""
    return tuple(
        (package["name"], package.get("version"), package.get("marker"))
        for package in tomllib.loads(pylock).get("packages", [])
    )


def locked_packages(pylock: str, environment: dict[str, str]) -> list[LockedPackage]:
    """The packages in a `uv export --format pylock.toml` that apply to this environment."""
    packages = []
    for name, version, marker in _lock_packages(pylock):
        if marker and not Marker(marker).evaluate(environment):
            continue
        packages.append(LockedPackage(canonicalize_name(name), version))
    return packages


def installed_distributions(site: Path) -> list[InstalledDistribution]:
    """Name and version of every distribution installed in `site`, from its METADATA."""
    found = []
    for metadata in sorted(site.glob("*.dist-info/METADATA")):
        fields = _metadata_fields(metadata.read_text(encoding="utf-8", errors="replace"))
        name, version = fields.get("Name", ""), fields.get("Version", "")
        found.append(
            InstalledDistribution(
                canonicalize_name(name),
                version,
                metadata.parent.name,
                fields.get("Requires-Python", ""),
            )
        )
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
    """(path, hash) for each file a RECORD lists; hash is "" for RECORD itself. Paths should use
    "/", but some wheels built on Windows use "\\" (ormsgpack 1.12.2, found by the nightly smoke
    test); pip and uv install them anyway, so they're read the same way."""
    for row in csv.reader(io.StringIO(text)):
        if row:
            yield row[0].replace("\\", "/"), (row[1] if len(row) > 1 else "")


def _added_on_purpose(path: str) -> bool:
    parts = path.split("/")
    return parts[0] in (SCRIPT_DIR, RUNTIME_DIR) or any(part in ADDED_DIRS for part in parts[:-1])


def record_paths(text: str) -> list[str]:
    """Every path a RECORD lists."""
    return [path for path, _hash in _record_entries(text)]


def check_records(
    site: Path,
    written: dict[str, str],
    *,
    removed: Collection[str] = (),
    added: Collection[str] = (),
) -> list[str]:
    """Compare the payload with every RECORD in `site`.

    `written` maps each payload path (POSIX, relative) to the RECORD-style hash of the bytes that
    went into the zip; `removed` lists RECORD paths bundleup left out on purpose, `added` files it
    put in that no RECORD lists (a PEP 723 script outside __bundleup_script__/).
    """
    problems = []
    covered: set[str] = set()
    for record in sorted(site.glob("*.dist-info/RECORD")):
        for path, expected in _record_entries(record.read_text(encoding="utf-8")):
            covered.add(path)
            if (
                path.startswith(REMOVED_PREFIXES)
                or path in removed
                or not expected
                or path.endswith(".pyc")
            ):
                continue  # removed on purpose, RECORD itself, or bytecode bundleup recompiles
            actual = written.get(path)
            if actual is None:
                problems.append(f"missing file: {path} (from {record.parent.name})")
            elif actual != expected:
                problems.append(f"changed file: {path} differs from {record.parent.name}/RECORD")
    for path in sorted(set(written) - covered):
        if not _added_on_purpose(path) and path not in added:
            problems.append(f"extra file: {path} isn't listed in any wheel's RECORD")
    return problems


@dataclass(frozen=True)
class VerifyReport:
    """What `bundleup verify` found. `ok` is True only if every check passed."""

    bundle: Path
    name: str
    files: int  # files the manifest lists
    problems: list[str] = field(default_factory=list)  # the bundle file vs its manifest
    cache: Path | None = None  # this machine's extracted copy, if there is one
    cache_problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and not self.cache_problems

    def to_json_dict(self) -> dict[str, object]:
        return {
            "bundle": str(self.bundle),
            "name": self.name,
            "files": self.files,
            "problems": self.problems,
            "cache": None
            if self.cache is None
            else {"path": str(self.cache), "problems": self.cache_problems},
        }


def _hash_file(path: Path) -> str:
    return record_hash(path.read_bytes())


def _check_payload(payload: zipfile.ZipFile, files: dict[str, str]) -> list[str]:
    problems = []
    seen = set()
    for info in payload.infolist():
        seen.add(info.filename)
        expected = files.get(info.filename)
        if expected is None:
            problems.append(f"extra file: {info.filename} isn't in the manifest")
        elif record_hash(payload.read(info)) != expected:
            problems.append(f"changed file: {info.filename}")
    problems += [f"missing file: {path}" for path in sorted(set(files) - seen)]
    return problems


def _check_cache(cache: Path, files: dict[str, str]) -> list[str]:
    """Compare an extracted copy with the manifest. Bytecode may be missing (some Pythons keep
    it under sys.pycache_prefix instead) or rewritten by Python, so it's only checked if present."""
    problems = []
    for path, expected in sorted(files.items()):
        local = cache / path
        if not local.is_file():
            if not path.endswith(".pyc"):
                problems.append(f"missing file: {path}")
        elif _hash_file(local) != expected:
            problems.append(f"changed file: {path}")
    for local in sorted(cache.rglob("*")):
        rel = local.relative_to(cache).as_posix()
        if local.is_file() and rel not in files and not rel.endswith(".pyc"):
            problems.append(f"extra file: {rel} isn't in the manifest")
    return problems


def _find_cache(bundle: Path, cache_dir: str) -> Path | None:
    """This machine's extracted copy, found the way the bundle's loader finds it."""
    for root, shared in _loader._roots(str(bundle)):
        candidate = os.path.join(root, cache_dir)
        if os.path.isdir(candidate) and (not shared or _loader._private(root)):
            return Path(candidate)
    return None


MANIFEST_KEYS = ("name", "loader")
PAYLOAD_KEYS = ("files", "payload", "cache_dir")  # at the top, or in each of "payloads" (ADR-0038)


def _read_manifest(bundle: Path) -> dict[str, Any]:  # Any: JSON
    try:
        with zipfile.ZipFile(bundle) as outer:
            manifest = json.loads(outer.read("manifest.json"))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as e:
        raise NotABundleError(
            f"{bundle} isn't a bundleup bundle with a manifest ({type(e).__name__}: {e})",
            hint="bundles carry manifest.json since bundleup's `build` command; rebuild it",
        ) from None
    payloads = manifest.get("payloads") or [manifest]
    missing = [key for key in MANIFEST_KEYS if key not in manifest]
    missing += sorted({key for p in payloads for key in PAYLOAD_KEYS if key not in p})
    if missing:
        raise NotABundleError(f"{bundle}'s manifest is incomplete (no {', '.join(missing)})")
    return manifest


def _check_loader(outer: zipfile.ZipFile, expected: dict[str, str]) -> list[str]:
    """__main__.py and __main__.pyc run first on every start, so they're checked too."""
    problems = []
    for name, digest in sorted(expected.items()):
        try:
            data = outer.read(name)
        except (KeyError, zipfile.BadZipFile) as e:
            problems.append(f"corrupted: {name} can't be read ({type(e).__name__}: {e})")
            continue
        if record_hash(data) != digest:
            problems.append(f"changed file: {name} (the loader)")
    return problems


def _payloads(manifest: dict[str, Any]) -> list[dict[str, Any]]:  # Any: JSON
    """Each payload's entry: the manifest itself for a single payload, else its "payloads"."""
    return manifest.get("payloads") or [{**manifest, "member": "payload.zip"}]


def _check_payload_zip(outer: zipfile.ZipFile, manifest: dict[str, Any]) -> list[str]:  # Any: JSON
    """A payload's hash, then every file inside it, against its manifest entry."""
    member = manifest["member"]
    try:
        with tempfile.TemporaryFile() as spool:
            digest = hashlib.sha256()
            with outer.open(member) as source:  # can be hundreds of MB: stream it
                for chunk in iter(lambda: source.read(1 << 20), b""):
                    digest.update(chunk)
                    spool.write(chunk)
            if digest.hexdigest() != manifest["payload"]["sha256"]:
                return [f"changed file: {member} doesn't match its recorded hash"]
            spool.seek(0)
            with zipfile.ZipFile(spool) as payload:
                return _check_payload(payload, manifest["files"])
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        return [f"corrupted: {member} can't be read ({type(e).__name__}: {e})"]


def _check_bundle(bundle: Path, manifest: dict[str, Any]) -> list[str]:  # Any: JSON
    """The bundle file against its manifest. Corruption is a problem to report, not a crash."""
    try:
        with zipfile.ZipFile(bundle) as outer:
            problems = _check_loader(outer, manifest["loader"])
            checked: set[str] = set()
            for payload in _payloads(manifest):
                if payload["member"] not in checked:  # identical payloads are stored once
                    checked.add(payload["member"])
                    problems += _check_payload_zip(outer, payload)
            return problems
    except (OSError, zipfile.BadZipFile) as e:
        return [f"corrupted: {bundle.name} can't be read ({type(e).__name__}: {e})"]


def verify(bundle: Path) -> VerifyReport:
    """Check a bundle against its embedded manifest, and this machine's unpacked copy too.

    Raises NotABundleError if `bundle` isn't a bundleup bundle with a manifest.
    """
    bundle = bundle.absolute()
    manifest = _read_manifest(bundle)
    payloads = _payloads(manifest)
    problems = _check_bundle(bundle, manifest)
    # This machine's unpacked copy: of whichever payload was unpacked here (one per machine).
    cache, cache_problems = None, []
    for payload in payloads:
        cache = _find_cache(bundle, payload["cache_dir"])
        if cache:
            cache_problems = _check_cache(cache, payload["files"])
            break
    unique = {p["member"]: len(p["files"]) for p in payloads}
    return VerifyReport(
        bundle, manifest["name"], sum(unique.values()), problems, cache, cache_problems
    )
