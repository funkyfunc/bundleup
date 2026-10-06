"""Run real projects' own test suites against their bundles (gauntlet/suites.toml). CI only: it
runs third-party code (ADR-0017).

    uv run gauntlet/suites.py --python 3.12 --check --out suites

For each suite: clone the repository at the tag, make a throwaway project that depends on the
released package plus pytest and the test dependencies, then run the tests (1) in that project's
venv and (2) from its bundle, whose entry point is pytest. A probe plugin prints where the module
under test was imported from, to prove the bundle's copy was tested. Passes when both runs end
the same way with the same counts.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb

SUITES = Path(__file__).with_name("suites.toml")
PROBE = """\
import importlib, os

def pytest_sessionstart(session):
    module = importlib.import_module(os.environ["SUITE_MODULE"])
    print("SUITE-MODULE-FILE", module.__file__, flush=True)
"""
Suite = dict[str, Any]  # one [[suite]] from suites.toml; Any: TOML values
COUNTS = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)")


@dataclass
class Outcome:
    exit_code: int
    counts: dict[str, int]
    module_file: str
    tail: str


@dataclass
class Record:
    name: str
    outcome: str = ""  # pass | mismatch | not-from-bundle | build-fail | setup-fail
    venv: Outcome | None = None
    bundle: Outcome | None = None
    detail: str = ""


def summarize(text: str, exit_code: int) -> Outcome:
    lines = [line for line in text.splitlines() if line.strip()]
    found = re.search(r"SUITE-MODULE-FILE (.+)", text)
    last = lines[-1] if lines else ""
    counts = {
        kind.rstrip("s") if kind.startswith("error") else kind: int(n)
        for n, kind in COUNTS.findall(last)
    }
    return Outcome(
        exit_code, counts, found.group(1).strip() if found else "", "\n".join(lines[-15:])
    )


def run_tests(cmd: list[str], *, clone: Path, env: dict[str, str]) -> Outcome:
    args = [str(clone / "tests"), "-q", "-p", "no:cacheprovider", "-p", "suite_probe"]
    done = rb.sh([*cmd, *args, "--import-mode=importlib"], cwd=clone, env=env, timeout=1800)
    return summarize(done.stdout + done.stderr, done.returncode)


def run_suite(suite: Suite, python: str, work: Path) -> Record:
    rec = Record(str(suite["name"]))
    root = work / rec.name
    shutil.rmtree(root, ignore_errors=True)
    clone, project, probe, cache = root / "repo", root / "project", root / "probe", root / "cache"
    for d in (project, probe, cache):
        d.mkdir(parents=True)
    cloned = rb.sh(
        [
            "git",
            "clone",
            "-q",
            "--depth",
            "1",
            "--branch",
            str(suite["tag"]),
            str(suite["repo"]),
            str(clone),
        ]
    )
    if cloned.returncode:
        rec.outcome, rec.detail = "setup-fail", cloned.stderr[-800:]
        return rec
    deps = [suite["package"], *suite["test_deps"]]
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "suite-{rec.name}"\nversion = "0"\nrequires-python = ">=3.9"\n'
        f"dependencies = {json.dumps(deps)}\n"
    )
    (probe / "suite_probe.py").write_text(PROBE)
    synced = rb.sh(["uv", "sync", "-q", "--python", python], cwd=project)
    if synced.returncode:
        rec.outcome, rec.detail = "setup-fail", synced.stderr[-800:]
        return rec
    env = {
        **os.environ,
        "PYTHONPATH": str(probe),
        "SUITE_MODULE": str(suite["module"]),
        "BUNDLEUP_CACHE": str(cache),
    }
    venv_python = project / ".venv" / ("Scripts/python.exe" if rb.WINDOWS else "bin/python")
    rec.venv = run_tests([str(venv_python), "-m", "pytest"], clone=clone, env=env)
    bundle = root / "suite.pyz"
    built = rb.sh(
        [
            str(rb.BUNDLEUP),
            "build",
            str(project),
            "--python",
            python,
            "--entry",
            "pytest:console_main",
            "-o",
            str(bundle),
        ]
    )
    if built.returncode:
        rec.outcome, rec.detail = "build-fail", built.stderr[-1500:]
        return rec
    rec.bundle = run_tests([rb.python_path(python), str(bundle)], clone=clone, env=env)
    if not rec.bundle.module_file.startswith(str(cache)):
        rec.outcome = "not-from-bundle"
        rec.detail = f"{suite['module']} came from {rec.bundle.module_file or '(no probe output)'}"
    elif (rec.bundle.exit_code, rec.bundle.counts) != (rec.venv.exit_code, rec.venv.counts):
        rec.outcome = "mismatch"
        venv, bundled = rec.venv, rec.bundle
        rec.detail = (
            f"venv: {venv.exit_code} {venv.counts}; bundle: {bundled.exit_code} {bundled.counts}"
        )
    else:
        rec.outcome = "pass"
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*")
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--check", action="store_true", help="exit 1 unless every suite passes")
    parser.add_argument("--out", default="suites")
    opts = parser.parse_args()
    suites = tomllib.loads(SUITES.read_text())["suite"]
    work = rb.WORK / "suites"
    records = []
    for suite in suites:
        if opts.only and suite["name"] not in opts.only:
            continue
        rec = run_suite(suite, rb.python_path(opts.python), work)
        records.append(rec)
        counts = rec.bundle.counts if rec.bundle else {}
        print(f"{rec.outcome:<16} {rec.name:<14} {counts} {rec.detail[:200]}", flush=True)
    out = rb.RESULTS / f"{opts.out}.json"
    out.write_text(json.dumps([asdict(r) for r in records], indent=1) + "\n")
    print(f"wrote {out}")
    return 1 if opts.check and any(r.outcome != "pass" for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
