"""Precompile a bundle's Python files with the target interpreter, reusing earlier work.

Bytecode depends only on the source and the exact Python version, and a published wheel never
changes, so each distribution is compiled once per Python version and its `.pyc` files are kept in
bundleup's build cache, keyed by the distribution's RECORD (every file with its hash). Rebuilds only
compile the project's own code and whatever changed (roadmap item 9).

The `.pyc` files are unchecked-hash: they never consult the source's mtime, which suits a bundle's
immutable, content-addressed cache and survives extraction (mtimes aren't kept).
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

# Runs on the target interpreter. compileall.compile_file is a module-level function, so worker
# processes can receive it; `ddir` gives each file a relative co_filename (reproducible builds).
COMPILE_FILES = """
import compileall, concurrent.futures, os, py_compile, sys
site, listing, workers = sys.argv[1], sys.argv[2], int(sys.argv[3])
files = open(listing, encoding="utf-8").read().splitlines()
mode = py_compile.PycInvalidationMode.UNCHECKED_HASH
args = [
    [os.path.join(site, f) for f in files],
    [os.path.dirname(f) for f in files],
]
n = len(files)
rest = [[False] * n, [None] * n, [2] * n, [False] * n, [-1] * n, [mode] * n]
if workers == 1:
    list(map(compileall.compile_file, *args, *rest))
else:
    with concurrent.futures.ProcessPoolExecutor() as pool:
        list(pool.map(compileall.compile_file, *args, *rest, chunksize=32))
"""
# Part of every cache key: bump it when the way bytecode is compiled changes, so older cache
# entries are never reused (v2: compiled with PYTHONHASHSEED=0).
FORMAT = "v2"
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
    override = os.environ.get("BUNDLEUP_BUILD_CACHE")
    if override:
        return Path(override) / "bytecode"
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
        sources = [
            line.split(",", 1)[0]
            for line in content.decode("utf-8").splitlines()
            if line.split(",", 1)[0].endswith(".py")
        ]
        sources = [s for s in sources if not s.startswith("..") and (site / s).is_file()]
        found.append(Distribution(record.parent.name, key, sources))
    return found


def _restore(dist: Distribution, cache: Path, site: Path) -> bool:
    """Copy a distribution's cached bytecode into `site`. False if there's none."""
    cached = cache / dist.key
    if not cached.is_dir():
        return False
    made: set[str] = set()
    for rel, source in walk_files(cached):
        target = os.path.join(site, rel)
        parent = os.path.dirname(target)
        if parent not in made:
            os.makedirs(parent, exist_ok=True)
            made.add(parent)
        shutil.copyfile(source, target)
    return True


def _store(dist: Distribution, cache: Path, site: Path, cache_tag: str) -> None:
    """Keep a distribution's freshly compiled bytecode, atomically (parallel builds may race)."""
    final = cache / dist.key
    if final.exists():
        return
    cache.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dist.key}-", dir=cache))
    try:
        for source in dist.sources:
            pyc = pyc_path(source, cache_tag)
            if (site / pyc).is_file():
                (tmp / pyc).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(site / pyc, tmp / pyc)
        tmp.rename(final)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)  # someone else stored it first, or no space


def precompile(
    site: Path,
    *,
    python: str,
    python_identity: str,
    cache_tag: str,
    run: Callable[[list[str]], object],
) -> tuple[int, int]:
    """Compile everything in `site` with `python`, reusing cached bytecode.

    Returns (files compiled now, distributions restored from the cache).
    """
    cache = cache_dir()
    dists = distributions(site, python_identity=python_identity)
    covered = {source for dist in dists for source in dist.sources}
    restored = [dist for dist in dists if _restore(dist, cache, site)]
    fresh = [dist for dist in dists if dist not in restored]
    # Files no RECORD lists (a PEP 723 script) are always compiled.
    extra = [rel for rel, _ in walk_files(site) if rel.endswith(".py") and rel not in covered]
    todo = [source for dist in fresh for source in dist.sources] + extra
    if todo:
        listing = site.parent / "compile-list.txt"
        listing.write_text("\n".join(todo), encoding="utf-8")
        workers = 0 if len(todo) >= PARALLEL_FROM else 1
        run([python, "-I", "-c", COMPILE_FILES, str(site), str(listing), str(workers)])
    for dist in fresh:
        _store(dist, cache, site, cache_tag)
    return len(todo), len(restored)
