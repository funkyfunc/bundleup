"""Shared test setup: keep bundleup's caches out of the user's real cache directories."""

from __future__ import annotations

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
