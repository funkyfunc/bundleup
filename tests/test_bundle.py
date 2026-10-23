"""Loader and CLI behaviour the gauntlet doesn't exercise. The gauntlet remains the acceptance test
(ADR-0007); these cover edge cases of ADR-0010 and ADR-0011 that need a crafted environment."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

import bundleup
from bundleup import BuildOptions, UsageError, build, verify
from bundleup._cli import main, parsers
from bundleup._payload import pth_files
from bundleup._source import script_metadata

PROBE = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json, os, subprocess, sys
child = None
if os.environ.get("PROBE_CHILD"):  # "self" (the bundle's interpreter) or another Python's path
    python = sys.executable if os.environ["PROBE_CHILD"] == "self" else os.environ["PROBE_CHILD"]
    code = "import json, sys; m = sys.modules.get('sitecustomize'); "
    code += "print(json.dumps([sys.path, getattr(m, '__file__', None)]))"
    done = subprocess.run([python, "-c", code], capture_output=True, text=True)
    child = json.loads(done.stdout) if done.returncode == 0 else done.stderr
tool = None
if os.environ.get("PROBE_TOOL"):  # a script installed with this same Python, not bundle code
    cmd = [sys.executable, os.environ["PROBE_TOOL"]]
    done = subprocess.run(cmd, capture_output=True, text=True)
    tool = done.stdout.strip() or done.stderr.strip()[-200:]
env = sorted(k for k in os.environ if k.startswith("BUNDLEUP_"))
print(json.dumps({"path": sys.path, "file": __file__, "pythonpath": os.environ.get("PYTHONPATH"),
                  "site": os.environ.get("BUNDLEUP_RUNTIME_SITE"), "argv": sys.argv[1:],
                  "child": child, "env": env, "tool": tool}))
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
    # Children get the shim, never the payload itself (ADR-0027).
    assert out["pythonpath"].split(os.pathsep) == [os.path.join(site, "__bundleup__")]


def test_nested_bundle_drops_parent_packages(bundle: Path, tmp_path: Path) -> None:
    parent = "/somewhere/else/parent-bundle"
    shim = os.path.join(parent, "__bundleup__")
    env = env_for(
        tmp_path,
        BUNDLEUP_RUNTIME_SITE=parent,
        BUNDLEUP_RUNTIME_PATHS=parent,
        PYTHONPATH=os.pathsep.join([shim, "/keep/me"]),
    )
    out = probe(bundle, env)
    assert parent not in out["path"]
    assert out["pythonpath"].split(os.pathsep)[1:] == ["/keep/me"]


def test_children_of_the_same_interpreter_see_the_bundle(bundle: Path, tmp_path: Path) -> None:
    out = probe(bundle, env_for(tmp_path, PROBE_CHILD="self"))
    child_path, _sitecustomize = out["child"]
    assert out["site"] in child_path
    assert os.path.join(out["site"], "__bundleup__") not in child_path  # the shim removes itself


def test_other_pythons_are_left_alone(bundle: Path, tmp_path: Path) -> None:
    """A Python from another environment (here a venv) must not import the bundle's packages,
    and still imports the sitecustomize it would without the bundle (the review found the old
    PYTHONPATH leaked)."""
    venv = tmp_path / "other-venv"
    subprocess.run([base_python(), "-m", "venv", "--without-pip", str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if WINDOWS else "bin/python")
    purelib = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (Path(purelib) / "sitecustomize.py").write_text("CHAINED = 1\n")
    # Which sitecustomize this Python imports on its own: the venv's, or one earlier on its path
    # (Ubuntu's Python has one in the standard library directory).
    own = "import sys; m = sys.modules.get('sitecustomize'); print(getattr(m, '__file__', None))"
    expected = subprocess.run(
        [str(python), "-c", own], capture_output=True, text=True, check=True, env=env_for(tmp_path)
    ).stdout.strip()
    out = probe(bundle, env_for(tmp_path, PROBE_CHILD=str(python)))
    child_path, imported = out["child"]
    assert not any(p.startswith(out["site"]) for p in child_path)
    assert str(imported) == expected


def test_tools_installed_with_the_same_python_keep_their_packages(
    bundle: Path, tmp_path: Path
) -> None:
    """Third review: a bundle run by an environment's Python that starts a tool installed in that
    environment (a Docker image with `pip install awscli`) hid the tool's packages. Children
    activate the bundle only when they run its code."""
    venv = tmp_path / "env"
    subprocess.run([base_python(), "-m", "venv", "--without-pip", str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if WINDOWS else "bin/python")
    purelib = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (Path(purelib) / "toolpkg.py").write_text("NAME = 'toolpkg'\n")
    tool = tmp_path / "mytool.py"
    tool.write_text("import toolpkg\nprint(toolpkg.NAME)\n")
    env = env_for(tmp_path, PROBE_TOOL=str(tool), PROBE_CHILD="self")
    r = run(bundle, env, python=str(python))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["tool"] == "toolpkg"  # the tool sees its environment
    assert out["site"] in out["child"][0]  # a `-c` child still sees the bundle


def test_a_bundle_sets_no_variable_the_cli_reads(bundle: Path, tmp_path: Path) -> None:
    """bundleup must work from inside a bundled program (second review: the runtime set
    BUNDLEUP_PYTHON, which is also --python's variable)."""
    help_text = "\n".join(p.format_help() for p in parsers().values())
    cli_variables = set(re.findall(r"\[env: (BUNDLEUP_[A-Z_]+)\]", help_text))
    seen = set(probe(bundle, env_for(tmp_path))["env"])
    assert cli_variables and seen and not seen & cli_variables


def test_bundleup_cache_override(bundle: Path, tmp_path: Path) -> None:
    out = probe(bundle, env_for(tmp_path, BUNDLEUP_CACHE=str(tmp_path / "c")))
    assert out["file"].startswith(str(tmp_path / "c"))


def test_an_unusable_explicit_cache_is_named(bundle: Path, tmp_path: Path) -> None:
    """No fallback when BUNDLEUP_CACHE is set (ADR-0048), so the message says what to change."""
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder")
    r = run(bundle, env_for(tmp_path, BUNDLEUP_CACHE=str(blocked / "cache")))
    assert r.returncode == 1 and "BUNDLEUP_CACHE is set" in r.stderr, r.stderr


def test_an_explicit_cache_is_the_only_one(bundle: Path, tmp_path: Path) -> None:
    """A copy already in the user cache must not win over BUNDLEUP_CACHE (seventh review: on a
    cluster, the login node's copy on NFS beat the compute nodes' local scratch)."""
    probe(bundle, env_for(tmp_path))  # unpacked into the user cache first
    out = probe(bundle, env_for(tmp_path, BUNDLEUP_CACHE=str(tmp_path / "local")))
    assert out["file"].startswith(str(tmp_path / "local"))


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


@pytest.mark.skipif(WINDOWS, reason="POSIX ownership and permission bits")
def test_a_copy_planted_next_to_the_bundle_is_ignored(bundle: Path, tmp_path: Path) -> None:
    """A bundle in a shared directory (/tmp, a team drive) must not run a copy someone else put
    in `.bundleup/` beside it (second review: it did)."""
    env = env_for(tmp_path)
    site = Path(probe(bundle, env)["site"])  # a genuine unpacked copy, to tamper with
    shared = tmp_path / "shared"
    shared.mkdir()
    copy = shared / bundle.name
    copy.write_bytes(bundle.read_bytes())
    planted = shared / ".bundleup" / site.name
    shutil.copytree(site, planted)
    script = planted / "__bundleup_script__" / "probe.py"
    script.write_text("print('HIJACKED')\n")
    (shared / ".bundleup").chmod(0o777)  # anyone could have written it
    fresh = env_for(tmp_path / "victim")  # nothing unpacked in the user cache yet
    r = run(copy, fresh)
    assert r.returncode == 0 and "HIJACKED" not in r.stdout, r.stdout


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
    fake = relabel(bundle, tmp_path / "v.pyz", PYTHON=(3, 99), PYTHON_MAX=(3, 99))
    r = run(fake, env_for(tmp_path))
    assert r.returncode == 1
    assert "bundled for Python 3.99, but it's running on Python" in r.stderr
    assert "Traceback" not in r.stderr
    newer = relabel(bundle, tmp_path / "n.pyz", PYTHON=(3, 2), PYTHON_MAX=(3, 3))
    assert "Run it with Python 3.3 instead" in run(newer, env_for(tmp_path)).stderr


@pytest.mark.skipif(WINDOWS, reason="python3.X commands are a POSIX convention")
def test_the_wrong_python_reruns_with_a_matching_one(bundle: Path, tmp_path: Path) -> None:
    """`./app.pyz` runs whatever python3 is; with a matching python3.X on PATH the bundle runs
    itself again with it, once (third review: a versioned shebang failed on a stock Mac)."""
    here = f"{sys.version_info[0]}.{sys.version_info[1]}"
    other = next(
        (
            found
            for version in ("3.9", "3.10", "3.11", "3.13")
            if version != here
            and (found := subprocess.run(
                ["uv", "python", "find", version], capture_output=True, text=True, cwd=tmp_path
            ).stdout.strip())
        ),
        None,
    )  # fmt: skip
    if other is None:
        pytest.skip("needs a second Python")
    exact = relabel(bundle, tmp_path / "exact.pyz", PYTHON=sys.version_info[:2],
                    PYTHON_MAX=sys.version_info[:2])  # fmt: skip
    links = tmp_path / "bin"
    links.mkdir()
    (links / f"python{here}").symlink_to(base_python())
    env = env_for(tmp_path)
    env["PATH"] = f"{links}{os.pathsep}{env['PATH']}"
    r = run(exact, env, python=other)
    assert r.returncode == 0, r.stderr
    assert "RERUN" not in " ".join(json.loads(r.stdout)["env"])  # not passed on to children
    alone = env_for(tmp_path)  # no matching Python anywhere: the one-sentence error
    assert "bundled for Python" in run(exact, alone, python=other).stderr
    # Only an unversioned python3 of the right version, as Apple's /usr/bin/python3 is (fourth
    # review): asked for its version, then used.
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "python3").symlink_to(base_python())
    env = env_for(tmp_path)
    env["PATH"] = f"{plain}{os.pathsep}{env['PATH']}"
    r = run(exact, env, python=other)
    assert r.returncode == 0, r.stderr


def test_a_pure_python_bundle_runs_on_other_versions(bundle: Path, tmp_path: Path) -> None:
    """No compiled code: the bundle runs on every version the lock allows (ADR-0030), with
    bytecode compiled on first import for versions other than the build's."""
    with zipfile.ZipFile(bundle) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["target"]["python_range"]["max"] is None  # no upper limit
    assert manifest["target"]["any_os"] is True  # and any OS (ADR-0034)
    anywhere = relabel(bundle, tmp_path / "anywhere.pyz", PLATFORM=None)
    assert run(anywhere, env_for(tmp_path)).returncode == 0
    assert bundle.read_bytes().startswith(b"#!/usr/bin/env python3\n")
    if not os.path.exists(SYSTEM_PYTHON):
        pytest.skip("needs a second Python")
    version = [SYSTEM_PYTHON, "-c", "import sys; print(sys.version_info[:2])"]
    if subprocess.run(version, capture_output=True, text=True).stdout.strip() == str(
        sys.version_info[:2]
    ):
        pytest.skip(f"{SYSTEM_PYTHON} is the same version as the test Python")
    r = run(bundle, env_for(tmp_path), python=SYSTEM_PYTHON)
    assert r.returncode == 0, r.stderr
    # Under PYTHONDONTWRITEBYTECODE another version would compile on every start: what a run
    # imported gets bytecode for it at exit (seventh and eighth reviews), wherever that Python
    # looks for it (Apple's 3.9 sets sys.pycache_prefix under the home folder).
    cache = tmp_path / "nobytecode"
    env = env_for(tmp_path, BUNDLEUP_CACHE=str(cache), PYTHONDONTWRITEBYTECODE="1")
    tag = subprocess.run(
        [SYSTEM_PYTHON, "-c", "import sys; print(sys.implementation.cache_tag)"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    assert run(bundle, env, python=SYSTEM_PYTHON).returncode == 0
    assert list(tmp_path.rglob(f"*.{tag}.pyc"))
    assert verify(bundle).ok


def test_the_loader_picks_the_payload_that_fits(bundle: Path, tmp_path: Path) -> None:
    """A multi-platform bundle (ADR-0038): payloads for other machines are passed over."""
    with zipfile.ZipFile(bundle) as zf:
        dirname = json.loads(zf.read("manifest.json"))["cache_dir"]
    here = sys.version_info[:2]
    common = {"python": here, "python_max": here, "abiflags": None, "pth": [], "libc": None}
    elsewhere = {**common, "dirname": "x-0", "members": ["nothing.zip"], "platform": "sunos5",
                 "machine": None, "target": "Python on Solaris", "macos": None}  # fmt: skip
    fits = {**common, "dirname": dirname, "members": ["payload.zip"], "platform": None,
            "machine": None, "target": "Python here", "macos": None}  # fmt: skip
    multi = relabel(bundle, tmp_path / "multi.pyz", PAYLOADS=[elsewhere, fits])
    assert probe(multi, env_for(tmp_path))["argv"] == []
    nowhere = relabel(bundle, tmp_path / "nowhere.pyz", PAYLOADS=[elsewhere])
    r = run(nowhere, env_for(tmp_path))
    assert r.returncode == 1 and "bundled for Python on Solaris" in r.stderr


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


@pytest.mark.skipif(sys.platform not in ("darwin", "linux"), reason="glibc and macOS checks")
def test_too_old_system_is_explained(bundle: Path, tmp_path: Path) -> None:
    """A native wheel built for a newer glibc or macOS fails with one sentence (ADR-0029)."""
    if sys.platform == "darwin":
        fake = relabel(bundle, tmp_path / "old.pyz", MACOS=(99, 0))
        expected = "this app needs macOS 99.0 or newer"
    else:
        fake = relabel(bundle, tmp_path / "old.pyz", LIBC=("glibc", (99, 0)))
        expected = "bundled for Linux with glibc 99.0 or newer"
    r = run(fake, env_for(tmp_path))
    assert r.returncode == 1 and expected in r.stderr, r.stderr


def test_reproducible_payload(tmp_path: Path) -> None:
    src = tmp_path / "probe.py"
    src.write_text(PROBE)
    for name in ("one.pyz", "two.pyz"):
        args = ["build", str(src), "-o", str(tmp_path / name), "--python", sys.executable, "-q"]
        assert main(args) == 0
    assert (tmp_path / "one.pyz").read_bytes() == (tmp_path / "two.pyz").read_bytes()


def test_bundle_layout(bundle: Path) -> None:
    with zipfile.ZipFile(bundle) as zf:
        expected = ["__main__.py", "__main__.pyc", "manifest.json", "payload.zip"]
        assert sorted(zf.namelist()) == expected
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
    assert script_metadata(PROBE) == {"requires-python": ">=3.9", "dependencies": []}
    assert script_metadata("print('no block')") == {}


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


@pytest.mark.parametrize("name", ["_loader.py", "_runtime.py", "_sitecustomize.py"])
def test_loader_parses_on_any_python_3(name: str) -> None:
    """The loader must get far enough on an old Python to print "this app needs Python X"; the
    children's sitecustomize is imported by whatever Python the app starts."""
    source = (Path(bundleup.__file__).parent / name).read_text()
    ast.parse(source, feature_version=(3, 5))  # raises SyntaxError on newer-only syntax


SET_LITERALS = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
WORDS = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"}
def check(word: str) -> bool:
    return word in {"one", "two", "three", "four", "five", "six", "seven", "eight"}
print(check("two"), len(WORDS))
"""


def test_reproducible_with_and_without_the_bytecode_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set literals are stored in hash order, and string hashes are randomised per process: the
    bytecode must still be identical, whether compiled now or restored from the cache."""
    src = tmp_path / "sets.py"
    src.write_text(SET_LITERALS)
    outputs = []
    for name, cache in (("cold", "c1"), ("warm", "c1"), ("other", "c2")):
        monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(tmp_path / cache))
        out = tmp_path / f"{name}.pyz"
        assert main(["build", str(src), "-o", str(out), "--python", sys.executable, "-q"]) == 0
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1] == outputs[2]


def base_python() -> str:
    """A plain interpreter of the test's Python version (the test runs in a venv, and venvs
    hide the user's site-packages, which would make an isolation test pass vacuously)."""
    return getattr(sys, "_base_executable", sys.executable)


def plant_user_module(env: dict[str, str], tmp_path: Path) -> None:
    """Install a module into the user's site-packages, the way `pip install --user` would."""
    env["PYTHONUSERBASE"] = str(tmp_path / "userbase")
    where = subprocess.run(
        [base_python(), "-c", "import site; print(site.getusersitepackages())"],
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()
    Path(where).mkdir(parents=True)
    (Path(where) / "bundleup_planted.py").write_text("PLANTED = True\n")


@pytest.mark.parametrize(("inherit", "visible"), [(None, False), ("1", True)])
def test_machine_packages_are_hidden_unless_inherited(
    tmp_path: Path, inherit: str | None, visible: bool
) -> None:
    script = tmp_path / "isolation.py"
    script.write_text(
        '# /// script\n# requires-python = ">=3.9"\n# dependencies = []\n# ///\n'
        "import importlib.util\n"
        "print(importlib.util.find_spec('bundleup_planted') is not None)\n"
    )
    out = tmp_path / "isolation.pyz"
    assert main(["build", str(script), "-o", str(out), "--python", sys.executable, "-q"]) == 0
    env = env_for(tmp_path)
    plant_user_module(env, tmp_path)
    if inherit:
        env["BUNDLEUP_INHERIT_PATH"] = inherit
    r = run(out, env, python=base_python())
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(visible)


def test_pth_files_are_processed_like_site_py(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bundleup import _runtime

    (tmp_path / "extra").mkdir()
    lines = [
        "# a comment",
        "extra",
        "missing-directory",
        # Old namespace-package .pth files read `sitedir` from their caller's frame, as site.py's.
        "import sys; sys.modules['__g_sitedir__'] = sys._getframe(1).f_locals['sitedir']",
        "import nonexistent_module_for_this_test",
        "after-the-error",
    ]
    (tmp_path / "a.pth").write_text("\n".join(lines) + "\n")
    (tmp_path / "after-the-error").mkdir()
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "__g_sitedir__", raising=False)
    _runtime.add_pth(str(tmp_path), "a.pth", set())
    added = [p for p in sys.path if p.startswith(os.path.normcase(str(tmp_path)))]
    assert added == [os.path.normcase(str(tmp_path / "extra"))]
    assert sys.modules["__g_sitedir__"] == str(tmp_path)
    assert "error in a.pth line 5" in capsys.readouterr().err
    del sys.modules["__g_sitedir__"]
    (tmp_path / ".hidden.pth").write_text("")
    assert pth_files(tmp_path) == ["a.pth"]


TOOL = """\
import sys
import time

import acme_private  # from the bundle
import helper  # beside this script, as with plain python

print(acme_private.WHO, helper.NAME, sys.argv[1:])
"""


def test_entry_python_runs_scripts_beside_it_with_the_bundles_packages(
    tmp_path: Path, private_index: str
) -> None:
    """`--entry python` (a skill's dependencies for all its scripts): the bundle runs a script,
    `-m module` or `-c code` the way python does, with the bundle's packages importable."""
    (tmp_path / "deps.py").write_text(private_index)
    locked = subprocess.run(
        ["uv", "lock", "--script", "deps.py"], cwd=tmp_path, capture_output=True
    )
    assert locked.returncode == 0, locked.stderr
    out = tmp_path / "deps.pyz"
    result = build(BuildOptions(path=tmp_path / "deps.py", output=out, entry="python"))
    assert result.entry == "python"
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text(TOOL)
    (scripts / "helper.py").write_text('NAME = "helper"\n')
    env = env_for(tmp_path)

    def python(*args: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(out), *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tmp_path)

    r = python(str(scripts / "tool.py"), "--flag", "x")
    assert r.stdout.strip() == "the company index helper ['--flag', 'x']", r.stderr
    r = python("-c", "import acme_private, sys; print(acme_private.WHO, sys.argv)", "a")
    assert r.stdout.strip() == "the company index ['-c', 'a']", r.stderr
    r = python("-m", "acme_private", "b")
    assert r.stdout.strip() == "the company index ['b']", r.stderr
    r = python("--nope")
    assert r.returncode == 1 and "usage: python deps.pyz" in r.stderr
    r = python("-u", "x.py")  # an interpreter option: say where it goes
    assert r.returncode == 1 and "put it before the bundle, as in python -u deps.pyz" in r.stderr
    # A program on stdin, piped or with `-`, as python runs it (fourth review: a prompt opened).
    for args in ([], ["-", "z"]):
        done = subprocess.run(
            [sys.executable, str(out), *args],
            input="import acme_private, sys; print(acme_private.WHO, sys.argv)",
            capture_output=True, text=True, env=env, cwd=tmp_path,
        )  # fmt: skip
        assert done.stdout.strip() == f"the company index {['-', *args[1:]]}", done.stderr
    # Code from -c runs as the real __main__: pickle finds its classes.
    r = python(
        "-c", "import pickle\nclass A: pass\nprint(type(pickle.loads(pickle.dumps(A()))).__name__)"
    )
    assert r.stdout.strip() == "A", r.stderr
    # A script that starts a sibling with sys.executable: the sibling sees the bundle too.
    (scripts / "parent.py").write_text(
        "import os, subprocess, sys\n"
        "here = os.path.dirname(os.path.abspath(__file__))\n"
        "subprocess.run([sys.executable, os.path.join(here, 'tool.py'), 'child'], check=True)\n"
    )
    r = python(str(scripts / "parent.py"))
    assert r.stdout.strip() == "the company index helper ['child']", r.stderr


def test_entry_python_is_for_a_pyz(tmp_path: Path) -> None:
    (tmp_path / "deps.py").write_text("# /// script\n# dependencies = []\n# ///\n")
    with pytest.raises(UsageError, match=r"--entry python makes a \.pyz"):
        build(BuildOptions(path=tmp_path / "deps.py", format="dir", entry="python"))


def test_no_warnings_under_dev_mode(bundle: Path, tmp_path: Path) -> None:
    """`python -X dev -W error` (as test suites like click's run): the loader leaves no file open
    at exit, cold or warm."""
    env = env_for(tmp_path)
    for _ in ("cold", "warm"):
        r = subprocess.run(
            [sys.executable, "-X", "dev", "-W", "error", str(bundle)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0 and "Warning" not in r.stderr, r.stderr


def test_an_undeclared_import_is_refused_with_the_way_to_declare_it(tmp_path: Path) -> None:
    """A script without a `# /// script` block or requirements.txt that imports a package: the
    refusal names it and says how to declare it (it used to blame the Python)."""
    (tmp_path / "tool.py").write_text("import six\n")
    with pytest.raises(
        bundleup.ProjectError, match="imports six, which isn't in the standard"
    ) as e:
        build(BuildOptions(path=tmp_path / "tool.py"))
    assert e.value.hint is not None and "uv add --script tool.py" in e.value.hint


CHILD_ON_STDIN = """\
import subprocess, sys
code = "import sys, acme_private; print(acme_private.WHO, 'importlib' in sys.modules)"
for args in ([sys.executable, "-"], [sys.executable]):
    done = subprocess.run(args, input=code, capture_output=True, text=True)
    print(done.stdout.strip() or done.stderr.strip().splitlines()[-1])
"""


def test_a_child_reading_its_program_from_stdin_sees_the_bundle(
    tmp_path: Path, private_index: str
) -> None:
    """`python -` (click's test suite) or python with piped input, started by the bundle's
    program: the program's own code, so it sees the bundle, like `-c` (nightly suites,
    2026-10-08). It loads importlib only if plain Python does (Ubuntu's own sitecustomize)."""
    (tmp_path / "deps.py").write_text(private_index)
    locked = subprocess.run(
        ["uv", "lock", "--script", "deps.py"], cwd=tmp_path, capture_output=True
    )
    assert locked.returncode == 0, locked.stderr
    out = tmp_path / "deps.pyz"
    build(BuildOptions(path=tmp_path / "deps.py", output=out, entry="python"))
    env = env_for(tmp_path)
    plain = subprocess.run(
        [sys.executable, "-c", "import sys; print('importlib' in sys.modules)"],
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()
    r = run(out, env, "-c", CHILD_ON_STDIN)
    assert r.stdout.splitlines() == [f"the company index {plain}"] * 2, r.stderr + r.stdout


@pytest.mark.skipif(WINDOWS, reason="pruning needs file locks to tell a copy in use")
def test_unpacking_prunes_old_unused_copies_of_the_same_bundle(
    bundle: Path, tmp_path: Path
) -> None:
    """End users can't run `bundleup cache clean`: a new copy removes older copies of the same
    bundle unused for 30 days, unless a running program holds one (fourth review)."""
    import fcntl

    cache = tmp_path / "cache"
    cache.mkdir()
    month = time.time() - 40 * 86400

    def copy(digest: str, age: float) -> Path:
        path = cache / f"probe-{digest}"
        (path / "pkg").mkdir(parents=True)
        os.utime(path, (age, age))
        return path

    old, recent, held, other = (
        copy("0" * 16, month),
        copy("1" * 16, time.time()),
        copy("2" * 16, month),
        cache / f"other-{'3' * 16}",
    )
    other.mkdir()
    os.utime(other, (month, month))
    lock = open(cache / f".lock-{held.name}", "a+b")  # noqa: SIM115  # held for the test's length
    fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
    try:
        assert probe(bundle, env_for(tmp_path, BUNDLEUP_CACHE=str(cache)))
    finally:
        lock.close()
    assert not old.exists() and recent.exists() and held.exists() and other.exists()


def test_a_noexec_cache_is_skipped_for_native_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A filesystem mounted noexec can't load compiled modules (a hardened container's /tmp broke
    pex's scies, rounds 6 and 7): a bundle with native code skips such cache folders. The real
    mount is a gauntlet condition on Linux CI."""
    from bundleup import _loader

    noexec = 8

    class Stat:
        f_flag = noexec

    monkeypatch.setattr(_loader.os, "ST_NOEXEC", noexec, raising=False)
    monkeypatch.setattr(_loader.os, "statvfs", lambda path: Stat(), raising=False)
    monkeypatch.setattr(_loader, "ABIFLAGS", "")  # native code
    assert not _loader._loads_code(str(tmp_path / "not-yet-created"))
    monkeypatch.setattr(_loader, "ABIFLAGS", None)  # pure Python: any folder will do
    assert _loader._loads_code(str(tmp_path))


def test_rebuilding_after_editing_source_picks_up_the_change(tmp_path: Path) -> None:
    """uv keys cached wheels of local directories on pyproject.toml alone, so without
    `--refresh-package` for local packages a second build after editing `src/` bundled old code."""
    proj = tmp_path / "proj"
    (proj / "src" / "proj").mkdir(parents=True)
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "proj"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
        'dependencies = []\n[project.scripts]\nproj = "proj:main"\n'
        '[build-system]\nrequires = ["uv_build>=0.12,<0.13"]\nbuild-backend = "uv_build"\n'
    )
    init = proj / "src" / "proj" / "__init__.py"
    init.write_text('def main(): print("v1")\n')
    assert subprocess.run(["uv", "lock"], cwd=proj, capture_output=True).returncode == 0
    first = build(BuildOptions(path=proj, output=proj / "a.pyz", smoke=()))
    assert first.smoke is not None and first.smoke.output.strip() == "v1"
    init.write_text('def main(): print("v2")\n')
    second = build(BuildOptions(path=proj, output=proj / "b.pyz", smoke=()))
    assert second.smoke is not None and second.smoke.output.strip() == "v2"


def test_bundleup_checks_itself_cleanly() -> None:
    """Self-hosting: `bundleup check --strict .` on this repository finds no errors or warnings."""
    report = bundleup.check(BuildOptions(path=Path(__file__).parent.parent, strict=True))
    assert report.ok and report.diagnostics == []


def test_bytecode_compilation_is_deterministic_and_cached_across_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ninth review: `-I` implied `-E` in CPython and ignored `PYTHONHASHSEED=0`, making frozen
    frozenset constants depend on OS randomness; and non-RECORD `.py` files weren't cached."""
    from bundleup._steps import ProgressEvent

    monkeypatch.setenv("BUNDLEUP_CACHE", str(tmp_path / "cache"))
    script = tmp_path / "app.py"
    script.write_text(
        "# /// script\n# dependencies = []\n# ///\n"
        "S = frozenset({'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta'})\n"
        "print(sorted(S)[0])\n"
    )
    a = build(BuildOptions(path=script, output=tmp_path / "a.pyz")).output.read_bytes()
    monkeypatch.setenv("BUNDLEUP_CACHE", str(tmp_path / "cache2"))
    b = build(BuildOptions(path=script, output=tmp_path / "b.pyz")).output.read_bytes()
    assert a == b

    # Warm build with the same cache: compiling bytecode spawns no py_compile subprocess.
    events: list[ProgressEvent] = []
    build(BuildOptions(path=script, output=tmp_path / "c.pyz"), progress=events.append)
    compile_cmds = [e for e in events if e.kind == "command" and "py_compile" in e.text]
    assert compile_cmds == []


def test_a_bundle_replaced_while_it_starts_is_not_unpacked_under_its_name(tmp_path: Path) -> None:
    """Twelfth review: the loader reopens its file by path to unpack it. Replaced by another
    build in the meantime (an update), that build's payload was unpacked under this build's name,
    and every later run of this build ran the other's code."""
    script = tmp_path / "tool.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('first')\n")
    first = tmp_path / "first.pyz"
    assert main(["build", str(script), "-o", str(first), "-q"]) == 0
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint('second')\n")
    second = tmp_path / "second.pyz"
    assert main(["build", str(script), "-o", str(second), "-q"]) == 0
    mixed = tmp_path / "mixed.pyz"  # what the first build's loader reads once the file was swapped
    with zipfile.ZipFile(first) as old, zipfile.ZipFile(second) as new, open(mixed, "wb") as f:
        f.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("__main__.py", old.read("__main__.py"))
            zf.writestr("payload.zip", new.read("payload.zip"))
    env = env_for(tmp_path)
    done = run(mixed, env)
    assert done.returncode == 1 and "was replaced" in done.stderr, done.stderr
    assert run(first, env).stdout.strip() == "first"  # its own copy is still its own


def test_a_tilde_in_bundleup_cache_means_home(bundle: Path, tmp_path: Path) -> None:
    """Twelfth review: `BUNDLEUP_CACHE='~/cache'` made a folder named `~` in the working
    directory, so every folder a bundle ran from got its own copy."""
    env = env_for(tmp_path, BUNDLEUP_CACHE="~/bundles")
    env["USERPROFILE"] = env["HOME"]  # where Windows' expanduser looks
    done = subprocess.run(
        [sys.executable, str(bundle)], env=env, capture_output=True, text=True, cwd=tmp_path
    )
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "home" / "bundles").is_dir() and not (tmp_path / "~").exists()


@pytest.mark.skipif(WINDOWS, reason="abandoned unpacks are pruned on POSIX only")
def test_an_unpack_abandoned_by_a_killed_run_is_removed(bundle: Path, tmp_path: Path) -> None:
    """Twelfth review: a first run killed while unpacking left its temporary folder (170 MB in
    a test), and only `bundleup cache clean` removed it, which people who run bundles don't
    have. The next unpack of the same bundle removes it once its process is gone."""
    cache = tmp_path / "cache"
    env = env_for(tmp_path, BUNDLEUP_CACHE=str(cache))
    assert run(bundle, env).returncode == 0
    (copy,) = [p for p in cache.iterdir() if not p.name.startswith(".")]
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    abandoned = cache / f".tmp-{copy.name}-{gone.pid}-0123abcd"
    (abandoned / "pkg").mkdir(parents=True)
    old = time.time() - 120
    os.utime(abandoned, (old, old))
    shutil.rmtree(copy)  # so the next run unpacks
    assert run(bundle, env).returncode == 0
    assert copy.is_dir() and not abandoned.exists()


def test_a_missing_module_is_one_line_as_python_says_it(tmp_path: Path) -> None:
    """Twelfth review: `bundle.pyz -m nonexistent` printed a 15-line traceback through the
    loader; plain Python prints one line."""
    script = tmp_path / "tool.py"
    script.write_text("print('hi')\n")
    out = tmp_path / "py.pyz"
    assert main(["build", str(script), "--entry", "python", "-o", str(out), "-q"]) == 0
    done = run(out, env_for(tmp_path), "-m", "no_such_module_here")
    assert done.returncode == 1
    assert "No module named" in done.stderr and "Traceback" not in done.stderr, done.stderr


@pytest.mark.skipif(WINDOWS, reason="POSIX signals")
def test_ctrl_c_exits_as_an_interrupted_python_does(tmp_path: Path) -> None:
    """Twelfth review: with PYTHONDONTWRITEBYTECODE set, the bundle writes bytecode at exit,
    and the imports that did it lost Ctrl-C's exit status on Python 3.9-3.12 (exit 1)."""
    import signal

    script = tmp_path / "wait.py"
    script.write_text(
        "# /// script\n# dependencies = []\n# ///\n"
        "import sys, time\nprint('ready', flush=True)\ntime.sleep(30)\n"
    )
    out = tmp_path / "wait.pyz"
    assert main(["build", str(script), "-o", str(out), "-q"]) == 0
    env = env_for(tmp_path, PYTHONDONTWRITEBYTECODE="1")
    child = subprocess.Popen(
        [sys.executable, "-O", str(out)], env=env, stdout=subprocess.PIPE, text=True
    )
    assert child.stdout and child.stdout.readline().strip() == "ready"
    child.send_signal(signal.SIGINT)
    child.communicate(timeout=30)
    assert child.returncode in (-signal.SIGINT, 130)


def _apple_prefix() -> bool:
    """Whether macOS's own Python is here and keeps bytecode under a prefix of its own."""
    if not os.path.exists(SYSTEM_PYTHON) or sys.platform != "darwin":
        return False
    done = subprocess.run(
        [SYSTEM_PYTHON, "-s", "-S", "-c", "import sys; print(sys.pycache_prefix or '')"],
        capture_output=True,
        text=True,
    )
    return done.returncode == 0 and bool(done.stdout.strip())


@pytest.mark.skipif(not _apple_prefix(), reason="needs macOS's /usr/bin/python3 and its prefix")
def test_a_bundle_built_with_macos_own_python_carries_its_bytecode(tmp_path: Path) -> None:
    """Twelfth review: Apple's Python keeps bytecode under ~/Library/Caches/com.apple.python
    unless told otherwise, so a build with it compiled everything there and bundled no .pyc."""
    script = tmp_path / "tool.py"
    script.write_text('# /// script\n# requires-python = ">=3.9"\n# dependencies = []\n# ///\n')
    out = tmp_path / "tool.pyz"
    assert main(["build", str(script), "-o", str(out), "--python", SYSTEM_PYTHON, "-q"]) == 0
    with zipfile.ZipFile(out) as outer, zipfile.ZipFile(outer.open("payload.zip")) as payload:
        assert any(name.endswith(".pyc") for name in payload.namelist())
