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
import stat as stat_mod
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

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
def _lock_packages(pylock: str) -> tuple[tuple[str, str | None, Marker | None], ...]:
    """(name, version, marker) of every package in a pylock.toml, parsed once per text: the range
    and portability checks evaluate one lock for dozens of environments."""
    raw = tomllib.loads(pylock).get("packages", [])
    if not isinstance(raw, list):
        return ()
    return tuple(
        (
            canonicalize_name(package["name"]),
            package.get("version"),
            Marker(package["marker"]) if isinstance(package.get("marker"), str) else None,
        )
        for package in raw
        if isinstance(package, dict) and isinstance(package.get("name"), str)
    )


def locked_packages(pylock: str, environment: dict[str, str]) -> list[LockedPackage]:
    """The packages in a `uv export --format pylock.toml` that apply to this environment."""
    packages = []
    for name, version, marker in _lock_packages(pylock):
        if marker and not marker.evaluate(environment):
            continue
        packages.append(LockedPackage(name, version))
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


def _walk_dir(root: Path) -> tuple[dict[str, str], set[str], list[str]]:
    """Every regular file (rel -> full path), non-regular entry/symlink (rel), and unreadable
    directory problem under `root`, without building a Path per entry or following symlinks."""
    found: dict[str, str] = {}
    special: set[str] = set()
    errors: list[str] = []
    prefix = str(root)
    cut = len(prefix) + (0 if prefix.endswith(os.sep) else 1)

    def on_error(e: OSError) -> None:
        bad = os.fspath(e.filename) if e.filename else prefix
        rel = bad[cut:].replace(os.sep, "/") if bad.startswith(prefix) else bad
        errors.append(f"corrupted: {rel or '.'} can't be read ({type(e).__name__}: {e})")

    for dirpath, dirnames, filenames in os.walk(prefix, followlinks=False, onerror=on_error):
        dirnames.sort()
        rel_dir = dirpath[cut:].replace(os.sep, "/")
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                special.add(f"{rel_dir}/{d}" if rel_dir else d)
                dirnames.remove(d)
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = f"{rel_dir}/{name}" if rel_dir else name
            try:
                mode = os.lstat(full).st_mode
            except OSError as e:
                errors.append(f"corrupted: {rel} can't be read ({type(e).__name__}: {e})")
                continue
            if stat_mod.S_ISLNK(mode) or not stat_mod.S_ISREG(mode):
                special.add(rel)
            else:
                found[rel] = full
    return found, special, errors


DIR_MANIFEST = "bundleup-manifest.json"  # in a `dir` output and at the top of a Lambda zip
EXE_HEADS = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe")


def _check_payload(
    payload: zipfile.ZipFile, files: dict[str, str], *, ignore: Collection[str] = ()
) -> list[str]:
    problems = []
    seen = set()
    for info in payload.infolist():
        if info.filename in ignore:
            continue
        seen.add(info.filename)
        expected = files.get(info.filename)
        if expected is None:
            problems.append(f"extra file: {info.filename} isn't in the manifest")
            continue
        try:
            data = payload.read(info)
        except (OSError, zipfile.BadZipFile, zlib.error, EOFError) as e:
            problems.append(f"corrupted: {info.filename} can't be read ({type(e).__name__}: {e})")
            continue
        if record_hash(data) != expected:
            problems.append(f"changed file: {info.filename}")
    problems += [f"missing file: {path}" for path in sorted(set(files) - seen)]
    return problems


def _check_dir(folder: Path, files: dict[str, str]) -> list[str]:
    """Compare a `--format dir` output with its `bundleup-manifest.json`."""
    found, special, problems = _walk_dir(folder)
    for path, expected in sorted(files.items()):
        full = found.get(path)
        if full is None:
            problems.append(f"changed file: {path}" if path in special else f"missing file: {path}")
            continue
        try:
            actual = record_hash(Path(full).read_bytes())
        except OSError as e:
            problems.append(f"corrupted: {path} can't be read ({type(e).__name__}: {e})")
            continue
        if actual != expected:
            problems.append(f"changed file: {path}")
    for rel in sorted((set(found) | special) - set(files)):
        if rel != DIR_MANIFEST:
            problems.append(f"extra file: {rel} isn't in the manifest")
    return problems


def _check_cache(cache: Path, files: dict[str, str]) -> list[str]:
    """Compare an extracted copy with the manifest. Bytecode may be missing (some Pythons keep
    it under sys.pycache_prefix instead) or rewritten by Python, so it's only checked if present."""
    found, special, problems = _walk_dir(cache)
    for path, expected in sorted(files.items()):
        full = found.get(path)
        if full is None:
            if path in special:
                problems.append(f"changed file: {path}")
            elif not path.endswith(".pyc"):
                problems.append(f"missing file: {path}")
            continue
        try:
            actual = record_hash(Path(full).read_bytes())
        except OSError as e:
            problems.append(f"corrupted: {path} can't be read ({type(e).__name__}: {e})")
            continue
        if actual != expected:
            problems.append(f"changed file: {path}")
    for rel in sorted((set(found) | special) - set(files)):
        if not rel.endswith(".pyc") or rel in special:
            problems.append(f"extra file: {rel} isn't in the manifest")
    return problems


def _find_cache(bundle: Path, cache_dir: str) -> Path | None:
    """This machine's extracted copy, found the way the bundle's loader finds it."""
    for root, shared in _loader._roots(os.path.realpath(bundle)):
        candidate = os.path.join(root, cache_dir)
        if os.path.isdir(candidate) and (not shared or _loader._private(root)):
            return Path(candidate)
    return None


MANIFEST_KEYS = ("name", "loader")
PAYLOAD_KEYS = ("files", "payload", "cache_dir")  # a bundle for one platform: at the top
# A bundle for several (ADR-0038): "layers" (member -> sha256, size, files), and "payloads", each
# with its "members" (layers, unpacked in order) and "cache_dir".
LAYERED_KEYS = ("members", "cache_dir")


def _read_scie_trailer(bundle: Path) -> tuple[dict[str, Any], int] | None:  # Any: JSON
    """The `{"scie": ...}` JSON line at the end of a `--format exe` binary and the byte offset
    where its leading `\\n` starts, or None if the file doesn't end with one."""
    try:
        size = bundle.stat().st_size
        read_len = min(size, 65536)
        with bundle.open("rb") as f:
            f.seek(size - read_len)
            tail = f.read(read_len)
    except OSError:
        return None
    if not tail.endswith(b"\n"):
        return None
    nl = tail.rfind(b"\n", 0, len(tail) - 1)
    if nl < 0:
        return None
    line = tail[nl + 1 : -1]
    if not line.startswith(b"{"):
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("scie"), dict):
        return None
    return data["scie"], size - (len(tail) - nl)


def _is_exe(bundle: Path, outer: zipfile.ZipFile | None = None) -> bool:
    """Whether `bundle` is a `--format exe` executable (even if its head or tail was damaged)."""
    try:
        with bundle.open("rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if head.startswith(EXE_HEADS):
        return True
    if _read_scie_trailer(bundle) is not None:
        return True
    return bool(
        not head.startswith(b"#!")
        and outer
        and outer.infolist()
        and outer.infolist()[0].header_offset > 64
    )


def _hash_span(f: IO[bytes], size: int) -> str | None:
    """SHA-256 hex digest of the next `size` bytes from `f`, or None on short read."""
    digest = hashlib.sha256()
    remaining = size
    while remaining > 0:
        chunk = f.read(min(remaining, 1 << 20))
        if not chunk:
            return None
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.hexdigest()


def _check_exe(bundle: Path) -> list[str]:
    """Check a `--format exe` binary's launcher, bundled Python archive and scie trailer."""
    from ._exe import JUMPS

    found = _read_scie_trailer(bundle)
    if found is None:
        return ["corrupted: executable trailer can't be read"]
    scie, trailer_offset = found
    try:
        jump = scie["jump"]
        jump_size = int(jump["size"])
        jump_hash = str(jump["hash"])
        files = [
            (str(entry["name"]), int(entry["size"]), str(entry["hash"]))
            for entry in scie["lift"]["files"]
        ]
    except (KeyError, TypeError, ValueError):
        return ["corrupted: executable trailer is incomplete"]
    if jump_size < 0 or jump_size + sum(size for _, size, _ in files) != trailer_offset:
        return ["corrupted: executable size doesn't match its trailer"]
    known_jumps = {digest for _, digest in JUMPS.values()}
    problems: list[str] = []
    with bundle.open("rb") as f:
        actual_jump = _hash_span(f, jump_size)
        if actual_jump != jump_hash or jump_hash not in known_jumps:
            problems.append("changed file: launcher doesn't match its recorded hash")
        for name, size, expected in files:
            if size < 0 or _hash_span(f, size) != expected:
                problems.append(f"changed file: {name} doesn't match its recorded hash")
    return problems


def _open(bundle: Path) -> tuple[zipfile.ZipFile, bytes | None]:
    """The bundle's zip, and a .py bundle's code (everything before its data, ADR-0046), which
    it checks instead of a .pyz's __main__.py and __main__.pyc. Raises BadZipFile for neither."""
    try:
        return zipfile.ZipFile(bundle), None
    except zipfile.BadZipFile:
        text = bundle.read_bytes()
        start, end = text.rfind(_loader.DATA_START), text.rfind(_loader.DATA_END)
        if start < 0 or end < start:
            raise
        try:
            data = base64.b64decode(text[start + len(_loader.DATA_START) : end].replace(b"#", b""))
        except ValueError:
            raise zipfile.BadZipFile("the data at the end of the file is damaged") from None
        return zipfile.ZipFile(io.BytesIO(data)), text[:start]


def _str_dict(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    )


def _read_manifest(bundle: Path) -> dict[str, Any]:  # Any: JSON
    if not bundle.exists():
        raise NotABundleError(
            f"{bundle} does not exist",
            hint="give the path to a bundle file or directory",
        )
    if bundle.is_dir():
        try:
            manifest = json.loads((bundle / DIR_MANIFEST).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            raise NotABundleError(
                f"{bundle} isn't a bundleup directory with {DIR_MANIFEST} ({type(e).__name__}: {e})"
            ) from None
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest.get("name"), str)
            or not _str_dict(manifest.get("files"))
        ):
            raise NotABundleError(f"{bundle}'s manifest is incomplete")
        return manifest
    try:
        outer, _code = _open(bundle)
        with outer:
            names = set(outer.namelist())
            entry = "manifest.json" if "manifest.json" in names else DIR_MANIFEST
            manifest = json.loads(outer.read(entry))
    except (OSError, zipfile.BadZipFile, zlib.error, EOFError, KeyError, ValueError) as e:
        found = _read_scie_trailer(bundle)
        if found is not None and isinstance(found[0].get("lift"), dict):
            name = str(found[0]["lift"].get("name", bundle.name))
            return {"name": name, "format": "exe", "files": {}, "loader": {}}
        raise NotABundleError(
            f"{bundle} isn't a bundleup bundle with a manifest ({type(e).__name__}: {e})",
            hint="bundles carry manifest.json since bundleup's `build` command; rebuild it",
        ) from None
    if not isinstance(manifest, dict):
        raise NotABundleError(f"{bundle} isn't a bundleup bundle with a manifest")
    if manifest.get("format") in ("dir", "zip", "lambda"):
        if not isinstance(manifest.get("name"), str) or not _str_dict(manifest.get("files")):
            raise NotABundleError(f"{bundle}'s manifest is incomplete")
        return manifest
    missing = [key for key in MANIFEST_KEYS if key not in manifest]
    if "payloads" in manifest:
        layers = manifest.get("layers")
        payloads = manifest["payloads"]
        if (
            not isinstance(layers, dict)
            or not isinstance(payloads, list)
            or not all(isinstance(p, dict) for p in payloads)
        ):
            raise NotABundleError(f"{bundle}'s manifest is incomplete")
        missing += [] if layers else ["layers"]
        missing += sorted(
            {k for p in payloads if isinstance(p, dict) for k in LAYERED_KEYS if k not in p}
        )
        if not missing and (
            not payloads
            or not all(
                isinstance(p.get("cache_dir"), str)
                and bool(p.get("cache_dir"))
                and isinstance(p.get("members"), list)
                and all(isinstance(m, str) for m in p["members"])
                for p in payloads
            )
            or not all(
                isinstance(layer, dict)
                and isinstance(layer.get("sha256"), str)
                and _str_dict(layer.get("files"))
                for layer in layers.values()
            )
        ):
            raise NotABundleError(f"{bundle}'s manifest is incomplete")
        missing += sorted({m for p in payloads for m in p.get("members", [])} - set(layers))
    else:
        missing += [key for key in PAYLOAD_KEYS if key not in manifest]
        if not missing and (
            not _str_dict(manifest.get("files"))
            or not isinstance(manifest.get("payload"), dict)
            or not isinstance(manifest["payload"].get("sha256"), str)
            or not (manifest.get("cache_dir") is None or isinstance(manifest.get("cache_dir"), str))
        ):
            raise NotABundleError(f"{bundle}'s manifest is incomplete")
    if missing:
        raise NotABundleError(f"{bundle}'s manifest is incomplete (no {', '.join(missing)})")
    parts = manifest.get("parts")
    if (
        not isinstance(manifest.get("name"), str)
        or not (manifest.get("loader") is None or _str_dict(manifest.get("loader")))
        or not (parts is None or (isinstance(parts, str) and bool(parts)))
    ):
        raise NotABundleError(f"{bundle}'s manifest is incomplete")
    return manifest


def _check_loader(
    outer: zipfile.ZipFile, expected: dict[str, str], code: bytes | None
) -> list[str]:
    """__main__.py and __main__.pyc (or a .py bundle's code) run first on every start, so they're
    checked too."""
    problems = []
    for name, digest in sorted((expected or {}).items()):
        try:
            data = code if code is not None else outer.read(name)
        except (OSError, KeyError, zipfile.BadZipFile, zlib.error, EOFError) as e:
            problems.append(f"corrupted: {name} can't be read ({type(e).__name__}: {e})")
            continue
        if record_hash(data) != digest:
            what = "the code before its data" if code is not None else name
            problems.append(f"changed file: {what} (the loader)")
    return problems


def _layers(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:  # Any: JSON
    """Each zip in the bundle: member -> its sha256 and files."""
    if "payloads" in manifest:
        return manifest["layers"]
    if not manifest.get("payload"):
        return {}
    return {"payload.zip": {"sha256": manifest["payload"]["sha256"], "files": manifest["files"]}}


def _payloads(manifest: dict[str, Any]) -> list[dict[str, Any]]:  # Any: JSON
    """Each payload: its cache directory and every file it unpacks (from all its layers)."""
    if "payloads" not in manifest:
        if not manifest.get("cache_dir"):
            return []
        return [{"cache_dir": manifest["cache_dir"], "files": manifest["files"]}]
    layers = manifest["layers"]
    return [
        {
            "cache_dir": p["cache_dir"],
            "files": {rel: h for m in p["members"] for rel, h in layers[m]["files"].items()},
        }
        for p in manifest["payloads"]
    ]


def _check_layer(
    open_member: Callable[[str], IO[bytes]], member: str, layer: dict[str, Any]
) -> list[str]:  # Any: JSON
    """A zip's hash, then every file inside it, against the manifest."""
    try:
        with tempfile.TemporaryFile() as spool:
            digest = hashlib.sha256()
            with open_member(member) as source:  # can be hundreds of MB: stream it
                for chunk in iter(lambda: source.read(1 << 20), b""):
                    digest.update(chunk)
                    spool.write(chunk)
            if digest.hexdigest() != layer["sha256"]:
                return [f"changed file: {member} doesn't match its recorded hash"]
            spool.seek(0)
            with zipfile.ZipFile(spool) as payload:
                return _check_payload(payload, layer["files"])
    except FileNotFoundError:
        return [f"missing file: {member}, a part of the split bundle"]
    except (OSError, KeyError, zipfile.BadZipFile, zlib.error, EOFError) as e:
        return [f"corrupted: {member} can't be read ({type(e).__name__}: {e})"]


def _parts_dir(bundle: Path, parts: str) -> Path:
    real_parts = bundle.resolve().parent / parts
    if not real_parts.is_dir() and (bundle.parent / parts).is_dir():
        return bundle.parent / parts
    return real_parts


def _check_bundle(bundle: Path, manifest: dict[str, Any]) -> list[str]:  # Any: JSON
    """The bundle file against its manifest, and a split bundle's parts folder (ADR-0045).
    Corruption is a problem to report, not a crash."""
    if bundle.is_dir():
        return _check_dir(bundle, manifest["files"])
    try:
        outer, code = _open(bundle)
        with outer:
            if manifest.get("format") in ("dir", "zip", "lambda"):
                return _check_payload(outer, manifest["files"], ignore=(DIR_MANIFEST,))
            problems = _check_exe(bundle) if _is_exe(bundle, outer) else []
            problems += _check_loader(outer, manifest.get("loader") or {}, code)
            parts = manifest.get("parts")
            # A split bundle's layers are files in the folder beside the real bundle file.
            parts_dir = _parts_dir(bundle, parts) if parts else None
            source = parts_dir.joinpath if parts_dir else None
            layers = _layers(manifest)
            for member, layer in sorted(layers.items()):
                opener = (lambda m: source(m).open("rb")) if source else outer.open
                problems += _check_layer(opener, member, layer)
            if parts_dir is not None and parts_dir.is_dir():
                for entry in sorted(parts_dir.iterdir()):
                    if entry.name not in layers:
                        problems.append(f"extra file: {parts}/{entry.name} isn't in the manifest")
            return problems
    except (OSError, zipfile.BadZipFile, zlib.error, EOFError) as e:
        problems = _check_exe(bundle) if _is_exe(bundle) else []
        return problems or [f"corrupted: {bundle.name} can't be read ({type(e).__name__}: {e})"]


def unpacks(bundle: Path) -> bool:
    """Whether `bundle` unpacks to a cache directory at run time (`dir` and `zip` don't)."""
    if bundle.is_dir():
        return False
    try:
        return _read_manifest(bundle).get("format") not in ("dir", "zip", "lambda")
    except NotABundleError:
        return False


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
    layers = _layers(manifest)
    files = (
        sum(len(layer["files"]) for layer in layers.values())
        if layers
        else len(manifest.get("files", {}))
    )
    return VerifyReport(bundle, manifest["name"], files, problems, cache, cache_problems)
