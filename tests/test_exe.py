"""`--format exe`: one file with its own Python, for machines without one (ADR-0047). Downloads
the launcher and an interpreter once per test session (the build cache is the session's)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build, verify

APP = """\
# /// script
# requires-python = ">=3.9"
# dependencies = ["colorama==0.4.6"]
# ///
import sys
import colorama
print("exe OK", colorama.__version__, sys.argv[1:], sys.version_info[:2])
"""
HERE = f"{sys.version_info[0]}.{sys.version_info[1]}"
WINDOWS = sys.platform == "win32"
# The first bytes of an executable for each OS: PE, ELF, Mach-O (64-bit, little-endian).
HEADS = {"windows": b"MZ", "linux": b"\x7fELF", "macos": b"\xcf\xfa\xed\xfe"}


@pytest.fixture
def app(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(APP)
    return tmp_path / "app.py"


def test_it_runs_with_no_python_on_the_machine(app: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / ("tool.exe" if WINDOWS else "tool")
    result = build(BuildOptions(path=app, output=out, python=HERE, format="exe", smoke=("x",)))
    assert result.format == "exe" and result.smoke is not None
    assert result.smoke.command == ["./tool.exe" if WINDOWS else "./tool", "x"]
    home = tmp_path / "home"
    home.mkdir()
    # No PATH at all, a fresh home: nothing but the file itself.
    env = {"HOME": str(home), "USERPROFILE": str(home), "PATH": "", "SYSTEMROOT": "C:\\Windows"}
    env["LOCALAPPDATA"] = str(home / "AppData")
    r = subprocess.run([str(out), "a", "b c"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"exe OK 0.4.6 ['a', 'b c'] {sys.version_info[:2]}\n"
    assert verify(out).ok  # the .pyz inside is checked through the executable


@pytest.mark.parametrize(
    ("platform", "head"),
    [("x86_64-pc-windows-msvc", "windows"), ("x86_64-manylinux_2_28", "linux")],
)
def test_it_builds_for_another_os_from_here(
    app: Path, tmp_path: Path, platform: str, head: str
) -> None:
    out = tmp_path / "tool"
    result = build(
        BuildOptions(path=app, output=out, python=HERE, format="exe", python_platform=platform,
                     smoke=())
    )  # fmt: skip
    assert out.read_bytes()[:4].startswith(HEADS[head])
    assert verify(out).ok
    # Described as what it is, not as the pure .pyz inside, which runs anywhere; and not run
    # here (seventh review: --smoke tried to run a Windows .exe on macOS).
    target = result.to_json_dict()["target"]
    assert isinstance(target, dict) and target["any_os"] is False
    assert target["python_range"] == {"min": HERE, "max": HERE}
    if head != ("windows" if WINDOWS else "linux" if sys.platform == "linux" else "macos"):
        assert result.smoke is None
        assert "smoke-skipped" in [d.code for d in result.diagnostics]


def test_one_platform_and_no_split(app: Path, tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="one platform"):
        build(
            BuildOptions(
                path=app,
                output=tmp_path / "t",
                python=HERE,
                format="exe",
                python_platform="linux",
                more_python_platforms=("windows",),
            )
        )
    with pytest.raises(UsageError, match="--split"):
        build(BuildOptions(path=app, output=tmp_path / "t", format="exe", split=10**8))
