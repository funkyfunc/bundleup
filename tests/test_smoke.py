"""`--smoke`: the finished bundle runs once, in a fresh home folder with the network blocked where
the OS allows it (sixth review: the only check that sees run-time failures)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bundleup import BuildOptions, CheckFailedError, UsageError, build
from bundleup._smoke import parse_args

SCRIPT = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import os, sys
print("ran", sys.argv[1:], os.path.basename(os.getcwd()))
"""
NETWORK = (
    SCRIPT
    + """\
import socket
socket.create_connection(("pypi.org", 443), timeout=5)
"""
)


def test_a_bundle_that_runs_passes(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text(SCRIPT)
    result = build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "t.pyz", smoke=()))
    assert result.smoke is not None and result.smoke.exit_code == 0
    assert result.smoke.command == ["python", "t.pyz", "--help"]  # the default arguments
    assert "ran ['--help'] work" in result.smoke.output  # in a fresh folder, not here
    assert result.to_json_dict()["smoke"] == result.smoke.to_json_dict()
    args = parse_args("tool.py --name 'two words'")
    assert args == ("tool.py", "--name", "two words")


def test_a_bundle_that_fails_fails_the_build(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text(SCRIPT + "raise SystemExit(3)\n")
    with pytest.raises(CheckFailedError, match="exited with 3") as e:
        build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "t.pyz", smoke=("go",)))
    (diag,) = e.value.diagnostics
    assert diag.code == "smoke-failed" and diag.detail and "ran ['go']" in diag.detail
    assert (tmp_path / "t.pyz").exists()  # written, so it can be looked at


@pytest.mark.skipif(
    sys.platform != "darwin", reason="sandbox-exec is macOS's; Linux may lack unshare"
)
def test_the_network_is_blocked(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text(NETWORK)
    with pytest.raises(CheckFailedError, match="exited with 1") as e:
        build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "t.pyz", smoke=()))
    assert "no network" in e.value.diagnostics[0].message


def test_what_smoke_refuses_or_skips(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text(SCRIPT)
    with pytest.raises(UsageError, match=r"--smoke runs a \.pyz"):
        build(BuildOptions(path=tmp_path / "tool.py", format="dir", smoke=()))
    with pytest.raises(UsageError, match="needs a script to run for --entry python"):
        build(BuildOptions(path=tmp_path / "tool.py", entry="python", smoke=()))
    other = "windows" if sys.platform != "win32" else "linux"
    (tmp_path / "native.py").write_text(SCRIPT.replace("[]", '["pyyaml"]'))
    result = build(
        BuildOptions(path=tmp_path / "native.py", python_platform=other, smoke=(),
                     output=tmp_path / "n.pyz")
    )  # fmt: skip
    assert "smoke-skipped" in [d.code for d in result.diagnostics] and result.smoke is None
