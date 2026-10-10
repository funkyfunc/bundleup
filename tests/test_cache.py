"""`bundleup cache list|clean` (ADR-0022): what counts as an unpacked bundle, what gets removed, and
the loader's once-a-day "last used" mark. Every cache location points into a temp directory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest

import bundleup
from bundleup import _cli

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "docs" / "schema" / "cache-v1.json").read_text())
DAY = 86400


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every place the loader might cache into tmp_path; return the explicit root."""
    for name in ("HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "XDG_CACHE_HOME", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / "elsewhere" / name.lower()))
    root = tmp_path / "cache"
    root.mkdir()
    monkeypatch.setenv("BUNDLEUP_CACHE", str(root))
    return root


def unpacked(root: Path, name: str, *, age_days: float, size: int = 100) -> Path:
    path = root / f"{name}-{'ab' * 8}"
    path.mkdir()
    (path / "module.py").write_bytes(b"x" * size)
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def test_list_finds_only_unpacked_bundles(cache: Path) -> None:
    unpacked(cache, "recent", age_days=1)
    unpacked(cache, "old", age_days=40)
    (cache / "build" / "bytecode").mkdir(parents=True)  # bundleup's own build cache
    (cache / "something-else").mkdir()
    (cache / ".tmp-recent-abababababababab-123-ff").mkdir()
    found = bundleup.list_cache()
    assert [b.name for b in found] == ["recent", "old"]  # most recently used first
    assert found[0].size_bytes == 100


def test_the_working_directorys_bundleup_folder_is_never_touched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.bundleup/` beside a bundle can't be found from here, and the one in the folder you run
    `cache` from isn't a cache root (eighth review: `cache clean` offered to remove it)."""
    for name in ("HOME", "USERPROFILE", "TMPDIR", "TEMP", "TMP", "XDG_CACHE_HOME", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / "elsewhere" / name.lower()))
    monkeypatch.delenv("BUNDLEUP_CACHE", raising=False)
    here = tmp_path / "work"
    (here / ".bundleup").mkdir(parents=True)
    old = unpacked(here / ".bundleup", "foo", age_days=90)
    monkeypatch.chdir(here)
    assert bundleup.list_cache() == []
    bundleup.clean_cache(older_than_days=0)
    assert old.exists()


def test_clean_removes_old_copies_and_leftovers_only(cache: Path) -> None:
    keep = unpacked(cache, "recent", age_days=1)
    old = unpacked(cache, "old", age_days=40)
    (cache / f".lock-{old.name}").write_text("")
    (cache / f".lock-{keep.name}").write_text("")
    leftover = cache / ".tmp-old-abababababababab-123-ff"
    leftover.mkdir()
    os.utime(leftover, (time.time() - DAY, time.time() - DAY))
    build = cache / "build"
    build.mkdir()

    dry = bundleup.clean_cache(older_than_days=30, dry_run=True)
    assert dry.removed == sorted([old, cache / f".lock-{old.name}", leftover])
    assert old.exists() and dry.freed_bytes >= 100

    report = bundleup.clean_cache(older_than_days=30)
    assert not old.exists() and not leftover.exists() and not (cache / f".lock-{old.name}").exists()
    assert keep.exists() and (cache / f".lock-{keep.name}").exists() and build.exists()
    assert report.freed_bytes >= 100


def test_clean_also_removes_bytecode_under_a_pycache_prefix(
    cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS's /usr/bin/python3 keeps bytecode under ~/Library/Caches/com.apple.python; the
    loader puts a bundle's .pyc files there, so cleaning must too (the review found it didn't)."""
    from bundleup import _cache

    prefix = tmp_path / "apple-pycache"
    monkeypatch.setattr(_cache, "PYCACHE_PREFIXES", [prefix])
    old = unpacked(cache, "old", age_days=40)
    mirror = prefix / os.path.splitdrive(str(old))[1].lstrip("\\/")
    mirror.mkdir(parents=True)
    (mirror / "module.cpython-39.pyc").write_bytes(b"pyc")
    report = bundleup.clean_cache(older_than_days=30)
    assert set(report.removed) == {old, mirror}
    assert not mirror.exists()


def test_clean_build_cache_only_when_asked(
    cache: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(tmp_path / "build-cache"))
    bytecode = tmp_path / "build-cache" / "bytecode"
    (bytecode / "key").mkdir(parents=True)
    bundleup.clean_cache()
    assert bytecode.exists()
    bundleup.clean_cache(build=True)
    assert not bytecode.exists()


def test_running_a_bundle_marks_it_used_at_most_daily(cache: Path, tmp_path: Path) -> None:
    script = tmp_path / "app.py"
    script.write_text('# /// script\n# dependencies = []\n# ///\nprint("hi")\n')
    bundle = tmp_path / "app.pyz"
    assert _cli.main(["build", str(script), "-o", str(bundle), "-q"]) == 0

    def run() -> None:
        subprocess.run([sys.executable, str(bundle)], check=True, capture_output=True)

    run()  # unpacks
    [copy] = bundleup.list_cache()
    hour_ago, two_days_ago = time.time() - 3600, time.time() - 2 * DAY
    os.utime(copy.path, (hour_ago, hour_ago))
    run()
    assert abs(copy.path.stat().st_mtime - hour_ago) < 1  # used within a day: no write
    os.utime(copy.path, (two_days_ago, two_days_ago))
    run()
    assert time.time() - copy.path.stat().st_mtime < 60  # refreshed


def test_cli_json(cache: Path, capsys: pytest.CaptureFixture[str]) -> None:
    unpacked(cache, "old", age_days=40)
    assert _cli.main(["cache", "list", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    jsonschema.validate(document, SCHEMA)
    assert [b["name"] for b in document["result"]["bundles"]] == ["old"]
    assert _cli.main(["cache", "clean", "--json", "--dry-run"]) == 0
    document = json.loads(capsys.readouterr().out)
    jsonschema.validate(document, SCHEMA)
    assert document["result"]["dry_run"] is True and len(document["result"]["removed"]) == 1


def test_cache_needs_a_subcommand(cache: Path) -> None:
    assert _cli.main(["cache"]) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="the in-use lock is POSIX only")
def test_clean_never_removes_a_copy_a_running_program_uses(cache: Path, tmp_path: Path) -> None:
    """Third review: a long-running service's copy looked unused after 30 days (the mark is set at
    start-up) and `cache clean` deleted files it still needed."""
    script = tmp_path / "service.py"
    script.write_text(
        '# /// script\n# requires-python = ">=3.9"\n# dependencies = []\n# ///\n'
        "import sys, time\nprint('ready', flush=True)\nsys.stdin.read()\n"
    )
    bundle = tmp_path / "service.pyz"
    assert _cli.main(["build", str(script), "-o", str(bundle), "-q"]) == 0
    service = subprocess.Popen(
        [sys.executable, str(bundle)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert service.stdout and service.stdout.readline().strip() == "ready"
        (copy,) = bundleup.list_cache()
        old = time.time() - 40 * DAY
        os.utime(copy.path, (old, old))
        report = bundleup.clean_cache(older_than_days=30)
        assert report.in_use == [copy.path] and copy.path not in report.removed
        assert copy.path.is_dir()
    finally:
        service.communicate("")
    assert copy.path in bundleup.clean_cache(older_than_days=30).removed  # once it has exited
