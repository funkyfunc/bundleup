"""Output formats (ADR-0025) and --max-size (ADR-0039)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import BuildOptions, CheckFailedError, UsageError, build
from bundleup import _formats as f

SCRIPT = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
def handler(event, context):
    return {"ok": event["n"] + 1}
"""


def test_sizes_read_as_people_write_limits() -> None:
    assert f.parse_size("30MB") == 30_000_000
    assert f.parse_size("250 MiB") == 250 * 2**20
    assert f.parse_size("1.5mb") == 1_500_000
    assert f.parse_size("1000") == 1000
    with pytest.raises(UsageError, match="can't read the size `30 MBs`"):
        f.parse_size("30 MBs")
    assert (f.describe_size(30_000_000), f.describe_size(1_500_000)) == ("30 MB", "1.5 MB")


def test_a_lambda_zip_must_be_for_linux(tmp_path: Path) -> None:
    """Lambda runs Linux: a zip of macOS or Windows wheels would fail there, so it's an error
    (unless everything is pure Python, which runs anywhere)."""
    (tmp_path / "fn.py").write_text(
        SCRIPT.replace("dependencies = []", 'dependencies = ["pyyaml"]')
    )
    lock = subprocess.run(["uv", "lock", "--script", "fn.py"], cwd=tmp_path, capture_output=True)
    assert lock.returncode == 0, lock.stderr
    windows = BuildOptions(path=tmp_path / "fn.py", format="lambda", python_platform="windows")
    with pytest.raises(CheckFailedError) as e:
        build(windows)
    assert [d.code for d in e.value.diagnostics] == ["lambda-not-linux"]


def test_dir_output_is_importable_and_replaced_only_if_ours(tmp_path: Path) -> None:
    (tmp_path / "fn.py").write_text(SCRIPT)
    out = tmp_path / "out"
    result = build(BuildOptions(path=tmp_path / "fn.py", format="dir", output=out))
    assert result.format == "dir" and (out / "bundleup-manifest.json").is_file()
    code = "import fn; print(fn.handler({'n': 1}, None))"
    env = {**os.environ, "PYTHONPATH": str(out)}
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert done.stdout.strip() == "{'ok': 2}", done.stderr
    build(BuildOptions(path=tmp_path / "fn.py", format="dir", output=out))  # ours: replaced
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "keep.txt").write_text("")
    with pytest.raises(UsageError, match="isn't a directory bundleup wrote"):
        build(BuildOptions(path=tmp_path / "fn.py", format="dir", output=tmp_path / "other"))


def test_lambda_zip_has_code_at_the_top_with_bytecode(tmp_path: Path) -> None:
    (tmp_path / "fn.py").write_text(SCRIPT)
    out = tmp_path / "fn.zip"
    result = build(BuildOptions(path=tmp_path / "fn.py", format="lambda", output=out))
    names = zipfile.ZipFile(out).namelist()
    tag = sys.implementation.cache_tag
    assert {"fn.py", f"__pycache__/fn.{tag}.pyc", "bundleup-manifest.json"} <= set(names)
    manifest = json.loads(zipfile.ZipFile(out).read("bundleup-manifest.json"))
    assert (manifest["format"], manifest["payload"]) == ("lambda", None)
    assert result.to_json_dict()["format"] == "lambda"


def test_dir_output_notices_edited_sources(tmp_path: Path) -> None:
    """dir and lambda outputs can be edited in place (Lambda's console editor, a plugin folder),
    so their bytecode is hash-checked, unlike a .pyz's (the review found edits were ignored)."""
    (tmp_path / "fn.py").write_text(SCRIPT)
    out = tmp_path / "out"
    build(BuildOptions(path=tmp_path / "fn.py", format="dir", output=out))
    pyc = out / "__pycache__" / f"fn.{sys.implementation.cache_tag}.pyc"
    assert int.from_bytes(pyc.read_bytes()[4:8], "little") == 0b11  # hash-based, checked
    (out / "fn.py").write_text(SCRIPT.replace('event["n"] + 1', 'event["n"] + 100'))
    code = "import fn; print(fn.handler({'n': 1}, None))"
    env = {**os.environ, "PYTHONPATH": str(out), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert done.stdout.strip() == "{'ok': 101}", done.stderr


def test_max_size_refuses_every_format_before_writing(tmp_path: Path) -> None:
    (tmp_path / "fn.py").write_text(SCRIPT)
    outputs: list[tuple[f.Format, str]] = [("pyz", "fn.pyz"), ("dir", "out"), ("lambda", "fn.zip")]
    for fmt, name in outputs:
        out = tmp_path / name
        options = BuildOptions(path=tmp_path / "fn.py", format=fmt, output=out, max_size=10)
        with pytest.raises(CheckFailedError) as e:
            build(options)
        assert [d.code for d in e.value.diagnostics] == ["max-size"]
        assert not out.exists()
    result = build(BuildOptions(path=tmp_path / "fn.py", max_size=10**9))
    assert result.output.is_file()
