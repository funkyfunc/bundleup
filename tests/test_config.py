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
    path = project(tmp_path, 'format = "dir"\npython = "3.11"\nstrict = true\n')
    options, used = apply(BuildOptions(path=path, format="lambda"))
    assert (options.format, options.python, options.strict) == ("lambda", "3.11", True)
    assert used == ['python = "3.11"', "strict = true"]


@pytest.mark.parametrize(
    ("table", "message", "hint"),
    [
        ('targt = "lambda"\n', "unknown key `targt`", "did you mean `target`?"),
        ("json = true\n", "`json` is a per-run setting", "pass --json on the command line"),
        ("strict = 1\n", "`strict` must be true or false", "for example: strict = true"),
        ('format = "exe"\n', "unknown format `exe`", "use one of pyz, dir, lambda"),
    ],
)
def test_mistakes_are_usage_errors(tmp_path: Path, table: str, message: str, hint: str) -> None:
    with pytest.raises(UsageError, match=message) as e:
        apply(BuildOptions(path=project(tmp_path, table)))
    assert e.value.hint == hint
