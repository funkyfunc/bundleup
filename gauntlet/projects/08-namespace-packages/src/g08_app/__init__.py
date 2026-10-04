"""Gauntlet 08: a namespace package assembled from two distributions."""
import acme
from acme.core import base
from acme.extras import bonus


def main() -> int:
    assert not hasattr(acme, "__file__") or acme.__file__ is None, "acme should be a namespace package"
    assert base() + bonus() == 42
    print("GAUNTLET OK 08-namespace-packages")
    return 0
