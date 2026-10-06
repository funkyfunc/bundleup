"""The gauntlet for bundleup's other output formats (ADR-0025): every project built as a `dir` and
run with only that directory on PYTHONPATH (as a host application would), or built for AWS Lambda
and invoked in AWS's own Lambda container image through its runtime interface emulator.

    uv run gauntlet/formats.py dir --check                  # any OS
    uv run gauntlet/formats.py lambda --check               # Linux with Docker (CI)
    uv run gauntlet/formats.py lambda --target lambda-arm64 # on an arm64 Linux machine

A small handler (HANDLER below) is added to each output before it runs: it calls the project's
entry point and returns what it printed. Results go to gauntlet/results/<--out>.json.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from packaging.specifiers import SpecifierSet

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb

HANDLER = """
import contextlib, importlib, io, runpy, sys, traceback

def handler(event, context):
    sys.argv = ["app", *event.get("args", [])]
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out):
        try:
            if event.get("script"):
                runpy.run_module(event["script"], run_name="__main__")
            else:
                module, _, function = event["entry"].partition(":")
                code = getattr(importlib.import_module(module), function)() or 0
        except SystemExit as e:
            code = e.code or 0
        except BaseException:
            return {"code": 1, "stdout": out.getvalue(), "error": traceback.format_exc()}
    return {"code": code, "stdout": out.getvalue()}
"""
RUN_LOCALLY = "import json, sys, gauntlet_handler; print(json.dumps(gauntlet_handler.handler(json.loads(sys.argv[1]), None)))"  # noqa: E501 (a one-line program)
LAMBDA_IMAGE = "public.ecr.aws/lambda/python:{python}"
INVOKE = "http://127.0.0.1:{port}/2015-03-31/functions/function/invocations"
# Projects that can't work in an output without bundleup's loader, and why (the check warns:
# `pth-not-run`). Gauntlet 19 passes on Lambda: its working directory is /var/task, and a
# `python -c` child puts the working directory on its path.
KNOWN = {
    "dir": {
        "23-pth-files": "no loader to run .pth files (`check` warns: pth-not-run)",
    },
    "lambda": {
        "23-pth-files": "no loader to run .pth files (`check` warns: pth-not-run)",
    },
}


@dataclass
class Record:
    project: str
    format: str
    outcome: str = ""  # pass | fail | known-fail | build-fail | skipped
    detail: str = ""
    build_s: float = 0.0


def event_for(meta: rb.Meta) -> dict[str, object]:
    event: dict[str, object] = {"args": meta.get("args", [])}
    if "script" in meta:
        event["script"] = Path(meta["script"]).stem
    else:
        event["entry"] = meta["entry"]
    return event


def build(project: Path, meta: rb.Meta, fmt: str, out: Path, extra: list[str]) -> Record:
    rec = Record(meta["id"], fmt)
    src = project / meta["script"] if "script" in meta else project
    entry = [] if "script" in meta else ["--entry", meta["entry"]]
    start = time.perf_counter()
    done = rb.sh([str(rb.BUNDLEUP), "build", str(src), *extra, *entry, "-o", str(out), "-q"])
    rec.build_s = round(time.perf_counter() - start, 2)
    if done.returncode:
        rec.outcome, rec.detail = "build-fail", done.stderr[-1500:]
    return rec


def judge(rec: Record, result: dict[str, object]) -> None:
    stdout = str(result.get("stdout", ""))
    ok = result.get("code") == 0 and f"GAUNTLET OK {rec.project}" in stdout
    known = KNOWN[rec.format].get(rec.project)
    if ok:
        rec.outcome = "pass"
    else:
        rec.outcome = "known-fail" if known else "fail"
        rec.detail = (known + ": " if known else "") + str(result.get("error") or stdout)[-1500:]


def run_dir(project: Path, meta: rb.Meta, work: Path, python: str) -> Record:
    out = work / meta["id"]
    shutil.rmtree(out, ignore_errors=True)
    rec = build(project, meta, "dir", out, ["--format", "dir", "--python", python])
    if rec.outcome:
        return rec
    (out / "gauntlet_handler.py").write_text(HANDLER)
    (work / "home" / "tmp").mkdir(parents=True, exist_ok=True)
    env = {**rb.run_env(work / "home"), "PYTHONPATH": str(out)}
    done = rb.sh([python, "-c", RUN_LOCALLY, json.dumps(event_for(meta))], cwd=work, env=env)
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        result = {"code": done.returncode, "error": done.stderr}
    judge(rec, result)
    return rec


def invoke(port: str, event: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(INVOKE.format(port=port), data=json.dumps(event).encode())
    deadline = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.loads(response.read())
        except OSError:  # the emulator isn't listening yet
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def run_lambda(project: Path, meta: rb.Meta, work: Path, target: str, python: str) -> Record:
    archive = work / f"{meta['id']}.zip"
    rec = build(project, meta, "lambda", archive, ["--target", target])
    if rec.outcome:
        return rec
    task = work / meta["id"]
    shutil.rmtree(task, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(task)
    for info in zipfile.ZipFile(archive).infolist():  # extractall drops the executable bits
        if (info.external_attr >> 16) & 0o111:
            (task / info.filename).chmod(0o755)
    (task / "gauntlet_handler.py").write_text(HANDLER)
    image = LAMBDA_IMAGE.format(python=python)
    mount = f"{task}:/var/task:ro"
    run = ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::8080", "-v", mount, image]
    started = rb.sh([*run, "gauntlet_handler.handler"])
    if started.returncode:
        rec.outcome, rec.detail = "fail", f"docker: {started.stderr[-800:]}"
        return rec
    container = started.stdout.strip()
    try:
        port = rb.sh(["docker", "port", container, "8080"]).stdout.strip().rsplit(":", 1)[-1]
        judge(rec, invoke(port, event_for(meta)))
    except OSError as e:
        rec.outcome, rec.detail = "fail", repr(e)
    finally:
        logs = rb.sh(["docker", "logs", container]).stderr[-800:]
        rb.sh(["docker", "stop", container])
        if rec.outcome == "fail":
            rec.detail += f"\ncontainer log: {logs}"
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("format", choices=["dir", "lambda"])
    parser.add_argument("only", nargs="*", help="project id prefixes")
    parser.add_argument("--python", default="3.12", help="dir: the Python to build for and run")
    parser.add_argument("--target", default="lambda", help="lambda: the preset to build with")
    parser.add_argument("--check", action="store_true", help="exit 1 on unexpected failures")
    parser.add_argument("--out", default=None)
    opts = parser.parse_args()
    lambda_python = "3.13"  # the presets' default; the image tag must match
    python = lambda_python if opts.format == "lambda" else opts.python
    work = rb.WORK / f"formats-{opts.format}"
    work.mkdir(parents=True, exist_ok=True)
    records = []
    for project in sorted(rb.PROJECTS.iterdir()):
        if not (project / "gauntlet.toml").exists():
            continue
        meta = rb.load(project)
        if meta.get("heavy") or (opts.only and not meta["id"].startswith(tuple(opts.only))):
            continue
        if python not in SpecifierSet(meta["requires_python"]) or meta.get("expect") != "pass":
            records.append(Record(meta["id"], opts.format, "skipped"))
            continue
        if opts.format == "dir":
            rec = run_dir(project, meta, work, rb.python_path(python))
        else:
            rec = run_lambda(project, meta, work, opts.target, lambda_python)
        records.append(rec)
        print(
            f"{rec.outcome:<11} {rec.format:<7} {rec.project:<32} {rec.detail[:90]!r}", flush=True
        )
    out = rb.RESULTS / f"{opts.out or 'formats-' + opts.format}.json"
    out.write_text(json.dumps([asdict(r) for r in records], indent=1) + "\n")
    print(f"\nwrote {out}")
    unexpected = [r for r in records if r.outcome in ("fail", "build-fail")]
    for r in unexpected:
        print(f"unexpected: {r.project} {r.outcome}\n{r.detail}", file=sys.stderr)
    return 1 if opts.check and unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
