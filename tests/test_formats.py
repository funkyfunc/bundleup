"""Output formats and target presets (ADR-0025)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build
from bundleup import _targets as t

SCRIPT = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
def handler(event, context):
    return {"ok": event["n"] + 1}
"""


def test_presets_expand_and_explicit_flags_win() -> None:
    options, flags = t.apply(BuildOptions(target="lambda"))
    assert flags == [
        "--format",
        "lambda",
        "--python",
        "3.13",
        "--python-platform",
        "x86_64-manylinux_2_34",
    ]
    assert (options.format, options.python, options.target) == ("lambda", "3.13", None)
    # Python 3.10 and 3.11 run on Amazon Linux 2, whose glibc is older.
    options, _ = t.apply(BuildOptions(target="lambda-arm64", python="3.11"))
    assert options.python_platform == "aarch64-manylinux_2_17"
    options, _ = t.apply(BuildOptions(target="lambda", format="dir", python_platform="x"))
    assert (options.format, options.python_platform) == ("dir", "x")
    assert t.apply(BuildOptions()) == (BuildOptions(), [])


def test_preset_errors() -> None:
    with pytest.raises(UsageError, match=r"no Python 3\.9 runtime"):
        t.apply(BuildOptions(target="lambda", python="3.9"))
    with pytest.raises(UsageError, match="unknown target `lamda`") as e:
        t.apply(BuildOptions(target="lamda"))
    assert e.value.hint == "did you mean `--target lambda`?"
    with pytest.raises(UsageError, match="needs a Python version"):
        t.apply(BuildOptions(target="lambda", python="/usr/bin/python3"))


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
