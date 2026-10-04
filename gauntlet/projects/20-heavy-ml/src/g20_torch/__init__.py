"""Gauntlet 20: PyTorch on CPU."""
import torch


def main() -> int:
    x = torch.arange(6, dtype=torch.float32).reshape(2, 3)
    assert torch.allclose((x @ x.T).sum(), torch.tensor(83.0))
    print("GAUNTLET OK 20-heavy-ml")
    return 0
