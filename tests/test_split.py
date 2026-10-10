"""`--split SIZE`: a bundle too big for one file becomes a small .pyz and a folder of parts beside
it, none over SIZE (ADR-0045)."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build, verify

APP = """\
# /// script
# requires-python = ">=3.9"
# dependencies = ["colorama==0.4.6", "idna==3.10"]
# ///
import colorama
import idna  # big enough to need several parts
print("split OK", colorama.__version__)
"""
HERE = f"{sys.version_info[0]}.{sys.version_info[1]}"


def run(bundle: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    env = {"BUNDLEUP_CACHE": str(cache), "PATH": "", "SYSTEMROOT": "C:\\Windows"}
    return subprocess.run([sys.executable, str(bundle)], capture_output=True, text=True, env=env)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(APP)
    return tmp_path / "app.py"


def test_a_split_bundle_runs_verifies_and_keeps_every_file_under_the_size(
    app: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out" / "app.pyz"
    result = build(BuildOptions(path=app, output=out, python=HERE, split=100_000))
    parts = out.with_name("app.pyz.parts")
    assert result.parts == parts and len(list(parts.iterdir())) > 1
    assert all(p.stat().st_size <= 100_000 for p in [out, *parts.iterdir()])
    assert result.size_bytes == sum(p.stat().st_size for p in [out, *parts.iterdir()])
    with zipfile.ZipFile(out) as zf:  # the .pyz keeps only the loader and the manifest
        assert sorted(zf.namelist()) == ["__main__.py", "__main__.pyc", "manifest.json"]
        assert json.loads(zf.read("manifest.json"))["parts"] == "app.pyz.parts"
    assert result.to_json_dict()["parts"] == "out/app.pyz.parts"  # relative to the project
    r = run(out, tmp_path / "cache")
    assert r.returncode == 0 and r.stdout.startswith("split OK"), r.stderr
    assert verify(out).ok


def test_a_missing_or_foreign_part_is_refused_by_name(app: Path, tmp_path: Path) -> None:
    out = tmp_path / "app.pyz"
    build(BuildOptions(path=app, output=out, python=HERE, split=100_000))
    part = sorted(out.with_name("app.pyz.parts").iterdir())[0]
    data = part.read_bytes()
    part.write_bytes(data + b"x")
    r = run(out, tmp_path / "cache")
    assert r.returncode == 1 and "doesn't match it" in r.stderr and "Traceback" not in r.stderr
    assert any(part.name in p for p in verify(out).problems)
    part.unlink()
    r = run(out, tmp_path / "cache")
    assert r.returncode == 1 and f"part {part.name} is missing" in r.stderr
    assert not any((tmp_path / "cache").glob("app-*"))  # nothing unpacked under its name
    assert any("missing file" in p for p in verify(out).problems)


def test_a_bundle_that_fits_stays_one_file_and_replaces_a_stale_parts_folder(
    app: Path, tmp_path: Path
) -> None:
    out = tmp_path / "app.pyz"
    build(BuildOptions(path=app, output=out, python=HERE, split=100_000))
    assert out.with_name("app.pyz.parts").is_dir()
    result = build(BuildOptions(path=app, output=out, python=HERE, split=100_000_000))
    assert result.parts is None and not out.with_name("app.pyz.parts").exists()
    with zipfile.ZipFile(out) as zf:
        assert "payload.zip" in zf.namelist()
    r = run(out, tmp_path / "cache")
    assert r.returncode == 0, r.stderr


def test_split_mistakes_are_usage_errors(app: Path, tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="too big for a part"):
        build(BuildOptions(path=app, output=tmp_path / "a.pyz", python=HERE, split=30_000))
    with pytest.raises(UsageError, match=r"--split cuts a \.pyz"):
        build(BuildOptions(path=app, output=tmp_path / "d", python=HERE, split=10**6, format="dir"))
    (tmp_path / "b.pyz.parts").mkdir()
    (tmp_path / "b.pyz.parts" / "notes.txt").write_text("mine")
    with pytest.raises(UsageError, match="isn't a parts folder"):
        build(BuildOptions(path=app, output=tmp_path / "b.pyz", python=HERE, split=100_000))
    assert (tmp_path / "b.pyz.parts" / "notes.txt").exists()
