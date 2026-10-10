"""`--against FILE`: a destination described as data (ADR-0044, rounds 6 and 7).

A small TOML file states what a destination is: its Python, platform and size limit, whether it
has network access and allows installs, and where those facts come from and when they were
checked. `--against` applies its settings to a build or check (flags still win) and reports the
facts. It's data anyone can read, copy or write, not a name built into bundleup (ADR-0039); the
ones bundleup's recipes use are in docs/targets/.

    name = "Claude API code execution and Skills"
    source = "https://platform.claude.com/docs/..."
    checked = "2026-10-09"
    python = "3.11"
    python-platform = "x86_64-manylinux_2_28"
    max-size = "30MB"
    network = false
    installs = false
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import _toml as tomllib
from ._errors import UsageError
from ._formats import FORMATS, Format, parse_size

if TYPE_CHECKING:
    from ._build import BuildOptions

TEXT = {"name", "source", "checked", "notes", "python", "python-platform", "max-size", "format"}
FLAGS = {"network", "installs"}
REQUIRED = ("name", "source", "checked")


@dataclass(frozen=True)
class TargetFile:
    """A destination described as data. `to_json_dict()` is `result.against` in `--json`."""

    path: Path
    name: str
    source: str
    checked: str
    python: str | None = None
    python_platform: str | None = None
    max_size: int | None = None
    max_size_text: str | None = None  # as written: "30MB"
    format: Format | None = None
    network: bool | None = None
    installs: bool | None = None
    notes: str | None = None

    def flags(self) -> list[str]:
        """The settings it stands for, as command-line flags."""
        out = []
        for flag, value in (
            ("--format", self.format),
            ("--python", self.python),
            ("--python-platform", self.python_platform),
            ("--max-size", self.max_size_text),
        ):
            if value:
                out += [flag, str(value)]
        return out

    def facts(self) -> str:
        """`no network, no installs`, from what the file says."""
        said = []
        if self.network is not None:
            said.append("network" if self.network else "no network")
        if self.installs is not None:
            said.append("installs allowed" if self.installs else "no installs")
        return ", ".join(said)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "file": str(self.path),
            "name": self.name,
            "source": self.source,
            "checked": self.checked,
            "network": self.network,
            "installs": self.installs,
            "flags": self.flags(),
        }


def load(path: Path) -> TargetFile:
    """Read and check a target file. Raises UsageError for a missing file or a mistake in it."""
    try:
        data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))  # Any: TOML
    except OSError as e:
        raise UsageError(f"can't read --against {path}: {e.strerror or e}") from None
    except tomllib.TOMLDecodeError as e:
        raise UsageError(f"--against {path} isn't valid TOML: {e}") from None
    for key, value in data.items():
        if key not in TEXT | FLAGS:
            import difflib  # only on this error path

            close = difflib.get_close_matches(key, sorted(TEXT | FLAGS), n=1)
            raise UsageError(
                f"unknown key `{key}` in {path.name}",
                hint=f"did you mean `{close[0]}`?"
                if close
                else f"keys: {', '.join(sorted(TEXT | FLAGS))}",
            )
        wanted = bool if key in FLAGS else str
        if not isinstance(value, wanted):
            kind = "true or false" if wanted is bool else "a string"
            raise UsageError(f"`{key}` in {path.name} must be {kind}")
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise UsageError(
            f"{path.name} doesn't say {', '.join(missing)}",
            hint="a target file names the destination, its source and when it was checked",
        )
    fmt = data.get("format")
    if fmt is not None and fmt not in FORMATS:
        raise UsageError(
            f"unknown format `{fmt}` in {path.name}", hint=f"use one of {', '.join(FORMATS)}"
        )
    return TargetFile(
        path=path,
        name=data["name"],
        source=data["source"],
        checked=data["checked"],
        python=data.get("python"),
        python_platform=data.get("python-platform"),
        max_size=parse_size(data["max-size"]) if "max-size" in data else None,
        max_size_text=data.get("max-size"),
        format=fmt,
        network=data.get("network"),
        installs=data.get("installs"),
        notes=data.get("notes"),
    )


def apply(options: BuildOptions, target: TargetFile) -> BuildOptions:
    """Fill every setting the options don't already have from the target file: flags and the
    environment win over it, and it wins over [tool.bundleup] (it was asked for on this run)."""
    return replace(
        options,
        python=options.python or target.python,
        python_platform=options.python_platform or target.python_platform,
        max_size=options.max_size if options.max_size is not None else target.max_size,
        format=options.format or target.format,
    )
