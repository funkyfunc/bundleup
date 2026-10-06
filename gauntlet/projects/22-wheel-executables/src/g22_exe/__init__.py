"""Gauntlet 22: a dependency's own executable must be shipped and found."""

import subprocess

from ruff.__main__ import find_ruff_bin


def main() -> int:
    exe = find_ruff_bin()
    out = subprocess.run([exe, "--version"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ruff 0.14.0"), out.stdout
    print("GAUNTLET OK 22-wheel-executables")
    return 0
