"""The lock-vs-bundle and RECORD checks must catch each kind of mismatch (testing-strategy.md)."""

from __future__ import annotations

from pathlib import Path

from bundleup import _verify as v
from bundleup._uv import launchers

MAC_312 = {
    "implementation_name": "cpython",
    "python_full_version": "3.12.4",
    "python_version": "3.12",
    "sys_platform": "darwin",
    "platform_system": "Darwin",
    "platform_machine": "arm64",
    "os_name": "posix",
}
PYLOCK = """
lock-version = "1.0"
[[packages]]
name = "my-app"
directory = { path = "." }
[[packages]]
name = "Click"
version = "8.1.8"
marker = "python_full_version < '3.10'"
[[packages]]
name = "click"
version = "8.5.0"
marker = "python_full_version >= '3.10'"
[[packages]]
name = "colorama"
version = "0.4.6"
marker = "sys_platform == 'win32'"
[[packages]]
name = "charset_normalizer"
version = "3.4.0"
"""


def dist(name: str, version: str) -> v.InstalledDistribution:
    return v.InstalledDistribution(name, version, f"{name}-{version}.dist-info")


def test_markers_select_the_packages_for_the_target() -> None:
    locked = v.locked_packages(PYLOCK, MAC_312)
    assert locked == [
        v.LockedPackage("my-app", None),
        v.LockedPackage("click", "8.5.0"),
        v.LockedPackage("charset-normalizer", "3.4.0"),
    ]


def test_matching_install_has_no_problems() -> None:
    locked = v.locked_packages(PYLOCK, MAC_312)
    installed = [dist("my-app", "0.1.0"), dist("click", "8.5.0"), dist("charset-normalizer", "3.4")]
    assert v.check_lock(locked, installed) == []  # 3.4 == 3.4.0 as versions


def test_lock_problems_are_each_reported() -> None:
    locked = v.locked_packages(PYLOCK, MAC_312)
    installed = [dist("click", "8.1.8"), dist("colorama", "0.4.6"), dist("my-app", "0.1.0")]
    assert v.check_lock(locked, installed) == [
        "missing: charset-normalizer==3.4.0 is locked but not in the bundle",
        "wrong version: click==8.5.0 is locked, 8.1.8 is bundled",
        "extra: colorama==0.4.6 is bundled but not locked",
    ]


def test_duplicate_distributions_are_reported() -> None:
    locked = [v.LockedPackage("click", "8.5.0")]
    problems = v.check_lock(locked, [dist("click", "8.5.0"), dist("click", "8.1.8")])
    assert problems == ["click is installed more than once (8.5.0, 8.1.8)"]


def test_installed_distributions_reads_metadata(tmp_path: Path) -> None:
    info = tmp_path / "Click-8.5.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: Click\nVersion: 8.5.0\n\nName: no")
    expected = v.InstalledDistribution("click", "8.5.0", "Click-8.5.0.dist-info")
    assert v.installed_distributions(tmp_path) == [expected]  # name canonical, body ignored


def make_site(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, dict[str, str]]:
    """A site directory with one distribution whose RECORD lists `files` with correct hashes."""
    site = tmp_path / "site"
    rows = []
    for rel, data in files.items():
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_bytes(data)
        rows.append(f"{rel},{v.record_hash(data)},{len(data)}")
    rows.append("pkg-1.0.dist-info/RECORD,,")
    (site / "pkg-1.0.dist-info").mkdir(parents=True, exist_ok=True)
    (site / "pkg-1.0.dist-info" / "RECORD").write_text("\n".join(rows) + "\n")
    written = {rel: v.record_hash(data) for rel, data in files.items()}
    written["pkg-1.0.dist-info/RECORD"] = v.record_hash(b"")
    return site, written


def test_records_match(tmp_path: Path) -> None:
    site, written = make_site(tmp_path, {"pkg/__init__.py": b"x = 1\n", "bin/tool": b"#!py\n"})
    del written["bin/tool"]  # bundleup removes console-script launchers on purpose
    written["pkg/__pycache__/__init__.cpython-312.pyc"] = ""  # and adds compiled bytecode
    written["__bundleup_script__/app.py"] = v.record_hash(b"print(1)")  # and a PEP 723 script
    assert v.check_records(site, written, removed={"bin/tool"}) == []
    # Anything else in bin/ is something the wheel ships (ruff's binary): it must be there.
    assert v.check_records(site, written) == ["missing file: bin/tool (from pkg-1.0.dist-info)"]


def test_only_launchers_are_removed(tmp_path: Path) -> None:
    files = {
        "bin/tool": b"#!py\n",
        "bin/tool.exe": b"MZ",
        "bin/engine": b"\x7fELF",
        "pkg/a.py": b"",
    }
    site, _written = make_site(tmp_path, files)
    entry_points = "[console_scripts]\ntool = pkg.a:main\n"
    (site / "pkg-1.0.dist-info" / "entry_points.txt").write_text(entry_points)
    assert launchers(site) == {"bin/tool", "bin/tool.exe"}


def test_record_problems_are_each_reported(tmp_path: Path) -> None:
    site, written = make_site(tmp_path, {"pkg/a.py": b"a", "pkg/b.py": b"b"})
    del written["pkg/a.py"]
    written["pkg/b.py"] = v.record_hash(b"tampered")
    written["pkg/stray.py"] = v.record_hash(b"?")
    assert v.check_records(site, written) == [
        "missing file: pkg/a.py (from pkg-1.0.dist-info)",
        "changed file: pkg/b.py differs from pkg-1.0.dist-info/RECORD",
        "extra file: pkg/stray.py isn't listed in any wheel's RECORD",
    ]


def test_record_paths_with_backslashes_are_accepted(tmp_path: Path) -> None:
    # ormsgpack 1.12.2's Windows wheels write RECORD paths with backslashes; pip and uv accept it.
    site, written = make_site(tmp_path, {"pkg/a.py": b"a"})
    record = site / "pkg-1.0.dist-info" / "RECORD"
    record.write_text(record.read_text().replace("pkg/a.py", "pkg\\a.py"))
    assert v.check_records(site, written) == []


def test_record_hash_format() -> None:
    # The format wheels use: urlsafe base64 of the sha256 digest, without "=" padding.
    assert v.record_hash(b"") == "sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"


def test_a_long_shebang_is_not_mistaken_for_an_executable(tmp_path: Path) -> None:
    """Ninth review: a .pyz with a >64-byte shebang (e.g. Nix store) shifts the first zip entry's
    header_offset past 64 bytes, which _is_exe used to treat as a damaged `--format exe`."""
    from bundleup import BuildOptions, build

    script = tmp_path / "app.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('ok')\n")
    pyz = build(BuildOptions(path=script, output=tmp_path / "app.pyz")).output
    raw = pyz.read_bytes()
    nix_shebang = b"#!/nix/store/00000000000000000000000000000000-python3-3.12.0/bin/python3\n"
    pyz.write_bytes(nix_shebang + raw[raw.index(b"\n") + 1 :])
    report = v.verify(pyz)
    assert report.ok, report.problems


def test_dir_and_cache_checks_report_symlinks_and_unreadable_files(
    tmp_path: Path, capsys: object
) -> None:
    """Ninth review: symlinks and unreadable files in a `dir` bundle or cache are reported as
    verification problems rather than ignored or crashing with PermissionError."""
    import os
    import sys

    from bundleup import BuildOptions, _cli, build

    script = tmp_path / "app.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('ok')\n")
    out = build(BuildOptions(path=script, output=tmp_path / "dir_out", format="dir")).output
    assert _cli.main(["verify", str(out)]) == 0
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "Verified" in err and "unpacked copy" not in err

    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    try:
        (out / "stray_link").symlink_to(outside)
    except OSError:
        return  # Windows without symlink privileges
    assert "extra file: stray_link isn't in the manifest" in v.verify(out).problems
    (out / "stray_link").unlink()

    target = out / "app.py"
    saved = target.read_bytes()
    target.unlink()
    target.symlink_to(outside)
    assert "changed file: app.py" in v.verify(out).problems
    target.unlink()
    target.write_bytes(saved)

    if sys.platform != "win32" and os.geteuid() != 0:
        target.chmod(0o000)
        try:
            problems = v.verify(out).problems
            assert any(p.startswith("corrupted: app.py can't be read") for p in problems)
        finally:
            target.chmod(0o644)


def test_walk_dir_handles_fifos_unreadable_dirs_and_malformed_manifests(
    tmp_path: Path, capsys: object
) -> None:
    """Tenth review: FIFOs inside a directory bundle or cache never block read_bytes(), unreadable
    subdirectories are reported, non-object JSON manifests raise BundleTamperedError, and lambda
    zips don't print 'unpacked copy: not unpacked on this machine'."""
    import os
    import sys

    import pytest

    from bundleup import BuildOptions, _cli, build
    from bundleup._errors import NotABundleError

    script = tmp_path / "app.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('ok')\n")
    out = build(BuildOptions(path=script, output=tmp_path / "dir_out", format="dir")).output

    if hasattr(os, "mkfifo") and sys.platform != "win32":
        fifo = out / "pipe.fifo"
        os.mkfifo(fifo)
        try:
            problems = v.verify(out).problems
            assert "extra file: pipe.fifo isn't in the manifest" in problems
        finally:
            fifo.unlink()
        app_py = out / "app.py"
        saved = app_py.read_bytes()
        app_py.unlink()
        os.mkfifo(app_py)
        try:
            problems = v.verify(out).problems
            assert any(p.startswith("changed file: app.py") for p in problems)
        finally:
            app_py.unlink()
            app_py.write_bytes(saved)

    if sys.platform != "win32" and os.geteuid() != 0:
        sub = out / "unreadable_dir"
        sub.mkdir()
        (sub / "hidden.py").write_text("x = 1\n")
        sub.chmod(0o000)
        try:
            problems = v.verify(out).problems
            assert any("unreadable_dir can't be read" in p for p in problems)
        finally:
            sub.chmod(0o755)
            (sub / "hidden.py").unlink()
            sub.rmdir()

    bad_dir = tmp_path / "bad_manifest"
    bad_dir.mkdir()
    (bad_dir / "bundleup-manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(NotABundleError, match="incomplete"):
        v.verify(bad_dir)
    (bad_dir / "bundleup-manifest.json").write_text('{"layers": []}', encoding="utf-8")
    with pytest.raises(NotABundleError, match="incomplete"):
        v.verify(bad_dir)

    lam = build(
        BuildOptions(
            path=script,
            output=tmp_path / "fn.zip",
            format="zip",
            python_platform="x86_64-manylinux_2_34",
        )
    ).output
    assert _cli.main(["verify", str(lam)]) == 0
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "Verified" in err and "unpacked copy" not in err


def test_eleventh_review_corrupted_deflate_and_malformed_manifest_types(
    tmp_path: Path,
) -> None:
    """Eleventh review: corrupted deflate streams in zips report a verification problem instead
    of raising raw zlib.error, and malformed manifest field types raise NotABundleError."""
    import zipfile

    import pytest

    from bundleup import BuildOptions, build
    from bundleup._errors import NotABundleError

    script = tmp_path / "app.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('ok' * 100)\n")
    lam = build(
        BuildOptions(
            path=script,
            output=tmp_path / "corrupt_fn.zip",
            format="zip",
            python_platform="x86_64-manylinux_2_34",
        )
    ).output
    raw = bytearray(lam.read_bytes())
    # Corrupt deflate payload bytes inside the zip so zf.read() raises zlib.error / BadZipFile
    with zipfile.ZipFile(lam) as zf:
        info = zf.getinfo("app.py")
        offset = info.header_offset + 30 + len(info.filename) + len(info.extra)
    raw[offset : offset + 8] = b"\xff" * 8
    corrupted = tmp_path / "corrupted.zip"
    corrupted.write_bytes(raw)
    report = v.verify(corrupted)
    assert not report.ok

    bad_dir = tmp_path / "bad_types"
    bad_dir.mkdir()
    (bad_dir / "bundleup-manifest.json").write_text(
        '{"name": "a", "format": "dir", "files": {"x": 123}}', encoding="utf-8"
    )
    with pytest.raises(NotABundleError, match="incomplete"):
        v.verify(bad_dir)

    bad_zip = tmp_path / "bad_manifest.pyz"
    for bad_json in (
        '{"name": "a", "format": "pyz", "loader": [], "payload": {"sha256": "abc"}, "files": {}}',
        '{"name": "a", "format": "pyz", "loader": {"sha256": "abc"}, "payload": {}}',
        '{"name": "a", "format": "pyz", "loader": {"sha256": "abc"}, "payloads": [123]}',
        '{"name": "a", "format": "zip", "files": ["not-a-dict"]}',
    ):
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("manifest.json", bad_json)
        with pytest.raises(NotABundleError, match="incomplete"):
            v.verify(bad_zip)


def test_phase3_exe_trailer_precompiled_and_verify_exe(tmp_path: Path, monkeypatch: object) -> None:
    """Phase 3 audit: `_exe._jump_trailer` rejects short/corrupt jump binaries, `_exe.precompiled`
    rejects corrupt cached tarballs and normalizes read-only directory entries with trailing
    slashes, and `_verify._check_exe` detects trailing garbage between the embedded .pyz EOCD
    and the scie trailer."""
    import hashlib
    import io
    import json
    import struct
    import sys
    import tarfile
    import zipfile

    import pytest

    from bundleup import BuildOptions, _exe, _python, build
    from bundleup._errors import BundleupError

    assert isinstance(monkeypatch, pytest.MonkeyPatch)

    # 1. _jump_trailer rejects short or invalid UTF-8 jump files
    short_jump = tmp_path / "short_jump"
    short_jump.write_bytes(b"short")
    with pytest.raises(BundleupError, match="isn't a scie-jump launcher"):
        _exe._jump_trailer(short_jump)
    bad_utf8 = tmp_path / "bad_utf8_jump"
    bad_utf8.write_bytes(
        b"x" * 20 + b"\xff\xff\xff\xff" + struct.pack("<BII", 4, 33, _exe.JUMP_MAGIC)
    )
    with pytest.raises(BundleupError, match="isn't a scie-jump launcher"):
        _exe._jump_trailer(bad_utf8)

    # 2. precompiled() rejects corrupt tarballs, fixes 0o555 dir modes, and deduplicates dir/
    ver = sys.version_info[:2]
    target = _python.Target(
        executable=sys.executable,
        version=ver,
        full_version=f"{ver[0]}.{ver[1]}.0",
        platform="linux",
        machine="x86_64",
        abiflags="",
        implementation="cpython",
        cache_tag=sys.implementation.cache_tag,
        markers={},
    )
    corrupt_tar = tmp_path / "corrupt.tar.gz"
    corrupt_tar.write_bytes(b"not a gzip archive")
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(BundleupError, match="corrupted"):
        _exe.precompiled(corrupt_tar, target, stage)

    valid_tar = tmp_path / "valid.tar.gz"
    lib_dir = f"python/lib/python{ver[0]}.{ver[1]}/"
    with tarfile.open(valid_tar, "w:gz") as tf:
        for dname in ("python/", "python/lib/", lib_dir):
            ti = tarfile.TarInfo(dname)
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o555
            tf.addfile(ti)
        fi = tarfile.TarInfo(f"{lib_dir}os.py")
        data = b"x = 1\n"
        fi.size = len(data)
        fi.mode = 0o444
        tf.addfile(fi, io.BytesIO(data))
    out_tar = _exe.precompiled(valid_tar, target, stage)
    with tarfile.open(out_tar, "r:gz") as tf:
        members = tf.getmembers()
        dir_modes = [m.mode for m in members if m.isdir()]
        assert all(m & 0o700 == 0o700 for m in dir_modes)
        names = [m.name.rstrip("/") for m in members]
        assert len(names) == len(set(names))

    # 3. _check_exe detects trailing bytes appended after app.pyz EOCD before the scie trailer
    script = tmp_path / "app.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('ok')\n")
    pyz = build(BuildOptions(path=script, output=tmp_path / "app.pyz")).output
    pyz_bytes = pyz.read_bytes()
    jump = b"\x7fELF" + b"\x00" * 16 + b"1.9.0" + struct.pack("<BII", 5, 34, _exe.JUMP_MAGIC)
    jump_digest = hashlib.sha256(jump).hexdigest()
    monkeypatch.setitem(_exe.JUMPS, ("linux", "x86_64"), ("scie-jump-linux-x86_64", jump_digest))
    py_tar = b"fake-python-tar"
    app_with_junk = pyz_bytes + b"SMUGGLED_GARBAGE"
    lift = {
        "scie": {
            "jump": {
                "size": len(jump),
                "version": "1.9.0",
                "hash": jump_digest,
            },
            "lift": {
                "name": "app",
                "files": [
                    {
                        "name": "python.tar.gz",
                        "key": "python",
                        "size": len(py_tar),
                        "hash": hashlib.sha256(py_tar).hexdigest(),
                    },
                    {
                        "name": "app.pyz",
                        "key": "app",
                        "size": len(app_with_junk),
                        "hash": hashlib.sha256(app_with_junk).hexdigest(),
                    },
                ],
                "boot": {
                    "commands": {
                        "": {
                            "exe": "{python}/python/bin/python3",
                            "args": ["{app}"],
                            "env": v.EXPECTED_EXE_ENV,
                        }
                    }
                },
            },
        }
    }
    fake_exe = tmp_path / "fake_exe"
    fake_exe.write_bytes(jump + py_tar + app_with_junk + b"\n" + json.dumps(lift).encode() + b"\n")
    with zipfile.ZipFile(fake_exe) as outer:
        assert v._check_exe(fake_exe, outer) == [
            "corrupted: fake_exe has trailing data after the zip archive"
        ]
