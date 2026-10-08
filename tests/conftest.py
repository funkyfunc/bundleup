"""Shared test setup: keep bundleup's caches out of the user's real cache directories; a
private package index for tests that need a dependency without the network."""

from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_build_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    cache = tmp_path_factory.getbasetemp() / "build-cache"
    monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(cache))
    # Bundles a test runs with the inherited environment unpack here, not into the developer's
    # cache (the second review found 57 leftovers there). Tests that check the cache's location
    # pass their own environment.
    monkeypatch.setenv("BUNDLEUP_CACHE", str(tmp_path_factory.getbasetemp() / "unpacked"))
    return cache


WHEEL_FILES = {
    "acme_private/__init__.py": 'WHO = "the company index"\n',
    "acme_private/__main__.py": "import sys\nfrom acme_private import WHO\n"
    "print(WHO, sys.argv[1:])\n",
    "acme_private-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: acme-private\n"
    "Version: 1.0\n",
    "acme_private-1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\n"
    "Root-Is-Purelib: true\nTag: py3-none-any\n",
}


@pytest.fixture
def private_index(tmp_path: Path) -> str:
    """A flat index (a folder) holding one tiny wheel, `acme-private`, written by hand so no
    build backend or network is needed. Returns the PEP 723 lines that depend on it."""
    index = tmp_path / "index"
    index.mkdir()
    record = []
    with zipfile.ZipFile(index / "acme_private-1.0-py3-none-any.whl", "w") as zf:
        for name, text in WHEEL_FILES.items():
            data = text.encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
            record.append(f"{name},sha256={digest.decode()},{len(data)}")
            zf.writestr(name, data)
        record.append("acme_private-1.0.dist-info/RECORD,,")
        zf.writestr("acme_private-1.0.dist-info/RECORD", "\n".join(record) + "\n")
    return f"""\
# /// script
# requires-python = ">=3.9"
# dependencies = ["acme-private"]
# [[tool.uv.index]]
# name = "corp"
# url = "{index.as_posix()}"
# format = "flat"
# explicit = true
# [tool.uv.sources]
# acme-private = {{ index = "corp" }}
# ///
"""
