"""What's being bundled: a project directory, a script or a folder of modules, and what decides
its dependencies: a lockfile, or, without one, what declares them (ADR-0041)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.utils import canonicalize_name

from . import _toml as tomllib
from . import _verify
from ._errors import ProjectError
from ._formats import Format
from ._imports import imports_of, stdlib_ever, top_level_modules

PEP723 = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


@dataclass(frozen=True)
class Source:
    """What's being bundled: a project directory, a script, or a folder of modules."""

    path: Path  # project directory, script file, or folder
    name: str
    requires_python: str | None
    is_script: bool
    pylock: Path | None = None  # a project's pylock.toml (PEP 751), used when there's no uv.lock
    # Without a lock (ADR-0041), what declares the dependencies, resolved at build time: a
    # requirements.txt, or the project's pyproject.toml, setup.py or setup.cfg.
    declared: Path | None = None
    app: bool = False  # a folder of modules and a requirements.txt: its files go in as they are
    pep723: bool = True  # a script with a `# /// script` block (else: requirements.txt or none)

    @property
    def workdir(self) -> Path:
        """Where uv commands run: relative paths in the lock resolve against it."""
        return self.path.parent if self.is_script else self.path

    @property
    def locked(self) -> bool:
        """Whether a lockfile decides the contents (uv.lock, pylock.toml, <script>.lock)."""
        if self.is_script and self.pep723:
            return self.path.with_name(self.path.name + ".lock").is_file()
        return not self.is_script and not self.app and self.declared is None


def load_source(path: Path) -> Source:
    """Read what's being bundled. Raises ProjectError if it's none of the things bundleup takes."""
    path = path.resolve()
    if path.is_file() and path.suffix == ".py":
        return _load_script(path)
    if not path.is_dir():
        raise ProjectError(
            f"{path} is not a project directory or a .py script",
            hint="point bundleup at a folder with pyproject.toml, setup.py or requirements.txt, "
            "or at a .py script",
        )
    pyproject = path / "pyproject.toml"
    if pyproject.is_file():
        return _load_project(path, pyproject)
    legacy = next((path / n for n in ("setup.py", "setup.cfg") if (path / n).is_file()), None)
    if legacy is not None:
        # A setuptools project without pyproject.toml: uv builds it the way pip would.
        return Source(path, _legacy_name(path), None, is_script=False, declared=legacy)
    requirements = path / "requirements.txt"
    if requirements.is_file() or any((path / n).is_file() for n in APP_MAINS):
        undeclared = [] if requirements.is_file() else third_party_imports(path, local=path)
        if undeclared:
            raise ProjectError(
                f"{path.name} imports {_which(undeclared)} in the standard library, and has "
                "no requirements.txt saying which packages provide them",
                hint="list them in requirements.txt (an empty one says it needs none)",
            )
        declared = requirements if requirements.is_file() else None
        return Source(
            path, safe_name(path.name), None, is_script=False, declared=declared, app=True
        )
    raise ProjectError(
        f"{path} has no pyproject.toml, setup.py, requirements.txt or main.py",
        hint="point bundleup at a project directory, a folder of modules, or a .py script",
    )


# What runs when a folder of modules is bundled without --entry: what `python folder/` runs, then
# the usual names.
APP_MAINS = ("__main__.py", "main.py", "app.py")


def _load_script(path: Path) -> Source:
    text = path.read_text(encoding="utf-8")
    if any(m.group("type") == "script" for m in PEP723.finditer(text)):
        meta = script_metadata(text)
        return Source(path, path.stem, meta.get("requires-python"), is_script=True)
    # No `# /// script` block: a requirements.txt beside it, or only the standard library.
    requirements = path.with_name("requirements.txt")
    if requirements.is_file():
        return Source(path, path.stem, None, is_script=True, declared=requirements, pep723=False)
    undeclared = third_party_imports(path, local=path.parent)
    if undeclared:
        name = path.name
        raise ProjectError(
            f"{name} imports {_which(undeclared)} in the standard library, but doesn't say "
            "which packages provide them",
            hint=f"add them: `uv add --script {name} <packages>` (a `# /// script` block), or "
            "list them in a requirements.txt beside it",
        )
    return Source(path, path.stem, None, is_script=True, pep723=False)


def _load_project(path: Path, pyproject: Path) -> Source:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{pyproject} isn't valid TOML: {e}") from None
    project = data.get("project") or {}
    poetry = data.get("tool", {}).get("poetry", {})
    name = project.get("name") or poetry.get("name")
    if not name and not (path / "setup.py").is_file() and not (path / "setup.cfg").is_file():
        raise ProjectError(
            f"{pyproject} has no [project] name", hint='add `name = "..."` under [project]'
        )
    name = name or _legacy_name(path)
    # uv.lock first (it's what uv users have); a standard pylock.toml otherwise (ADR-0026).
    # Without either, the dependencies pyproject.toml declares are resolved at build time, in
    # the stage: bundleup never writes a lock into the project (ADR-0028, ADR-0041).
    uv_lock = find_uv_lock(path)
    lock = path / "pylock.toml"
    pylock = lock if lock.is_file() and uv_lock is None else None
    declared = pyproject if uv_lock is None and pylock is None else None
    return Source(
        path,
        name,
        project.get("requires-python"),
        is_script=False,
        pylock=pylock,
        declared=declared,
    )


def _legacy_name(path: Path) -> str:
    """A setuptools project's name: setup.cfg's [metadata], a literal in setup.py, or the folder."""
    import configparser

    cfg = configparser.ConfigParser()
    try:
        cfg.read(path / "setup.cfg", encoding="utf-8")
        if cfg.has_option("metadata", "name"):
            return cfg.get("metadata", "name")
    except configparser.Error:
        pass
    setup = path / "setup.py"
    if setup.is_file():
        found = re.search(r"""\bname\s*=\s*["']([^"']+)["']""", setup.read_text(encoding="utf-8"))
        if found:
            return found.group(1)
    return safe_name(path.name)


def third_party_imports(path: Path, *, local: Path) -> list[str]:
    """Top-level modules a script (or every .py in a folder) imports for sure that are neither
    in any version's standard library nor beside it. Empty when this Python can't tell (3.9 has
    no sys.stdlib_module_names)."""
    ever = stdlib_ever()
    if ever is None:
        return []
    files = [path] if path.is_file() else list(_app_files(path, suffix=".py"))
    neighbours = top_level_modules(local)
    found: set[str] = set().union(*(imports_of(f) for f in files)) if files else set()
    return sorted(found - ever - neighbours - {"__future__", "__main__"})


def _which(names: list[str]) -> str:
    return f"{names[0]}, which isn't" if len(names) == 1 else f"{', '.join(names)}, which aren't"


# Not part of a folder app: tooling, environments and build output.
SKIP_DIRS = {"__pycache__", "node_modules", "dist", "build", "site-packages", "venv", "env"}


def _app_files(folder: Path, *, suffix: str = "") -> list[Path]:
    """The files of a folder app, sorted: everything but hidden files, virtual environments,
    caches and build output."""
    found = []
    for item in sorted(folder.iterdir()):
        if item.name.startswith(".") or item.name.endswith(".egg-info"):
            continue
        if item.is_dir():
            if item.is_symlink() or item.name in SKIP_DIRS or (item / "pyvenv.cfg").exists():
                continue  # a symlinked folder could loop, or lead anywhere
            found += _app_files(item, suffix=suffix)
        elif item.is_file() and item.name.endswith(suffix) and not item.name.endswith(".pyc"):
            found.append(item)
    return found


def python_files(folder: Path, *, deep: bool = True) -> list[tuple[str, Path]]:
    """The .py files in a folder (with `deep`, under it, as for a folder app; .gitignore applies
    in a git work tree) and their POSIX paths relative to it."""
    if not deep:
        return [(f.name, f) for f in sorted(folder.glob("*.py")) if f.is_file()]
    tracked = _git_files(folder)
    found = [(f.relative_to(folder).as_posix(), f) for f in _app_files(folder, suffix=".py")]
    return [(rel, f) for rel, f in found if tracked is None or rel in tracked]


def app_files(source: Source) -> list[tuple[str, Path]]:
    """A folder app's files and where each goes in the payload (POSIX, relative): in a git
    repository only what git would track (.gitignore applies), never bundles (`*.pyz`) or the
    requirements files themselves (fourth review: a credentials.json and an earlier output went
    in)."""
    tracked = _git_files(source.path)
    found = []
    for file in _app_files(source.path):
        rel = file.relative_to(source.path).as_posix()
        if file.suffix == ".pyz" or (
            file.name.startswith("requirements") and file.suffix == ".txt"
        ):
            continue
        if tracked is None or rel in tracked:
            found.append((rel, file))
    return found


def _git_files(folder: Path) -> set[str] | None:
    """The files under `folder` git tracks or would (not ignored), relative to it; None outside a
    git work tree or without git."""
    import subprocess

    try:
        done = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=folder,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode:
        return None
    return {name for name in done.stdout.decode("utf-8", "replace").split("\0") if name}


# Files that usually hold secrets: a folder app shouldn't ship them without the author noticing.
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".env"}
SECRET_WORDS = {"credential", "credentials", "secret", "secrets", "password", "passwords",
                "token", "tokens", "key", "keys"}  # fmt: skip
DATA_SUFFIXES = {".json", ".yaml", ".yml", ".txt", ".ini", ".cfg", ".toml", ".env"}


def looks_secret(rel: str) -> bool:
    """A file name that usually holds secrets: a key or certificate, an .env file, id_rsa, or
    data named for credentials (`service-account.json`, `api-token.txt`; not `tokenizer.json`)."""
    name = rel.rsplit("/", 1)[-1].lower()
    stem, dot, suffix = name.rpartition(".")
    suffix = dot + suffix if dot else ""
    if suffix in SECRET_SUFFIXES or name.startswith(("id_rsa", "id_ed25519", "id_ecdsa")):
        return True
    words = set(re.split(r"[-_.\s]+", stem))
    return suffix in DATA_SUFFIXES and bool(
        words & SECRET_WORDS or "service-account" in stem or "service_account" in stem
    )


def find_uv_lock(project: Path) -> Path | None:
    """The project's uv.lock, or its workspace's: uv keeps one lock at the workspace root. A lock
    further up counts only if that root's [tool.uv.workspace] lists this project as a member;
    another project's lock higher in the repository isn't this one's (fourth review)."""
    if (project / "uv.lock").is_file():
        return project / "uv.lock"
    if (project / ".git").exists():
        return None  # the repository's root: nothing above it is this project's
    for directory in project.parents:
        if (directory / "uv.lock").is_file() and _is_member(project, directory):
            return directory / "uv.lock"
        if (directory / ".git").exists():
            break  # don't wander out of the repository
    return None


def _is_member(project: Path, root: Path) -> bool:
    """Whether `root`'s uv workspace includes `project` (its `members` globs, minus `exclude`)."""
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    workspace = data.get("tool", {}).get("uv", {}).get("workspace")
    if not isinstance(workspace, dict):
        return False

    def matched(key: str) -> bool:
        return any(project.resolve() in root.glob(g) for g in workspace.get(key, []))

    return matched("members") and not matched("exclude")


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
