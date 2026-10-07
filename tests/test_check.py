"""The analysis behind `bundleup check` (ADR-0024), on hand-made payloads."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_the_range_starts_at_the_oldest_python_the_code_compiles_on(tmp_path: Path) -> None:
    """requires-python may promise more than the code delivers (ADR-0030): the project's code is
    compiled with the Pythons below the target, oldest first: installed ones, or the target's
    interpreter checking the older syntax (second review; ADR-0035)."""
    from dataclasses import replace

    from bundleup._python import PythonRange

    site = tmp_path / "site"
    install(site, "app", {"app/__init__.py": "match x:\n    case 1: pass\n"})
    pyc = site / _bytecode.pyc_path("app/__init__.py", TARGET.cache_tag)
    pyc.parent.mkdir(exist_ok=True)
    pyc.write_bytes(b"")  # it compiled for the target
    target = replace(TARGET, version=(3, 14))
    wide = PythonRange((3, 9), None)

    def fake(cmd: list[str]) -> str:  # "python 3.9" can't compile a match statement
        return '[["app/__init__.py", 1, "invalid syntax"]]' if cmd[0] == "py39" else "[]"

    def oldest(interpreters: dict[tuple[int, int], str | None]) -> tuple[PythonRange, list[str]]:
        found, diags = c.oldest_python(
            site,
            project="app",
            script=None,
            pythons=wide,
            target=target,
            interpreters=interpreters,
            run=fake,
        )
        return found, [d.code for d in diags]

    some = {(3, 9): "py39", (3, 10): None, (3, 11): "py311", (3, 12): None, (3, 13): None}
    # 3.9 fails; 3.10 isn't installed, so the target's interpreter checks its syntax: it passes.
    assert oldest(some) == (PythonRange((3, 10), None), ["python-range"])
    assert oldest({(3, 9): "py39"}) == (PythonRange((3, 14), None), ["python-range"])
    assert oldest({(3, 9): "py311"}) == (wide, [])
    # Not installed: the target's interpreter checks the syntax for that version (ast.parse with
    # feature_version), for real here: a match statement isn't Python 3.9.
    missing: dict[tuple[int, int], str | None] = {(3, 9): None}
    narrowed, diags = c.oldest_python(
        site,
        project="app",
        script=None,
        pythons=wide,
        target=target,
        interpreters=missing,
        run=run,
    )
    assert narrowed == PythonRange((3, 14), None)
    assert [d.message.split(" doesn't compile on ")[1][:10] for d in diags] == ["Python 3.9"]


def test_an_older_interpreter_catches_what_ast_cannot(tmp_path: Path) -> None:
    """Third review: ast.parse(feature_version=) accepts PEP 701 f-strings (3.12+), so the range
    check uses a real interpreter of the oldest version when there is one (ADR-0035)."""
    from dataclasses import replace

    from bundleup._python import PythonRange

    found = subprocess.run(
        ["uv", "python", "find", "3.11"], capture_output=True, text=True, cwd=tmp_path
    ).stdout.strip()
    if not found or sys.version_info < (3, 12):
        pytest.skip("needs a Python 3.11 and a test Python of 3.12 or newer")
    site = tmp_path / "site"
    install(site, "app", {"app/__init__.py": 'd = {"a": 1}\nprint(f"{d["a"]}")\n'})
    pyc = site / _bytecode.pyc_path("app/__init__.py", TARGET.cache_tag)
    pyc.parent.mkdir(exist_ok=True)
    pyc.write_bytes(b"")
    target = replace(TARGET, version=(3, 12))
    narrowed, diags = c.oldest_python(
        site,
        project="app",
        script=None,
        pythons=PythonRange((3, 11), None),
        target=target,
        interpreters={(3, 11): found},
        run=run,
    )
    assert narrowed == PythonRange((3, 12), None)
    assert [d.code for d in diags] == ["python-range"]
