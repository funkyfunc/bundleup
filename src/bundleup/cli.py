"""Command-line entry point. Placeholder until the bundler exists."""

import sys

from . import __version__

MESSAGE = """\
bundleup {version}: pre-alpha, nothing to bundle yet.

bundleup will turn a locked Python project into one checked .pyz that runs on
plain Python with no install step.

Follow along: https://github.com/funkyfunc/bundleup
"""


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args in (["--version"], ["-V"]):
        print(f"bundleup {__version__}")
        return 0
    if not args or args[0] in ("-h", "--help"):
        print(MESSAGE.format(version=__version__))
        return 0
    print(MESSAGE.format(version=__version__), file=sys.stderr)
    return 2
