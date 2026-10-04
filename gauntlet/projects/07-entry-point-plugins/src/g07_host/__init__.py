"""Gauntlet 07: plugin discovery via entry points."""
import sys
from importlib.metadata import entry_points

GROUP = "g07.plugins"


def discover():
    if sys.version_info >= (3, 10):
        eps = entry_points(group=GROUP)
    else:
        eps = entry_points().get(GROUP, [])
    return {ep.name: ep.load() for ep in eps}


def main() -> int:
    plugins = discover()
    assert "shout" in plugins, f"no plugins discovered: {sorted(plugins)}"
    assert plugins["shout"]("gauntlet") == "GAUNTLET!"
    print("GAUNTLET OK 07-entry-point-plugins")
    return 0
