"""Breadth smoke test: bundle popular PyPI packages and compare each bundle with a normal install.

For each package: a throwaway locked project that depends on it is installed with `uv sync` and
bundled with bundleup, then the gauntlet's `matches-venv` comparison runs (same distributions and
versions, same entry points, the same top-level modules importing). A package that doesn't install
normally on this platform is skipped, not counted as a bundleup failure.

Imports third-party code, so it runs on CI runners (ADR-0017), not on personal machines, except
for packages the gauntlet already uses.

Usage:
    uv run gauntlet/smoke.py --top 200 --out smoke-<date>       # the most-downloaded packages
    uv run gauntlet/smoke.py click requests --python 3.12       # specific packages
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
import shutil
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb

TOP_PACKAGES_URL = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json"
SMOKE = rb.WORK / "smoke"
# What to run in the bundle: `python -m platform` prints one line and exits. The point of the
# bundle is its packages, which the comparison inspects.
ENTRY = "platform"


@dataclass
class SmokeResult:
    package: str
    python: str
    outcome: str = ""  # pass | skipped | build-fail | mismatch | harness-error
    version: str = ""  # the version that was locked
    detail: str = ""
    network_blocked: bool = True


def top_packages(count: int) -> list[str]:
    with urllib.request.urlopen(TOP_PACKAGES_URL, timeout=60) as response:
        rows = json.load(response)["rows"]
    return [row["project"] for row in rows[:count]]


def make_project(package: str, directory: Path, python: str) -> None:
    """A project that only depends on `package` (a uv "virtual" project: nothing to build)."""
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        f'[project]\nname = "smoke-{package}"\nversion = "0"\n'
        f'requires-python = ">={python}"\ndependencies = ["{package}"]\n\n'
        "[tool.uv]\npackage = false\n"
    )


def locked_version(project: Path, package: str) -> str:
    lock = (project / "uv.lock").read_text()
    marker = f'name = "{package.lower()}"\nversion = "'
    start = lock.find(marker)
    return lock[start + len(marker) :].split('"', 1)[0] if start >= 0 else ""


def smoke(package: str, python: str) -> SmokeResult:
    res = SmokeResult(package, python, network_blocked=rb.network_blocker() is not None)
    py = rb.python_path(python)
    stage = SMOKE / package / python
    project = stage / "project"
    make_project(package, project, python)
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    lock = rb.sh(["uv", "lock", "-q", "--python", py], cwd=project, env=env)
    if lock.returncode:
        res.outcome, res.detail = "skipped", "doesn't resolve: " + lock.stderr.strip()[-400:]
        return res
    res.version = locked_version(project, package)
    meta: rb.Meta = {"id": package, "args": []}
    try:
        rb.install_normally(project, meta, py=py, venv=stage / "venv")
    except rb.subprocess.CalledProcessError as e:
        res.outcome = "skipped"
        res.detail = "doesn't install normally here: " + str(e.stderr or e)[-400:]
        return res
    build = [str(rb.BUNDLEUP), "build", str(project), "--python", py, "--entry", ENTRY]
    built = rb.sh([*build, "-o", str(stage / "app.pyz"), "--json"], env=env)
    if built.returncode:
        res.outcome, res.detail = "build-fail", (built.stdout or built.stderr)[-1200:]
        return res
    compared = rb.matches_venv(project, meta, py=py, version=python, stage=stage)
    res.outcome = "pass" if compared.outcome == "pass" else "mismatch"
    res.detail = compared.detail
    return res


def write_summary(results: list[SmokeResult], counts: dict[str, int]) -> None:
    """A markdown summary for the GitHub Actions run page, when running there."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    lines = [f"### Smoke test: {len(results)} packages", "", f"`{counts}`", ""]
    problems = [r for r in results if r.outcome not in ("pass", "skipped")]
    if problems:
        lines += ["| Package | Version | Outcome | Detail |", "|---|---|---|---|"]
        for r in problems:
            detail = r.detail.replace("\n", " ").replace("|", "\\|")[:300]
            lines.append(f"| {r.package} | {r.version} | {r.outcome} | {detail} |")
    with open(summary, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", nargs="*", help="packages to test (default: --top N)")
    parser.add_argument("--top", type=int, default=0, help="test the N most-downloaded packages")
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", help="write results JSON to gauntlet/results/<out>.json")
    parser.add_argument("--check", action="store_true", help="exit 1 on any build-fail/mismatch")
    opts = parser.parse_args()
    packages = opts.packages or top_packages(opts.top)
    if not packages:
        parser.error("name packages or pass --top N")
    rb.sh(["uv", "sync", "--quiet"], cwd=rb.ROOT.parent).check_returncode()

    results: list[SmokeResult] = []
    with cf.ThreadPoolExecutor(opts.jobs) as pool:
        futures = {pool.submit(smoke, p, opts.python): p for p in packages}
        for future in cf.as_completed(futures):
            try:
                r = future.result()
            except Exception as e:  # harness bug: record it rather than crash the whole run
                r = SmokeResult(futures[future], opts.python, "harness-error", detail=repr(e))
            results.append(r)
            print(f"{r.outcome:<13} {r.package:<32} {r.version:<14} {r.detail[:80]!r}", flush=True)

    results.sort(key=lambda r: r.package)
    if opts.out:
        rb.RESULTS.mkdir(exist_ok=True)
        (rb.RESULTS / f"{opts.out}.json").write_text(
            json.dumps([asdict(r) for r in results], indent=2)
        )
    counts = {o: sum(r.outcome == o for r in results) for o in sorted({r.outcome for r in results})}
    print(f"\n{len(results)} packages: {counts}")
    write_summary(results, counts)
    failed = [r for r in results if r.outcome in ("build-fail", "mismatch", "harness-error")]
    return 1 if opts.check and failed else 0


if __name__ == "__main__":
    sys.exit(main())
