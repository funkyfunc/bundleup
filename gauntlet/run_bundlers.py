"""Build every gauntlet project with each bundler, run the result, and record what happens.

The existing tools all get the same inputs: the project's locked dependencies exported from uv.lock
(or the PEP 723 header) plus the project itself built as a wheel. bundleup is given the project
directory (or script) directly, so its build time also includes the export and the project build.
Each bundle is built with the target Python, then run with that Python from an empty directory, a
fresh HOME, and network access denied where the platform allows it (macOS: sandbox-exec; Linux:
`sudo unshare --net`, as on CI runners; Windows: not blocked, recorded per result), cold then warm.

Usage:
    uv run gauntlet/run_bundlers.py                         # everything, Python 3.9 + 3.12
    uv run gauntlet/run_bundlers.py --tool pex --python 3.12 05 13
    uv run gauntlet/run_bundlers.py --conditions            # also run hostile conditions
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import concurrent.futures as cf
import functools
import getpass
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).parent
PROJECTS = ROOT / "projects"
WORK = ROOT / ".work"
RESULTS = ROOT / "results"
SNAPSHOT = ROOT / "snapshot.py"

# Tool name -> the pinned package uvx runs it from (None: not run through uvx).
TOOLS: dict[str, str | None] = {
    "pex": "pex==2.103.4",
    "shiv": "shiv==1.0.8",
    "zipapps": "zipapps==2026.4.17",
    "zipapp-naive": None,
    "bundleup": None,
}
WINDOWS = sys.platform == "win32"
# This repo's bundleup, installed by `uv sync`.
BUNDLEUP = ROOT.parent / ".venv" / ("Scripts/bundleup.exe" if WINDOWS else "bin/bundleup")
DEFAULT_PYTHONS = ["3.9", "3.12"]
# The "user's Python" for a version, where the OS ships one worth testing; otherwise uv-managed.
SYSTEM_PYTHONS = {"darwin": {"3.9": "/usr/bin/python3"}}
NO_NETWORK = "(version 1)(allow default)(deny network*)"  # macOS sandbox-exec profile
# Outcomes that mean "the project didn't do what gauntlet.toml says it should" (see --check).
UNEXPECTED = {"run-fail", "build-fail", "late-fail", "harness-error"}
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 300

Meta = dict[str, Any]  # a project's gauntlet.toml plus derived keys; Any: TOML values


@dataclass
class Result:
    tool: str
    project: str
    python: str
    condition: str = "base"
    outcome: str = ""  # pass | build-fail | run-fail | refused | late-fail | skipped
    expected: str = "pass"
    build_s: float | None = None
    size_bytes: int | None = None
    cold_s: float | None = None
    warm_s: float | None = None
    error_kind: str = ""
    detail: str = ""
    extra: list[str] = field(default_factory=list)
    network_blocked: bool = True


@dataclass(frozen=True)
class Inputs:
    """What the existing tools are given: pinned requirements, built wheels, a script's folder."""

    reqs: Path
    wheels: list[Path]
    script_dir: Path | None


@dataclass(frozen=True)
class Run:
    """One run of a bundle."""

    ok: bool
    elapsed: float
    output: str  # stderr, or stdout if stderr is empty
    stdout_lines: list[str]


def sh(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = BUILD_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


@functools.cache
def python_path(version: str) -> str:
    """The interpreter bundles are built with and run on: never a virtual environment.

    Inside this repo, `uv python find` returns the repo's own .venv, whose site-packages (bundleup's
    dependencies) could mask a package missing from a bundle. So ask from outside the repo, for a
    uv-managed Python, and refuse anything that turns out to be a venv.
    """
    system = SYSTEM_PYTHONS.get(sys.platform, {}).get(version)
    if system and Path(system).exists():
        return system
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    found = sh(
        ["uv", "python", "find", version, "--managed-python"],
        cwd=Path(tempfile.gettempdir()),
        env=env,
    )
    exe = found.stdout.strip()
    if found.returncode or not exe:
        raise RuntimeError(f"no uv-managed Python {version}; run: uv python install {version}")
    is_venv = sh([exe, "-c", "import sys; print(sys.prefix != sys.base_prefix)"]).stdout.strip()
    if is_venv != "False":
        raise RuntimeError(f"{exe} is a virtual environment; the gauntlet needs a plain Python")
    return exe


@functools.cache
def network_blocker() -> str | None:
    """How this machine can run a process without network: "sandbox-exec", "unshare" or None."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if sys.platform.startswith("linux") and shutil.which("unshare") and shutil.which("sudo"):
        # Needs passwordless sudo (CI runners have it). A user-namespace `unshare -rn` would be
        # simpler, but its fake root can write to read-only directories, which defeats the
        # read-only hostile conditions.
        if sh(["sudo", "-n", "unshare", "--net", "true"], timeout=30).returncode == 0:
            return "unshare"
    return None


def without_network(cmd: list[str], env: dict[str, str]) -> list[str]:
    """Wrap a command so it runs with no network access, if this machine supports that."""
    blocker = network_blocker()
    if blocker == "sandbox-exec":
        return ["sandbox-exec", "-p", NO_NETWORK, *cmd]
    if blocker == "unshare":
        # sudo resets the environment, so pass it explicitly to the dropped-back-to-us command.
        user = ["sudo", "-n", "-u", getpass.getuser(), "--"]
        return ["sudo", "-n", "unshare", "--net", "--", *user, "env", "-i",
                *(f"{k}={v}" for k, v in env.items()), *cmd]  # fmt: skip
    return cmd


def run_env(home: Path) -> dict[str, str]:
    """A minimal environment with a fresh HOME (and on Windows, fresh profile directories)."""
    tmp = home / "tmp"
    env = {"HOME": str(home), "TMPDIR": str(tmp), "LANG": "en_US.UTF-8"}
    if WINDOWS:
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env |= {
            "SYSTEMROOT": system_root,  # Python can't start without it
            # Always set in a real session; the loader reads the CPU from it.
            "PROCESSOR_ARCHITECTURE": os.environ.get("PROCESSOR_ARCHITECTURE", ""),
            "PATH": rf"{system_root}\System32",
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TEMP": str(tmp),
            "TMP": str(tmp),
        }
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


def load(project: Path) -> Meta:
    meta = tomllib.loads((project / "gauntlet.toml").read_text())
    if "script" in meta:
        header = (project / meta["script"]).read_text()
        found = re.search(r'requires-python = "([^"]+)"', header)
        if found is None:
            raise ValueError(f"{project.name}: the script has no requires-python")
        meta["requires_python"] = found.group(1)
        meta["entry"] = f"{Path(meta['script']).stem}:main"
    else:
        pyproject = tomllib.loads((project / "pyproject.toml").read_text())
        meta["requires_python"] = pyproject["project"]["requires-python"]
    return meta


def prepare(project: Path, meta: Meta, stage: Path) -> Inputs:
    """Export pinned requirements and build first-party code as wheels."""
    stage.mkdir(parents=True, exist_ok=True)
    reqs = stage / "requirements.txt"
    flags = ["--frozen", "--no-hashes", "--no-header", "--no-annotate", "-o", str(reqs)]
    if "script" in meta:
        sh(["uv", "export", "--script", meta["script"], *flags[1:]], cwd=project).check_returncode()
        script_dir = stage / "script"
        script_dir.mkdir(exist_ok=True)
        shutil.copy(project / meta["script"], script_dir)
        return Inputs(reqs, [], script_dir)
    no_project = ["--no-dev", "--no-emit-project", "--no-emit-workspace"]
    sh(["uv", "export", *flags, *no_project], cwd=project).check_returncode()
    wheels = stage / "wheels"
    build = ["uv", "build", "--wheel", "--all-packages", "-q", "-o", str(wheels)]
    sh(build, cwd=project).check_returncode()
    return Inputs(reqs, sorted(wheels.glob("*.whl")), None)


def build_command(tool: str, py: str, *, inputs: Inputs, entry: str, out: Path) -> list[str]:
    package = TOOLS[tool]
    if package is None:
        raise ValueError(f"{tool} isn't run through uvx")
    uvx = ["uvx", "--python", py, "--from", package]
    wheels = [str(p) for p in inputs.wheels]
    reqs = ["-r", str(inputs.reqs)]
    script_dir = inputs.script_dir
    if tool == "pex":
        src = ["-D", str(script_dir)] if script_dir else []
        return [*uvx, "pex", *wheels, *src, *reqs, "-e", entry, "-o", str(out)]
    if tool == "shiv":
        src = ["--site-packages", str(script_dir)] if script_dir else []
        shebang = ["-p", "/usr/bin/env python3"]
        return [*uvx, "shiv", *wheels, *src, *reqs, "-e", entry, "-o", str(out), *shebang]
    if tool == "zipapps":
        src = ["-a", str(next(script_dir.glob("*.py")))] if script_dir else []
        native = ["-c", "-u", "AUTO"]  # zipapps' documented way to handle compiled extensions
        uv = ["--uv", shutil.which("uv") or "uv"]
        zipapps = ["python", "-m", "zipapps", *native, "-m", entry, "-o", str(out)]
        return [*uvx, *zipapps, *src, *uv, *reqs, *wheels]
    raise ValueError(tool)


def build_naive(
    py: str, *, inputs: Inputs, entry: str, out: Path, stage: Path
) -> subprocess.CompletedProcess[str]:
    """What most people try first: pip install --target, add a __main__.py, run stdlib zipapp."""
    target = stage / "naive-site"
    shutil.rmtree(target, ignore_errors=True)
    wheels = [str(p) for p in inputs.wheels]
    install = ["uv", "pip", "install", "-q", "--python", py, "--target", str(target)]
    r = sh([*install, "-r", str(inputs.reqs), *wheels])
    if r.returncode:
        return r
    if inputs.script_dir:
        shutil.copytree(inputs.script_dir, target, dirs_exist_ok=True)
    module, func = entry.split(":")
    main = f"import sys\nfrom {module} import {func}\nsys.exit({func}())\n"
    (target / "__main__.py").write_text(main)
    return sh([py, "-m", "zipapp", str(target), "-o", str(out)])


def classify(text: str) -> str:
    for kind in (
        "ModuleNotFoundError",
        "PackageNotFoundError",
        "FileNotFoundError",
        "NotADirectoryError",
        "SyntaxError",
        "ImportError",
        "PermissionError",
        "AssertionError",
        "OSError",
        "TimeoutExpired",
    ):
        if kind in text:
            return kind
    return "other"


def run_bundle(
    py: str,
    bundle: Path,
    *,
    args: list[str],
    home: Path,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> Run:
    env = run_env(home) | (extra_env or {})
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    cmd = without_network([py, str(bundle), *args], env)
    start = time.perf_counter()
    try:
        r = sh(cmd, cwd=cwd, env=env, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return Run(False, RUN_TIMEOUT, "TimeoutExpired", [])
    elapsed = time.perf_counter() - start
    output = (r.stderr or r.stdout).strip()
    return Run(r.returncode == 0, elapsed, output, r.stdout.strip().splitlines())


def fresh_dirs(base: Path, name: str) -> tuple[Path, Path]:
    home, cwd = base / f"{name}-home", base / f"{name}-cwd"
    for d in (home, cwd):
        if d.exists():
            for p in d.rglob("*"):
                if p.is_dir():
                    p.chmod(0o755)
            shutil.rmtree(d)
        d.mkdir(parents=True)
    return home, cwd


def one(tool: str, project: Path, version: str, conditions: bool) -> list[Result]:
    """Build one project with one tool for one Python, run it, and optionally run hostile cases."""
    meta = load(project)
    res = Result(tool, meta["id"], version, network_blocked=network_blocker() is not None)
    if version not in SpecifierSet(meta["requires_python"]):
        below = meta.get("expect_refuse_below")
        if not below:
            res.outcome, res.detail = "skipped", f"requires {meta['requires_python']}"
            return [res]
        res.expected = "refuse"
    py = python_path(version)
    stage = WORK / tool / meta["id"] / version
    shutil.rmtree(stage, ignore_errors=True)
    out = stage / ("app.pex" if tool == "pex" else "app.pyz")

    inputs = None
    if tool != "bundleup":
        try:
            inputs = prepare(project, meta, stage / "inputs")
        except subprocess.CalledProcessError as e:
            res.outcome, res.detail = "build-fail", f"input preparation failed: {e}"
            return [res]

    start = time.perf_counter()
    try:
        if inputs is None:  # bundleup reads the project itself
            src = project / meta["script"] if "script" in meta else project
            b = sh([str(BUNDLEUP), "build", str(src), "--python", py, "-o", str(out), "--quiet"])
        elif tool == "zipapp-naive":
            b = build_naive(py, inputs=inputs, entry=meta["entry"], out=out, stage=stage)
        else:
            b = sh(build_command(tool, py, inputs=inputs, entry=meta["entry"], out=out))
    except subprocess.TimeoutExpired:
        res.outcome, res.error_kind = "build-fail", "TimeoutExpired"
        return [res]
    res.build_s = round(time.perf_counter() - start, 2)
    if b.returncode or not out.exists():
        text = (b.stderr or b.stdout).strip()
        res.outcome = "refused" if res.expected == "refuse" else "build-fail"
        res.error_kind, res.detail = classify(text), text[-1200:]
        return [res]
    res.size_bytes = out.stat().st_size

    args = meta.get("args", [])
    home, cwd = fresh_dirs(stage, "base")
    cold = run_bundle(py, out, args=args, home=home, cwd=cwd)
    ok = cold.ok and f"GAUNTLET OK {meta['id']}" in "\n".join(cold.stdout_lines)
    res.cold_s = round(cold.elapsed, 2)
    res.extra = [s for s in cold.stdout_lines if "=" in s and not s.startswith("GAUNTLET")]
    if ok:
        warm = run_bundle(py, out, args=args, home=home, cwd=cwd)
        res.warm_s = round(warm.elapsed, 2) if warm.ok else None
        res.outcome = "pass" if res.expected == "pass" else "late-fail"
    else:
        res.outcome = "late-fail" if res.expected == "refuse" else "run-fail"
        res.error_kind, res.detail = classify(cold.output), cold.output[-1200:]
    results = [res]
    if conditions and res.outcome == "pass":
        results += hostile(tool, meta, py=py, version=version, bundle=out, stage=stage)
        if tool == "bundleup":
            results.append(matches_venv(project, meta, py=py, version=version, stage=stage))
    return results


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if WINDOWS else "bin/python")


def install_normally(project: Path, meta: Meta, *, py: str, venv: Path) -> None:
    """Install the project the way its users would without bundleup: `uv sync` (or, for a PEP 723
    script, its exported dependencies into a fresh venv)."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    if "script" not in meta:
        env["UV_PROJECT_ENVIRONMENT"] = str(venv)
        sync = ["uv", "sync", "--frozen", "--no-dev", "--no-editable", "--python", py, "-q"]
        sh(sync, cwd=project, env=env).check_returncode()
        return
    sh(["uv", "venv", "-q", "--python", py, str(venv)], env=env).check_returncode()
    flags = ["--no-hashes", "--no-header", "--no-annotate", "-q"]
    if (project / f"{meta['script']}.lock").exists():
        flags.append("--frozen")  # a script without dependencies has no lockfile
    export = sh(["uv", "export", "--script", meta["script"], *flags], cwd=project, env=env)
    export.check_returncode()
    if export.stdout.strip():
        reqs = venv.parent / "venv-requirements.txt"
        reqs.write_text(export.stdout)
        install = [
            "uv",
            "pip",
            "install",
            "-q",
            "--python",
            str(venv_python(venv)),
            "-r",
            str(reqs),
        ]
        sh(install, env=env).check_returncode()


def matches_venv(project: Path, meta: Meta, *, py: str, version: str, stage: Path) -> Result:
    """Compare the bundle's packages with a normal install: same distributions and versions, same
    entry points, and the same top-level modules import (docs/testing-strategy.md)."""
    res = Result("bundleup", meta["id"], version, condition="matches-venv")
    res.network_blocked = network_blocker() is not None
    try:
        venv = stage / "venv"
        install_normally(project, meta, py=py, venv=venv)
        purelib = "import sysconfig; print(sysconfig.get_paths()['purelib'])"
        venv_site = sh([str(venv_python(venv)), "-c", purelib]).stdout.strip()
        normal = sh([str(venv_python(venv)), str(SNAPSHOT), venv_site])
        cache = stage / "venv-cache"
        home, cwd = fresh_dirs(stage, "venv-compare")
        extra = {"BUNDLEUP_CACHE": str(cache)}
        bundle = stage / "app.pyz"
        run_bundle(py, bundle, args=meta.get("args", []), home=home, cwd=cwd, extra_env=extra)
        extracted = next(p for p in cache.iterdir() if not p.name.startswith("."))
        bundled = sh([py, "-S", str(SNAPSHOT), str(extracted), "--as-bundle"])
    except (subprocess.CalledProcessError, StopIteration, OSError) as e:
        res.outcome, res.error_kind, res.detail = "run-fail", "harness", repr(e)
        return res
    if normal.returncode or bundled.returncode:
        res.outcome, res.error_kind = "run-fail", "snapshot-failed"
        res.detail = (normal.stderr + bundled.stderr)[-1200:]
        return res
    differences = compare_snapshots(json.loads(normal.stdout), json.loads(bundled.stdout))
    res.outcome = "run-fail" if differences else "pass"
    if differences:
        res.error_kind, res.detail = "mismatch", "\n".join(differences)[-1200:]
    return res


def compare_snapshots(normal: dict[str, Any], bundled: dict[str, Any]) -> list[str]:
    """Readable differences between a venv snapshot and a bundle snapshot."""
    differences = []
    for key in ("distributions", "entry_points"):
        venv_only = [x for x in normal[key] if x not in bundled[key]]
        bundle_only = [x for x in bundled[key] if x not in normal[key]]
        differences += [f"{key}: only in the venv: {x}" for x in venv_only]
        differences += [f"{key}: only in the bundle: {x}" for x in bundle_only]
    for name in sorted(set(normal["imports"]) | set(bundled["imports"])):
        a, b = normal["imports"].get(name, "absent"), bundled["imports"].get(name, "absent")
        if a != b:
            differences.append(f"import {name}: venv {a}, bundle {b}")
    return differences


def plant_shadows(py: str, bundle: Path, home: Path) -> None:
    """Put a broken copy of each of the bundle's top-level modules in the user's site-packages."""
    where = sh([py, "-c", "import site; print(site.getusersitepackages())"], env=run_env(home))
    user_site = Path(where.stdout.strip())
    with zipfile.ZipFile(bundle) as zf:
        files = json.loads(zf.read("manifest.json"))["files"]
    names = {
        name.split("/")[0].split(".")[0]
        for name in files
        if name.endswith((".py", ".so", ".pyd"))
        and not name.split("/")[0].endswith(".dist-info")
        and not name.startswith("__bundleup_script__")
    }
    for name in names:
        package = user_site / name
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text(
            "raise ImportError('a stale copy in the user site-packages was imported')\n"
        )


OTHER_PYTHONS = ["3.9", "3.10", "3.11", "3.12", "3.13"]


def in_range_pythons(bundle: Path, built_for: str) -> list[str]:
    """Other installed Pythons a bundleup bundle's manifest says it runs on."""
    with zipfile.ZipFile(bundle) as zf:
        span = json.loads(zf.read("manifest.json"))["target"].get("python_range") or {}
    if not span:
        return []

    def key(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    found = []
    for other in OTHER_PYTHONS:
        if other == built_for or key(other) < key(span["min"]):
            continue
        if span["max"] and key(other) > key(span["max"]):
            continue
        try:
            python_path(other)
        except RuntimeError:
            continue  # not installed here
        found.append(other)
    return found


def hostile(
    tool: str, meta: Meta, *, py: str, version: str, bundle: Path, stage: Path
) -> list[Result]:
    """Re-run a passing bundle under conditions that commonly break bundles."""
    out: list[Result] = []
    marker = f"GAUNTLET OK {meta['id']}"
    args = meta.get("args", [])

    def passed(run: Run) -> bool:
        return run.ok and marker in "\n".join(run.stdout_lines)

    def record(condition: str, run: Run) -> None:
        r = Result(tool, meta["id"], version, condition=condition)
        r.network_blocked = network_blocker() is not None
        r.outcome, r.cold_s = ("pass" if passed(run) else "run-fail"), round(run.elapsed, 2)
        if not passed(run):
            r.error_kind, r.detail = classify(run.output), run.output[-800:]
        out.append(r)

    # 1. Bundle and working directory under a path with spaces and non-ASCII characters.
    weird = stage / "my apps" / "ünïcødé dir"
    weird.mkdir(parents=True, exist_ok=True)
    copy = weird / bundle.name
    shutil.copy(bundle, copy)
    home, _ = fresh_dirs(stage, "weird")
    record("path-with-spaces", run_bundle(py, copy, args=args, home=home, cwd=weird))

    # 2. Two cold starts at the same time sharing one HOME (first-run extraction race).
    home, cwd = fresh_dirs(stage, "race")
    with cf.ThreadPoolExecutor(2) as pool:
        runs = list(
            pool.map(lambda _: run_bundle(py, bundle, args=args, home=home, cwd=cwd), range(2))
        )
    record("concurrent-first-run", next((r for r in runs if not passed(r)), runs[0]))

    # A broken copy of every top-level package in the user's site-packages, like an old
    # `pip install --user`: the bundle must not see it (ADR-0021). Not tested with
    # BUNDLEUP_INHERIT_PATH=1: there, a stale *regular* package beats a bundle's namespace
    # package (PEP 420), whatever the order (gauntlet 08 shows it).
    if tool == "bundleup":
        home, cwd = fresh_dirs(stage, "usersite")
        plant_shadows(py, bundle, home)
        record("user-site-conflict", run_bundle(py, bundle, args=args, home=home, cwd=cwd))

        # A cache on a filesystem mounted noexec (a hardened container's /tmp): compiled modules
        # can't load from it, so a native bundle must use another cache folder (rounds 6 and 7).
        # CI mounts one on Linux and names it in BUNDLEUP_GAUNTLET_NOEXEC.
        noexec = os.environ.get("BUNDLEUP_GAUNTLET_NOEXEC")
        if noexec and Path(noexec).is_dir():
            home, cwd = fresh_dirs(stage, "noexec")
            cache = Path(noexec) / f"cache-{os.getpid()}-{bundle.stem}"
            env = {"BUNDLEUP_CACHE": str(cache)}
            record(
                "noexec-cache", run_bundle(py, bundle, args=args, home=home, cwd=cwd, extra_env=env)
            )

        # A pure-Python bundle runs on every version in its range (ADR-0030): run it on each other
        # installed Python the manifest allows.
        for other in in_range_pythons(bundle, version):
            home, cwd = fresh_dirs(stage, f"py{other}")
            record(f"other-python-{other}", run_bundle(python_path(other), bundle, args=args,
                                                        home=home, cwd=cwd))  # fmt: skip

    if WINDOWS:  # Windows ignores the read-only attribute on directories: nothing to test
        return out

    # 3. Read-only working directory (e.g. launched from / or a mounted volume).
    home, cwd = fresh_dirs(stage, "rocwd")
    cwd.chmod(stat.S_IRUSR | stat.S_IXUSR)
    record("read-only-cwd", run_bundle(py, bundle, args=args, home=home, cwd=cwd))
    cwd.chmod(0o755)

    # 4. HOME not writable, so no cache can be created there.
    home, cwd = fresh_dirs(stage, "rohome")
    (home / "tmp").mkdir()
    home.chmod(stat.S_IRUSR | stat.S_IXUSR)
    record("read-only-home", run_bundle(py, bundle, args=args, home=home, cwd=cwd))
    home.chmod(0o755)

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", help="project id prefixes")
    parser.add_argument("--tool", action="append", choices=list(TOOLS))
    parser.add_argument("--python", action="append", help="e.g. 3.9, 3.11 (default: 3.9 and 3.12)")
    parser.add_argument("--heavy", action="store_true")
    parser.add_argument(
        "--conditions", action="store_true", help="also run hostile conditions on passing bundles"
    )
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--out", default="baseline")
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if any result isn't what the project expects"
    )
    opts = parser.parse_args()

    projects = []
    for p in sorted(PROJECTS.iterdir()):
        if not (p / "gauntlet.toml").exists():
            continue
        meta = load(p)
        if opts.only and not any(meta["id"].startswith(o) for o in opts.only):
            continue
        if meta.get("heavy") and not opts.heavy:
            continue
        projects.append(p)

    if "bundleup" in (opts.tool or TOOLS):
        sh(["uv", "sync", "--quiet"], cwd=ROOT.parent).check_returncode()
    jobs = [
        (t, p, v)
        for t in (opts.tool or TOOLS)
        for p in projects
        for v in (opts.python or DEFAULT_PYTHONS)
    ]
    results: list[Result] = []
    with cf.ThreadPoolExecutor(opts.jobs) as pool:
        futures = {pool.submit(one, t, p, v, opts.conditions): (t, p.name, v) for t, p, v in jobs}
        for f in cf.as_completed(futures):
            t, name, v = futures[f]
            try:
                rs = f.result()
            except Exception as e:  # harness bug: record it rather than crash the whole run
                rs = [Result(t, name, v, outcome="harness-error", detail=repr(e))]
            for r in rs:
                results.append(r)
                columns = f"{r.outcome:<13} {r.tool:<13} {r.project:<30} py{r.python:<5}"
                print(f"{columns} {r.condition:<21} {r.error_kind}", flush=True)

    RESULTS.mkdir(exist_ok=True)
    results.sort(key=lambda r: (r.project, r.tool, r.python, r.condition))
    (RESULTS / f"{opts.out}.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"\nwrote {RESULTS / (opts.out + '.json')}")
    if network_blocker() is None:
        print("note: network access was NOT blocked on this machine", file=sys.stderr)
    unexpected = [r for r in results if r.outcome in UNEXPECTED]
    if opts.check and unexpected:
        print(f"{len(unexpected)} unexpected result(s):", file=sys.stderr)
        for r in unexpected:
            detail = r.detail.strip().splitlines()[-1:] or [""]
            print(f"  {r.project} {r.tool} py{r.python} {r.condition}: {r.outcome} "
                  f"{r.error_kind} {detail[0]}", file=sys.stderr)  # fmt: skip
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
