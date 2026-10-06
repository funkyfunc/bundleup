"""The CLI's contracts (docs/cli-style-guide.md): output snapshots (rule 47), exit codes (48), the
--json schema (50), the public API (44), the startup budget (35) and the generated CLI reference
(34). Regenerate snapshots after an intended change with:

    UPDATE_SNAPSHOTS=1 uv run pytest -q tests/test_cli.py
"""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from dataclasses import fields
from pathlib import Path

import jsonschema
import pytest

import bundleup
from bundleup import _cli

ROOT = Path(__file__).parent.parent
SNAPSHOTS = Path(__file__).parent / "snapshots"
SCHEMA = json.loads((ROOT / "docs" / "schema" / "build-v1.json").read_text())
CHECK_SCHEMA = json.loads((ROOT / "docs" / "schema" / "check-v1.json").read_text())
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"
# argparse's help layout changes between Python versions; help snapshots use the dev Python.
HELP_PYTHON = (3, 12)
help_snapshot = pytest.mark.skipif(
    sys.version_info[:2] != HELP_PYTHON, reason="argparse help layout differs by Python version"
)

SCRIPT = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
print("hi")
"""
# Doesn't compile on any Python: the check's syntax-error finding, in the project's own code.
BROKEN = SCRIPT.replace('print("hi")', 'print("hi"')


def cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run `python -m bundleup` the way a user's terminal would, minus colour."""
    env = {k: v for k, v in os.environ.items() if k not in ("FORCE_COLOR", "BUNDLEUP_PYTHON")}
    env |= {"NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "bundleup", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def redact(text: str, tmp: Path) -> str:
    """Remove what varies between machines and runs: paths, sizes, durations, the platform."""
    text = text.replace(str(tmp), "<TMP>").replace(sys.executable, "<PYTHON>")
    text = re.sub(r"\d+(\.\d+)? (B|KiB|MiB|GiB)\b", "<SIZE>", text)
    text = re.sub(r"in \d+\.\d+s", "in <DURATION>", text)
    text = re.sub(r"Python \d+\.\d+(\.\d+)?", "Python <VERSION>", text)
    text = re.sub(r" on (macOS|Linux|Windows)( \w+)?", " on <PLATFORM>", text)
    return text.replace("\\", "/")


def check_snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE:
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"no snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text == path.read_text(encoding="utf-8")


@pytest.fixture
def script(tmp_path: Path) -> Path:
    path = tmp_path / "app.py"
    path.write_text(SCRIPT)
    return path


# --- output snapshots (rule 47) and exit codes (rule 48) ---------------------------------------


@help_snapshot
def test_help(tmp_path: Path) -> None:
    r = cli("--help", cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == ""
    check_snapshot("help", r.stdout)


@help_snapshot
def test_build_help(tmp_path: Path) -> None:
    r = cli("build", "--help", cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == ""
    assert len(r.stdout.splitlines()) <= 32  # rule 32: short enough to read at a glance
    check_snapshot("build-help", r.stdout)


def test_version(tmp_path: Path) -> None:
    r = cli("--version", cwd=tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, f"bundleup {bundleup.__version__}\n", "")


@help_snapshot
def test_bare_command_prints_help_and_fails(tmp_path: Path) -> None:
    r = cli(cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == ""
    check_snapshot("bare", r.stderr)


def test_unknown_command_suggests_the_closest(tmp_path: Path) -> None:
    r = cli("buld", cwd=tmp_path)
    assert r.returncode == 2 and r.stdout == ""
    check_snapshot("typo", r.stderr)


def test_success(tmp_path: Path, script: Path) -> None:
    r = cli("build", "app.py", "-o", "app.pyz", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""  # stdout is for machine output only (rule 10)
    assert len(r.stderr.splitlines()) <= 2  # rule 11
    check_snapshot("success", redact(r.stderr, tmp_path))


def test_quiet_success_prints_nothing(tmp_path: Path, script: Path) -> None:
    r = cli("build", "app.py", "-o", "app.pyz", "-q", cwd=tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


@help_snapshot
def test_check_help(tmp_path: Path) -> None:
    r = cli("check", "--help", cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == ""
    assert len(r.stdout.splitlines()) <= 32  # rule 32
    check_snapshot("check-help", r.stdout)


def test_check_success(tmp_path: Path, script: Path) -> None:
    r = cli("check", "app.py", cwd=tmp_path)
    assert r.returncode == 0 and r.stdout == "", r.stderr
    check_snapshot("check-success", redact(r.stderr, tmp_path))
    assert not (tmp_path / "dist").exists()  # check never writes a bundle


def redact_compiler(text: str) -> str:
    """The compiler's wording differs between Python versions."""
    return re.sub(r"(doesn't compile on Python <VERSION>): .*", r"\1: <MESSAGE>", text)


def test_check_and_build_report_code_that_does_not_compile(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(BROKEN)
    r = cli("check", "app.py", cwd=tmp_path)
    assert r.returncode == 1 and r.stdout == ""
    check_snapshot("check-syntax-error", redact_compiler(redact(r.stderr, tmp_path)))
    r = cli("build", "app.py", "-o", "app.pyz", cwd=tmp_path)
    assert r.returncode == 1 and not (tmp_path / "app.pyz").exists()
    check_snapshot("error-check-failed", redact_compiler(redact(r.stderr, tmp_path)))
    r = cli("build", "app.py", "--json", cwd=tmp_path)
    document = json.loads(r.stdout)
    jsonschema.validate(document, SCHEMA)
    assert [d["code"] for d in document["diagnostics"]] == ["syntax-error", "check-failed"]
    assert document["diagnostics"][0]["file"] == "__bundleup_script__/app.py"


def test_check_json_matches_the_schema(tmp_path: Path, script: Path) -> None:
    r = cli("check", "app.py", "--json", cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == ""
    document = json.loads(r.stdout)
    jsonschema.validate(document, CHECK_SCHEMA)
    assert document["ok"] and document["diagnostics"] == []
    assert [p["name"] for p in document["result"]["packages"]] == ["app"]
    (tmp_path / "app.py").write_text(BROKEN)
    r = cli("check", "app.py", "--json", cwd=tmp_path)
    document = json.loads(r.stdout)
    jsonschema.validate(document, CHECK_SCHEMA)
    assert (r.returncode, document["ok"]) == (1, False)
    assert document["diagnostics"][0]["line"] == 5


def test_error_not_a_project(tmp_path: Path) -> None:
    r = cli("build", "nowhere", cwd=tmp_path)
    assert r.returncode == 1 and r.stdout == ""
    check_snapshot("error-not-a-project", redact(r.stderr, tmp_path))


def test_error_python_mismatch(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "future"\nrequires-python = ">=99"\n'
    )
    r = cli("build", "--python", sys.executable, cwd=tmp_path)
    assert r.returncode == 1
    check_snapshot("error-python-mismatch", redact(r.stderr, tmp_path))


def test_usage_error_entry_with_script(tmp_path: Path, script: Path) -> None:
    r = cli("build", "app.py", "--entry", "app:main", cwd=tmp_path)
    assert r.returncode == 2
    check_snapshot("error-entry-with-script", redact(r.stderr, tmp_path))


def test_crash_is_reported_as_a_bug(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], script: Path
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("bundleup._build.build", explode)
    assert _cli.main(["build", str(script)]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    check_snapshot("crash", captured.err)
    assert _cli.main(["build", str(script), "-v"]) == 3
    assert "Traceback" in capsys.readouterr().err  # -v shows it


def test_ctrl_c_exits_130(monkeypatch: pytest.MonkeyPatch, script: Path) -> None:
    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("bundleup._build.build", interrupt)
    assert _cli.main(["build", str(script)]) == 130


# --- --json (rules 16-20, 50) -------------------------------------------------------------------


def test_json_success_matches_the_schema(tmp_path: Path, script: Path) -> None:
    r = cli("build", "app.py", "-o", "app.pyz", "--json", cwd=tmp_path)
    assert r.returncode == 0 and r.stderr == ""  # human output is suppressed
    document = json.loads(r.stdout)  # exactly one document
    jsonschema.validate(document, SCHEMA)
    assert document["ok"] and document["result"]["output"] == "app.pyz"
    assert document["result"]["version"] is None  # a script has no version


def test_json_error_matches_the_schema(tmp_path: Path) -> None:
    r = cli("build", "nowhere", "--json", cwd=tmp_path)
    assert r.returncode == 1 and r.stderr == ""
    document = json.loads(r.stdout)
    jsonschema.validate(document, SCHEMA)
    assert [d["code"] for d in document["diagnostics"]] == ["invalid-project"]


def test_json_usage_error(tmp_path: Path) -> None:
    r = cli("build", "--nope", "--json", cwd=tmp_path)
    assert r.returncode == 2 and r.stderr == ""
    jsonschema.validate(json.loads(r.stdout), SCHEMA)


# --- the public API (rule 44) -------------------------------------------------------------------


def api_description() -> str:
    lines = [f"__all__ = {sorted(bundleup.__all__)}"]
    lines.append(f"build{inspect.signature(bundleup.build)}")
    lines.append(f"check{inspect.signature(bundleup.check)}")
    lines.append(f"verify{inspect.signature(bundleup.verify)}")
    lines.append(f"list_cache{inspect.signature(bundleup.list_cache)}")
    lines.append(f"clean_cache{inspect.signature(bundleup.clean_cache)}")
    public_types = (
        bundleup.BuildOptions,
        bundleup.BuildResult,
        bundleup.ProgressEvent,
        bundleup.Diagnostic,
        bundleup.CheckReport,
        bundleup.PackageSize,
        bundleup.VerifyReport,
        bundleup.CachedBundle,
        bundleup.CleanReport,
    )
    for cls in public_types:
        lines.append(f"{cls.__name__}: " + ", ".join(f"{f.name}: {f.type}" for f in fields(cls)))
    lines.append("ExitCode: " + ", ".join(f"{c.name}={c.value}" for c in bundleup.ExitCode))
    for name in sorted(bundleup.__all__):
        obj = getattr(bundleup, name)
        if isinstance(obj, type) and issubclass(obj, bundleup.BundleupError):
            lines.append(f"{name}: code={obj.code!r} exit_code={int(obj.exit_code)}")
    return "\n".join(lines) + "\n"


def test_public_api_is_unchanged() -> None:
    check_snapshot("api", api_description())


# --- startup budget (rule 35) and the generated reference (rule 34) ------------------------------


def test_version_and_help_import_nothing_heavy(tmp_path: Path) -> None:
    for args in (["--version"], ["--help"]):
        r = subprocess.run(
            [sys.executable, "-X", "importtime", "-m", "bundleup", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        imported = {line.split("|")[-1].strip() for line in r.stderr.splitlines() if "|" in line}
        heavy = {"bundleup._build", "packaging", "zipfile", "subprocess", "tempfile", "difflib"}
        assert not heavy & imported, f"{args} imported {sorted(heavy & imported)}"


def reference_markdown() -> str:
    sections = []
    for name, command in _cli.parsers().items():
        title = "bundleup" if name == "bundleup" else f"bundleup {name}"
        sections.append(f"## `{title}`\n\n```\n{command.format_help()}```\n")
    return (
        "# Command-line reference\n\n"
        "Generated from the parser by `tests/test_cli.py` (rule 34 of the "
        "[CLI style guide](cli-style-guide.md)); don't edit by hand. Regenerate with\n"
        "`UPDATE_SNAPSHOTS=1 uv run pytest -q tests/test_cli.py`.\n\n" + "\n".join(sections)
    )


@help_snapshot
def test_cli_reference_is_up_to_date() -> None:
    path = ROOT / "docs" / "cli-reference.md"
    text = reference_markdown()
    if UPDATE:
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text, "docs/cli-reference.md is stale"
