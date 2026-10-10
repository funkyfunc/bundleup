"""`--format py`: the bundle as one plain-text .py file (ADR-0046)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bundleup import BuildOptions, NotABundleError, UsageError, build, verify

APP = """\
# /// script
# requires-python = ">=3.9"
# dependencies = ["colorama==0.4.6"]
# ///
import sys
import colorama
print("py OK", colorama.__version__, sys.argv[1:])
"""
HERE = f"{sys.version_info[0]}.{sys.version_info[1]}"


def run(bundle: Path, cache: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"BUNDLEUP_CACHE": str(cache), "PATH": "", "SYSTEMROOT": "C:\\Windows"}
    command = [sys.executable, str(bundle), *args]
    return subprocess.run(command, capture_output=True, text=True, env=env, cwd=bundle.parent)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(APP)
    return tmp_path / "src" / "app.py"


def test_one_text_file_that_runs_says_what_it_holds_and_verifies(app: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "tool.py"
    result = build(BuildOptions(path=app, output=out, python=HERE, format="py"))
    assert result.format == "py" and result.output == out
    text = out.read_text(encoding="ascii")  # plain text: it goes where only .py files go
    head = text[:2000]
    assert head.startswith("#!/usr/bin/env python3\n# /// bundleup\n")
    assert '#     "colorama==0.4.6",' in head and "# /// script" not in head  # nothing installs it
    assert "python3 tool.py" in head and "bundleup verify tool.py" in head
    r = run(out, tmp_path / "cache", "a", "b")
    assert r.returncode == 0 and r.stdout == "py OK 0.4.6 ['a', 'b']\n", r.stderr
    assert verify(out).ok


def test_files_beside_it_dont_shadow_its_packages(app: Path, tmp_path: Path) -> None:
    """`python tool.py` puts tool.py's folder first on sys.path; the bundle takes it off, as a
    .pyz's folder isn't on it either."""
    out = tmp_path / "out" / "tool.py"
    build(BuildOptions(path=app, output=out, python=HERE, format="py"))
    (out.parent / "colorama.py").write_text("raise SystemExit('shadowed')\n")
    r = run(out, tmp_path / "cache")
    assert r.returncode == 0 and r.stdout.startswith("py OK"), r.stderr


def test_windows_line_endings_still_run_and_damage_is_reported(app: Path, tmp_path: Path) -> None:
    out = tmp_path / "tool.py"
    build(BuildOptions(path=app, output=out, python=HERE, format="py"))
    data = out.read_bytes()
    crlf = tmp_path / "crlf" / "tool.py"
    crlf.parent.mkdir()
    crlf.write_bytes(data.replace(b"\n", b"\r\n"))  # as a Windows checkout might write it
    r = run(crlf, tmp_path / "cache-crlf")
    assert r.returncode == 0 and r.stdout.startswith("py OK"), r.stderr
    cut = tmp_path / "cut" / "tool.py"
    cut.parent.mkdir()
    cut.write_bytes(data[: len(data) * 2 // 3])  # an upload cut short
    r = run(cut, tmp_path / "cache-cut")
    assert r.returncode == 1 and "missing or damaged" in r.stderr and "Traceback" not in r.stderr
    with pytest.raises(NotABundleError):  # no manifest to check it against
        verify(cut)


def test_entry_python_and_several_platforms(app: Path, tmp_path: Path) -> None:
    other = "linux" if sys.platform == "win32" else "windows"
    out = tmp_path / "deps.py"
    build(
        BuildOptions(
            path=app,
            output=out,
            python=HERE,
            format="py",
            entry="python",
            python_platform=None,
            more_python_platforms=(other,),
        )
    )
    r = run(out, tmp_path / "cache", "-c", "import colorama; print('deps', colorama.__version__)")
    assert r.returncode == 0 and r.stdout == "deps 0.4.6\n", r.stderr
    assert verify(out).ok


def test_split_is_for_pyz_only(app: Path, tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="--split"):
        build(BuildOptions(path=app, output=tmp_path / "t.py", format="py", split=10**6))
