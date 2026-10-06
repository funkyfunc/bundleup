"""The caches bundleup leaves behind, and cleaning them up (ADR-0022).

- Unpacked bundles: one directory per bundle version in each cache root the loader uses (the user
  cache directory, a private temp directory, or $BUNDLEUP_CACHE). A running bundle refreshes its
  directory's timestamp at most once a day, so "unused for N days" is measurable.
- The build cache: compiled bytecode kept between builds (ADR-0020).

Nothing here runs inside a bundle: bundles never delete anything, since another process may still be
running an older version.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import _bytecode, _loader

DAY = 86400.0
LEFTOVER_AGE = 3600.0  # an interrupted unpack's temp directory older than this is abandoned


@dataclass(frozen=True)
class CachedBundle:
    """One unpacked bundle version."""

    path: Path
    name: str
    size_bytes: int
    last_used: float  # seconds since the epoch

    def to_json_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "size_bytes": self.size_bytes,
            "last_used": round(self.last_used),
        }


@dataclass(frozen=True)
class CleanReport:
    removed: list[Path] = field(default_factory=list)
    freed_bytes: int = 0
    dry_run: bool = False

    def to_json_dict(self) -> dict[str, object]:
        return {
            "removed": [str(p) for p in self.removed],
            "freed_bytes": self.freed_bytes,
            "dry_run": self.dry_run,
        }


def cache_roots() -> list[Path]:
    """The loader's cache directories that exist and are ours (it also uses `.bundleup/` next to
    each bundle, which can't be found from here)."""
    roots = []
    for root, shared in _loader._roots("")[:-1]:
        if os.path.isdir(root) and (not shared or _loader._private(root)):
            roots.append(Path(root))
    return roots


def _size(path: Path) -> int:
    total = 0
    for _rel, file in _bytecode.walk_files(path):
        with contextlib.suppress(OSError):  # removed while we looked: doesn't count
            total += os.lstat(file).st_size
    return total


# How the loader names an unpacked bundle: "<name>-<first 16 hex digits of the payload's hash>".
# Anything else in a cache root (bundleup's own `build/` cache, for one) is left alone.
UNPACKED = re.compile(r"(?P<name>.+)-[0-9a-f]{16}")


def list_cache() -> list[CachedBundle]:
    """Every unpacked bundle in the cache roots, most recently used first."""
    found = []
    for root in cache_roots():
        for entry in os.scandir(root):
            match = UNPACKED.fullmatch(entry.name)
            if match and entry.is_dir(follow_symlinks=False):
                path = Path(entry.path)
                mtime = entry.stat(follow_symlinks=False).st_mtime
                found.append(CachedBundle(path, match["name"], _size(path), mtime))
    return sorted(found, key=lambda b: b.last_used, reverse=True)


def clean_cache(
    *, older_than_days: float = 30, build: bool = False, dry_run: bool = False
) -> CleanReport:
    """Remove unpacked bundles unused for `older_than_days`, abandoned temp directories and stale
    lock files; with `build`, also the build cache. With `dry_run`, only report."""
    now = time.time()
    doomed: list[Path] = [b.path for b in list_cache() if now - b.last_used > older_than_days * DAY]
    for root in cache_roots():
        for entry in os.scandir(root):
            age = now - entry.stat(follow_symlinks=False).st_mtime
            if entry.name.startswith(".tmp-") and age > LEFTOVER_AGE:
                doomed.append(Path(entry.path))
            elif entry.name.startswith(".lock-"):
                unpacked = root / entry.name[len(".lock-") :]
                if unpacked in doomed or (not unpacked.exists() and age > LEFTOVER_AGE):
                    doomed.append(Path(entry.path))
    if build and _bytecode.cache_dir().exists():
        doomed.append(_bytecode.cache_dir())
    freed = sum(_size(p) if p.is_dir() else p.stat().st_size for p in doomed)
    if not dry_run:
        for path in doomed:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    return CleanReport(sorted(doomed), freed, dry_run)
