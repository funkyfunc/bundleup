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
    options, used = apply(BuildOptions(path=project(tmp_path, table), format="lambda"))
    assert (options.format, options.python, options.strict) == ("lambda", "3.11", True)
    assert options.max_size == 30_000_000
    assert used == ['python = "3.11"', "strict = true", 'max-size = "30MB"']


@pytest.mark.parametrize(
    ("table", "message", "hint"),
    [
        ('formt = "dir"\n', "unknown key `formt`", "did you mean `format`?"),
        ('max-size = "big"\n', "can't read the size `big`", "a number with an optional unit"),
        ("json = true\n", "`json` is a per-run setting", "pass --json on the command line"),
        ("strict = 1\n", "`strict` must be true or false", "for example: strict = true"),
        ('format = "msi"\n', "unknown format `msi`", "use one of pyz, py, dir, lambda"),
    ],
)
def test_mistakes_are_usage_errors(tmp_path: Path, table: str, message: str, hint: str) -> None:
    with pytest.raises(UsageError, match=message) as e:
        apply(BuildOptions(path=project(tmp_path, table)))
    assert e.value.hint is not None and e.value.hint.startswith(hint)
