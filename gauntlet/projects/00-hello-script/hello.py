# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Gauntlet 00: the simplest possible program."""
import json
import sys


def main() -> int:
    payload = json.dumps({"hello": "world", "python": list(sys.version_info[:2])})
    assert json.loads(payload)["hello"] == "world"
    print("GAUNTLET OK 00-hello-script")
    return 0


if __name__ == "__main__":
    sys.exit(main())
