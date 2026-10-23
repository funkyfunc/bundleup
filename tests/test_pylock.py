"""Lockfiles: a standard pylock.toml (PEP 751) instead of uv.lock (ADR-0026), and no lockfile
at all (ADR-0028, ADR-0041)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bundleup import BuildOptions, LockfileOutdatedError, NoLockfileError, ProjectError, build

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


def test_a_project_without_a_lockfile_builds_with_a_warning_and_is_left_untouched(
    tmp_path: Path,
) -> None:
    """Resolved at build time, in the stage (ADR-0041): never a uv.lock or build output written
    into the project (ADR-0028; the review found a uv.lock written). --locked refuses."""
    path = project(tmp_path / "p", PYLOCK)
    (path / "pylock.toml").unlink()
    result = build(BuildOptions(path=path, output=tmp_path / "app.pyz"))
    assert [d.code for d in result.diagnostics] == ["unlocked"]
    assert sorted(p.name for p in path.iterdir()) == ["pyproject.toml", "src"]
    assert sorted(p.name for p in (path / "src").iterdir()) == ["locked_app"]
    with pytest.raises(NoLockfileError) as e:
        build(BuildOptions(path=path, output=tmp_path / "b.pyz", lock_mode="locked"))
    assert e.value.hint and "uv lock" in e.value.hint


def test_an_unlocked_script_with_dependencies_gets_a_warning(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text(
        '# /// script\n# requires-python = ">=3.9"\n# dependencies = ["packaging"]\n# ///\n'
        "import packaging\n"
    )
    result = build(BuildOptions(path=script, output=tmp_path / "tool.pyz"))
    assert [d.code for d in result.diagnostics] == ["unlocked"]
    assert not (tmp_path / "tool.py.lock").exists()


def test_a_stale_uv_lock_is_an_error_and_is_never_rewritten(tmp_path: Path) -> None:
    """Without --frozen, the lock is checked against pyproject.toml (ADR-0033): the second review
    found a stale uv.lock was silently re-locked, and the new versions bundled."""
    path = project(tmp_path / "p", PYLOCK)
    (path / "pylock.toml").unlink()
    subprocess.run(["uv", "lock", "-q"], cwd=path, check=True)
    lock = (path / "uv.lock").read_bytes()
    pyproject = path / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('">=3.9"', '">=3.10"'))
    with pytest.raises(LockfileOutdatedError):
        build(BuildOptions(path=path, output=tmp_path / "app.pyz"))
    assert (path / "uv.lock").read_bytes() == lock
    build(BuildOptions(path=path, output=tmp_path / "app.pyz", lock_mode="frozen"))
    assert (path / "uv.lock").read_bytes() == lock


def wheel(folder: Path, version: str) -> str:
    """A hand-made `acme-fork` wheel (no network, no build backend); returns its pylock entry."""
    import base64
    import hashlib
    import zipfile

    folder.mkdir(exist_ok=True)
    path = folder / f"acme_fork-{version}-py3-none-any.whl"
    files = {
        "acme_fork.py": f"VERSION = {version!r}\n",
        f"acme_fork-{version}.dist-info/METADATA": "Metadata-Version: 2.1\nName: acme-fork\n"
        f"Version: {version}\n",
        f"acme_fork-{version}.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record = []
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=")
            record.append(f"{name},sha256={digest.decode()},{len(text)}")
            zf.writestr(name, text)
        record.append(f"acme_fork-{version}.dist-info/RECORD,,")
        zf.writestr(f"acme_fork-{version}.dist-info/RECORD", "\n".join(record) + "\n")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return f'wheels = [{{ path = "wheels/{path.name}", hashes = {{ sha256 = "{sha}" }} }}]\n'


def test_a_lock_forked_on_the_full_python_version_installs_this_versions_side(
    tmp_path: Path,
) -> None:
    """Twelfth review: installs passed `--python-version 3.X`, which uv reads as 3.X.0, so a lock
    forked at `python_full_version <= '3.X'` (cryptography in gauntlet 11) installed the 3.X.0
    side, and the lock check refused the bundle on any later 3.X."""
    minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    path = tmp_path / "p"
    path.mkdir()
    old = f"marker = \"python_full_version <= '{minor}'\"\n" + wheel(path / "wheels", "1.0")
    new = f"marker = \"python_full_version > '{minor}'\"\n" + wheel(path / "wheels", "2.0")
    pylock = PYLOCK + PROJECT_ENTRY.format(editable="false")
    pylock += '\n[[packages]]\nname = "acme-fork"\nversion = "1.0"\n' + old
    pylock += '\n[[packages]]\nname = "acme-fork"\nversion = "2.0"\n' + new
    project(path, pylock)
    pyproject = path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            "[project.scripts]", 'dependencies = ["acme-fork"]\n[project.scripts]'
        )
    )
    (path / "src" / "locked_app" / "__init__.py").write_text(
        "def main():\n    import acme_fork\n    print(acme_fork.VERSION)\n"
    )
    result = build(BuildOptions(path=path, output=tmp_path / "app.pyz", python=sys.executable))
    done = subprocess.run([sys.executable, str(result.output)], capture_output=True, text=True)
    assert done.stdout.strip() == ("1.0" if sys.version_info.micro == 0 else "2.0"), done.stderr


@pytest.mark.parametrize("modern", [False, True], ids=["any-syntax", "match-statement"])
def test_a_payload_for_older_pythons_is_built_only_where_the_code_runs(
    tmp_path: Path, modern: bool
) -> None:
    """ADR-0052 builds an extra payload where the lock picks other packages for older Pythons
    (here `acme-fork` 1.0 below 3.10). Twelfth review: that payload skipped every code check, so
    code with a `match` statement claimed 3.9 and failed there with a SyntaxError."""
    path = tmp_path / "p"
    path.mkdir()
    old = "marker = \"python_version < '3.10'\"\n" + wheel(path / "wheels", "1.0")
    new = "marker = \"python_version >= '3.10'\"\n" + wheel(path / "wheels", "2.0")
    pylock = PYLOCK + PROJECT_ENTRY.format(editable="false")
    pylock += '\n[[packages]]\nname = "acme-fork"\nversion = "1.0"\n' + old
    pylock += '\n[[packages]]\nname = "acme-fork"\nversion = "2.0"\n' + new
    project(path, pylock)
    pyproject = path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            "[project.scripts]", 'dependencies = ["acme-fork"]\n[project.scripts]'
        )
    )
    body = "    match 1:\n        case _:\n            pass\n" if modern else ""
    (path / "src" / "locked_app" / "__init__.py").write_text(
        f"def main():\n{body}    import acme_fork\n    print(acme_fork.VERSION)\n"
    )
    result = build(BuildOptions(path=path, output=tmp_path / "app.pyz"))
    assert result.pythons is not None
    assert result.pythons.min == ((3, 10) if modern else (3, 9))
    done = subprocess.run([sys.executable, str(result.output)], capture_output=True, text=True)
    assert done.stdout.strip() == ("1.0" if sys.version_info < (3, 10) else "2.0"), done.stderr
