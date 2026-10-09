"""Input without a lock (ADR-0041): a requirements.txt beside a script, a folder of modules with
one, a setuptools project, a script that needs only the standard library. Each builds, resolved
at build time with an `unlocked` warning unless every version is pinned, and nothing is written
into the input."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import BuildOptions, NoLockfileError, ProjectError, UvError, build
from bundleup._source import third_party_imports
from bundleup._uv import pinned_requirements


def index_of(private_index: str) -> Path:
    """The flat index folder the `private_index` fixture made."""
    line = next(line for line in private_index.splitlines() if line.startswith("# url = "))
    return Path(line.split('"')[1])


def requirements(folder: Path, private_index: str, pin: str = "") -> Path:
    """A requirements.txt that finds acme-private in the fixture's index."""
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / "requirements.txt"
    file.write_text(f"--find-links {index_of(private_index).as_posix()}\nacme-private{pin}\n")
    return file


def run(bundle: Path, *args: str) -> str:
    done = subprocess.run([sys.executable, str(bundle), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_a_script_with_requirements_txt_beside_it(tmp_path: Path, private_index: str) -> None:
    requirements(tmp_path, private_index)
    (tmp_path / "tool.py").write_text("import acme_private\nprint(acme_private.WHO)\n")
    result = build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "tool.pyz"))
    assert [d.code for d in result.diagnostics] == ["unlocked"]  # "acme-private": any version
    assert run(result.output) == "the company index"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "index", "requirements.txt", "tool.py", "tool.pyz"
    ]  # fmt: skip


def test_a_fully_pinned_requirements_txt_is_a_lock(tmp_path: Path, private_index: str) -> None:
    requirements(tmp_path, private_index, pin="==1.0")
    (tmp_path / "tool.py").write_text("import acme_private\nprint(acme_private.WHO)\n")
    result = build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "tool.pyz"))
    assert result.diagnostics == []
    locked = BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "b.pyz", lock_mode="locked")
    assert build(locked).diagnostics == []


def test_hashes_in_requirements_txt_are_checked(tmp_path: Path, private_index: str) -> None:
    wheel = next(index_of(private_index).glob("*.whl"))
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (tmp_path / "tool.py").write_text("import acme_private\nprint(acme_private.WHO)\n")
    file = requirements(tmp_path, private_index, pin=f"==1.0 --hash=sha256:{digest}")
    result = build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "tool.pyz"))
    assert result.diagnostics == [] and run(result.output) == "the company index"
    file.write_text(file.read_text().replace(digest, "0" * 64))
    with pytest.raises(UvError):
        build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "bad.pyz"))
    assert not (tmp_path / "bad.pyz").exists()


def test_a_folder_of_modules_with_requirements_txt(tmp_path: Path, private_index: str) -> None:
    """Its modules and files go in as they are (templates too), its venv and caches don't; it
    runs __main__.py, main.py or app.py, or what --entry names."""
    app = tmp_path / "app"
    requirements(app, private_index)
    (app / "main.py").write_text(
        "import os, acme_private, helper\n"
        "here = os.path.dirname(__file__)\n"
        "print(acme_private.WHO, helper.X, open(os.path.join(here, 'templates', 't.txt')).read())\n"
    )
    (app / "other.py").write_text("print('other')\n")
    (app / "helper.py").write_text("X = 42\n")
    (app / "templates").mkdir()
    (app / "templates" / "t.txt").write_text("template")
    (app / ".venv" / "lib").mkdir(parents=True)
    (app / ".venv" / "pyvenv.cfg").write_text("")
    (app / "venv").mkdir()
    (app / "venv" / "big.py").write_text("")
    result = build(BuildOptions(path=app, output=tmp_path / "app.pyz"))
    assert run(result.output) == "the company index 42 template"
    assert result.name == "app"
    other = build(BuildOptions(path=app, output=tmp_path / "other.pyz", entry="other.py"))
    assert run(other.output) == "other"
    assert sorted(p.name for p in app.iterdir()) == [
        ".venv", "helper.py", "main.py", "other.py", "requirements.txt", "templates", "venv"
    ]  # fmt: skip


def test_a_script_that_needs_only_the_standard_library(tmp_path: Path) -> None:
    (tmp_path / "helper.py").write_text("X = 1\n")
    (tmp_path / "tool.py").write_text(
        "import json, sys\n"
        "try:\n    import ujson\nexcept ImportError:\n    pass\n"  # optional: doesn't count
        "print(json.dumps(sys.argv[1:]))\n"
    )
    result = build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "tool.pyz"))
    assert result.diagnostics == [] and run(result.output, "a") == '["a"]'


@pytest.mark.skipif(sys.version_info < (3, 10), reason="3.9 has no sys.stdlib_module_names")
def test_which_imports_need_a_package(tmp_path: Path) -> None:
    (tmp_path / "local.py").write_text("")
    (tmp_path / "tool.py").write_text(
        "import os, local, yaml.loader\n"
        "from requests import get\n"
        "from . import sibling\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    import numpy\n"
        "try:\n    import orjson\nexcept (ValueError, ImportError):\n    orjson = None\n"
        "try:\n    import attrs\nexcept ValueError:\n    pass\n"
    )
    assert third_party_imports(tmp_path / "tool.py", local=tmp_path) == [
        "attrs",
        "requests",
        "yaml",
    ]
    with pytest.raises(ProjectError, match="imports attrs, requests, yaml, which aren't"):
        build(BuildOptions(path=tmp_path / "tool.py"))


@pytest.mark.parametrize(
    ("text", "pins", "hashed"),
    [
        ("a==1.0\nb==2 --hash=sha256:x\n", {"a": "1.0", "b": "2"}, False),
        ("a==1.0 \\\n    --hash=sha256:x\n# note\n--index-url https://x\n", {"a": "1.0"}, True),
        ("a>=1.0\n", None, False),
        ("a==1.*\n", None, False),
        ("-r other.txt\na==1\n", None, False),
        ("a @ https://x/a.whl\n", None, False),
        ("./local\n", None, False),
    ],
)
def test_what_counts_as_pinned(
    tmp_path: Path, text: str, pins: dict[str, str] | None, hashed: bool
) -> None:
    (tmp_path / "requirements.txt").write_text(text)
    assert pinned_requirements(tmp_path / "requirements.txt") == (pins, hashed)


def test_a_setuptools_project_without_pyproject(tmp_path: Path) -> None:
    """setup.py only: built as pip would, and its build/ and egg-info don't stay behind."""
    project = tmp_path / "legacy"
    (project / "lapp").mkdir(parents=True)
    (project / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='lapp', version='1.0', packages=['lapp'],"
        " entry_points={'console_scripts': ['lapp=lapp:main']})\n"
    )
    (project / "lapp" / "__init__.py").write_text("def main():\n    print('lapp')\n")
    result = build(BuildOptions(path=project, output=tmp_path / "lapp.pyz"))
    assert (result.name, result.version) == ("lapp", "1.0")
    assert run(result.output) == "lapp"
    assert sorted(p.name for p in project.iterdir()) == ["lapp", "setup.py"]
    with pytest.raises(NoLockfileError):
        build(BuildOptions(path=project, output=tmp_path / "b.pyz", lock_mode="locked"))


def test_a_lock_higher_up_counts_only_for_a_workspace_member(tmp_path: Path) -> None:
    """A repository root with its own uv.lock isn't the lock of an unrelated project below it
    (fourth review: the build failed with uv's "--locked was provided"); a member's is."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "root"\nversion = "1"\n')
    (root / "uv.lock").write_text("version = 1\n")
    sub = root / "tools" / "sub"
    sub.mkdir(parents=True)
    from bundleup._source import find_uv_lock

    assert find_uv_lock(sub) is None
    (root / "pyproject.toml").write_text(
        '[project]\nname = "root"\nversion = "1"\n[tool.uv.workspace]\nmembers = ["tools/*"]\n'
    )
    assert find_uv_lock(sub) == root / "uv.lock"
    (root / "pyproject.toml").write_text(
        '[project]\nname = "root"\nversion = "1"\n'
        '[tool.uv.workspace]\nmembers = ["tools/*"]\nexclude = ["tools/sub"]\n'
    )
    assert find_uv_lock(sub) is None


@pytest.mark.skipif(sys.version_info < (3, 10), reason="3.9 has no sys.stdlib_module_names")
def test_undeclared_imports_are_reported(tmp_path: Path, private_index: str) -> None:
    """A bundle can't see the machine's packages, so an import the dependencies don't provide
    fails at run time: a warning at build time (fourth review). With --entry python, the scripts
    it will be given are read too (beside a script; anywhere under a project or folder app), and
    their neighbours count; tests aren't."""
    (tmp_path / "deps.py").write_text(private_index + "import acme_private, yaml\n")
    (tmp_path / "edit.py").write_text("import acme_private, helper, json, requests\n")
    (tmp_path / "helper.py").write_text("X = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("import pytest\n")
    result = build(
        BuildOptions(path=tmp_path / "deps.py", entry="python", output=tmp_path / "d.pyz")
    )
    found = {d.file: d.message for d in result.diagnostics if d.code == "undeclared-import"}
    assert found == {
        "deps.py": "deps.py imports yaml: neither the bundle nor the standard library has it",
        "edit.py": "edit.py imports requests: neither the bundle nor the standard library has it",
    }


@pytest.mark.skipif(sys.version_info < (3, 10), reason="3.9 has no sys.stdlib_module_names")
def test_modules_from_pth_folders_count_and_the_targets_stdlib_decides(tmp_path: Path) -> None:
    """Fifth review: gauntlet 23's .pth-added modules (and pywin32's win32api) were reported
    missing, and the standard library was the build machine's, not the target's."""
    from bundleup._imports import provided_by, stdlib

    site = tmp_path / "site"
    (site / "win32" / "lib").mkdir(parents=True)
    (site / "win32" / "win32api.pyd").write_text("")
    (site / "win32" / "lib" / "win32con.py").write_text("")
    (site / "pywin32.pth").write_text("# comment\nwin32\nwin32/lib\nimport os\n")
    (site / "_distutils_hack").mkdir()
    assert {"win32api", "win32con", "distutils"} <= provided_by(site)
    old, new, older = stdlib((3, 11)), stdlib((3, 13)), stdlib((3, 10))
    assert old is not None and new is not None and older is not None
    assert "imp" in old and "imp" not in new and "tomllib" in old and "tomllib" not in older


@pytest.mark.skipif(sys.version_info < (3, 10), reason="3.9 has no sys.stdlib_module_names")
def test_a_pure_bundles_range_stops_where_the_stdlib_lacks_an_import(tmp_path: Path) -> None:
    """Fifth review: `import imp` was claimed for 3.12+, where it's gone."""
    from bundleup._check import stdlib_range
    from bundleup._python import PythonRange

    narrowed, diags = stdlib_range(PythonRange((3, 9), None), (3, 10), {"imp", "json"}, set())
    assert narrowed == PythonRange((3, 9), (3, 11)) and [d.code for d in diags] == ["python-range"]
    narrowed, _ = stdlib_range(PythonRange((3, 9), None), (3, 12), {"tomllib"}, set())
    assert narrowed == PythonRange((3, 11), None)
    unchanged, diags = stdlib_range(
        PythonRange((3, 9), None), (3, 12), {"distutils"}, {"distutils"}
    )
    assert unchanged == PythonRange((3, 9), None) and diags == []


def test_a_folder_app_follows_gitignore_and_flags_secrets(tmp_path: Path) -> None:
    """Fourth review: everything not hidden went in, credentials and earlier bundles too."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("print('hi')\n")
    (app / "requirements.txt").write_text("")
    (app / "old.pyz").write_text("")
    (app / "credentials.json").write_text("{}")
    (app / "data").mkdir()
    (app / "data" / "big.bin").write_text("x")
    result = build(BuildOptions(path=app, output=tmp_path / "a.pyz"))
    assert [d.code for d in result.diagnostics] == ["secret-file"]
    subprocess.run(["git", "init", "-q"], cwd=app, check=True)
    (app / ".gitignore").write_text("credentials.json\ndata/\n")
    result = build(BuildOptions(path=app, output=tmp_path / "b.pyz"))
    assert result.diagnostics == []
    with zipfile.ZipFile(tmp_path / "b.pyz") as outer:
        names = zipfile.ZipFile(io.BytesIO(outer.read("payload.zip"))).namelist()
    assert "main.py" in names and not {
        "old.pyz",
        "credentials.json",
        "data/big.bin",
        "requirements.txt",
    } & set(names)


@pytest.mark.parametrize(
    ("name", "secret"),
    [
        ("service-account.json", True), ("prod.env", True), ("gcp-key.json", True),
        ("certs/server.pem", True), ("id_rsa", True), ("api-token.txt", True),
        ("tokenizer.json", False), ("keyboard.py", False), ("monkey.json", False),
    ],
)  # fmt: skip
def test_which_names_look_like_secrets(name: str, secret: bool) -> None:
    from bundleup._source import looks_secret

    assert looks_secret(name) is secret


def test_stdlib_tables_cover_this_python() -> None:
    """The added/removed tables stop at _imports.NEWEST: a newer Python needs them updated (from
    its "What's new" page) before the range check can be trusted (sixth review)."""
    from bundleup._imports import NEWEST

    assert sys.version_info[:2] <= NEWEST, "update ADDED/REMOVED in _imports.py for this Python"


def test_downloading_a_python_is_announced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """ADR-0035, as the owner accepted it: a build that downloads an interpreter says so, and how
    to turn it off."""
    from bundleup import _python
    from bundleup._steps import ProgressEvent

    monkeypatch.setattr(_python, "find_interpreter", lambda *a, **k: None)

    def offline(*args: object, **kwargs: object) -> str:
        raise UvError("uv python install failed")

    monkeypatch.setattr(_python, "run", offline)
    events: list[ProgressEvent] = []
    assert _python.fetch_interpreter("uv", "3.8", cwd=tmp_path, progress=events.append) is None
    assert [e.kind for e in events] == ["note"] and "UV_PYTHON_DOWNLOADS=never" in events[0].text
