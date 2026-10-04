"""Gauntlet 16: worker processes started with spawn."""
import multiprocessing

from .work import square


def main() -> int:
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(2) as pool:
        results = pool.map(square, range(5))
    assert results == [0, 1, 4, 9, 16], results
    print("GAUNTLET OK 16-multiprocessing-spawn")
    return 0
