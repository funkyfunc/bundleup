"""Measure build time, first run and warm start, sequentially and repeatedly, for bundleup and the
tools it's compared against, plus an installed venv as the floor.

run_bundlers.py checks correctness and runs builds in parallel, so its timings are noisy. This script
runs one thing at a time and reports medians, so speed claims can be reproduced.

- warm start: the bundle (or venv) has already run once; median of --runs runs.
- first run: every run gets a fresh HOME and TMPDIR, so nothing is cached; median of --cold-runs runs.
- build: median of --builds builds with uv's (and the tools') caches warm.

Usage:
    uv run gauntlet/bench.py                          # 03, 13 and 21 on Python 3.12
    uv run gauntlet/bench.py --python 3.9 03 --tool bundleup --tool venv
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb  # noqa: E402  (reuse input preparation and build commands)

BENCH = rb.WORK / "bench"
TOOLS = ["venv", "bundleup", "shiv", "pex"]


def timed(cmd, cwd, env) -> float:
    start = time.perf_counter()
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    if r.returncode or "GAUNTLET OK" not in r.stdout:
        raise RuntimeError(f"{cmd} failed:\n{r.stderr or r.stdout}")
    return elapsed


def env_for(home: Path) -> dict:
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(home / "tmp"), "LANG": "en_US.UTF-8"}


def fresh(path: Path) -> Path:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def build(tool: str, project: Path, meta: dict, py: str, stage: Path) -> tuple[list[str], float]:
    """Build once and return (command that runs the result, build seconds)."""
    args = meta.get("args", [])
    if tool == "venv":
        venv = stage / "venv"
        shutil.rmtree(venv, ignore_errors=True)
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv)}
        rb.sh(["uv", "sync", "--frozen", "--no-dev", "--no-editable", "--python", py, "-q"], cwd=project,
              env=env).check_returncode()
        script = next(iter(tomllib.loads((project / "pyproject.toml").read_text())["project"]["scripts"]))
        return [str(venv / "bin" / script), *args], 0.0
    out = stage / ("app.pex" if tool == "pex" else "app.pyz")
    if tool == "bundleup":
        cmd = [str(rb.BUNDLEUP), str(project), "--python", py, "-o", str(out), "--quiet"]
    else:
        reqs, wheels, script_dir = rb.prepare(project, meta, stage / "inputs")
        cmd = rb.build_command(tool, py, reqs, wheels, script_dir, meta["entry"], out)
    start = time.perf_counter()
    rb.sh(cmd).check_returncode()
    return [py, str(out), *args], time.perf_counter() - start


def bench(tool, project, version, runs, cold_runs, builds) -> dict:
    meta = rb.load(project)
    py = rb.python_path(version)
    stage = fresh(BENCH / tool / meta["id"] / version)
    times = []
    for _ in range(builds if tool != "venv" else 1):
        cmd, t = build(tool, project, meta, py, stage)
        times.append(t)
    cwd = fresh(stage / "cwd")
    cold = []
    if tool != "venv":
        for i in range(cold_runs):
            cold.append(timed(cmd, cwd, env_for(fresh(stage / f"cold-home-{i}"))))
    env = env_for(fresh(stage / "warm-home"))
    timed(cmd, cwd, env)  # populate caches and __pycache__
    warm = [timed(cmd, cwd, env) for _ in range(runs)]
    ms = lambda xs: round(statistics.median(xs) * 1000, 1) if xs else None
    return {"tool": tool, "project": meta["id"], "python": version, "build_ms": ms(times) if tool != "venv" else None,
            "first_run_ms": ms(cold), "warm_ms": ms(warm), "warm_min_ms": round(min(warm) * 1000, 1)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", default=["03", "13", "21"], help="project id prefixes")
    parser.add_argument("--tool", action="append", choices=TOOLS)
    parser.add_argument("--python", action="append", choices=list(rb.PYTHONS))
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--cold-runs", type=int, default=10)
    parser.add_argument("--builds", type=int, default=3)
    parser.add_argument("--out", help="write results JSON to gauntlet/results/<out>.json")
    opts = parser.parse_args()
    rb.sh(["uv", "sync", "--quiet"], cwd=rb.ROOT.parent).check_returncode()

    projects = [p for p in sorted(rb.PROJECTS.iterdir())
                if (p / "gauntlet.toml").exists() and any(p.name.startswith(o) for o in opts.only)]
    rows = []
    print("| Tool | Project | Python | Build (ms) | First run (ms) | Warm start (ms) |")
    print("|---|---|---|---|---|---|")
    for project in projects:
        for version in opts.python or ["3.12"]:
            for tool in opts.tool or TOOLS:
                r = bench(tool, project, version, opts.runs, opts.cold_runs, opts.builds)
                rows.append(r)
                cell = lambda v: "–" if v is None else f"{v:,.0f}"
                print(f"| {tool} | {r['project']} | {version} | {cell(r['build_ms'])} | {cell(r['first_run_ms'])} "
                      f"| {cell(r['warm_ms'])} |", flush=True)
    if opts.out:
        (rb.RESULTS / f"{opts.out}.json").write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
