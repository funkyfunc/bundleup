"""Gauntlet 17: syntax only Python 3.12+ can parse."""
from .generic import first, Pair


def main() -> int:
    pair: Pair[int] = (1, 2)
    assert first(pair) == 1
    names = ["a", "b"]
    assert f"{"-".join(names)}" == "a-b"  # PEP 701: reused quotes inside an f-string
    print("GAUNTLET OK 17-modern-syntax")
    return 0
