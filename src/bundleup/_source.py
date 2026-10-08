"""What's being bundled: a project directory or a PEP 723 script, and its lockfile."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.utils import canonicalize_name

from . import _toml as tomllib
from . import _verify
from ._errors import (
    NoLockfileError,
    ProjectError,
)
from ._formats import Format

PEP723 = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


@dataclass(frozen=True)
class Source:
    """What's being bundled: a project directory or a PEP 723 script."""

    path: Path  # project directory or script file
    name: str
    requires_python: str | None
    is_script: bool
    pylock: Path | None = None  # a project's pylock.toml (PEP 751), used when there's no uv.lock

    @property
    def workdir(self) -> Path:
        """Where uv commands run: relative paths in the lock resolve against it."""
        return self.path.parent if self.is_script else self.path


def load_source(path: Path) -> Source:
    """Read what's being bundled. Raises ProjectError if it isn't a project or a script."""
    path = path.resolve()
    if path.is_file() and path.suffix == ".py":
        meta = script_metadata(path.read_text(encoding="utf-8"))
        return Source(path, path.stem, meta.get("requires-python"), is_script=True)
    if path.is_dir():
        pyproject = path / "pyproject.toml"
        if not pyproject.exists():
            raise ProjectError(
                f"{path} has no pyproject.toml",
                hint="point bundleup at a project directory or a .py script",
            )
        try:
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project") or {}
        except tomllib.TOMLDecodeError as e:
            raise ProjectError(f"{pyproject} isn't valid TOML: {e}") from None
        if "name" not in project:
            raise ProjectError(
                f"{pyproject} has no [project] name", hint='add `name = "..."` under [project]'
            )
        # uv.lock first (it's what uv users have); a standard pylock.toml otherwise (ADR-0026).
        # Without either, refuse: `uv export` would resolve and write a uv.lock into the
        # project, and the bundle would match nothing anyone reviewed (ADR-0028).
        uv_lock = find_uv_lock(path)
        lock = path / "pylock.toml"
        pylock = lock if lock.is_file() and uv_lock is None else None
        if uv_lock is None and pylock is None:
            raise NoLockfileError(
                f"{path.name} has no lockfile, so bundleup can't tell exactly what to bundle",
                hint="run `uv lock` in the project (or write a pylock.toml), then build again",
            )
        return Source(
            path, project["name"], project.get("requires-python"), is_script=False, pylock=pylock
        )
    raise ProjectError(
        f"{path} is not a project directory or a .py script",
        hint="pass a directory with pyproject.toml, or a PEP 723 script",
    )


def find_uv_lock(project: Path) -> Path | None:
    """The project's uv.lock, or its workspace's (uv keeps one lock at the workspace root)."""
    for directory in (project, *project.parents):
        if (directory / "uv.lock").is_file():
            return directory / "uv.lock"
        if (directory / ".git").exists():
            break  # don't wander out of the repository
    return None


def script_metadata(text: str) -> dict[str, Any]:  # Any: TOML values have no fixed type
    """The PEP 723 `script` block, parsed as TOML (empty if there is none)."""
    blocks = [m for m in PEP723.finditer(text) if m.group("type") == "script"]
    if len(blocks) > 1:
        raise ProjectError("the script has more than one `# /// script` block")
    if not blocks:
        return {}
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in blocks[0].group("content").splitlines(keepends=True)
    )
    return tomllib.loads(content)


def script_path(source: Source, fmt: Format) -> str | None:
    """Where a PEP 723 script goes in the payload: out of the way in a .pyz (the loader runs it),
    at the top for `dir` and `lambda`, where it's imported as a module (a Lambda handler)."""
    if not source.is_script:
        return None
    return f"{_verify.SCRIPT_DIR}/{source.path.name}" if fmt == "pyz" else source.path.name


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "app"


def project_version(site: Path, source: Source) -> str | None:
    """The project's version as installed (so dynamic versions work); None for a script."""
    if source.is_script:
        return None
    want = canonicalize_name(source.name)
    for dist in _verify.installed_distributions(site):
        if dist.name == want:
            return dist.version
    return None
