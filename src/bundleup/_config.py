"""`[tool.bundleup]` configuration (ADR-0032, style guide rules 28-31): settings that belong to the
project, in `pyproject.toml` or a PEP 723 script's `[tool.bundleup]` table. Flags and
environment variables win over it; it wins over defaults.

    [tool.bundleup]
    format = "zip"
    entry = "app:handler"
    max-size = "30MB"
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _toml as tomllib
from ._errors import ProjectError, UsageError
from ._formats import FORMATS, parse_size
from ._imports import code_frame

if TYPE_CHECKING:
    from ._build import BuildOptions


# Key in [tool.bundleup] -> BuildOptions field. Strings unless listed in BOOLEANS or LISTS.
KEYS = {
    "format": "format",
    "python": "python",
    "python-platform": "python_platform",
    "entry": "entry",
    "output": "output",
    "strict": "strict",
    "max-size": "max_size",
    "split": "split",
    "external": "external",
}
BOOLEANS = {"strict"}
# Keys that also take a list: a .pyz for several Pythons or platforms (ADR-0038).
LISTS = {"python": "more_pythons", "python-platform": "more_python_platforms"}
# Per-run settings: flags and environment only (rule 29).
PER_RUN = {"json", "quiet", "verbose", "color", "dry-run", "locked", "frozen", "smoke", "matrix"}


def read(path: Path) -> tuple[dict[str, Any], Path | None]:
    """The [tool.bundleup] table for a project directory or PEP 723 script, and the file it came
    from (None when there's none). Any: TOML values, validated by `apply`."""
    import os

    from ._source import (
        read_python_text,
        script_metadata,
    )  # imported here: _source is heavier than this module

    path = Path(os.path.abspath(path))
    if path.is_file() and path.suffix == ".py":
        try:
            text = read_python_text(path)
            tool = script_metadata(text, path).get("tool")
        except (OSError, ProjectError):
            return {}, None  # reported when the script is loaded
        if isinstance(tool, dict) and "bundleup" in tool:
            return tool["bundleup"], path
        return {}, None
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file():
        return {}, None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}, None  # reported, with its line, when the project is loaded
    tool = data.get("tool")
    if isinstance(tool, dict) and "bundleup" in tool:
        return tool["bundleup"], pyproject
    return {}, None


def _key_line(where: Path, key: str | None) -> int | None:
    """1-based line number of `key = ...` inside `[tool.bundleup]` in `where`, if found."""
    try:
        lines = where.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    prefix = r"^\s*#\s?" if where.suffix == ".py" else r"^\s*"
    header = re.compile(rf"{prefix}\[\s*tool\.bundleup\s*\]")
    if key is None:
        table_assign = re.compile(rf"{prefix}(?:tool\.)?bundleup\s*=")
        for i, raw in enumerate(lines, start=1):
            if header.match(raw) or table_assign.match(raw):
                return i
        return None
    in_section = False
    other_header = re.compile(rf"{prefix}\[\s*\[?\s*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\s*\]")
    key_pat = re.compile(rf"{prefix}(?:['\"])?{re.escape(key)}(?:['\"])?\s*=")
    dotted_pat = re.compile(
        rf"{prefix}(?:tool\.)?bundleup\.(?:['\"])?{re.escape(key)}(?:['\"])?\s*="
    )
    fallback: int | None = None
    for i, raw in enumerate(lines, start=1):
        if header.match(raw):
            in_section = True
        elif in_section and other_header.match(raw):
            in_section = False
        elif in_section and key_pat.match(raw):
            return i
        elif fallback is None and dotted_pat.match(raw):
            fallback = i
    return fallback


def _invalid(where: Path, message: str, hint: str, *, key: str | None = None) -> UsageError:
    line = _key_line(where, key)
    loc = f"{where.name}:{line}" if line else where.name
    return UsageError(
        f"invalid [tool.bundleup] in {loc}: {message}",
        hint=hint,
        detail=code_frame(where, line),
    )


def _validate_platforms(where: Path, items: list[str], key: str) -> None:
    from . import _platforms

    for item in items:
        try:
            _platforms.parse(item)
        except UsageError as e:
            raise _invalid(where, str(e), e.hint or "", key=key) from None


def _validate_entry_syntax(where: Path, value: str, key: str) -> None:
    if not value.strip():
        raise _invalid(
            where,
            "entry point is empty",
            "write module:callable (or module, or a [project.scripts] name)",
            key=key,
        )
    if value.count(":") > 1 or value.startswith(":") or value.endswith(":"):
        raise _invalid(
            where,
            f"invalid entry point: {value!r}",
            "write module:callable (for example: my_app.cli:main)",
            key=key,
        )


def apply(options: BuildOptions, *, for_check: bool = False) -> tuple[BuildOptions, list[str]]:
    """Fill every option not set by a flag or the environment from [tool.bundleup]. Returns the
    options and the settings taken from the file, as `key = value` lines for -v."""
    table, where = read(options.path)
    if where is None:
        return options, []
    if not isinstance(table, dict):
        line = _key_line(where, None)
        raise ProjectError(
            f"[tool.bundleup] in {where.name} must be a table",
            hint="use a [tool.bundleup] section header",
            detail=code_frame(where, line),
        )
    if not table:
        return options, []
    fmt_override = options.format
    changes: dict[str, Any] = {}
    used = []
    for key, value in table.items():
        if key in PER_RUN:
            hint = (
                "only 'bundleup cache clean' takes --dry-run"
                if key == "dry-run"
                else f"pass --{key} on the command line"
            )
            raise _invalid(where, f"`{key}` is a per-run setting", hint, key=key)
        field = KEYS.get(key)
        if field is None:
            import difflib  # only on this error path

            close = difflib.get_close_matches(key, KEYS, n=1)
            hint = f"did you mean `{close[0]}`?" if close else f"keys: {', '.join(sorted(KEYS))}"
            raise _invalid(where, f"unknown key `{key}`", hint, key=key)
        if key == "external":
            if isinstance(value, str) and [x.strip() for x in value.split(",") if x.strip()]:
                items = [value]
            elif (
                isinstance(value, list)
                and value
                and all(isinstance(v, str) and v.strip() for v in value)
            ):
                items = value
            else:
                raise _invalid(
                    where,
                    "`external` must be a string or a list of strings",
                    f"for example: external = {_example('external')}",
                    key=key,
                )
            if not options.external:
                changes["external"] = tuple(items)
                used.append(
                    f'external = "{value}"' if isinstance(value, str) else f"external = {value}"
                )
            continue
        if key in LISTS and isinstance(value, list):
            if not value or not all(isinstance(v, str) and v.strip() for v in value):
                raise _invalid(
                    where,
                    f"`{key}` must be a string or a list of strings",
                    f"for example: {key} = {_list_example(key)}",
                    key=key,
                )
            flat = [x.strip() for v in value for x in v.split(",") if x.strip()]
            if not flat:
                raise _invalid(
                    where,
                    f"`{key}` must be a string or a list of strings",
                    f"for example: {key} = {_list_example(key)}",
                    key=key,
                )
            if key == "python-platform":
                _validate_platforms(where, flat, key)
            more = LISTS[key]
            if getattr(options, field) is None and not getattr(options, more):
                single_only = (for_check and key == "python") or (
                    not for_check and fmt_override is not None and fmt_override not in ("pyz", "py")
                )
                if single_only:
                    changes[field] = flat[0]
                    used.append(f'{key} = "{flat[0]}"')
                else:
                    changes[field], changes[more] = flat[0], tuple(flat[1:])
                    used.append(f"{key} = {value}")
            continue
        wanted = bool if key in BOOLEANS else str
        if not isinstance(value, wanted):
            kind = (
                "true or false"
                if wanted is bool
                else ("a string or a list of strings" if key in LISTS else "a string")
            )
            raise _invalid(
                where,
                f"`{key}` must be {kind}",
                f"for example: {key} = {_example(key)}",
                key=key,
            )
        if key in ("max-size", "split"):  # "30MB", as on the command line
            try:
                parsed = parse_size(str(value))
            except UsageError as e:
                raise _invalid(where, str(e), e.hint or "", key=key) from None
            if parsed <= 0:
                raise _invalid(
                    where,
                    f"{key} must be greater than 0: {value!r}",
                    "write a positive size like 50MB or 500KB",
                    key=key,
                )
            if getattr(options, field) is None and not (
                key == "split" and fmt_override is not None and fmt_override != "pyz"
            ):
                changes[field] = parsed
                used.append(f'{key} = "{value}"')
            continue
        if key == "format" and value not in FORMATS:
            raise _invalid(
                where,
                f"unknown format `{value}`",
                f"use one of {', '.join(FORMATS)}",
                key=key,
            )
        if key in LISTS and isinstance(value, str):
            parts = [x.strip() for x in value.split(",") if x.strip()]
            if not parts:
                raise _invalid(
                    where,
                    f"`{key}` must be a string or a list of strings",
                    f"for example: {key} = {_example(key)}",
                    key=key,
                )
            if key == "python-platform":
                _validate_platforms(where, parts, key)
            if (
                (for_check and key == "python")
                or (
                    not for_check and fmt_override is not None and fmt_override not in ("pyz", "py")
                )
            ) and len(parts) > 1:
                value = parts[0]
        if key == "entry" and isinstance(value, str):
            _validate_entry_syntax(where, value, key)
        current = getattr(options, field)
        if field == "strict":
            if value and not current:
                changes[field] = True
                used.append(f"{key} = true")
        elif current is None and isinstance(value, str):
            if key == "entry" and value == "python" and fmt_override in ("dir", "zip"):
                continue
            # A relative output is relative to the file that names it, not to where you run.
            changes[field] = (where.parent / value) if field == "output" else value
            used.append(f'{key} = "{value}"')
    return replace(options, **changes), used


def _example(key: str) -> str:
    return {
        "strict": "true",
        "format": '"zip"',
        "python": '"3.12"',
        "python-platform": '"linux"',
        "max-size": '"30MB"',
        "split": '"100MB"',
        "external": '["boto3"]',
        "entry": '"my_app.cli:main"',
        "output": '"dist/my-app.pyz"',
    }.get(key, '"..."')


def _list_example(key: str) -> str:
    return {
        "python": '["3.11", "3.12"]',
        "python-platform": '["linux", "macos"]',
    }.get(key, _example(key))
