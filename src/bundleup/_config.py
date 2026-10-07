"""`[tool.bundleup]` configuration (ADR-0032, style guide rules 28-31): settings that belong to the
project, in `pyproject.toml` or a PEP 723 script's `[tool.bundleup]` table. Flags and
environment variables win over it; it wins over defaults.

    [tool.bundleup]
    target = "lambda"
    entry = "app:handler"
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _toml as tomllib
from ._errors import ProjectError, UsageError
from ._targets import FORMATS

if TYPE_CHECKING:
    from ._build import BuildOptions


# Key in [tool.bundleup] -> BuildOptions field. Strings unless listed in BOOLEANS or LISTS.
KEYS = {
    "target": "target",
    "format": "format",
    "python": "python",
    "python-platform": "python_platform",
    "entry": "entry",
    "output": "output",
    "strict": "strict",
}
BOOLEANS = {"strict"}
# Keys that also take a list: a .pyz for several Pythons or platforms (ADR-0038).
LISTS = {"python": "more_pythons", "python-platform": "more_python_platforms"}
# Per-run settings: flags and environment only (rule 29).
PER_RUN = {"json", "quiet", "verbose", "color", "dry-run", "locked", "frozen"}


def read(path: Path) -> tuple[dict[str, Any], Path | None]:
    """The [tool.bundleup] table for a project directory or PEP 723 script, and the file it came
    from (None when there's none). Any: TOML values, validated by `apply`."""
    from ._source import script_metadata  # imported here: _source is heavier than this module

    path = path.resolve()
    if path.is_file() and path.suffix == ".py":
        table = script_metadata(path.read_text(encoding="utf-8")).get("tool", {}).get("bundleup")
        return (table or {}), (path if table else None)
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return {}, None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}, None  # reported, with its line, when the project is loaded
    table = data.get("tool", {}).get("bundleup")
    return (table or {}), (pyproject if table else None)


def _invalid(where: Path, message: str, hint: str) -> UsageError:
    return UsageError(f"invalid [tool.bundleup] in {where.name}: {message}", hint=hint)


def apply(options: BuildOptions) -> tuple[BuildOptions, list[str]]:
    """Fill every option not set by a flag or the environment from [tool.bundleup]. Returns the
    options and the settings taken from the file, as `key = value` lines for -v."""
    table, where = read(options.path)
    if not table or where is None:
        return options, []
    if not isinstance(table, dict):
        raise ProjectError(f"[tool.bundleup] in {where.name} must be a table")
    changes: dict[str, Any] = {}
    used = []
    for key, value in table.items():
        if key in PER_RUN:
            raise _invalid(
                where, f"`{key}` is a per-run setting", f"pass --{key} on the command line"
            )
        field = KEYS.get(key)
        if field is None:
            import difflib  # only on this error path

            close = difflib.get_close_matches(key, KEYS, n=1)
            hint = f"did you mean `{close[0]}`?" if close else f"keys: {', '.join(sorted(KEYS))}"
            raise _invalid(where, f"unknown key `{key}`", hint)
        if key in LISTS and isinstance(value, list):
            if not value or not all(isinstance(v, str) for v in value):
                raise _invalid(where, f"`{key}` must be a string or a list of strings",
                               f'for example: {key} = ["3.11", "3.12"]')  # fmt: skip
            if getattr(options, field) is None:
                changes[field], changes[LISTS[key]] = value[0], tuple(value[1:])
                used.append(f"{key} = {value}")
            continue
        wanted = bool if key in BOOLEANS else str
        if not isinstance(value, wanted):
            kind = "true or false" if wanted is bool else "a string"
            raise _invalid(
                where, f"`{key}` must be {kind}", f"for example: {key} = {_example(key)}"
            )
        if key == "format" and value not in FORMATS:
            raise _invalid(where, f"unknown format `{value}`", f"use one of {', '.join(FORMATS)}")
        current = getattr(options, field)
        if field == "strict":
            if value and not current:
                changes[field] = True
                used.append(f"{key} = true")
        elif current is None and isinstance(value, str):
            # A relative output is relative to the file that names it, not to where you run.
            changes[field] = (where.parent / value) if field == "output" else value
            used.append(f'{key} = "{value}"')
    return replace(options, **changes), used


def _example(key: str) -> str:
    return {"strict": "true", "format": '"lambda"', "target": '"lambda"'}.get(key, '"..."')
