"""Gauntlet 13: native code with vendored shared libraries (NumPy + OpenBLAS)."""
import numpy as np


def main() -> int:
    a = np.arange(9, dtype=float).reshape(3, 3) + np.eye(3)
    inv = np.linalg.inv(a)  # goes through the bundled BLAS/LAPACK
    assert np.allclose(a @ inv, np.eye(3))
    print("GAUNTLET OK 13-native-bundled-libs")
    return 0
