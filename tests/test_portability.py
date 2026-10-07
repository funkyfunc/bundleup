"""Which OSes and CPUs a pure-Python bundle runs on (ADR-0034), from the lock's markers."""

from __future__ import annotations

from pathlib import Path

from bundleup._payload import portability
from bundleup._platforms import parse
from bundleup._python import Portability, PythonRange, Target

LINUX = parse("x86_64-unknown-linux-gnu")
TARGET = Target(
    executable="python3.12",
    version=(3, 12),
    full_version="3.12.0",
    platform="linux",
    machine="x86_64",
    abiflags="",
    implementation="cpython",
    cache_tag="cpython-312",
    markers=LINUX.markers(python_full_version="3.12.0"),
)
HEAD = 'lock-version = "1.0"\ncreated-by = "test"\n'
PURE = '\n[[packages]]\nname = "pure"\nversion = "1.0"\n'


def reach(tmp_path: Path, extra: str, *, native: bool = False) -> Portability:
    lock = tmp_path / "pylock.toml"
    lock.write_text(HEAD + PURE + extra)
    return portability(lock, target=TARGET, pythons=PythonRange((3, 10), None), native=native)


def test_the_same_packages_everywhere_runs_anywhere(tmp_path: Path) -> None:
    assert reach(tmp_path, "") == Portability(any_os=True, any_cpu=True)
    assert reach(tmp_path, "", native=True) == Portability()  # compiled code: never


def test_an_os_marker_ties_it_to_its_os(tmp_path: Path) -> None:
    windows_only = '\n[[packages]]\nname = "colorama"\nversion = "0.4.6"\n'
    windows_only += "marker = \"sys_platform == 'win32'\"\n"
    assert reach(tmp_path, windows_only) == Portability(any_os=False, any_cpu=True)


def test_a_cpu_marker_ties_it_to_its_cpu(tmp_path: Path) -> None:
    arm_only = '\n[[packages]]\nname = "armstuff"\nversion = "1"\n'
    arm_only += "marker = \"platform_machine == 'aarch64'\"\n"
    assert reach(tmp_path, arm_only) == Portability(any_os=False, any_cpu=False)


def test_a_marker_on_one_python_version_in_the_range_counts(tmp_path: Path) -> None:
    old_windows = '\n[[packages]]\nname = "colorama"\nversion = "0.4.6"\n'
    old_windows += "marker = \"python_version == '3.11' and sys_platform == 'win32'\"\n"
    assert reach(tmp_path, old_windows).any_os is False
