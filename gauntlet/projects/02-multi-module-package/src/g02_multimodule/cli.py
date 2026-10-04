from .core import compute
from .core.format import render


def main() -> int:
    result = compute.total([1, 2, 3, 4])
    assert result == 10, result
    assert render(result) == "total=10"
    print("GAUNTLET OK 02-multi-module-package")
    return 0
