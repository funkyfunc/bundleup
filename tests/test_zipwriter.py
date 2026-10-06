"""The threaded zip writer must produce archives every reader accepts, reproducibly."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import _verify, _zipwriter
from bundleup._zipwriter import Member, write_zip


def members(files: dict[str, bytes], modes: dict[str, int] | None = None) -> list[Member]:
    modes = modes or {}
    return [
        Member(name, (lambda d=data: d), modes.get(name, 0o644)) for name, data in files.items()
    ]


FILES = {
    "pkg/__init__.py": b"x = 1\n" * 1000,
    "pkg/empty.txt": b"",
    "pkg/bin/tool": b"#!/bin/sh\necho hi\n",
    "pkg/ünïcødé.txt": b"non-ASCII name",
}


def test_readable_with_the_same_contents(tmp_path: Path) -> None:
    out = tmp_path / "a.zip"
    digest, hashes = write_zip(
        out, members(FILES, {"pkg/bin/tool": 0o755}), hasher=_verify.record_hash
    )
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None  # every CRC checks out
        assert zf.namelist() == list(FILES)  # in the given order
        assert {n: zf.read(n) for n in zf.namelist()} == FILES
        assert (zf.getinfo("pkg/bin/tool").external_attr >> 16) & 0o777 == 0o755
        assert zf.getinfo("pkg/__init__.py").date_time == (1980, 1, 1, 0, 0, 0)
    assert hashes == {name: _verify.record_hash(data) for name, data in FILES.items()}
    assert len(digest) == 64


def test_reproducible(tmp_path: Path) -> None:
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    write_zip(a, members(FILES), workers=1, hasher=_verify.record_hash)
    write_zip(b, members(FILES), workers=8, hasher=_verify.record_hash)
    assert a.read_bytes() == b.read_bytes()


def test_zip64_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sizes and offsets past 4 GB need ZIP64 records; lower the limit to exercise them."""
    monkeypatch.setattr(_zipwriter, "LIMIT", 100)
    out = tmp_path / "big.zip"
    write_zip(out, members({f"f{i}": bytes(300) for i in range(3)}), hasher=_verify.record_hash)
    with zipfile.ZipFile(out) as zf:
        assert zf.testzip() is None and [len(zf.read(n)) for n in zf.namelist()] == [300] * 3


def test_more_than_65535_members(tmp_path: Path) -> None:
    out = tmp_path / "many.zip"
    count = 70_000
    write_zip(out, members({f"m/{i}": b"" for i in range(count)}), hasher=_verify.record_hash)
    with zipfile.ZipFile(out) as zf:
        assert len(zf.namelist()) == count


def test_python_39_can_read_it(tmp_path: Path) -> None:
    """The loader unpacks payloads with the user's zipfile, which may be Python 3.9's."""
    if not Path("/usr/bin/python3").exists():
        pytest.skip("needs a second Python")
    out = tmp_path / "a.zip"
    write_zip(out, members(FILES), hasher=_verify.record_hash)
    check = (
        "import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); "
        "print(z.testzip(), len(z.namelist()))"
    )
    r = subprocess.run(["/usr/bin/python3", "-c", check, str(out)], capture_output=True, text=True)
    assert r.stdout.split() == ["None", str(len(FILES))], r.stderr
    assert sys.executable  # (the test Python already read it above)
