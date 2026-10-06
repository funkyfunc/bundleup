"""Shared test setup: keep bundleup's build cache out of the user's real cache directory."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_build_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    cache = tmp_path_factory.getbasetemp() / "build-cache"
    monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(cache))
    return cache
