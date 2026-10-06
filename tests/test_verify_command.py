"""`bundleup verify`: the embedded manifest catches every kind of change, in the bundle file and in
its unpacked copy (docs/testing-strategy.md "What correct means")."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import jsonschema
import pytest

import bundleup
from bundleup import _cli

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "docs" / "schema" / "verify-v1.json").read_text())
SCRIPT = """# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json
print(json.dumps({"ok": True}))
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh cache location for both the bundle and `verify` (they must agree on it)."""
    cache = tmp_path / "cache"
    monkeypatch.setenv("BUNDLEUP_CACHE", str(cache))
    return cache


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    script = tmp_path / "app.py"
    script.write_text(SCRIPT)
    out = tmp_path / "app.pyz"
    assert _cli.main(["build", str(script), "-o", str(out), "-q"]) == 0
    return out


def run(bundle: Path) -> None:
    subprocess.run([sys.executable, str(bundle)], check=True, capture_output=True, env=os.environ)


def test_fresh_bundle_matches(bundle: Path, home: Path) -> None:
    report = bundleup.verify(bundle)
    assert report.ok and report.cache is None and report.files > 0


def test_unpacked_copy_matches_after_running(bundle: Path, home: Path) -> None:
    run(bundle)
    report = bundleup.verify(bundle)
    assert report.ok and report.cache is not None and report.cache.parent == home


def test_tampered_unpacked_copy_is_caught(bundle: Path, home: Path) -> None:
    run(bundle)
    script = next(home.glob("*/__bundleup_script__/app.py"))
    script.write_text(script.read_text() + "print('tampered')\n")
    report = bundleup.verify(bundle)
    assert not report.ok
    assert report.cache_problems == ["changed file: __bundleup_script__/app.py"]


def test_extra_file_in_unpacked_copy_is_caught(bundle: Path, home: Path) -> None:
    run(bundle)
    [unpacked] = [p for p in home.iterdir() if p.is_dir() and not p.name.startswith(".")]
    (unpacked / "planted.py").write_text("import os\n")
    assert bundleup.verify(bundle).cache_problems == [
        "extra file: planted.py isn't in the manifest"
    ]


def test_changed_payload_is_caught(bundle: Path, home: Path, tmp_path: Path) -> None:
    """A payload swapped for a different, valid one: its hash no longer matches the manifest."""
    with zipfile.ZipFile(bundle) as zf:
        entries = {name: zf.read(name) for name in zf.namelist()}
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("__bundleup_script__/app.py", "print('not the original')\n")
    entries["payload.zip"] = other.read_bytes()
    swapped = tmp_path / "swapped.pyz"
    with zipfile.ZipFile(swapped, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    assert bundleup.verify(swapped).problems == [
        "changed file: payload.zip doesn't match its recorded hash"
    ]


def corrupt(bundle: Path, member: str, out: Path) -> Path:
    """A copy of `bundle` with one byte flipped in the middle of `member`'s stored data."""
    with zipfile.ZipFile(bundle) as zf:
        info = zf.getinfo(member)
    data = bytearray(bundle.read_bytes())
    header = info.header_offset
    name_len = int.from_bytes(data[header + 26 : header + 28], "little")
    extra_len = int.from_bytes(data[header + 28 : header + 30], "little")
    data[header + 30 + name_len + extra_len + info.compress_size // 2] ^= 0xFF
    out.write_bytes(bytes(data))
    return out


def test_corrupted_payload_is_caught(bundle: Path, home: Path, tmp_path: Path) -> None:
    corrupted = corrupt(bundle, "payload.zip", tmp_path / "corrupted.pyz")
    [problem] = bundleup.verify(corrupted).problems
    assert problem.startswith("corrupted: payload.zip can't be read")


def test_changed_loader_is_caught(bundle: Path, home: Path, tmp_path: Path) -> None:
    """The loader runs first on every start, so tampering with it must be caught too."""
    corrupted = corrupt(bundle, "__main__.py", tmp_path / "loader.pyz")
    [problem] = bundleup.verify(corrupted).problems
    assert problem.startswith("corrupted: __main__.py can't be read")


def test_not_a_bundle(tmp_path: Path) -> None:
    other = tmp_path / "other.pyz"
    other.write_text("hello")
    with pytest.raises(bundleup.NotABundleError) as e:
        bundleup.verify(other)
    assert e.value.code == "not-a-bundle"


def test_cli_exit_codes_and_json(
    bundle: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cli.main(["verify", str(bundle), "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    jsonschema.validate(document, SCHEMA)
    run(bundle)
    script = next(home.glob("*/__bundleup_script__/app.py"))
    script.write_text("print('tampered')\n")
    assert _cli.main(["verify", str(bundle), "--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    jsonschema.validate(document, SCHEMA)
    assert [d["code"] for d in document["diagnostics"]] == ["cache-mismatch"]
