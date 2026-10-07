"""Target platforms for cross builds (ADR-0014): uv's names, CPU naming per OS, and wheel tags."""

from __future__ import annotations

import pytest

from bundleup import UsageError
from bundleup import _platforms as p
from bundleup._platforms import parse


@pytest.mark.parametrize(
    ("name", "sys_platform", "machine", "musl"),
    [
        ("linux", "linux", "x86_64", False),
        ("x86_64-manylinux_2_28", "linux", "x86_64", False),
        ("aarch64-unknown-linux-gnu", "linux", "aarch64", False),
        ("x86_64-unknown-linux-musl", "linux", "x86_64", True),
        ("macos", "darwin", "arm64", False),  # macOS calls aarch64 "arm64"
        ("x86_64-apple-darwin", "darwin", "x86_64", False),
        ("windows", "win32", "AMD64", False),  # Windows calls x86_64 "AMD64"
        ("aarch64-pc-windows-msvc", "win32", "ARM64", False),
    ],
)
def test_names(name: str, sys_platform: str, machine: str, musl: bool) -> None:
    platform = parse(name)
    assert (platform.sys_platform, platform.machine, platform.musl) == (sys_platform, machine, musl)
    assert platform.name == name  # passed to uv exactly as given


@pytest.mark.parametrize(
    "name", ["wasm32-pyodide2024", "aarch64-linux-android", "sparc-sun-solaris"]
)
def test_unsupported_names_are_usage_errors(name: str) -> None:
    with pytest.raises(UsageError) as e:
        parse(name)
    assert e.value.exit_code == 2 and "x86_64-manylinux_2_28" in (e.value.hint or "")


@pytest.mark.parametrize(
    ("name", "tag", "fits"),
    [
        ("linux", "py3-none-any", True),
        ("linux", "cp311-cp311-manylinux_2_17_x86_64", True),
        ("linux", "cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64", True),
        ("linux", "cp311-cp311-musllinux_1_2_x86_64", False),
        ("x86_64-unknown-linux-musl", "cp311-cp311-musllinux_1_2_x86_64", True),
        ("linux", "cp311-cp311-manylinux_2_17_aarch64", False),
        ("linux", "cp311-cp311-macosx_11_0_arm64", False),  # built on the host by mistake
        ("macos", "cp311-cp311-macosx_11_0_arm64", True),
        ("macos", "cp311-cp311-macosx_10_9_universal2", True),
        ("macos", "cp311-cp311-macosx_10_9_x86_64", False),
        ("windows", "cp311-cp311-win_amd64", True),
        ("windows", "cp311-cp311-win32", False),
        ("aarch64-pc-windows-msvc", "cp311-cp311-win_arm64", True),
    ],
)
def test_wheel_tags(name: str, tag: str, fits: bool) -> None:
    assert parse(name).accepts(tag) is fits


def test_markers() -> None:
    markers = parse("aarch64-apple-darwin").markers(python_full_version="3.11.9")
    assert markers["sys_platform"] == "darwin"
    assert markers["platform_system"] == "Darwin"
    assert markers["platform_machine"] == "arm64"
    assert markers["python_version"] == "3.11"
    assert markers["os_name"] == "posix"
    assert parse("windows").markers(python_full_version="3.12.1")["os_name"] == "nt"


def test_runtime_needs_take_the_strictest_wheel() -> None:
    needs = p.runtime_needs(
        [
            ["cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64"],  # needs glibc 2.17
            ["cp312-cp312-manylinux_2_28_x86_64"],
            ["py3-none-any"],
        ]
    )
    assert needs == p.RuntimeNeeds(libc=("glibc", (2, 28)))
    assert p.runtime_needs([["cp39-abi3-manylinux1_x86_64"]]).libc == ("glibc", (2, 5))
    assert p.runtime_needs([["cp312-cp312-musllinux_1_2_x86_64"]]).libc == ("musl", (1, 2))
    macos = p.runtime_needs(
        [["cp312-cp312-macosx_11_0_arm64"], ["cp38-abi3-macosx_10_9_universal2"]]
    )
    assert macos == p.RuntimeNeeds(macos=(11, 0))


@pytest.mark.parametrize(
    ("release", "macos"), [("19.6.0", (10, 15)), ("24.1.0", (15, 0)), ("25.6.0", (26, 0))]
)
def test_the_macos_version_from_darwins(
    monkeypatch: pytest.MonkeyPatch, release: str, macos: tuple[int, int]
) -> None:
    from bundleup import _loader

    class Uname:
        machine = "arm64"

    Uname.release = release  # type: ignore[attr-defined]  # a stand-in for os.uname()
    monkeypatch.setattr(_loader.os, "uname", lambda: Uname, raising=False)  # none on Windows
    assert _loader._macos() == macos


@pytest.mark.parametrize(
    ("version", "machine"),
    [
        ("3.12.10 (tags/v3.12.10) [MSC v.1943 64 bit (AMD64)]", "AMD64"),
        ("3.12.10 (tags/v3.12.10) [MSC v.1943 64 bit (ARM64)]", "ARM64"),
        ("3.12.10 (tags/v3.12.10) [MSC v.1943 32 bit (Intel)]", "x86"),
    ],
)
def test_the_windows_cpu_is_the_interpreters(
    monkeypatch: pytest.MonkeyPatch, version: str, machine: str
) -> None:
    from bundleup import _loader

    monkeypatch.setattr(_loader.sys, "platform", "win32")
    monkeypatch.setattr(_loader.sys, "version", version)
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "AMD64")  # what a 32-bit process sees on x64
    assert _loader._machine() == machine
