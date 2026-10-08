"""One .pyz for several platforms and Python versions (ADR-0038)."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from bundleup import BuildOptions, build, verify

PURE = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
print("hello")
"""
# colorama only on Windows: the lock selects different packages per OS, so no payload serves all.
PER_OS = PURE.replace("dependencies = []", "dependencies = [\"colorama; sys_platform == 'win32'\"]")


def manifest(bundle: Path) -> dict[str, object]:
    with zipfile.ZipFile(bundle) as zf:
        return json.loads(zf.read("manifest.json"))


def test_a_pure_bundle_for_any_os_needs_one_payload(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(PURE)
    python = f"{sys.version_info[0]}.{sys.version_info[1]}"
    result = build(
        BuildOptions(
            path=tmp_path / "app.py",
            output=tmp_path / "app.pyz",
            python=python,
            python_platform="linux",
            more_python_platforms=("windows", "macos"),
        )
    )
    assert "payloads" not in manifest(result.output)  # Linux's payload runs everywhere
    assert result.payloads == []


def test_a_payload_per_os_when_the_lock_differs_and_verify_checks_each(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(PER_OS)
    python = f"{sys.version_info[0]}.{sys.version_info[1]}"
    out = tmp_path / "app.pyz"
    result = build(
        BuildOptions(
            path=tmp_path / "app.py",
            output=out,
            python=python,
            python_platform="linux",
            more_python_platforms=("windows",),
        )
    )
    payloads = manifest(out)["payloads"]
    assert isinstance(payloads, list) and len(payloads) == 2
    assert [p["platform"] for p in result.payloads] == ["linux", "win32"]
    report = verify(out)
    assert report.ok, report.problems
    # Each file is stored once: a layer both payloads unpack, and colorama for Windows only.
    linux, windows = (p["members"] for p in payloads)
    assert len(linux) == 1 and windows[0] == linux[0] and len(windows) == 2
    with zipfile.ZipFile(out) as zf:
        assert sorted(n for n in zf.namelist() if n.startswith("layer-")) == sorted(windows)
    if sys.platform == "darwin":  # nothing for this machine: one sentence naming both targets
        r = subprocess.run([sys.executable, str(out)], capture_output=True, text=True)
        assert r.returncode == 1
        assert "on Linux" in r.stderr and "on Windows" in r.stderr and "Traceback" not in r.stderr


def test_a_layered_bundle_runs_here(tmp_path: Path) -> None:
    """This machine's payload is unpacked from its layers, and the program runs."""
    (tmp_path / "app.py").write_text(PER_OS)
    python = f"{sys.version_info[0]}.{sys.version_info[1]}"
    out = tmp_path / "app.pyz"
    other = "linux" if sys.platform == "win32" else "windows"
    build(
        BuildOptions(
            path=tmp_path / "app.py", output=out, python=python, more_python_platforms=(other,)
        )
    )
    payloads = manifest(out)["payloads"]
    assert isinstance(payloads, list) and len(payloads) == 2
    env = {"BUNDLEUP_CACHE": str(tmp_path / "cache"), "PATH": ""}
    r = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, env=env)
    assert (r.returncode, r.stdout.strip()) == (0, "hello"), r.stderr
    assert verify(out).ok
