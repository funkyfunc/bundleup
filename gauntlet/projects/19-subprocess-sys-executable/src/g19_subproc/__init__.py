"""Gauntlet 19: a child interpreter must see the same dependencies."""
import subprocess
import sys


def main() -> int:
    out = subprocess.run(
        [sys.executable, "-c", "import click, g19_subproc; print('child', click.__name__)"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "child click", out.stdout
    print("GAUNTLET OK 19-subprocess-sys-executable")
    return 0
