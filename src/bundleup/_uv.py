"""Driving uv: export the locked set (or read a pylock.toml) and install it into the payload."""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.utils import canonicalize_name

from . import _bytecode, _loader, _verify
from . import _toml as tomllib
from ._errors import (
    LockfileOutdatedError,
    NoCompatibleWheelError,
    NoLockfileError,
    ProjectError,
    UvError,
    UvNotFoundError,
)
from ._python import Target
from ._source import Source, app_files, find_uv_lock
from ._steps import Progress, run

# Copied into every .pyz payload's __bundleup__/ (ADR-0027): the code that activates the payload,
# shared by the loader and child processes, and the children's sitecustomize.py.
RUNTIME = {
    "_bundleup_runtime.py": Path(__file__).with_name("_runtime.py"),
    "sitecustomize.py": Path(__file__).with_name("_sitecustomize.py"),
}
# uv's lock file. Console-script launchers are removed too (see `launchers`).
SKIP_TOP = {".lock"}


MIN_UV = (0, 9)  # oldest uv whose CLI we rely on (export --no-editable, python find --script)


@functools.lru_cache(maxsize=4)
def _uv_version_ok(path: str) -> bool:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10).stdout
        return tuple(int(x) for x in out.split()[1].split(".")[:2]) >= MIN_UV
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return False


def find_uv() -> str:
    """The user's own uv if it's recent enough (it wrote their uv.lock), else the bundled one."""
    on_path = shutil.which("uv")
    if on_path and _uv_version_ok(on_path):
        return on_path
    try:
        from uv import find_uv_bin

        return find_uv_bin()
    except (ImportError, FileNotFoundError):
        pass
    if on_path:
        return on_path  # too old or unrecognised, but better than nothing: uv's errors will say why
    raise UvNotFoundError(
        "bundleup needs uv to resolve and install dependencies, and couldn't find it",
        hint="reinstall bundleup, or install uv: "
        "https://docs.astral.sh/uv/getting-started/installation/",
    )


def _clean_external(external: Sequence[str]) -> set[str]:
    return {
        canonicalize_name(head)
        for pkg in external
        if (head := re.split(r"[<>=!~;\[\s]", pkg, maxsplit=1)[0].strip())
    }


def _strip_external(text: str, external: Sequence[str]) -> str:
    """Remove `[[packages]]` entries whose canonical name is in `external` from a pylock.toml."""
    excluded = _clean_external(external)
    if not excluded or "[[packages]]" not in text:
        return text
    parts = re.split(r"(?m)(?=^\[\[packages\]\]\s*$)", text)
    head, kept = parts[0], []
    for block in parts[1:]:
        try:
            parsed = tomllib.loads(block).get("packages", [])
            name = canonicalize_name(str(parsed[0].get("name", ""))) if parsed else ""
        except tomllib.TOMLDecodeError:
            name = ""
        if name not in excluded:
            kept.append(block)
    if not kept:
        head = (
            re.sub(r"(?m)^packages\s*=\s*\[\s*\](?:\s*#.*)?$", "", head).rstrip()
            + "\npackages = []\n"
        )
        return head
    return head + "".join(kept)


def _load_pylock_packages(text: str, path: Path) -> list[dict[str, Any]]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{path} isn't valid TOML: {e}") from None
    req_py = data.get("requires-python")
    if req_py is not None and not isinstance(req_py, str):
        raise ProjectError(
            f"{path} has a non-string requires-python: {req_py!r}",
            hint='write a version specifier string, e.g. `requires-python = ">=3.12"`',
        )
    packages = data.get("packages", [])
    if not isinstance(packages, list) or not all(isinstance(p, dict) for p in packages):
        raise ProjectError(
            f"{path} isn't a valid PEP 751 lockfile: `packages` must be a list of tables",
            hint="re-export or regenerate pylock.toml (e.g. `uv export --format pylock.toml`)",
        )
    for p in packages:
        directory = p.get("directory")
        if directory is not None and not isinstance(directory, dict):
            raise ProjectError(
                f"{path} isn't a valid PEP 751 lockfile: package `directory` must be a table"
            )
    return packages


def _check_pylock_freshness(
    source: Source,
    packages: list[dict[str, Any]],
    *,
    external: Sequence[str] = (),
    markers: dict[str, str] | None = None,
) -> None:
    pyproject = source.path / "pyproject.toml"
    if not pyproject.is_file():
        return
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return
    project = data.get("project")
    deps = project.get("dependencies") if isinstance(project, dict) else None
    if not isinstance(deps, list):
        return
    from packaging.markers import (
        InvalidMarker,
        Marker,
        UndefinedEnvironmentName,
        default_environment,
    )
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.specifiers import InvalidSpecifier
    from packaging.version import InvalidVersion

    def _matches_spec(req: Requirement, ver: str) -> bool:
        try:
            return req.specifier.contains(ver, prereleases=True)
        except (InvalidSpecifier, InvalidVersion):
            return True

    env: dict[str, Any] = {
        **(markers or {k: str(v) for k, v in default_environment().items()}),
        "extra": "",
        "extras": set(),
        "dependency_groups": set(),
    }
    excluded = _clean_external(external)
    locked: dict[str, list[str | None]] = {}
    for p in packages:
        name = p.get("name")
        if not name:
            continue
        raw_marker = p.get("marker")
        if isinstance(raw_marker, str):
            try:
                if not Marker(raw_marker).evaluate(env):
                    continue
            except (InvalidMarker, UndefinedEnvironmentName):
                pass
        ver = p.get("version")
        locked.setdefault(canonicalize_name(str(name)), []).append(
            ver if isinstance(ver, str) else None
        )
    for raw in deps:
        if not isinstance(raw, str):
            continue
        try:
            req = Requirement(raw)
        except InvalidRequirement:
            continue
        canon = canonicalize_name(req.name)
        if canon in excluded:
            continue
        if req.marker is not None:
            try:
                if not req.marker.evaluate(env):
                    continue
            except UndefinedEnvironmentName:
                continue
        if canon not in locked:
            raise LockfileOutdatedError(
                "pylock.toml is out of date with pyproject.toml",
                hint="regenerate pylock.toml, then build again (or --frozen bundles the lock "
                "as it is)",
                detail=f"pyproject.toml requires {req}, which is missing from pylock.toml",
            )
        versions = [v for v in locked[canon] if isinstance(v, str)]
        if versions and req.specifier and not any(_matches_spec(req, v) for v in versions):
            raise LockfileOutdatedError(
                "pylock.toml is out of date with pyproject.toml",
                hint="regenerate pylock.toml, then build again (or --frozen bundles the lock "
                "as it is)",
                detail=f"pyproject.toml requires {req}, but pylock.toml has {versions[-1]}",
            )


_NETWORK_ERROR_PATTERNS = (
    "failed to fetch",
    "failed to download",
    "client error (connect)",
    "error sending request",
    "dns error",
    "failed to lookup address information",
    "nodename nor servname provided",
    "name or service not known",
    "network is unreachable",
    "network down",
    "no route to host",
    "connection refused",
    "temporary failure in name resolution",
    "operation timed out",
    "connection timed out",
)


def _is_network_error(detail: str | None) -> bool:
    if not detail:
        return False
    low = detail.lower()
    return any(p in low for p in _NETWORK_ERROR_PATTERNS)


def _run_with_offline_fallback(cmd: list[str], *, cwd: Path, what: str, progress: Progress) -> str:
    try:
        return run(cmd, cwd=cwd, what=what, progress=progress)
    except UvError as first_err:
        if "--offline" in cmd or not _is_network_error(first_err.detail):
            raise
        offline_cmd = [cmd[0], *cmd[1:2], "--offline", *cmd[2:]]
        if cmd[1:3] in (["pip", "compile"], ["pip", "install"]):
            offline_cmd = [cmd[0], "pip", cmd[2], "--offline", *cmd[3:]]
        try:
            return run(offline_cmd, cwd=cwd, what=what, progress=progress)
        except UvError:
            raise first_err from None


def from_pylock(
    source: Source,
    stage: Path,
    *,
    external: Sequence[str] = (),
    lock_mode: str | None = None,
    markers: dict[str, str] | None = None,
) -> tuple[list[list[str]], Path]:
    """Install arguments for a project's own pylock.toml, and the lock the check compares the
    bundle with. uv installs the file in place (its relative paths are relative to it). A lock
    from another tool may not list the project itself; then the project is installed alongside
    and added to the copy the check reads."""
    assert source.pylock is not None
    try:
        text = source.pylock.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ProjectError(f"{source.pylock} isn't valid TOML: {e}") from None
    packages = _load_pylock_packages(text, source.pylock)
    if lock_mode != "frozen":
        _check_pylock_freshness(source, packages, external=external, markers=markers)
    me = canonicalize_name(source.name)
    mine = [p for p in packages if canonicalize_name(str(p.get("name", ""))) == me]
    editable = next(
        (
            str(p.get("name") or source.name)
            for p in packages
            if isinstance(p.get("directory"), dict) and p.get("directory", {}).get("editable")
        ),
        None,
    )
    if editable is not None:
        raise ProjectError(
            f"{source.pylock.name} installs {editable} as editable, which would point the "
            "bundle back at this directory",
            hint="export the lock without editable installs (uv: --no-editable)",
        )
    check = stage.resolve() / "pylock.toml"
    if external:
        text = _strip_external(text, external)
        packages = _load_pylock_packages(text, source.pylock)
        lock_for_install = stage.resolve() / "pylock.install.toml"
        lock_for_install.write_text(text, encoding="utf-8")
        relocate_paths(lock_for_install, source.pylock.parent, from_root=True)
        text = lock_for_install.read_text(encoding="utf-8")
    else:
        lock_for_install = source.pylock
    installs = [["-r", str(lock_for_install)]] if packages else []  # uv rejects an empty lock
    if not mine and source.packaged:
        installs.append([str(source.path)])
        text = with_project(text, source.name)
    check.write_text(text, encoding="utf-8")
    extra = _refresh_local(check)
    return [[*args, *extra] for args in installs], check


def _refresh_local(pylock: Path) -> list[str]:
    """`--refresh-package` for every directory package in `pylock`: uv keys cached builds of local
    folders on pyproject.toml alone, so without this an edit to `src/` re-bundles the old wheel."""
    packages = _load_pylock_packages(pylock.read_text(encoding="utf-8"), pylock)
    return [
        arg
        for p in packages
        if "directory" in p and p.get("name")
        for arg in ("--refresh-package", str(p["name"]))
    ]


def with_project(pylock: str, name: str) -> str:
    """The pylock.toml text with the project itself listed, for the lock-vs-bundle check. (An
    empty `packages = []` would make the added [[packages]] table invalid TOML.)"""
    pylock = re.sub(r"(?m)^packages\s*=\s*\[\s*\](?:\s*#.*)?$", "", pylock)
    return pylock + f'\n[[packages]]\nname = {json.dumps(name)}\ndirectory = {{ path = "." }}\n'


def has_lock(source: Source) -> bool:
    """A uv lock to check: the project's (or its workspace's) uv.lock, or `<script>.lock`."""
    if source.is_script:
        return source.path.with_name(source.path.name + ".lock").is_file()
    return find_uv_lock(source.path) is not None


def export_cache_dir() -> Path:
    """Where locked `uv export` outputs (pre-relocation) are cached between builds (ADR-0051)."""
    return _bytecode.cache_dir().parent / "exports"


def _export_cache_key(
    uv: str, source: Source, selection: list[str], mode: str | None
) -> str | None:
    """Cache key for `uv export` when a single-project or script lockfile is present."""
    if mode not in ("locked", "frozen"):
        return None
    try:
        if source.is_script:
            lock_path = source.path.with_name(source.path.name + ".lock")
            if not lock_path.is_file():
                return None
            manifest_bytes = source.path.read_bytes()
            lock_bytes = lock_path.read_bytes()
        else:
            lock = find_uv_lock(source.path)
            pyproject = source.path / "pyproject.toml"
            if (
                lock is None
                or lock.parent != source.path
                or not pyproject.is_file()
                or (source.path / "setup.py").is_file()
                or (source.path / "setup.cfg").is_file()
            ):
                return None
            manifest_bytes = pyproject.read_bytes()
            if b"workspace" in manifest_bytes or b"dynamic" in manifest_bytes:
                return None
            lock_bytes = lock.read_bytes()
        if re.search(rb'source\s*=\s*\{\s*(?:directory|editable|path)\s*=\s*"(?!\.")', lock_bytes):
            return None
        uv_mtime = str(os.stat(uv).st_mtime_ns) if os.path.exists(uv) else uv
    except OSError:
        return None
    digest = hashlib.sha256()
    for part in (uv, uv_mtime, str(source.workdir), *selection):
        digest.update(part.encode("utf-8", "replace") + b"\0")
    digest.update(manifest_bytes + b"\0" + lock_bytes)
    return digest.hexdigest()[:32]


def _strip_script_external(script_path: Path, excluded: set[str], stage: Path) -> Path:
    """When an unlocked PEP 723 script declares an `--external` package in `dependencies`, write a
    staged script with that package removed so `uv export --script` doesn't try to resolve it."""
    if not excluded:
        return script_path
    from ._source import PEP723, read_python_text, script_metadata

    text = read_python_text(script_path)
    meta = script_metadata(text)
    deps = meta.get("dependencies")
    tool = meta.get("tool")
    uv_tool = tool.get("uv") if isinstance(tool, dict) else None
    if not isinstance(deps, list) or "path" in str(uv_tool or ""):
        return script_path
    kept: list[str] = []
    removed = False
    for item in deps:
        if not isinstance(item, str):
            return script_path
        head = re.split(r"[<>=!~;\[\s]", item, maxsplit=1)[0].strip()
        if head and canonicalize_name(head) in excluded:
            removed = True
        else:
            kept.append(item)
    if not removed:
        return script_path
    match = next((m for m in PEP723.finditer(text) if m.group("type") == "script"), None)
    if match is None:
        return script_path
    toml_body = re.sub(r"(?m)^#( ?)", "", match.group("content"))
    new_deps = f"dependencies = [{', '.join(json.dumps(x) for x in kept)}]"
    patched_toml, count = re.subn(
        r'(?ms)^dependencies\s*=\s*\[(?:[^\]"\'#]|"(?:\\.|[^"\\])*"|\'[^\']*\'|#[^\n]*)*\]',
        lambda _: new_deps,
        toml_body,
        count=1,
    )
    if count != 1:
        return script_path
    try:
        tomllib.loads(patched_toml)
    except tomllib.TOMLDecodeError:
        return script_path
    commented = "".join(f"# {line}\n" if line else "#\n" for line in patched_toml.splitlines())
    staged = stage.resolve() / script_path.name
    staged.write_text(
        text[: match.start("content")] + commented + text[match.end("content") :],
        encoding="utf-8",
    )
    return staged


@dataclass(frozen=True)
class Exported:
    """What to install (`uv pip install` argument lists, one call each) and the pylock.toml the
    lock-vs-bundle check reads. `pinned`: the input fixes every version (a lock, or a fully
    pinned requirements.txt); otherwise they were resolved just now (ADR-0041)."""

    installs: list[list[str]]
    pylock: Path
    pinned: bool = True


def export(
    uv: str,
    source: Source,
    *,
    lock_mode: str | None,
    python: tuple[int, int],
    stage: Path,
    progress: Progress,
    external: Sequence[str] = (),
    markers: dict[str, str] | None = None,
) -> Exported:
    """What to install, as `uv pip install` arguments, and the pylock.toml (PEP 751) the
    lock-vs-bundle check reads. From uv.lock: exported as a pylock.toml, which names each
    package's index and files with their hashes, and installed from that, so a bundle gets
    exactly the locked files from wherever they were locked (a company index too), never a
    same-named package from PyPI. From a project's own pylock.toml: that file (ADR-0026)."""
    if source.pylock:
        return Exported(
            *from_pylock(source, stage, external=external, lock_mode=lock_mode, markers=markers)
        )
    if not (source.is_script and source.pep723) and not source.locked:
        # Only a requirements.txt (or an input with no dependencies) can turn out to pin
        # everything; an unlocked project can't, so --locked / --frozen refuses it before resolving.
        can_pin = source.declared is None or (
            source.declared.suffix == ".txt"
            and (
                lock_mode not in ("locked", "frozen")
                or pinned_requirements(source.declared, external=external)[0] is not None
            )
        )
        exported = None
        if can_pin or lock_mode not in ("locked", "frozen"):
            exported = resolve(
                uv, source, python=python, stage=stage, progress=progress, external=external
            )
        if exported is None or (lock_mode in ("locked", "frozen") and not exported.pinned):
            flag = f"--{lock_mode}"
            raise NoLockfileError(
                f"{source.path.name} has no lockfile, and {flag} asks for one",
                hint="lock it (`uv lock`, `pip lock .`, or pin every package in requirements.txt"
                f"), or build without {flag} to resolve the versions now",
            )
        return exported
    # The real path: uv writes local paths relative to the file as spelled, but reads them from
    # its real location, and macOS's temporary folder is behind a symlink (/var -> /private/var).
    pylock = stage.resolve() / "pylock.toml"
    locked_file = has_lock(source)
    excluded = _clean_external(external)
    script_arg = (
        _strip_script_external(source.path, excluded, stage)
        if source.is_script and not locked_file
        else source.path
    )
    selection = ["--script", str(script_arg)] if source.is_script else ["--no-dev", "--no-editable"]
    for clean in sorted(excluded):
        selection.extend(["--prune", clean])
    # A lock is checked against pyproject.toml / the script by default: uv would otherwise
    # re-lock a stale one, rewriting uv.lock and bundling versions nobody reviewed (ADR-0033).
    # --frozen uses it as is. A script without a lock has nothing to check (uv refuses --locked).
    mode = (lock_mode or "locked") if locked_file else (lock_mode if not source.is_script else None)
    if mode:
        selection.append(f"--{mode}")
    lock = None if source.is_script else find_uv_lock(source.path)
    root = lock.parent if lock else source.workdir
    cache_key = _export_cache_key(uv, source, selection, mode) if locked_file else None
    cached = export_cache_dir() / f"{cache_key}.toml" if cache_key else None
    restored_export = False
    if cached is not None and cached.is_file():
        with contextlib.suppress(OSError):
            shutil.copyfile(cached, pylock)
            restored_export = True
    if not restored_export:
        command = [
            uv,
            "export",
            "--quiet",
            *selection,
            "--format",
            "pylock.toml",
            "-o",
            str(pylock),
        ]
        try:
            _run_with_offline_fallback(
                command, cwd=source.workdir, what="uv export", progress=progress
            )
        except UvError as e:
            detail_low = (e.detail or "").lower()
            if mode == "locked" and (
                "needs to be updated" in detail_low
                or "out of date" in detail_low
                or ("lockfile" in detail_low and "--locked" in detail_low)
            ):
                what = f"{source.path.name}.lock" if source.is_script else "uv.lock"
                fix = f"uv lock --script {source.path.name}" if source.is_script else "uv lock"
                against = "the script" if source.is_script else "pyproject.toml"
                raise LockfileOutdatedError(
                    f"{what} is out of date with {against}",
                    hint=f"run `{fix}`, then build again (or --frozen bundles the lock as it is)",
                    detail=e.detail,
                ) from None
            raise
        relocate_paths(pylock, root, to_root=True)
        if cached is not None:
            tmp = cached.with_name(f".{cached.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pylock, tmp)
                tmp.replace(cached)
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    tmp.unlink(missing_ok=True)
    relocate_paths(pylock, root, from_root=True)
    if external:
        pylock.write_text(
            _strip_external(pylock.read_text(encoding="utf-8"), external), encoding="utf-8"
        )
    pinned = mode is not None or (
        source.is_script and _script_pinned(source, pylock, external=external)
    )
    if lock_mode in ("locked", "frozen") and not pinned:
        flag = f"--{lock_mode}"
        raise NoLockfileError(
            f"{source.path.name} has no lockfile, and {flag} asks for one",
            hint=f"run `uv lock --script {source.path.name}`, pin every package in "
            f"`dependencies` with ==, or build without {flag}",
        )
    text = pylock.read_text(encoding="utf-8")
    packages = _load_pylock_packages(text, pylock)
    lock_for_install = pylock
    add_self = (
        not source.is_script
        and source.packaged
        and not any(
            canonicalize_name(str(p.get("name", ""))) == canonicalize_name(source.name)
            for p in packages
        )
    )
    if add_self and packages:
        lock_for_install = stage.resolve() / "pylock.install.toml"
        shutil.copyfile(pylock, lock_for_install)
    installs = (
        [["-r", str(lock_for_install), *_refresh_local(lock_for_install)]] if packages else []
    )
    if add_self:
        installs.append([str(source.path), "--refresh-package", canonicalize_name(source.name)])
        pylock.write_text(with_project(text, source.name), encoding="utf-8")
    return Exported(installs, pylock, pinned=pinned)


EMPTY_PYLOCK = 'lock-version = "1.0"\ncreated-by = "bundleup"\npackages = []\n'


def _strip_pyproject_external(declared: Path, excluded: set[str], stage: Path) -> Path | None:
    """If `declared` is an unlocked `pyproject.toml` and lists packages in `excluded`, write a
    staged `requirements.in` without them so `uv pip compile` doesn't resolve their transitive
    dependencies."""
    from packaging.requirements import InvalidRequirement, Requirement

    try:
        data = tomllib.loads(declared.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return declared
    project = data.get("project")
    tool = data.get("tool")
    uv_cfg = tool.get("uv") if isinstance(tool, dict) else None
    uv_custom_resolution = isinstance(uv_cfg, dict) and bool(
        set(uv_cfg)
        & {
            "sources",
            "index",
            "index-url",
            "extra-index-url",
            "find-links",
            "constraint-dependencies",
            "override-dependencies",
            "build-constraint-dependencies",
        }
    )
    if (
        not isinstance(project, dict)
        or "dynamic" in project
        or (isinstance(tool, dict) and (uv_custom_resolution or "poetry" in tool))
    ):
        return declared
    deps = project.get("dependencies", [])
    if not isinstance(deps, list):
        return declared
    kept: list[str] = []
    removed = False
    for raw in deps:
        if not isinstance(raw, str):
            return declared
        try:
            req = Requirement(raw)
        except InvalidRequirement:
            return declared
        if req.url is not None:
            return declared
        if canonicalize_name(req.name) in excluded:
            removed = True
        else:
            kept.append(raw)
    if not removed:
        return declared
    if not kept:
        return None
    staged = stage.resolve() / "requirements.in"
    staged.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return staged


def _requirement_lines(text: str) -> list[str]:
    """Join backslash-continued requirement lines without continuing comment lines."""
    lines: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        if not buf and raw.lstrip().startswith("#"):
            continue
        clean = re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
        if clean.endswith("\\"):
            buf.append(clean[:-1].rstrip() + " ")
        else:
            joined = ("".join(buf) + clean).strip()
            buf.clear()
            if joined and not joined.startswith("#"):
                lines.append(joined)
    if buf:
        joined = "".join(buf).strip()
        if joined and not joined.startswith("#"):
            lines.append(joined)
    return lines


def _strip_requirements_external(declared: Path, excluded: set[str], stage: Path) -> Path | None:
    """If `declared` is a `requirements.txt` or `pyproject.toml` and lists packages in `excluded`,
    write a staged copy without them so `uv pip compile` doesn't resolve them or their transitive
    dependencies. Returns None when every requirement in `declared` is external."""
    if not excluded:
        return declared
    if declared.name == "pyproject.toml":
        return _strip_pyproject_external(declared, excluded, stage)
    if not declared.name.endswith(".txt"):
        return declared
    from packaging.requirements import InvalidRequirement, Requirement

    text = declared.read_text(encoding="utf-8-sig")
    kept: list[str] = []
    kept_reqs = 0
    removed = False
    for line in _requirement_lines(text):
        if line.startswith("-"):
            opt = line.split()[0].split("=")[0]
            if opt in INCLUDES:
                return declared
            if opt != "--require-hashes":
                kept.append(line)
            continue
        spec = re.split(r"\s+--", line, maxsplit=1)[0]
        try:
            req = Requirement(spec.strip())
        except InvalidRequirement:
            return declared
        if canonicalize_name(req.name) in excluded:
            removed = True
        else:
            kept.append(spec.strip())
            kept_reqs += 1
    if not removed:
        return declared
    if kept_reqs == 0:
        return None
    staged = stage.resolve() / "requirements.in"
    staged.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return staged


def resolve(
    uv: str,
    source: Source,
    *,
    python: tuple[int, int],
    stage: Path,
    progress: Progress,
    external: Sequence[str] = (),
) -> Exported:
    """Without a lock (ADR-0041): resolve what `source.declared` lists (a requirements.txt, or a
    project's pyproject.toml, setup.py or setup.cfg) for every platform at once, as uv.lock
    would, into the stage. Nothing is written into the project. A project is installed from its
    folder alongside; a requirements.txt with a hash on every line is installed from itself, so
    uv checks those hashes."""
    resolved = stage.resolve() / "resolved" / "pylock.toml"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    check = stage.resolve() / "pylock.toml"
    declared = source.declared
    if declared is None:  # a script or folder app that needs only the standard library
        check.write_text(EMPTY_PYLOCK, encoding="utf-8")
        return Exported([], check)
    excluded = _clean_external(external)
    compile_input = _strip_requirements_external(declared, excluded, stage)
    if compile_input is None:
        resolved.write_text(EMPTY_PYLOCK, encoding="utf-8")
    else:
        oldest = _oldest_python(source.requires_python, python)
        with untouched(source):  # reading a setup.py/setup.cfg project's metadata builds it
            actual_input = (
                declared.parent / "setup.py"
                if compile_input == declared
                and declared.name == "setup.cfg"
                and (declared.parent / "setup.py").is_file()
                else compile_input
            )
            cmd = [uv, "pip", "compile", "--quiet", "--universal", "--format", "pylock.toml"]
            cmd += ["--python-version", oldest, "-o", str(resolved), str(actual_input)]
            _run_with_offline_fallback(
                cmd, cwd=declared.parent, what="uv pip compile", progress=progress
            )
        relocate_paths(resolved, declared.parent)
    text = _strip_external(resolved.read_text(encoding="utf-8"), external)
    text = re.sub(
        r"(?m)^(\s*directory\s*=\s*\{[^\n}]*?),\s*editable\s*=\s*true(\s*\})",
        r"\1\2",
        text,
    )
    resolved.write_text(text, encoding="utf-8")
    installs: list[list[str]] = [["-r", str(resolved)]] if "[[packages]]" in text else []
    pinned = False
    if declared.name.endswith(".txt"):
        pins, hashed = pinned_requirements(declared, external=external)
        compiled = {
            canonicalize_name(str(p["name"])) for p in tomllib.loads(text).get("packages", [])
        }
        pinned = pins is not None and compiled <= set(pins)
        if pinned and hashed and not external:
            # Every line pinned and hashed, nothing missing: install from the file itself,
            # which makes uv check the hashes it lists.
            installs = [["-r", str(declared)]]
    elif (
        source.packaged
    ):  # the project itself, built from its folder like `pip install .`, and in the check
        installs.append([str(source.path)])
        text = with_project(text, source.name)
    check.write_text(text, encoding="utf-8")
    extra = _refresh_local(check)
    return Exported([[*args, *extra] for args in installs], check, pinned=pinned)


def _oldest_python(requires: str | None, python: tuple[int, int]) -> str:
    """The lowest Python the resolution covers: the project's requires-python (from 3.9, the
    oldest Python bundles target), or the target's."""
    if requires:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet

        try:
            spec = SpecifierSet(requires)
        except InvalidSpecifier:
            spec = None
        for minor in range(min(9, python[1]), python[1] + 1):
            if spec is not None and any(
                spec.contains(f"3.{minor}.{p}", prereleases=True) for p in (0, 99)
            ):
                return f"3.{minor}"
    return f"{python[0]}.{python[1]}"


# Options that bring in other requirements, so the file alone doesn't fix every version.
INCLUDES = ("-r", "-c", "-e", "--requirement", "--constraint", "--editable")


def pinned_requirements(
    path: Path, *, external: Sequence[str] = ()
) -> tuple[dict[str, str] | None, bool]:
    """The versions a requirements.txt pins (name -> version) if every requirement is pinned to
    one exact version (`name==1.2`) and none comes from elsewhere (-r, -c, -e, URLs, paths);
    else None. And whether every requirement carries a --hash."""
    from packaging.requirements import InvalidRequirement, Requirement

    excluded = _clean_external(external)
    pins: dict[str, str] = {}
    hashed = True
    had_external = False
    text = path.read_text(encoding="utf-8-sig")
    for line in _requirement_lines(text):
        if line.startswith("-"):
            if line.split()[0].split("=")[0] in INCLUDES:
                return None, False
            continue  # --index-url and friends: where from, not which version
        parts = re.split(r"\s+--", line, maxsplit=1)
        spec = parts[0]
        options = parts[1] if len(parts) > 1 else ""
        try:
            req = Requirement(spec.strip())
        except InvalidRequirement:
            return None, False  # a path or URL
        canon = canonicalize_name(req.name)
        if canon in excluded:
            had_external = True
            continue
        hashed = hashed and "hash" in options
        exact = [s for s in req.specifier if s.operator in ("==", "===") and "*" not in s.version]
        if req.url or len(exact) != 1 or len(req.specifier) != 1:
            return None, False
        pins[canon] = exact[0].version
    return pins, hashed and (bool(pins) and not had_external)


def _script_pinned(source: Source, pylock: Path, *, external: Sequence[str] = ()) -> bool:
    """Whether a PEP 723 script's `dependencies` list pins every package in `pylock` with ==."""
    from packaging.requirements import InvalidRequirement, Requirement

    from ._source import read_python_text, script_metadata

    deps = script_metadata(read_python_text(source.path)).get("dependencies")
    if deps is None or deps == []:
        return True
    if not isinstance(deps, list):
        return False
    excluded = _clean_external(external)
    pins: set[str] = set()
    for item in deps:
        if not isinstance(item, str):
            return False
        try:
            req = Requirement(item)
        except InvalidRequirement:
            return False
        canon = canonicalize_name(req.name)
        if canon in excluded:
            continue
        exact = [s for s in req.specifier if s.operator in ("==", "===") and "*" not in s.version]
        if req.url or len(exact) != 1 or len(req.specifier) != 1:
            return False
        pins.add(canon)
    compiled = {
        canonicalize_name(str(p["name"]))
        for p in tomllib.loads(pylock.read_text(encoding="utf-8")).get("packages", [])
    }
    return compiled <= pins


# A local path in uv's pylock.toml export: `directory = { path = "." }`, `path = "dist/x.whl"`.
LOCAL_PATH = re.compile(
    r"(?P<key>\bpath\s*=\s*)(?P<raw>"
    r'"""(?:[^\\]|\\.)*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\]|\\.)*"|\'[^\']*\''
    r")"
)


def relocate_paths(
    pylock: Path, root: Path, *, to_root: bool = False, from_root: bool = False
) -> None:
    """Make the export's local paths relative to the pylock.toml (or to `root` when caching), as
    PEP 751 says and uv reads them. uv 0.12.23 writes them so; older ones write them relative to
    the lock's directory (the workspace root), which is wrong once the file is in the stage."""
    here = os.path.abspath(pylock.parent)
    base = os.path.abspath(root) if to_root else here

    def relocated(m: re.Match[str]) -> str:
        try:
            value = str(tomllib.loads("v = " + m["raw"])["v"])  # the TOML string, unescaped
        except ValueError:
            return m[0]
        if not value or Path(value).is_absolute():
            return m[0]
        if to_root:
            if _is_local(Path(here, value)):
                target = os.path.abspath(Path(here, value))
            elif _is_local(root / value):
                target = os.path.abspath(root / value)
            else:
                return m[0]
        elif from_root:
            if not _is_local(root / value):
                return m[0]
            target = os.path.abspath(root / value)
        else:
            if _is_local(Path(here, value)) or not _is_local(root / value):
                return m[0]
            target = os.path.abspath(root / value)
        try:
            value = os.path.relpath(target, base)
        except ValueError:  # another drive on Windows: absolute is all there is
            value = target
        return m["key"] + json.dumps(Path(value).as_posix())

    text = pylock.read_text(encoding="utf-8")
    pylock.write_text(LOCAL_PATH.sub(relocated, text), encoding="utf-8")


def _is_local(path: Path) -> bool:
    """A project directory or a file uv can install from a pylock path."""
    return (
        path.is_file()
        or (path / "pyproject.toml").is_file()
        or (path / "setup.py").is_file()
        or (path / "setup.cfg").is_file()
    )


def add_runtime(site: Path) -> None:
    """The payload's own runtime files, under __bundleup__/ (see RUNTIME)."""
    dest = site / _verify.RUNTIME_DIR
    if dest.exists():
        raise ProjectError(f"a dependency installs a top-level {_verify.RUNTIME_DIR}/ directory")
    dest.mkdir()
    for name, source in RUNTIME.items():
        shutil.copyfile(source, dest / name)


def install(
    uv: str,
    source: Source,
    *,
    target: Target,
    reqs: list[list[str]],
    site: Path,
    script: str | None,
    progress: Progress,
) -> list[str]:
    """Install the exported set into `site`, the directory that becomes the payload. `reqs` is
    one `uv pip install` argument list per call (uv takes a pylock.toml only on its own). Returns
    the files copied in that no package installed: a folder app's (ADR-0041)."""
    # The export is the complete, pinned set, so --no-deps installs exactly the lock. Relative
    # paths in it (the project itself, workspace members) resolve against the working directory.
    platform = ["--python-platform", target.python_platform.name] if target.python_platform else []
    common = ["--quiet", "--no-deps", "--target", str(site), "--python", target.executable]
    site.mkdir(parents=True, exist_ok=True)  # also when there's nothing to install
    try:
        with untouched(source):
            for args in reqs:
                _run_with_offline_fallback(
                    [uv, "pip", "install", *common, *platform, *args],
                    cwd=source.workdir,
                    what="uv pip install",
                    progress=progress,
                )
    except UvError as e:
        if target.python_platform and "is not compatible with the target" in (e.detail or ""):
            raise NoCompatibleWheelError(
                f"a package has no wheel for {target.python_platform.name}",
                detail=e.detail,
                hint="uv could only build it from source, which works for this machine only; "
                "`bundleup check --python-platform ...` lists which platforms the locked wheels "
                "support",
            ) from None
        raise
    _ensure_site_writable(site)
    for name in SKIP_TOP:
        p = site / name
        if p.is_dir() and not p.is_symlink():
            _loader._rmtree(str(p))
        elif p.exists() or p.is_symlink():
            p.unlink(missing_ok=True)
    for launcher in launchers(site):
        (site / launcher).unlink(missing_ok=True)
    for folder in _verify.SCRIPT_DIRS:
        with contextlib.suppress(OSError):  # missing, or holds files a wheel ships: keep it
            (site / folder).rmdir()
    if script:
        dst = site / script
        if dst.exists():
            raise ProjectError(
                f"{script} would replace a file one of the dependencies installs",
                hint="rename the script",
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.path, dst)
        with contextlib.suppress(OSError):
            dst.chmod(dst.stat().st_mode | 0o200)
    copied = []
    if source.app:  # its modules and files at the top, where a project's packages would be
        for rel, file in app_files(source):
            dst = site / rel
            if dst.exists():
                raise ProjectError(
                    f"{rel} would replace a file one of the dependencies installs",
                    hint="rename it",
                )
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dst)
            with contextlib.suppress(OSError):
                dst.chmod(dst.stat().st_mode | 0o200)
            copied.append(rel)
    _strip_local_build_meta(site)
    return copied


def _strip_local_build_meta(site: Path) -> None:
    """Remove local build timestamps (`uv_cache.json`) and local filesystem paths
    (`direct_url.json` with `file://`) from `.dist-info` directories and their `RECORD`s so
    identical sources produce bit-for-bit identical bundles regardless of build directory or
    file timestamps."""
    import csv
    import io

    for dist_info in sorted(site.glob("*.dist-info")):
        removed: set[str] = set()
        uv_cache = dist_info / "uv_cache.json"
        if uv_cache.is_file():
            uv_cache.unlink()
            removed.add(f"{dist_info.name}/uv_cache.json")
        direct_url = dist_info / "direct_url.json"
        if direct_url.is_file():
            try:
                info = json.loads(direct_url.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            if isinstance(info, dict) and str(info.get("url", "")).startswith("file:"):
                direct_url.unlink()
                removed.add(f"{dist_info.name}/direct_url.json")
        record = dist_info / "RECORD"
        if removed and record.is_file():
            rows = [
                row
                for row in csv.reader(io.StringIO(record.read_text(encoding="utf-8")))
                if row and row[0].replace("\\", "/") not in removed
            ]
            buf = io.StringIO()
            csv.writer(buf, lineterminator="\n").writerows(rows)
            record.write_text(buf.getvalue(), encoding="utf-8")


def _ensure_site_writable(site: Path) -> None:
    """Ensure directories and files inside `site` are writable by the owner so bytecode
    compilation, cached bytecode restoration, and staging cleanup never fail on 0o444/0o555
    wheel entries."""
    for dirpath, dirnames, filenames in os.walk(site):
        with contextlib.suppress(OSError):
            st = os.lstat(dirpath)
            if (st.st_mode & 0o700) != 0o700:
                os.chmod(dirpath, st.st_mode | 0o700)
        for d in dirnames:
            p = os.path.join(dirpath, d)
            with contextlib.suppress(OSError):
                if not os.path.islink(p):
                    st = os.lstat(p)
                    if (st.st_mode & 0o700) != 0o700:
                        os.chmod(p, st.st_mode | 0o700)
        for f in filenames:
            p = os.path.join(dirpath, f)
            with contextlib.suppress(OSError):
                if not os.path.islink(p):
                    st = os.lstat(p)
                    if not (st.st_mode & 0o200):
                        os.chmod(p, st.st_mode | 0o200)


@contextlib.contextmanager
def untouched(source: Source) -> Iterator[None]:
    """Remove what building the project writes into it (setuptools' build/ and *.egg-info), and
    only what wasn't there before: bundleup never changes a project (ADR-0028)."""
    before = set() if source.is_script else _build_leftovers(source.path)
    shim = (
        source.path / "setup.py"
        if not source.is_script
        and (source.path / "setup.cfg").is_file()
        and not (source.path / "setup.py").exists()
        and not (source.path / "pyproject.toml").exists()
        else None
    )
    if shim is not None:
        with contextlib.suppress(OSError):
            shim.write_text("from setuptools import setup\nsetup()\n", encoding="utf-8")
    try:
        yield
    finally:
        if shim is not None:
            with contextlib.suppress(OSError):
                shim.unlink(missing_ok=True)
        if not source.is_script:
            for leftover in _build_leftovers(source.path) - before:
                _loader._rmtree(str(leftover))


def _build_leftovers(project: Path) -> set[Path]:
    """What setuptools writes into a project it builds: build/, and *.egg-info at the top or in
    src/. bundleup never changes a project (ADR-0028), so new ones are removed afterwards."""
    found = {p for p in (project / "build",) if p.is_dir()}
    for folder in (project, project / "src"):
        if folder.is_dir():
            found |= {p for p in folder.glob("*.egg-info") if p.is_dir()}
    return found


def scripts_of(dist_info: Path) -> dict[str, str]:
    """A distribution's console and GUI scripts (dynamic ones too): command name -> target."""
    ep = dist_info / "entry_points.txt"
    if not ep.exists():
        return {}
    scripts: dict[str, str] = {}
    section = None
    for line in ep.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line.strip("[]").strip()
        elif "=" in line and section in ("console_scripts", "gui_scripts"):
            key, value = line.split("=", 1)
            scripts[key.strip()] = value.strip()
    return scripts


def console_scripts(site: Path, name: str) -> dict[str, str]:
    """Console and GUI scripts from the project's installed metadata."""
    want = canonicalize_name(name)
    for dist in _verify.installed_distributions(site):
        if dist.name == want:
            return scripts_of(site / dist.dist_info)
    for dist_info in site.glob("*.dist-info"):
        dist_name = dist_info.name.removesuffix(".dist-info").rsplit("-", 1)[0]
        if canonicalize_name(dist_name) == want:
            return scripts_of(dist_info)
    return {}


def launchers(site: Path) -> set[str]:
    """The console-script launchers the installer generated in `bin/` (`Scripts/` on Windows), as
    RECORD paths. They start the build machine's Python by its absolute path, so they're useless
    elsewhere. Executables a wheel ships itself stay in the bundle: ruff's and uv's Python wrappers
    find their binary in `bin/` next to the packages (gauntlet 22)."""
    found = set()
    for dist_info in site.glob("*.dist-info"):
        names = scripts_of(dist_info)
        record = dist_info / "RECORD"
        if not names or not record.exists():
            continue
        launcher_names = {
            f"{n}{suffix}" for n in names for suffix in ("", ".exe", "-script.py", "-script.pyw")
        }
        for path in _verify.record_paths(record.read_text(encoding="utf-8")):
            folder, _, file = path.partition("/")
            if folder in _verify.SCRIPT_DIRS and file in launcher_names:
                found.add(path)
    return found
