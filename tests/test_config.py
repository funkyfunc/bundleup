"""`[tool.bundleup]` configuration (ADR-0032)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build
from bundleup._config import apply

SCRIPT = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# [tool.bundleup]
# format = "dir"
# output = "out"
# ///
print("hi")
"""


def project(tmp_path: Path, table: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "app"\n\n[tool.bundleup]\n{table}')
    return tmp_path


def test_a_scripts_table_applies_and_paths_are_relative_to_it(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text(SCRIPT)
    result = build(BuildOptions(path=tmp_path / "tool.py"))
    assert result.format == "dir" and result.output == tmp_path / "out"


def test_flags_and_environment_win(tmp_path: Path) -> None:
    table = 'format = "dir"\npython = "3.11"\nstrict = true\nmax-size = "30MB"\n'
    options, used = apply(BuildOptions(path=project(tmp_path, table), format="zip"))
    assert (options.format, options.python, options.strict) == ("zip", "3.11", True)
    assert options.max_size == 30_000_000
    assert used == ['python = "3.11"', "strict = true", 'max-size = "30MB"']


@pytest.mark.parametrize(
    ("table", "message", "hint"),
    [
        ('formt = "dir"\n', "unknown key `formt`", "did you mean `format`?"),
        ('max-size = "big"\n', "can't read the size `big`", "a number with an optional unit"),
        ("json = true\n", "`json` is a per-run setting", "pass --json on the command line"),
        ("strict = 1\n", "`strict` must be true or false", "for example: strict = true"),
        ('format = "msi"\n', "unknown format `msi`", "use one of pyz, py, exe, dir, zip"),
    ],
)
def test_mistakes_are_usage_errors(tmp_path: Path, table: str, message: str, hint: str) -> None:
    with pytest.raises(UsageError, match=message) as e:
        apply(BuildOptions(path=project(tmp_path, table)))
    assert e.value.hint is not None and e.value.hint.startswith(hint)


def test_check_allows_multi_target_lists_in_tool_bundleup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ninth & tenth reviews: a project with `python-platform = [...]` in `[tool.bundleup]` can
    still run `bundleup check` and `bundleup check --matrix`, folds the extra configured platforms
    into `also_platforms` in both the API and the CLI without duplicates, and rejects multiple CLI
    `--python-platform` flags before printing 'Building for ...'."""
    from bundleup import _cli, check
    from bundleup._errors import ProjectError
    from bundleup._source import load_source
    from bundleup._uv import pinned_requirements

    (tmp_path / "tool.py").write_text(
        SCRIPT.replace('format = "dir"', 'python-platform = ["linux", "macos"]')
    )
    report = check(BuildOptions(path=tmp_path / "tool.py"), matrix=True)
    assert report.ok and report.also_platforms == ["macos"]
    report2 = check(
        BuildOptions(path=tmp_path / "tool.py"), also_platforms=["macos", "linux", "macos"]
    )
    assert report2.also_platforms == ["macos"]

    assert _cli.main(["check", str(tmp_path / "tool.py")]) == 0
    err = capsys.readouterr().err
    assert "and its wheels for macos" in err

    assert (
        _cli.main(
            [
                "check",
                "--python-platform",
                "linux",
                "--python-platform",
                "macos",
                str(tmp_path / "tool.py"),
            ]
        )
        != 0
    )
    err = capsys.readouterr().err
    assert "Building for" not in err
    assert "one Python version and platform at a time" in err

    # UTF-8 BOM in PEP 723 script, pyproject.toml, and requirements.txt
    bom_script = tmp_path / "bom_script.py"
    bom_script.write_bytes(("\ufeff" + SCRIPT).encode("utf-8"))
    assert load_source(bom_script).pep723 is True
    options, _ = apply(BuildOptions(path=bom_script))
    assert options.format == "dir"

    req = tmp_path / "requirements.txt"
    req.write_bytes("\ufeffclick==8.1.7\n".encode("utf-8"))
    assert pinned_requirements(req) == ({"click": "8.1.7"}, False)

    bad_pep723 = tmp_path / "bad_pep723.py"
    bad_pep723.write_text("# /// script\n# dependencies = [\n# ///\nprint(1)\n")
    with pytest.raises(ProjectError, match="isn't valid TOML"):
        load_source(bad_pep723)
    assert apply(BuildOptions(path=bad_pep723))[1] == []


def test_eleventh_review_pep263_script_empty_env_vars_and_canonical_also_platforms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eleventh review: PEP 263 latin-1 scripts build and check cleanly, `-o` cannot overwrite the
    source script, empty BUNDLEUP_* env vars are ignored, and `also_platforms` deduplicates aliases
    against their expanded platform names."""
    from bundleup import _cli, build, check
    from bundleup._errors import UsageError

    latin1 = tmp_path / "latin1_app.py"
    code = '# -*- coding: latin-1 -*-\n# café\nimport json\nprint(json.dumps("café"))\n'
    latin1.write_bytes(code.encode("latin-1"))
    res = build(BuildOptions(path=latin1, output=tmp_path / "latin1.pyz"))
    assert res.output.is_file()

    with pytest.raises(UsageError, match="overwrite"):
        build(BuildOptions(path=latin1, output=latin1))

    monkeypatch.setenv("BUNDLEUP_MAX_SIZE", "")
    monkeypatch.setenv("BUNDLEUP_SPLIT", "")
    monkeypatch.setenv("BUNDLEUP_ENTRY", "")
    assert _cli.main(["check", str(latin1)]) == 0

    report = check(
        BuildOptions(path=latin1, python_platform="macos"),
        also_platforms=["aarch64-apple-darwin"],
    )
    assert report.also_platforms == []
