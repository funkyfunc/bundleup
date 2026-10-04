"""Gauntlet 18: a source-only dependency (docopt).

Usage:
  g18 ship [--speed=<kn>]
"""
from docopt import docopt


def main() -> int:
    args = docopt(__doc__)
    assert args["ship"] is True and args["--speed"] == "10", args
    print("GAUNTLET OK 18-sdist-only-dep")
    return 0
