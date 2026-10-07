"""Lockfiles: a standard pylock.toml (PEP 751) instead of uv.lock (ADR-0026), and no lockfile
at all (ADR-0028)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bundleup import BuildOptions, NoLockfileError, ProjectError, build

PYPROJECT = """\
[project]
name = "locked-app"
version = "1.2.0"
requires-python = ">=3.9"
[project.scripts]
locked-app = "locked_app:main"
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""
PYLOCK = """\
lock-version = "1.0"
created-by = "hand"
"""
PROJECT_ENTRY = """
[[packages]]
name = "locked-app"
directory = {{ path = ".", editable = {editable} }}
"""


def project(tmp_path: Path, pylock: str) -> Path:
    (tmp_path / "src" / "locked_app").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "src" / "locked_app" / "__init__.py").write_text("def main():\n    print('ok')\n")
    (tmp_path / "pylock.toml").write_text(pylock)
    return tmp_path


@pytest.mark.parametrize("listed", [True, False], ids=["project-listed", "project-not-listed"])
def test_builds_from_pylock_toml(tmp_path: Path, listed: bool) -> None:
    entry = PROJECT_ENTRY.format(editable="false") if listed else ""
    path = project(tmp_path / "p", PYLOCK + entry)
    result = build(BuildOptions(path=path, output=tmp_path / "app.pyz"))
    assert (result.name, result.version, result.packages) == ("locked-app", "1.2.0", 1)
    assert not (path / "uv.lock").exists()  # nothing was locked behind the user's back
    done = subprocess.run([sys.executable, str(result.output)], capture_output=True, text=True)
    assert done.stdout == "ok\n", done.stderr


def test_editable_project_in_pylock_is_refused(tmp_path: Path) -> None:
    path = project(tmp_path / "p", PYLOCK + PROJECT_ENTRY.format(editable="true"))
    with pytest.raises(ProjectError, match="as editable"):
        build(BuildOptions(path=path, output=tmp_path / "app.pyz"))


def test_a_project_without_a_lockfile_is_refused_and_left_untouched(tmp_path: Path) -> None:
    """bundleup never writes uv.lock into a project (ADR-0028; the review found it did)."""
    path = project(tmp_path / "p", PYLOCK)
    (path / "pylock.toml").unlink()
    with pytest.raises(NoLockfileError) as e:
        build(BuildOptions(path=path, output=tmp_path / "app.pyz"))
    assert e.value.hint and "uv lock" in e.value.hint
    assert sorted(p.name for p in path.iterdir()) == ["pyproject.toml", "src"]


def test_an_unlocked_script_with_dependencies_gets_a_warning(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text(
        '# /// script\n# requires-python = ">=3.9"\n# dependencies = ["packaging"]\n# ///\n'
        "import packaging\n"
    )
    result = build(BuildOptions(path=script, output=tmp_path / "tool.pyz"))
    assert [d.code for d in result.diagnostics] == ["unlocked"]
    assert not (tmp_path / "tool.py.lock").exists()
