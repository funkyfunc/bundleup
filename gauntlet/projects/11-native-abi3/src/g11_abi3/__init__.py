"""Gauntlet 11: an abi3 native extension (cryptography)."""
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes


def main() -> int:
    f = Fernet(Fernet.generate_key())
    assert f.decrypt(f.encrypt(b"gauntlet")) == b"gauntlet"

    digest = hashes.Hash(hashes.SHA256())
    digest.update(b"gauntlet")
    assert len(digest.finalize()) == 32
    print("GAUNTLET OK 11-native-abi3")
    return 0
