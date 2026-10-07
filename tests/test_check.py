"""The analysis behind `bundleup check` (ADR-0024), on hand-made payloads."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from bundleup import _bytecode
from bundleup import _check as c
from bundleup._python import Target
from bundleup._verify import record_hash

TARGET = Target(
    executable=sys.executable,
    version=(sys.version_info.major, sys.version_info.minor),
    full_version=platform.python_version(),
    platform=sys.platform,
    machine=platform.machine(),
    abiflags=None,
    implementation=sys.implementation.name,
    cache_tag=sys.implementation.cache_tag or "",
    markers={},
)


def install(site: Path, name: str, files: dict[str, str], *, native: bool = False) -> None:
    """A distribution installed into `site`, with METADATA, WHEEL and RECORD."""
    dist_info = site / f"{name}-1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    tag = "cp312-cp312-macosx_11_0_arm64" if native else "py3-none-any"
    (dist_info / "WHEEL").write_text(f"Wheel-Version: 1.0\nTag: {tag}\n")
    rows = []
    for rel, text in files.items():
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text(text)
        rows.append(f"{rel},{record_hash(text.encode())},{len(text)}")
    rows += [f"{dist_info.name}/{n},," for n in ("METADATA", "WHEEL", "RECORD")]
    (dist_info / "RECORD").write_text("\n".join(rows) + "\n")


def compile_all(site: Path) -> None:
    """What the build does before analyzing: compile everything, quietly skipping failures."""
    subprocess.run([sys.executable, "-m", "compileall", "-q", "-q", str(site)], check=False)


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def test_syntax_errors_are_errors_in_the_project_and_warnings_in_dependencies(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    install(site, "app", {"app/__init__.py": "x = (\n"})
    install(site, "lib", {"lib/__init__.py": "", "lib/a.py": "def f(:\n", "lib/b.py": "1 +\n"})
    compile_all(site)
    diags, _sizes = c.analyze(site, project="app", target=TARGET, run=run)
    assert [(d.code, d.level, d.package, d.file) for d in diags] == [
        ("syntax-error", "error", "app", "app/__init__.py"),
        ("syntax-error", "warning", "lib", "lib/a.py"),
    ]
    assert diags[0].line == 1 and diags[0].message.startswith("app/__init__.py:1 doesn't compile")
    assert diags[1].message.startswith("2 files in lib 1.0 don't compile on Python")
    assert diags[1].detail and diags[1].detail.splitlines()[1].startswith("lib/b.py:1: ")


def test_data_files_outside_packages_are_reported_but_documentation_is_not(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    files = {
        "kernel/__init__.py": "",
        "share/jupyter/kernels/k/kernel.json": "{}",
        "etc/jupyter/k.json": "{}",
        "share/man/man1/k.1": "",
        "include/k/k.h": "",
    }
    install(site, "kernel", files)
    install(site, "docs-only", {"docs_only.py": "", "share/doc/docs-only/README": ""})
    compile_all(site)
    diags, _sizes = c.analyze(site, project="app", target=TARGET, run=run)
    assert [(d.code, d.package) for d in diags] == [("data-files", "kernel")]
    assert diags[0].detail == "etc/jupyter/k.json\nshare/jupyter/kernels/k/kernel.json"


def test_sizes_count_bytecode_towards_its_package_largest_first(tmp_path: Path) -> None:
    site = tmp_path / "site"
    install(site, "small", {"small.py": "x = 1\n"})
    install(site, "big", {"big/__init__.py": "x = 1\n" * 1000}, native=True)
    compile_all(site)
    _diags, sizes = c.analyze(site, project="app", target=TARGET, run=run)
    assert [(p.name, p.native) for p in sizes] == [("big", True), ("small", False)]
    pyc = site / _bytecode.pyc_path("small.py", TARGET.cache_tag)
    dist_info = site / "small-1.0.dist-info"
    expected = sum(f.stat().st_size for f in [site / "small.py", pyc, *dist_info.iterdir()])
    assert sizes[1].size_bytes == expected
