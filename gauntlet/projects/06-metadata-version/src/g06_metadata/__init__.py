"""Gauntlet 06: versions read from installed distribution metadata."""
from importlib.metadata import requires, version

# A common pattern: the package's own version comes from metadata at import time.
__version__ = version("g06-metadata")


def main() -> int:
    assert __version__ == "1.4.2", __version__
    click_version = version("click")
    assert int(click_version.split(".")[0]) >= 8, click_version
    assert any(r.startswith("click") for r in requires("g06-metadata") or [])
    print("GAUNTLET OK 06-metadata-version")
    return 0
