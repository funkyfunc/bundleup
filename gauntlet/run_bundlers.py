"""Build every gauntlet project with each existing bundler, run the result, and record what happens.

Every existing tool gets the same inputs: the project's locked dependencies exported from uv.lock (or
the PEP 723 header) plus the project itself built as a wheel. bundleup is given the project directory
(or script) directly, so its build time also includes the export and the project build. Each bundle is built with the target
Python, then run with that Python from an empty directory, a fresh HOME, and network access denied
(macOS sandbox-exec), cold and then warm.

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
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).parent
PROJECTS = ROOT / "projects"
WORK = ROOT / ".work"
RESULTS = ROOT / "results"

TOOLS = {"pex": "pex==2.103.4", "shiv": "shiv==1.0.8", "zipapps": "zipapps==2026.4.17", "zipapp-naive": None,
         "bundleup": None}
BUNDLEUP = ROOT.parent / ".venv" / "bin" / "bundleup"  # this repo's bundleup, installed by `uv sync`
PYTHONS = {"3.9": "/usr/bin/python3", "3.12": None}  # None = ask uv
NO_NETWORK = "(version 1)(allow default)(deny network*)"
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 300


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


def sh(cmd, cwd=None, env=None, timeout=BUILD_TIMEOUT):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def python_path(version: str) -> str:
    if PYTHONS[version]:
        return PYTHONS[version]
    return sh(["uv", "python", "find", version]).stdout.strip()


def load(project: Path) -> dict:
    meta = tomllib.loads((project / "gauntlet.toml").read_text())
    if "script" in meta:
        header = (project / meta["script"]).read_text()
        meta["requires_python"] = re.search(r'requires-python = "([^"]+)"', header).group(1)
        meta["entry"] = f"{Path(meta['script']).stem}:main"
    else:
        meta["requires_python"] = tomllib.loads((project / "pyproject.toml").read_text())["project"]["requires-python"]
    return meta


def prepare(project: Path, meta: dict, stage: Path) -> tuple[Path, list[Path], Path | None]:
    """Export pinned requirements and build first-party code. Returns (requirements, wheels, script_dir)."""
    stage.mkdir(parents=True, exist_ok=True)
    reqs = stage / "requirements.txt"
    export = ["uv", "export", "--frozen", "--no-hashes", "--no-header", "--no-annotate", "-o", str(reqs)]
    if "script" in meta:
        sh([*export[:2], "--script", meta["script"], *export[3:]], cwd=project).check_returncode()
        script_dir = stage / "script"
        script_dir.mkdir(exist_ok=True)
        shutil.copy(project / meta["script"], script_dir)
        return reqs, [], script_dir
    sh([*export, "--no-dev", "--no-emit-project", "--no-emit-workspace"], cwd=project).check_returncode()
    wheels = stage / "wheels"
    sh(["uv", "build", "--wheel", "--all-packages", "-q", "-o", str(wheels)], cwd=project).check_returncode()
    return reqs, sorted(wheels.glob("*.whl")), None


def build_command(tool: str, py: str, reqs: Path, wheels: list[Path], script_dir: Path | None, entry: str, out: Path):
    w = [str(p) for p in wheels]
    if tool == "pex":
        src = ["-D", str(script_dir)] if script_dir else []
        return ["uvx", "--python", py, "--from", TOOLS[tool], "pex", *w, *src, "-r", str(reqs), "-e", entry, "-o", str(out)]
    if tool == "shiv":
        src = ["--site-packages", str(script_dir)] if script_dir else []
        return ["uvx", "--python", py, "--from", TOOLS[tool], "shiv", *w, *src, "-r", str(reqs),
                "-e", entry, "-o", str(out), "-p", "/usr/bin/env python3"]
    if tool == "zipapps":
        src = ["-a", str(next(script_dir.glob("*.py")))] if script_dir else []
        return ["uvx", "--python", py, "--from", TOOLS[tool], "python", "-m", "zipapps", "-c", "-u", "AUTO",
                "-m", entry, "-o", str(out), *src, "--uv", shutil.which("uv"), "-r", str(reqs), *w]
    raise ValueError(tool)


def build_naive(py: str, reqs: Path, wheels: list[Path], script_dir: Path | None, entry: str, out: Path, stage: Path):
    """What most people try first: pip install --target, add a __main__.py, run stdlib zipapp."""
    target = stage / "naive-site"
    shutil.rmtree(target, ignore_errors=True)
    r = sh(["uv", "pip", "install", "-q", "--python", py, "--target", str(target), "-r", str(reqs), *map(str, wheels)])
    if r.returncode:
        return r
    if script_dir:
        shutil.copytree(script_dir, target, dirs_exist_ok=True)
    module, func = entry.split(":")
    (target / "__main__.py").write_text(f"import sys\nfrom {module} import {func}\nsys.exit({func}())\n")
    return sh([py, "-m", "zipapp", str(target), "-o", str(out)])


def classify(text: str) -> str:
    for kind in ("ModuleNotFoundError", "PackageNotFoundError", "FileNotFoundError", "NotADirectoryError",
                 "SyntaxError", "ImportError", "PermissionError", "AssertionError", "OSError", "TimeoutExpired"):
        if kind in text:
            return kind
    return "other"


def run_bundle(py: str, bundle: Path, args: list[str], home: Path, cwd: Path, extra_env: dict | None = None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home / "tmp"), "LANG": "en_US.UTF-8"}
    env.update(extra_env or {})
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    cmd = ["sandbox-exec", "-p", NO_NETWORK, py, str(bundle), *args]
    start = time.perf_counter()
    try:
        r = sh(cmd, cwd=cwd, env=env, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, RUN_TIMEOUT, "TimeoutExpired", []
    elapsed = time.perf_counter() - start
    return r.returncode == 0, elapsed, (r.stderr or r.stdout).strip(), r.stdout.strip().splitlines()


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
    meta = load(project)
    res = Result(tool, meta["id"], version)
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

    if tool != "bundleup":
        try:
            reqs, wheels, script_dir = prepare(project, meta, stage / "inputs")
        except subprocess.CalledProcessError as e:
            res.outcome, res.detail = "build-fail", f"input preparation failed: {e}"
            return [res]

    start = time.perf_counter()
    try:
        if tool == "bundleup":
            src = project / meta["script"] if "script" in meta else project
            b = sh([str(BUNDLEUP), str(src), "--python", py, "-o", str(out), "--quiet"])
        elif tool == "zipapp-naive":
            b = build_naive(py, reqs, wheels, script_dir, meta["entry"], out, stage)
        else:
            b = sh(build_command(tool, py, reqs, wheels, script_dir, meta["entry"], out))
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
    ok, res.cold_s, err, stdout = run_bundle(py, out, args, home, cwd)
    ok = ok and f"GAUNTLET OK {meta['id']}" in "\n".join(stdout)
    res.cold_s = round(res.cold_s, 2)
    res.extra = [l for l in stdout if "=" in l and not l.startswith("GAUNTLET")]
    if ok:
        ok2, warm, _, _ = run_bundle(py, out, args, home, cwd)
        res.warm_s = round(warm, 2) if ok2 else None
        res.outcome = "pass" if res.expected == "pass" else "late-fail"
    else:
        res.outcome = "late-fail" if res.expected == "refuse" else "run-fail"
        res.error_kind, res.detail = classify(err), err[-1200:]
    results = [res]
    if conditions and res.outcome == "pass":
        results += hostile(tool, meta, py, version, out, stage, args)
    return results


def hostile(tool, meta, py, version, bundle, stage, args) -> list[Result]:
    """Re-run a passing bundle under conditions that commonly break bundles."""
    out = []
    marker = f"GAUNTLET OK {meta['id']}"

    def record(cond, ok, elapsed, err, stdout):
        r = Result(tool, meta["id"], version, condition=cond)
        ok = ok and marker in "\n".join(stdout)
        r.outcome, r.cold_s = ("pass" if ok else "run-fail"), round(elapsed, 2)
        if not ok:
            r.error_kind, r.detail = classify(err), err[-800:]
        out.append(r)

    # 1. Bundle and working directory under a path with spaces and non-ASCII characters.
    weird = stage / "my apps" / "ünïcødé dir"
    weird.mkdir(parents=True, exist_ok=True)
    copy = weird / bundle.name
    shutil.copy(bundle, copy)
    home, _ = fresh_dirs(stage, "weird")
    record("path-with-spaces", *run_bundle(py, copy, args, home, weird))

    # 2. Read-only working directory (e.g. launched from / or a mounted volume).
    home, cwd = fresh_dirs(stage, "rocwd")
    cwd.chmod(stat.S_IRUSR | stat.S_IXUSR)
    record("read-only-cwd", *run_bundle(py, bundle, args, home, cwd))
    cwd.chmod(0o755)

    # 3. HOME not writable, so no cache can be created there.
    home, cwd = fresh_dirs(stage, "rohome")
    (home / "tmp").mkdir()
    home.chmod(stat.S_IRUSR | stat.S_IXUSR)
    record("read-only-home", *run_bundle(py, bundle, args, home, cwd))
    home.chmod(0o755)

    # 4. Two cold starts at the same time sharing one HOME (first-run extraction race).
    home, cwd = fresh_dirs(stage, "race")
    with cf.ThreadPoolExecutor(2) as pool:
        runs = list(pool.map(lambda _: run_bundle(py, bundle, args, home, cwd), range(2)))
    worst = next((r for r in runs if not (r[0] and marker in "\n".join(r[3]))), runs[0])
    record("concurrent-first-run", *worst)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", help="project id prefixes")
    parser.add_argument("--tool", action="append", choices=list(TOOLS))
    parser.add_argument("--python", action="append", choices=list(PYTHONS))
    parser.add_argument("--heavy", action="store_true")
    parser.add_argument("--conditions", action="store_true", help="also run hostile conditions on passing bundles")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--out", default="baseline")
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
    jobs = [(t, p, v) for t in (opts.tool or TOOLS) for p in projects for v in (opts.python or PYTHONS)]
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
                print(f"{r.outcome:<13} {r.tool:<13} {r.project:<30} py{r.python:<5} {r.condition:<21} {r.error_kind}", flush=True)

    RESULTS.mkdir(exist_ok=True)
    results.sort(key=lambda r: (r.project, r.tool, r.python, r.condition))
    (RESULTS / f"{opts.out}.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"\nwrote {RESULTS / (opts.out + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
