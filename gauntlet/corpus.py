"""Nightly corpus run: real programs, installed normally and bundled, run the same way both times.

For each entry in corpus.toml: prepare the project (a throwaway locked project around a PyPI app,
or a GitHub repo cloned at its pinned commit), install it with `uv sync`, bundle it, then run each
command with the installed program and with the bundle (network blocked where possible). Exit
codes and output must match, with paths normalised. A program that doesn't install normally on
this platform is skipped. Runs third-party code: CI runners only (ADR-0017).

Usage:
    uv run gauntlet/corpus.py --out corpus-<os>              # everything in corpus.toml
    uv run gauntlet/corpus.py httpie yt-dlp --python 3.12    # entries whose name starts with these
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=23"]
# ///

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import run_bundlers as rb

CORPUS = Path(__file__).parent / "corpus.toml"
WORK = rb.WORK / "corpus"
Entry = dict[str, Any]  # one [[app]] or [[repo]] table; Any: TOML values


@dataclass
class CorpusResult:
    name: str
    kind: str  # app | repo
    pin: str  # the pinned requirement or commit
    os: str
    python: str
    outcome: str = ""  # pass | skipped | fail | harness-error
    phase: str = ""  # where it failed: prepare | install | build | run
    code: str = ""  # bundleup's diagnostic code, or what differed; part of the failure signature
    detail: str = ""
    network_blocked: bool = True


def name_of(entry: Entry) -> str:
    if "requirement" in entry:
        return re.split(r"[=<>!~ ]", entry["requirement"], maxsplit=1)[0]
    return entry["url"].rstrip("/").split("github.com/", 1)[-1]  # owner/name


def load_corpus() -> list[Entry]:
    data = tomllib.loads(CORPUS.read_text())
    return [{**e, "kind": "app"} for e in data.get("app", [])] + [
        {**e, "kind": "repo"} for e in data.get("repo", [])
    ]


def prepare(entry: Entry, project: Path, python: str) -> None:
    """A project directory: a wrapper around a PyPI app, or a repo at its pinned commit."""
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir(parents=True)
    if entry["kind"] == "app":
        (project / "pyproject.toml").write_text(
            f'[project]\nname = "corpus-{name_of(entry)}"\nversion = "0"\n'
            f'requires-python = ">={python}"\ndependencies = ["{entry["requirement"]}"]\n\n'
            "[tool.uv]\npackage = false\n"
        )
        rb.sh(["uv", "lock", "-q"], cwd=project).check_returncode()
        return
    for git in (
        ["git", "init", "-q"],
        ["git", "fetch", "-q", "--depth", "1", entry["url"], entry["commit"]],
        ["git", "checkout", "-q", "FETCH_HEAD"],
    ):
        rb.sh(git, cwd=project).check_returncode()


def console_script(venv: Path, command: str) -> str:
    """The `module:function` behind a console script, as installed in `venv`."""
    lookup = (
        "import importlib.metadata as m, sys; "
        "print(next(e.value for e in m.entry_points(group='console_scripts') "
        "if e.name == sys.argv[1]))"
    )
    found = rb.sh([str(rb.venv_python(venv)), "-c", lookup, command])
    found.check_returncode()
    return found.stdout.strip()


def normalise(text: str, replacements: list[tuple[str, str]]) -> str:
    """Make output comparable: one path style, each environment's locations replaced by a
    placeholder, and a crash reduced to its final exception line (the frames differ by design:
    a console-script launcher vs bundleup's loader)."""
    text = text.replace("\\", "/")
    for old, new in replacements:
        text = text.replace(old.replace("\\", "/"), new)
    text = text.strip()
    if "Traceback (most recent call last):" in text:
        text = text.splitlines()[-1]
    return text


def installed_command(entry: Entry, venv: Path) -> list[str]:
    """How a user runs the installed program: its console script, or (for an app that has
    none, like awscli) its entry function under the program's name."""
    command = entry["command"]
    if "entry" not in entry:
        folder, suffix = ("Scripts", ".exe") if rb.WINDOWS else ("bin", "")
        return [str(venv / folder / (command + suffix))]
    module, function = entry["entry"].split(":")
    call = f"import sys; sys.argv[0] = {command!r}; from {module} import {function}; "
    return [str(rb.venv_python(venv)), "-c", call + f"sys.exit({function}())"]


def site_packages(venv: Path) -> str:
    purelib = "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    return rb.sh([str(rb.venv_python(venv)), "-c", purelib]).stdout.strip()


def compare_run(entry: Entry, args: list[str], *, py: str, venv: Path, bundle: Path) -> str:
    """'' if the installed program and the bundle behave the same, else what differed."""
    command = entry["command"]
    stage = bundle.parent.parent
    home, _ = rb.fresh_dirs(stage, "run")
    cache = stage / "run-cache"
    shutil.rmtree(cache, ignore_errors=True)
    # Same hash seed both ways: some programs list things in set order (twine's subcommands).
    env = rb.run_env(home) | {"PYTHONHASHSEED": "0"}
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    timeout = rb.RUN_TIMEOUT
    installed = installed_command(entry, venv)
    normal = rb.sh([*installed, *args], cwd=home, env=env, timeout=timeout)
    bundle_env = env | {"BUNDLEUP_CACHE": str(cache)}
    bundled_cmd = rb.without_network([py, str(bundle), *args], bundle_env)
    bundled = rb.sh(bundled_cmd, cwd=home, env=bundle_env, timeout=timeout)
    unpacked = (
        [str(p) for p in cache.iterdir() if not p.name.startswith(".")] if cache.exists() else []
    )
    # Where each copy of the program lives shows up in output (`--version` "from <path>"): the
    # venv's site-packages and the bundle's unpacked copy are the same place, logically.
    paths = [(site, "<SITE>") for site in [site_packages(venv), *unpacked]]
    paths += [(installed[0], command), (str(bundle), command)]
    paths += [(str(venv), "<ENV>"), (str(home), "<HOME>"), (str(stage), "<STAGE>")]
    if normal.returncode != bundled.returncode:
        return (
            f"exit-code: `{command} {' '.join(args)}` exited {normal.returncode} installed, "
            f"{bundled.returncode} bundled: {normalise(bundled.stderr, paths)[-600:]}"
        )
    for stream in ("stdout", "stderr"):
        a = normalise(getattr(normal, stream), paths)
        b = normalise(getattr(bundled, stream), paths)
        if a != b:
            first = next(
                (
                    f"{x!r} vs {y!r}"
                    for x, y in zip(a.splitlines(), b.splitlines(), strict=False)
                    if x != y
                ),
                "different length",
            )
            return f"output: `{command} {' '.join(args)}` {stream} differs: {first[:400]}"
    return ""


def run_entry(entry: Entry, python: str) -> CorpusResult:
    name = name_of(entry)
    pin = entry.get("requirement") or entry["commit"]
    os_name = f"{sys.platform}-{platform.machine().lower()}"
    res = CorpusResult(name, entry["kind"], pin, os_name, python)
    res.network_blocked = rb.network_blocker() is not None
    stage = WORK / f"{entry['kind']}-{name.replace('/', '-')}" / python
    project, venv = stage / "project", stage / "venv"
    py = rb.python_path(python)
    try:
        prepare(entry, project, python)
    except subprocess.CalledProcessError as e:
        res.outcome, res.phase, res.code = "fail", "prepare", "prepare-failed"
        res.detail = str(e.stderr or e)[-600:]
        return res
    try:
        rb.install_normally(project, {"id": name, "args": []}, py=py, venv=venv)
        target = entry.get("entry") or console_script(venv, entry["command"])
    except subprocess.CalledProcessError as e:
        res.outcome, res.phase = "skipped", "install"
        res.detail = "doesn't install normally here: " + str(e.stderr or e)[-400:]
        return res
    bundle = stage / "bin" / entry["command"]  # named like the console script, so usage matches
    build = [str(rb.BUNDLEUP), "build", str(project), "--python", py, "--entry", target]
    built = rb.sh([*build, "-o", str(bundle), "--json"])
    if built.returncode:
        res.outcome, res.phase = "fail", "build"
        try:
            diagnostics = json.loads(built.stdout)["diagnostics"]
            res.code = diagnostics[0]["code"] if diagnostics else "build-failed"
            res.detail = json.dumps(diagnostics)[-1200:]
        except (ValueError, KeyError):
            res.code, res.detail = "build-crashed", (built.stderr or built.stdout)[-1200:]
        return res
    for args in entry["runs"]:
        difference = compare_run(entry, args, py=py, venv=venv, bundle=bundle)
        if difference:
            res.outcome, res.phase = "fail", "run"
            res.code, res.detail = difference.split(":", 1)[0], difference
            return res
    res.outcome = "pass"
    return res


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("only", nargs="*", help="entry name prefixes (default: all)")
    parser.add_argument("--python", default="3.12")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", help="write results JSON to gauntlet/results/<out>.json")
    parser.add_argument("--check", action="store_true", help="exit 1 if anything failed")
    opts = parser.parse_args()
    entries = [e for e in load_corpus() if not opts.only or name_of(e).startswith(tuple(opts.only))]
    rb.sh(["uv", "sync", "--quiet"], cwd=rb.ROOT.parent).check_returncode()

    results: list[CorpusResult] = []
    with cf.ThreadPoolExecutor(opts.jobs) as pool:
        futures = {pool.submit(run_entry, e, opts.python): e for e in entries}
        for future in cf.as_completed(futures):
            entry = futures[future]
            try:
                r = future.result()
            except Exception as e:  # harness bug: record it rather than crash the whole run
                r = CorpusResult(name_of(entry), entry["kind"], "", sys.platform, opts.python)
                r.outcome, r.code, r.detail = "harness-error", type(e).__name__, repr(e)[-600:]
            results.append(r)
            print(f"{r.outcome:<13} {r.name:<16} {r.phase:<8} {r.code:<16} {r.detail[:70]!r}")

    results.sort(key=lambda r: r.name)
    if opts.out:
        rb.RESULTS.mkdir(exist_ok=True)
        rows = [asdict(r) for r in results]
        (rb.RESULTS / f"{opts.out}.json").write_text(json.dumps(rows, indent=2))
    counts = {o: sum(r.outcome == o for r in results) for o in sorted({r.outcome for r in results})}
    print(f"\n{len(results)} programs: {counts}")
    return 1 if opts.check and any(r.outcome in ("fail", "harness-error") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
