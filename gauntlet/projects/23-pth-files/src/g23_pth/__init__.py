"""Gauntlet 23: .pth files in the installed packages must be processed, as in a venv."""

import subprocess
import sys


def main() -> int:
    import distutils  # setuptools' copy, through distutils-precedence.pth's `import` line

    assert "setuptools" in distutils.__file__, distutils.__file__
    import g23_hidden  # a directory added by a path line in g23_extra.pth

    assert g23_hidden.FOUND
    child = subprocess.run(
        [sys.executable, "-c", "import g23_hidden"], capture_output=True, text=True
    )
    assert child.returncode == 0, child.stderr
    if sys.platform == "win32":
        import win32api  # pywin32.pth adds win32/ and win32/lib

        assert win32api.GetCurrentProcessId() > 0
    print("GAUNTLET OK 23-pth-files")
    return 0
