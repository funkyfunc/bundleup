"""Measure build time, first run and warm start, sequentially and repeatedly, for bundleup and
the tools it's compared against, plus an installed venv as the floor.

run_bundlers.py checks correctness and runs builds in parallel, so its timings are noisy. This
script runs one thing at a time and reports medians, so speed claims can be reproduced.

- warm start: the bundle (or venv) has already run once; median of --runs runs.
- first run: every run gets a fresh HOME and TMPDIR, so nothing is cached; median of --cold-runs.
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
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb

BENCH = rb.WORK / "bench"
TOOLS = ["venv", "bundleup", "shiv", "pex"]


@dataclass(frozen=True)
class Row:
    """One line of results; also the JSON written with --out."""

    tool: str
    project: str
    python: str
    build_ms: float | None
    first_run_ms: float | None
    warm_ms: float | None
    warm_min_ms: float


def timed(cmd: list[str], cwd: Path, env: dict[str, str]) -> float:
    start = time.perf_counter()
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    if r.returncode or "GAUNTLET OK" not in r.stdout:
        raise RuntimeError(f"{cmd} failed:\n{r.stderr or r.stdout}")
    return elapsed


def env_for(home: Path) -> dict[str, str]:
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    return rb.run_env(home)


def fresh(path: Path) -> Path:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def median_ms(seconds: list[float]) -> float | None:
    return round(statistics.median(seconds) * 1000, 1) if seconds else None


def install_venv(project: Path, meta: rb.Meta, py: str, stage: Path) -> list[str]:
    """Install the project into a venv the normal way; return the command that runs it."""
    venv = stage / "venv"
    shutil.rmtree(venv, ignore_errors=True)
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(venv)}
    sync = ["uv", "sync", "--frozen", "--no-dev", "--no-editable", "--python", py, "-q"]
    rb.sh(sync, cwd=project, env=env).check_returncode()
    scripts = tomllib.loads((project / "pyproject.toml").read_text())["project"]["scripts"]
    return [str(venv / "bin" / next(iter(scripts))), *meta.get("args", [])]


def build(tool: str, project: Path, *, meta: rb.Meta, py: str, stage: Path) -> float:
    """Build a bundle at stage/app.pyz (or app.pex) and return the build time in seconds."""
    out = bundle_path(tool, stage)
    if tool == "bundleup":
        cmd = [str(rb.BUNDLEUP), str(project), "--python", py, "-o", str(out), "--quiet"]
    else:
        inputs = rb.prepare(project, meta, stage / "inputs")
        cmd = rb.build_command(tool, py, inputs=inputs, entry=meta["entry"], out=out)
    start = time.perf_counter()
    rb.sh(cmd).check_returncode()
    return time.perf_counter() - start


def bundle_path(tool: str, stage: Path) -> Path:
    return stage / ("app.pex" if tool == "pex" else "app.pyz")


def bench(tool: str, project: Path, *, version: str, runs: int, cold_runs: int, builds: int) -> Row:
    meta = rb.load(project)
    py = rb.python_path(version)
    stage = fresh(BENCH / tool / meta["id"] / version)
    build_times: list[float] = []
    if tool == "venv":
        cmd = install_venv(project, meta, py, stage)
    else:
        for _ in range(builds):
            build_times.append(build(tool, project, meta=meta, py=py, stage=stage))
        cmd = [py, str(bundle_path(tool, stage)), *meta.get("args", [])]
    cwd = fresh(stage / "cwd")
    cold: list[float] = []
    if tool != "venv":
        for i in range(cold_runs):
            cold.append(timed(cmd, cwd, env_for(fresh(stage / f"cold-home-{i}"))))
    env = env_for(fresh(stage / "warm-home"))
    timed(cmd, cwd, env)  # populate caches and __pycache__
    warm = [timed(cmd, cwd, env) for _ in range(runs)]
    return Row(
        tool=tool,
        project=meta["id"],
        python=version,
        build_ms=median_ms(build_times),
        first_run_ms=median_ms(cold),
        warm_ms=median_ms(warm),
        warm_min_ms=round(min(warm) * 1000, 1),
    )


def cell(value: float | None) -> str:
    return "–" if value is None else f"{value:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", default=["03", "13", "21"], help="project id prefixes")
    parser.add_argument("--tool", action="append", choices=TOOLS)
    parser.add_argument("--python", action="append", help="e.g. 3.9, 3.12 (default: 3.12)")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--cold-runs", type=int, default=10)
    parser.add_argument("--builds", type=int, default=3)
    parser.add_argument("--out", help="write results JSON to gauntlet/results/<out>.json")
    opts = parser.parse_args()
    rb.sh(["uv", "sync", "--quiet"], cwd=rb.ROOT.parent).check_returncode()

    projects = [
        p
        for p in sorted(rb.PROJECTS.iterdir())
        if (p / "gauntlet.toml").exists() and any(p.name.startswith(o) for o in opts.only)
    ]
    rows: list[Row] = []
    print("| Tool | Project | Python | Build (ms) | First run (ms) | Warm start (ms) |")
    print("|---|---|---|---|---|---|")
    for project in projects:
        for version in opts.python or ["3.12"]:
            for tool in opts.tool or TOOLS:
                r = bench(
                    tool,
                    project,
                    version=version,
                    runs=opts.runs,
                    cold_runs=opts.cold_runs,
                    builds=opts.builds,
                )
                rows.append(r)
                times = f"{cell(r.build_ms)} | {cell(r.first_run_ms)} | {cell(r.warm_ms)}"
                print(f"| {tool} | {r.project} | {version} | {times} |", flush=True)
    if opts.out:
        (rb.RESULTS / f"{opts.out}.json").write_text(
            json.dumps([asdict(r) for r in rows], indent=2)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
