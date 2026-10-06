"""The lock-vs-bundle and RECORD checks must catch each kind of mismatch (testing-strategy.md)."""

from __future__ import annotations

from pathlib import Path

from bundleup import _build as b
from bundleup import _verify as v

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
    assert b.launchers(site) == {"bin/tool", "bin/tool.exe"}


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


def test_record_hash_format() -> None:
    # The format wheels use: urlsafe base64 of the sha256 digest, without "=" padding.
    assert v.record_hash(b"") == "sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"
