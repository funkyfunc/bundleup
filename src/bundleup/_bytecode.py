"""Precompile a bundle's Python files with the target interpreter, reusing earlier work.

Bytecode depends only on the source and the exact Python version, and a published wheel never
changes, so each distribution is compiled once per Python version and its `.pyc` files are kept in
bundleup's build cache, keyed by the distribution's RECORD (every file with its hash). Rebuilds only
compile the project's own code and whatever changed (roadmap item 9).

The `.pyc` files are hash-based, never mtime-based (mtimes aren't kept in zips): unchecked in a
.pyz, whose content-addressed cache never changes; checked in `dir` and `zip` outputs, which
people may edit in place.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import _verify

# Runs on the target interpreter. compileall.compile_file is a module-level function, so worker
# processes can receive it; `ddir` gives each file a relative co_filename (reproducible builds).
COMPILE_FILES = """
import compileall, concurrent.futures, os, py_compile, sys
site, listing, workers, mode = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
files = open(listing, encoding="utf-8").read().splitlines()
mode = py_compile.PycInvalidationMode[mode]
args = [
    [os.path.join(site, f) for f in files],
    [os.path.dirname(f) for f in files],
]
n = len(files)
rest = [[True] * n, [None] * n, [2] * n, [False] * n, [-1] * n, [mode] * n]
if workers == 1:
    list(map(compileall.compile_file, *args, *rest))
else:
    with concurrent.futures.ProcessPoolExecutor() as pool:
        list(pool.map(compileall.compile_file, *args, *rest, chunksize=32))
"""
# Part of every cache key: bump it when the way bytecode is compiled changes, so older cache
# entries are never reused (v3: -s -S instead of -I so PYTHONHASHSEED=0 is honoured).
FORMAT = "v3"
# In .py files. Below this, starting worker interpreters costs more than they save.
PARALLEL_FROM = 300


def walk_files(root: Path) -> list[tuple[str, str]]:
    """(POSIX path relative to root, absolute path) of every file under `root`, sorted.

    Plain strings and os.walk on purpose: pathlib's relative_to() costs ~60 µs a call, over a
    second for a large bundle's 18,000 files.
    """
    base = str(root)
    found = []
    for dirpath, _dirnames, filenames in os.walk(base):
        prefix = dirpath[len(base) + 1 :].replace(os.sep, "/")
        for name in filenames:
            found.append((f"{prefix}/{name}" if prefix else name, os.path.join(dirpath, name)))
    found.sort()
    return found


@dataclass(frozen=True)
class Distribution:
    """An installed distribution's .py files and its cache key."""

    name: str
    key: str
    sources: list[str]  # relative to the site directory, POSIX style


def cache_dir() -> Path:
    """Where compiled bytecode is kept between builds (BUNDLEUP_BUILD_CACHE overrides it)."""
    override = os.environ.get("BUNDLEUP_BUILD_CACHE", "").strip()
    if override:
        return Path(override) / "bytecode"
    cache_override = os.environ.get("BUNDLEUP_CACHE", "").strip()
    if cache_override:
        return Path(cache_override) / "build" / "bytecode"
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "bundleup" / "build" / "bytecode"


def pyc_path(source: str, cache_tag: str) -> str:
    """Where Python looks for a source's bytecode: pkg/mod.py -> pkg/__pycache__/mod.<tag>.pyc."""
    head, _, name = source.rpartition("/")
    pyc = f"__pycache__/{name[:-3]}.{cache_tag}.pyc"
    return f"{head}/{pyc}" if head else pyc


def distributions(site: Path, *, python_identity: str) -> list[Distribution]:
    found = []
    for record in sorted(site.glob("*.dist-info/RECORD")):
        content = record.read_bytes()
        key = hashlib.sha256(content + python_identity.encode()).hexdigest()[:32]
        paths = _verify.record_paths(content.decode("utf-8"))  # "/" even if the wheel used "\\"
        sources = [path for path in paths if path.endswith(".py")]
        sources = [s for s in sources if not s.startswith("..") and (site / s).is_file()]
        found.append(Distribution(record.parent.name, key, sources))
    return found


def _extra_distribution(
    site: Path, covered: set[str], *, python_identity: str
) -> Distribution | None:
    """Files no wheel RECORD lists (the runtime shim, a PEP 723 script, or a folder app's files),
    keyed by their paths and contents so warm builds restore their bytecode from the cache too."""
    extra = [
        (rel, path) for rel, path in walk_files(site) if rel.endswith(".py") and rel not in covered
    ]
    if not extra:
        return None
    digest = hashlib.sha256(python_identity.encode())
    for rel, path in extra:
        digest.update(rel.encode("utf-8") + b"\0")
        with open(path, "rb") as f:
            digest.update(hashlib.sha256(f.read()).digest())
    return Distribution("__extra__", digest.hexdigest()[:32], [rel for rel, _ in extra])


def _restore(dist: Distribution, cache: Path, site: Path) -> bool:
    """Copy a distribution's cached bytecode into `site`. False if there's none."""
    cached = cache / dist.key
    if cached.is_symlink() or not cached.is_dir():
        return False
    files = walk_files(cached)
    if dist.sources and not files:
        return False
    made: set[str] = set()
    for rel, source in files:
        if os.path.islink(source):
            return False
        target = os.path.join(site, rel)
        parent = os.path.dirname(target)
        if parent not in made:
            try:
                os.makedirs(parent, exist_ok=True)
            except PermissionError:
                p_parent = os.path.dirname(parent)
                if os.path.isdir(p_parent):
                    os.chmod(p_parent, os.stat(p_parent).st_mode | 0o700)
                os.makedirs(parent, exist_ok=True)
            made.add(parent)
        try:
            shutil.copyfile(source, target)
        except PermissionError:
            try:
                os.chmod(parent, os.stat(parent).st_mode | 0o700)
                if os.path.exists(target):
                    os.chmod(target, os.stat(target).st_mode | 0o200)
                shutil.copyfile(source, target)
            except OSError:
                return False
        except OSError:
            return False
    return cached.is_dir() and not cached.is_symlink()


def _store(dist: Distribution, cache: Path, site: Path, cache_tag: str) -> None:
    """Keep a distribution's freshly compiled bytecode, atomically (parallel builds may race)."""
    final = cache / dist.key
    if not dist.sources or final.exists():
        return
    tmp: Path | None = None
    try:
        cache.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{dist.key}-", dir=cache))
        for source in dist.sources:
            pyc = pyc_path(source, cache_tag)
            if (site / pyc).is_file():
                (tmp / pyc).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(site / pyc, tmp / pyc)
        tmp.rename(final)
    except OSError:
        pass  # someone else stored it first, or no space
    finally:
        if tmp is not None and tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def precompile(
    site: Path,
    *,
    python: str,
    python_identity: str,
    cache_tag: str,
    run: Callable[[list[str]], object],
    checked: bool = False,
) -> tuple[int, int]:
    """Compile everything in `site` with `python`, reusing cached bytecode.

    `checked`: hash-checked .pyc files, which Python ignores once the source is edited (for
    `dir` and `zip` outputs, which people can edit in place); otherwise unchecked, the fastest
    for a .pyz, whose files never change. Returns (files compiled now, distributions restored
    from the cache).
    """
    mode = "CHECKED_HASH" if checked else "UNCHECKED_HASH"
    python_identity = f"{python_identity}-{mode}"
    cache = cache_dir()
    dists = distributions(site, python_identity=python_identity)
    covered = {source for dist in dists for source in dist.sources}
    extra = _extra_distribution(site, covered, python_identity=python_identity)
    all_dists = [*dists, extra] if extra is not None else dists
    restored: list[Distribution] = []
    fresh: list[Distribution] = []
    for dist in all_dists:
        (restored if _restore(dist, cache, site) else fresh).append(dist)
    todo = [source for dist in fresh for source in dist.sources]
    if todo:
        for rel_dir in {os.path.dirname(s) for s in todo}:
            d = os.path.join(site, rel_dir) if rel_dir else str(site)
            for p in (d, os.path.join(d, "__pycache__")):
                try:
                    if os.path.isdir(p) and (os.stat(p).st_mode & 0o700) != 0o700:
                        os.chmod(p, os.stat(p).st_mode | 0o700)
                except OSError:
                    pass
        listing = site.parent / "compile-list.txt"
        listing.write_text("\n".join(todo), encoding="utf-8")
        workers = 0 if len(todo) >= PARALLEL_FROM else 1
        # -s -S instead of -I: -I implies -E, which ignores PYTHONHASHSEED=0 in COMPILE_ENV. And no
        # pycache prefix: macOS's /usr/bin/python3 sets one, and the bytecode went there instead
        # of into the payload (twelfth review: 0 .pyc files bundled).
        no_prefix = ["-X", "pycache_prefix="]
        run(
            [
                python,
                "-s",
                "-S",
                *no_prefix,
                "-c",
                COMPILE_FILES,
                str(site),
                str(listing),
                str(workers),
                mode,
            ]
        )
    for dist in fresh:
        _store(dist, cache, site, cache_tag)
    return len(todo), sum(1 for d in restored if d.name != "__extra__")
