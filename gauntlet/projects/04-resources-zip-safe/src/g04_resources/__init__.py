"""Gauntlet 04: package data accessed through importlib.resources."""
import ssl
from importlib.resources import files

import certifi


def main() -> int:
    text = files("g04_resources").joinpath("data/greeting.txt").read_text()
    assert text.strip() == "hello from a package resource", text

    # certifi.where() must return a path that exists on disk, because ssl needs a real file.
    ctx = ssl.create_default_context(cafile=certifi.where())
    assert ctx.cert_store_stats()["x509_ca"] > 0
    print("GAUNTLET OK 04-resources-zip-safe")
    return 0
