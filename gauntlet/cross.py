"""Cross-target gauntlet (ADR-0014): build every project for another platform on one machine, then
run the bundles on that platform.

    # on the build machine (e.g. macOS):
    uv run gauntlet/cross.py build --python 3.11 --python-platform x86_64-manylinux_2_28 --dir out
    # on the target machine (e.g. Linux x86_64):
    uv run gauntlet/cross.py run --python 3.11 --dir out --check --out cross-linux

The run side uses the same checks as run_bundlers.py: the base run, the hostile conditions, and
`matches-venv` against a normal install made on the target itself.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path

from packaging.specifiers import SpecifierSet

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb

TOOL = "bundleup-cross"


def projects(only: list[str]) -> list[Path]:
    found = []
    for project in sorted(rb.PROJECTS.iterdir()):
        if not (project / "gauntlet.toml").exists():
            continue
        meta = rb.load(project)
        if meta.get("heavy") or (only and not meta["id"].startswith(tuple(only))):
            continue
        found.append(project)
    return found


def build_all(python: str, platform: str, out: Path, only: list[str]) -> int:
    """Build each project for `platform`; record what happened in out/builds.json."""
    out.mkdir(parents=True, exist_ok=True)
    py = rb.python_path(python)
    records = []
    for project in projects(only):
        meta = rb.load(project)
        src = project / meta["script"] if "script" in meta else project
        bundle = out / f"{meta['id']}.pyz"
        cmd = [str(rb.BUNDLEUP), "build", str(src), "--python", py]
        built = rb.sh([*cmd, "--python-platform", platform, "-o", str(bundle), "--json"])
        records.append(
            {"id": meta["id"], "built": built.returncode == 0, "output": built.stdout[-2000:]}
        )
        print(f"{'built' if built.returncode == 0 else 'not built':<10} {meta['id']}", flush=True)
    (out / "builds.json").write_text(
        json.dumps({"platform": platform, "builds": records}, indent=2)
    )
    return 0


def run_one(project: Path, python: str, out: Path, built: dict[str, bool]) -> list[rb.Result]:
    meta = rb.load(project)
    res = rb.Result(TOOL, meta["id"], python, network_blocked=rb.network_blocker() is not None)
    applies = python in SpecifierSet(meta["requires_python"])
    if not applies and not meta.get("expect_refuse_below"):
        res.outcome, res.detail = "skipped", f"requires {meta['requires_python']}"
        return [res]
    res.expected = "pass" if applies else "refuse"
    if not built.get(meta["id"]):
        res.outcome = "refused" if res.expected == "refuse" else "build-fail"
        return [res]
    py = rb.python_path(python)
    stage = rb.WORK / TOOL / meta["id"] / python
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    bundle = stage / "app.pyz"
    shutil.copy(out / f"{meta['id']}.pyz", bundle)
    args = meta.get("args", [])
    home, cwd = rb.fresh_dirs(stage, "base")
    start = time.perf_counter()
    cold = rb.run_bundle(py, bundle, args=args, home=home, cwd=cwd)
    res.cold_s = round(time.perf_counter() - start, 2)
    ok = cold.ok and f"GAUNTLET OK {meta['id']}" in "\n".join(cold.stdout_lines)
    if not ok:
        res.outcome = "late-fail" if res.expected == "refuse" else "run-fail"
        res.error_kind, res.detail = rb.classify(cold.output), cold.output[-1200:]
        return [res]
    res.outcome = "pass" if res.expected == "pass" else "late-fail"
    results = [res]
    if res.outcome == "pass":
        results += rb.hostile(TOOL, meta, py=py, version=python, bundle=bundle, stage=stage)
        compared = rb.matches_venv(project, meta, py=py, version=python, stage=stage)
        compared.tool = TOOL
        results.append(compared)
    return results


def run_all(python: str, out: Path, only: list[str], jobs: int) -> list[rb.Result]:
    built = {b["id"]: b["built"] for b in json.loads((out / "builds.json").read_text())["builds"]}
    results: list[rb.Result] = []
    with cf.ThreadPoolExecutor(jobs) as pool:
        futures = [pool.submit(run_one, p, python, out, built) for p in projects(only)]
        for future in cf.as_completed(futures):
            for r in future.result():
                results.append(r)
                print(
                    f"{r.outcome:<10} {r.project:<30} {r.condition:<21} {r.error_kind}", flush=True
                )
    return sorted(results, key=lambda r: (r.project, r.condition))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "run"])
    parser.add_argument("only", nargs="*", help="project id prefixes")
    parser.add_argument("--python", required=True)
    parser.add_argument("--python-platform", help="build: the target platform, in uv's terms")
    parser.add_argument("--dir", type=Path, required=True, help="where bundles go / come from")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", help="run: write results JSON to gauntlet/results/<out>.json")
    parser.add_argument("--check", action="store_true", help="run: exit 1 on unexpected results")
    opts = parser.parse_args()
    rb.sh(["uv", "sync", "--quiet"], cwd=rb.ROOT.parent).check_returncode()
    if opts.action == "build":
        if not opts.python_platform:
            parser.error("build needs --python-platform")
        return build_all(opts.python, opts.python_platform, opts.dir, opts.only)
    results = run_all(opts.python, opts.dir, opts.only, opts.jobs)
    if opts.out:
        rb.RESULTS.mkdir(exist_ok=True)
        rows = [asdict(r) for r in results]
        (rb.RESULTS / f"{opts.out}.json").write_text(json.dumps(rows, indent=2))
    unexpected = [r for r in results if r.outcome in rb.UNEXPECTED]
    for r in unexpected:
        print(
            f"unexpected: {r.project} {r.condition}: {r.outcome} {r.detail[-300:]}", file=sys.stderr
        )
    return 1 if opts.check and unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
