"""Loader and CLI behaviour the gauntlet doesn't exercise. The gauntlet remains the acceptance test
(ADR-0007); these cover edge cases of ADR-0010 and ADR-0011 that need a crafted environment."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import build as b
from bundleup.cli import main

PROBE = '''\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json, os, sys
print(json.dumps({"path": sys.path, "file": __file__, "pythonpath": os.environ.get("PYTHONPATH"),
                  "site": os.environ.get("BUNDLEUP_SITE"), "argv": sys.argv[1:]}))
'''
SYSTEM_PYTHON = "/usr/bin/python3"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> Path:
    src = tmp_path_factory.mktemp("src") / "probe.py"
    src.write_text(PROBE)
    out = src.parent / "probe.pyz"
    assert main([str(src), "-o", str(out), "--python", sys.executable, "-q"]) == 0
    return out


def env_for(tmp: Path, **extra) -> dict:
    home = tmp / "home"
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home / "tmp"), **extra}


def run(bundle: Path, env: dict, *args, python=sys.executable, cwd=None):
    return subprocess.run([python, str(bundle), *args], env=env, capture_output=True, text=True, cwd=cwd)


def probe(bundle, env, *args):
    r = run(bundle, env, *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def relabel(bundle: Path, out: Path, **config) -> Path:
    """A copy of the bundle whose loader config is changed, e.g. to pretend it was built elsewhere."""
    with zipfile.ZipFile(bundle) as zf:
        payload, loader = zf.read("payload.zip"), zf.read("__main__.py").decode()
    for key, value in config.items():
        lines = [f"{key} = {value!r}" if line.startswith(f"{key} = ") else line for line in loader.splitlines()]
        loader = "\n".join(lines) + "\n"
    with open(out, "wb") as f:
        f.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("payload.zip", payload)
            zf.writestr("__main__.py", loader)  # no .pyc: it would carry the old config
    return out


def test_runs_and_passes_arguments(bundle, tmp_path):
    out = probe(bundle, env_for(tmp_path), "a", "--b")
    assert out["argv"] == ["a", "--b"]
    assert "/Library/Caches/bundleup/" in out["file"] or "/.cache/bundleup/" in out["file"]


def test_payload_sits_before_site_packages_and_on_pythonpath(bundle, tmp_path):
    out = probe(bundle, env_for(tmp_path))
    site = out["site"]
    assert site in out["path"] and str(bundle) not in out["path"]
    stdlib = os.path.dirname(os.__file__)
    assert out["path"].index(stdlib) < out["path"].index(site)  # can't shadow the standard library
    assert out["pythonpath"].split(os.pathsep)[0] == site


def test_nested_bundle_drops_parent_packages(bundle, tmp_path):
    parent = "/somewhere/else/parent-bundle"
    env = env_for(tmp_path, BUNDLEUP_SITE=parent, PYTHONPATH=os.pathsep.join([parent, "/keep/me"]))
    out = probe(bundle, env)
    assert parent not in out["path"]
    assert out["pythonpath"].split(os.pathsep)[1:] == ["/keep/me"]


def test_bundleup_cache_override(bundle, tmp_path):
    out = probe(bundle, env_for(tmp_path, BUNDLEUP_CACHE=str(tmp_path / "c")))
    assert out["file"].startswith(str(tmp_path / "c"))


def test_untrusted_shared_temp_dir_is_skipped(bundle, tmp_path):
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


def test_pycache_prefix_gets_the_precompiled_bytecode(bundle, tmp_path):
    # macOS's /usr/bin/python3 sets sys.pycache_prefix, so Python ignores __pycache__ directories.
    prefix = tmp_path / "prefix"
    out = probe(bundle, env_for(tmp_path, PYTHONPYCACHEPREFIX=str(prefix)))
    site = Path(out["site"])
    tag = sys.implementation.cache_tag
    assert (prefix / str(site).lstrip("/") / "__bundleup_script__" / f"probe.{tag}.pyc").is_file()
    assert not list(site.rglob("*.pyc"))


def test_wrong_python_version_is_explained(bundle, tmp_path):
    if not os.path.exists(SYSTEM_PYTHON):
        pytest.skip("needs a second Python")
    r = run(bundle, env_for(tmp_path), python=SYSTEM_PYTHON)
    if f"{sys.version_info[0]}.{sys.version_info[1]}" in r.stderr.split("running on Python ")[-1][:5]:
        pytest.skip("same version")
    assert r.returncode == 1
    assert f"bundled for Python {sys.version_info[0]}.{sys.version_info[1]}" in r.stderr
    assert "Traceback" not in r.stderr


def test_wrong_platform_is_explained(bundle, tmp_path):
    fake = relabel(bundle, tmp_path / "linux.pyz", PLATFORM="linux", TARGET="Python 3.12 on Linux x86_64",
                   MACHINE="x86_64")
    r = run(fake, env_for(tmp_path))
    assert r.returncode == 1
    assert "bundled for Python 3.12 on Linux x86_64, but this machine is" in r.stderr
    assert "Traceback" not in r.stderr


def test_wrong_cpu_is_explained(bundle, tmp_path):
    fake = relabel(bundle, tmp_path / "cpu.pyz", MACHINE="riscv64", TARGET="Python on riscv64")
    r = run(fake, env_for(tmp_path))
    assert r.returncode == 1 and "bundled for Python on riscv64" in r.stderr


def test_reproducible_payload(tmp_path):
    src = tmp_path / "probe.py"
    src.write_text(PROBE)
    for name in ("one.pyz", "two.pyz"):
        assert main([str(src), "-o", str(tmp_path / name), "--python", sys.executable, "-q"]) == 0
    assert (tmp_path / "one.pyz").read_bytes() == (tmp_path / "two.pyz").read_bytes()


def test_bundle_layout(bundle):
    with zipfile.ZipFile(bundle) as zf:
        assert sorted(zf.namelist()) == ["__main__.py", "__main__.pyc", "payload.zip"]
        assert zf.getinfo("payload.zip").compress_type == zipfile.ZIP_STORED
    assert bundle.read_bytes().startswith(b"#!/usr/bin/env python3\n")
    assert os.access(bundle, os.X_OK)


def test_cli_version_and_help(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith("bundleup ")
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0 and "PEP 723" in capsys.readouterr().out


def test_cli_explains_missing_project(tmp_path, capsys):
    assert main([str(tmp_path)]) == 1
    assert "has no pyproject.toml" in capsys.readouterr().err


def test_script_metadata_parsing():
    assert b.script_metadata(PROBE) == {"requires-python": ">=3.9", "dependencies": []}
    assert b.script_metadata("print('no block')") == {}


def test_builds_without_uv_on_path(tmp_path):
    """bundleup depends on the `uv` package, so it works where uv was never installed (pipx, plain pip)."""
    src = tmp_path / "probe.py"
    src.write_text(PROBE)
    bundleup = Path(sys.executable).with_name("bundleup")
    r = subprocess.run([str(bundleup), str(src), "-o", str(tmp_path / "p.pyz"), "--python", sys.executable, "-q"],
                       env={"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"]}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert probe(tmp_path / "p.pyz", env_for(tmp_path))["argv"] == []
