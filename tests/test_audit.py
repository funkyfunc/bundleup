"""`check --audit`: supply-chain checks on the locked packages, against PyPI's answers (faked here,
so the tests need no network)."""

from __future__ import annotations

import io
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from bundleup import _audit
from bundleup._audit import Locked

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
OLD = "2020-01-01T00:00:00Z"
RECENT = (NOW - timedelta(days=10)).isoformat().replace("+00:00", "Z")

PYLOCK = """\
lock-version = "1.0"
[[packages]]
name = "Requests"
version = "2.19.0"
index = "https://pypi.org/simple"
[[packages]]
name = "acme-private"
version = "1.0"
index = "https://artifactory.example.com/simple"
[[packages]]
name = "colorama"
version = "0.4.6"
wheels = [{ url = "https://files.pythonhosted.org/packages/x/colorama-0.4.6-py3-none-any.whl" }]
[[packages]]
name = "app"
directory = { path = "." }
"""


def fake_pypi(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]) -> None:
    """PyPI's JSON API, as a dict of URL suffix -> response (an exception is raised)."""

    def get(url: str) -> dict[str, Any]:  # Any: JSON
        answer = answers[url.removeprefix(_audit.PYPI + "/")]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(_audit, "_get", get)


def release(
    *, uploaded: str = OLD, vulns: list[dict[str, Any]] | None = None, yanked: bool = False
) -> dict[str, Any]:
    return {
        "urls": [{"upload_time_iso_8601": uploaded, "yanked": yanked, "yanked_reason": "broken"}],
        "vulnerabilities": vulns or [],
    }


def test_only_packages_from_pypi_are_audited() -> None:
    found = _audit.from_pypi(PYLOCK, {"requests", "acme-private", "colorama", "app"})
    assert found == [Locked("Requests", "2.19.0"), Locked("colorama", "0.4.6")]
    assert _audit.from_pypi(PYLOCK, {"colorama"}) == [Locked("colorama", "0.4.6")]


def test_vulnerable_yanked_new_missing_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    vuln = {"id": "PYSEC-1", "fixed_in": ["2.20.0"], "withdrawn": None}
    withdrawn = {"id": "PYSEC-2", "fixed_in": ["9"], "withdrawn": "2025-01-01"}
    fake_pypi(
        monkeypatch,
        {
            "old-bad/1.0/json": release(vulns=[vuln, withdrawn]),
            "pulled/1.0/json": release(yanked=True),
            "fresh/0.1/json": release(uploaded=RECENT),
            "fresh/json": {"releases": {"0.1": [{"upload_time_iso_8601": RECENT}]}},
            "busy/9.0/json": release(uploaded=RECENT),  # a new version of an old project
            "busy/json": {"releases": {"1.0": [{"upload_time_iso_8601": OLD}]}},
            "gone/1.0/json": urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO()),  # type: ignore[arg-type]  # headers unused
            "down/1.0/json": OSError("network unreachable"),
        },
    )
    names = ["old-bad", "pulled", "busy", "gone", "down"]
    packages = [Locked(n, "1.0") for n in names[:2]] + [Locked("fresh", "0.1")]
    packages += [Locked("busy", "9.0")] + [Locked(n, "1.0") for n in names[3:]]
    diags = {(d.code, d.package): d for d in _audit.audit(packages, now=NOW)}
    assert sorted(diags) == [
        ("audit-incomplete", None),
        ("new-project", "fresh"),
        ("not-on-pypi", "gone"),
        ("vulnerable", "old-bad"),
        ("yanked", "pulled"),
    ]
    vulnerable = diags[("vulnerable", "old-bad")]
    assert "1 known vulnerability: PYSEC-1" in vulnerable.message  # the withdrawn one doesn't count
    assert vulnerable.hint is not None and "fixed in 2.20.0" in vulnerable.hint
    assert "yanked from PyPI: broken" in diags[("yanked", "pulled")].message
    assert "1 of 6 packages (down)" in diags[("audit-incomplete", None)].message
