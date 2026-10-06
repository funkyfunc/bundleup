"""Loader and CLI behaviour the gauntlet doesn't exercise. The gauntlet remains the acceptance test
(ADR-0007); these cover edge cases of ADR-0010 and ADR-0011 that need a crafted environment."""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from bundleup import _build as b
from bundleup._cli import main

PROBE = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json, os, sys
print(json.dumps({"path": sys.path, "file": __file__, "pythonpath": os.environ.get("PYTHONPATH"),
                  "site": os.environ.get("BUNDLEUP_SITE"), "argv": sys.argv[1:]}))
"""
SYSTEM_PYTHON = "/usr/bin/python3"
WINDOWS = sys.platform == "win32"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    src = tmp_path_factory.mktemp("src") / "probe.py"
    src.write_text(PROBE)
    out = src.parent / "probe.pyz"
    assert main(["build", str(src), "-o", str(out), "--python", sys.executable, "-q"]) == 0
    return out


def env_for(tmp: Path, **extra: str) -> dict[str, str]:
    """A minimal environment with a fresh home, so every test starts with an empty cache."""
    home = tmp / "home"
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "TMPDIR": str(home / "tmp"), "PATH": "/usr/bin:/bin"}
    if WINDOWS:
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env |= {
            "SYSTEMROOT": system_root,  # Python can't start without it
            "PATH": rf"{system_root}\System32",
            "PROCESSOR_ARCHITECTURE": os.environ.get("PROCESSOR_ARCHITECTURE", ""),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TEMP": str(home / "tmp"),
        }
    return env | extra


def run(
    bundle: Path, env: dict[str, str], *args: str, python: str = sys.executable
) -> subprocess.CompletedProcess[str]:
    return subprocess.run([python, str(bundle), *args], env=env, capture_output=True, text=True)


def probe(bundle: Path, env: dict[str, str], *args: str) -> dict[str, Any]:  # Any: JSON
    r = run(bundle, env, *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def relabel(bundle: Path, out: Path, **config: object) -> Path:
    """A copy of the bundle with its loader config changed, to pretend it was built elsewhere."""
    with zipfile.ZipFile(bundle) as zf:
        payload, loader = zf.read("payload.zip"), zf.read("__main__.py").decode()
    for key, value in config.items():
        lines = [
            f"{key} = {value!r}" if line.startswith(f"{key} = ") else line
            for line in loader.splitlines()
        ]
        loader = "\n".join(lines) + "\n"
    with open(out, "wb") as f:
        f.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("payload.zip", payload)
            zf.writestr("__main__.py", loader)  # no .pyc: it would carry the old config
    return out


def test_runs_and_passes_arguments(bundle: Path, tmp_path: Path) -> None:
    env = env_for(tmp_path)
    out = probe(bundle, env, "a", "--b")
    assert out["argv"] == ["a", "--b"]
    assert out["file"].startswith(env["HOME"])  # the user cache directory, inside the fresh home
    assert "bundleup" in Path(out["file"]).parts


def test_payload_sits_before_site_packages_and_on_pythonpath(bundle: Path, tmp_path: Path) -> None:
    out = probe(bundle, env_for(tmp_path))
    site = out["site"]
    assert site in out["path"] and str(bundle) not in out["path"]
    stdlib = os.path.dirname(os.__file__)
    assert out["path"].index(stdlib) < out["path"].index(site)  # can't shadow the standard library
    assert out["pythonpath"].split(os.pathsep)[0] == site


def test_nested_bundle_drops_parent_packages(bundle: Path, tmp_path: Path) -> None:
    parent = "/somewhere/else/parent-bundle"
    env = env_for(tmp_path, BUNDLEUP_SITE=parent, PYTHONPATH=os.pathsep.join([parent, "/keep/me"]))
    out = probe(bundle, env)
    assert parent not in out["path"]
    assert out["pythonpath"].split(os.pathsep)[1:] == ["/keep/me"]


def test_bundleup_cache_override(bundle: Path, tmp_path: Path) -> None:
    out = probe(bundle, env_for(tmp_path, BUNDLEUP_CACHE=str(tmp_path / "c")))
    assert out["file"].startswith(str(tmp_path / "c"))


@pytest.mark.skipif(WINDOWS, reason="POSIX ownership and permission bits")
def test_untrusted_shared_temp_dir_is_skipped(bundle: Path, tmp_path: Path) -> None:
    env = env_for(tmp_path)
    home = Path(env["HOME"])
    planted = Path(env["TMPDIR"]) / f"bundleup-{os.getuid()}"
    planted.mkdir()
    planted.chmod(0o777)  # writable by anyone: must not be trusted
    home.chmod(stat.S_IRUSR | stat.S_IXUSR)  # user cache dir can't be created
    copy = tmp_path / "app" / bundle.name
    copy.parent.mkdir()
    copy.write_bytes(bundle.read_bytes())
    try:
        out = probe(copy, env)
    finally:
        home.chmod(0o755)
    assert out["file"].startswith(str(copy.parent / ".bundleup"))


def test_pycache_prefix_gets_the_precompiled_bytecode(bundle: Path, tmp_path: Path) -> None:
    # macOS's /usr/bin/python3 sets sys.pycache_prefix, so Python ignores __pycache__ directories.
    prefix = tmp_path / "prefix"
    out = probe(bundle, env_for(tmp_path, PYTHONPYCACHEPREFIX=str(prefix)))
    site = Path(out["site"])
    tag = sys.implementation.cache_tag
    relative = os.path.splitdrive(str(site))[1].lstrip("\\/")
    assert (prefix / relative / "__bundleup_script__" / f"probe.{tag}.pyc").is_file()
    assert not list(site.rglob("*.pyc"))


def test_wrong_python_version_is_explained(bundle: Path, tmp_path: Path) -> None:
    if not os.path.exists(SYSTEM_PYTHON):
        pytest.skip("needs a second Python")
    probe_version = [SYSTEM_PYTHON, "-c", "import sys; print(sys.version_info[:2])"]
    if subprocess.run(probe_version, capture_output=True, text=True).stdout.strip() == str(
        sys.version_info[:2]
    ):
        pytest.skip(f"{SYSTEM_PYTHON} is the same version as the test Python")
    r = run(bundle, env_for(tmp_path), python=SYSTEM_PYTHON)
    assert r.returncode == 1
    assert f"bundled for Python {sys.version_info[0]}.{sys.version_info[1]}" in r.stderr
    assert "Traceback" not in r.stderr


def test_wrong_platform_is_explained(bundle: Path, tmp_path: Path) -> None:
    # A platform no test machine has, so this fails everywhere.
    fake = relabel(bundle, tmp_path / "other.pyz", PLATFORM="sunos5", TARGET="Python on Solaris")
    r = run(fake, env_for(tmp_path))
    assert r.returncode == 1
    assert "bundled for Python on Solaris, but this machine is" in r.stderr
    assert "Traceback" not in r.stderr


def test_wrong_cpu_is_explained(bundle: Path, tmp_path: Path) -> None:
    fake = relabel(bundle, tmp_path / "cpu.pyz", MACHINE="riscv64", TARGET="Python on riscv64")
    r = run(fake, env_for(tmp_path))
    assert r.returncode == 1 and "bundled for Python on riscv64" in r.stderr


def test_reproducible_payload(tmp_path: Path) -> None:
    src = tmp_path / "probe.py"
    src.write_text(PROBE)
    for name in ("one.pyz", "two.pyz"):
        args = ["build", str(src), "-o", str(tmp_path / name), "--python", sys.executable, "-q"]
        assert main(args) == 0
    assert (tmp_path / "one.pyz").read_bytes() == (tmp_path / "two.pyz").read_bytes()


def test_bundle_layout(bundle: Path) -> None:
    with zipfile.ZipFile(bundle) as zf:
        assert sorted(zf.namelist()) == ["__main__.py", "__main__.pyc", "payload.zip"]
        assert zf.getinfo("payload.zip").compress_type == zipfile.ZIP_STORED
    assert bundle.read_bytes().startswith(b"#!/usr/bin/env python3\n")
    if not WINDOWS:
        assert os.access(bundle, os.X_OK)


def test_cli_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith("bundleup ")
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0 and "PEP 723" in capsys.readouterr().out


def test_cli_explains_missing_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["build", str(tmp_path)]) == 1
    assert "has no pyproject.toml" in capsys.readouterr().err


def test_script_metadata_parsing() -> None:
    assert b.script_metadata(PROBE) == {"requires-python": ">=3.9", "dependencies": []}
    assert b.script_metadata("print('no block')") == {}


def test_builds_without_uv_on_path(tmp_path: Path) -> None:
    """bundleup depends on the `uv` package, so it works where uv was never installed."""
    src = tmp_path / "probe.py"
    src.write_text(PROBE)
    bundleup = Path(sys.executable).with_name("bundleup.exe" if WINDOWS else "bundleup")
    env = dict(os.environ)  # the real environment (uv's cache, home), minus uv on PATH
    env["PATH"] = env_for(tmp_path)["PATH"]
    r = subprocess.run(
        [
            str(bundleup),
            "build",
            str(src),
            "-o",
            str(tmp_path / "p.pyz"),
            "--python",
            sys.executable,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert probe(tmp_path / "p.pyz", env_for(tmp_path))["argv"] == []


def test_loader_parses_on_any_python_3() -> None:
    """The loader must get far enough on an old Python to print "this app needs Python X"."""
    source = (Path(b.__file__).parent / "_loader.py").read_text()
    ast.parse(source, feature_version=(3, 5))  # raises SyntaxError on newer-only syntax
