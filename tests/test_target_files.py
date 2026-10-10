"""`--against FILE`: a destination described as data (ADR-0044)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build
from bundleup._target_files import apply, load

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = """\
name = "A sandbox"
source = "https://example.com/docs"
checked = "2026-10-09"
python = "3.11"
python-platform = "x86_64-manylinux_2_28"
max-size = "30MB"
network = false
installs = false
"""


@pytest.mark.parametrize(
    "path", sorted((ROOT / "docs" / "targets").glob("*.toml")), ids=lambda p: p.stem
)
def test_the_published_target_files_are_valid(path: Path) -> None:
    target = load(path)
    assert target.name and target.source.startswith("https://") and target.checked


def test_settings_facts_and_precedence(tmp_path: Path) -> None:
    (tmp_path / "t.toml").write_text(CLAUDE)
    target = load(tmp_path / "t.toml")
    assert target.flags() == [
        "--python", "3.11", "--python-platform", "x86_64-manylinux_2_28", "--max-size", "30MB"
    ]  # fmt: skip
    assert target.facts() == "no network, no installs" and target.max_size == 30_000_000
    filled = apply(BuildOptions(python="3.12"), target)  # a flag wins over the file
    assert (filled.python, filled.python_platform, filled.max_size) == (
        "3.12", "x86_64-manylinux_2_28", 30_000_000
    )  # fmt: skip


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (CLAUDE.replace("python-platform", "python-platfrom"), "did you mean `python-platform`"),
        (CLAUDE.replace('checked = "2026-10-09"\n', ""), "doesn't say checked"),
        (CLAUDE.replace("network = false", 'network = "no"'), "must be true or false"),
        (CLAUDE + 'format = "msi"\n', "unknown format `msi`"),
    ],
)
def test_mistakes_are_usage_errors(tmp_path: Path, text: str, message: str) -> None:
    (tmp_path / "t.toml").write_text(text)
    with pytest.raises(UsageError) as e:
        load(tmp_path / "t.toml")
    assert message in str(e.value) or message in (e.value.hint or "")


def test_a_build_against_a_file_reports_it(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text("# /// script\n# dependencies = []\n# ///\nprint(1)\n")
    (tmp_path / "t.toml").write_text(
        'name = "Here"\nsource = "https://example.com"\nchecked = "2026-10-09"\n'
        'max-size = "10MB"\nnetwork = true\n'
    )
    result = build(BuildOptions(path=tmp_path / "tool.py", output=tmp_path / "t.pyz",
                                against=tmp_path / "t.toml"))  # fmt: skip
    assert result.against is not None and result.against.name == "Here"
    against = result.to_json_dict()["against"]
    assert isinstance(against, dict) and against["flags"] == ["--max-size", "10MB"]
