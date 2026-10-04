"""Gauntlet 10: native accelerators that are allowed to be missing."""
import charset_normalizer
import charset_normalizer.md
import yaml


def main() -> int:
    doc = yaml.safe_load("name: gauntlet\nitems: [1, 2, 3]\n")
    assert doc == {"name": "gauntlet", "items": [1, 2, 3]}, doc

    best = charset_normalizer.from_bytes("héllo wörld, ça va?".encode("utf-8")).best()
    assert best is not None and str(best) == "héllo wörld, ça va?"

    print(f"pyyaml libyaml={yaml.__with_libyaml__}")
    md_file = charset_normalizer.md.__file__ or ""
    print(f"charset_normalizer compiled={not md_file.endswith('.py')}")
    print("GAUNTLET OK 10-optional-accelerators")
    return 0
