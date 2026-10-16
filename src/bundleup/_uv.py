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

from packaging.utils import canonicalize_name

from . import _bytecode, _verify
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
        head = re.sub(r"(?m)^packages = \[\]\s*$", "", head).rstrip() + "\npackages = []\n"
        return head
    return head + "".join(kept)


def from_pylock(
    source: Source, stage: Path, *, external: Sequence[str] = ()
) -> tuple[list[list[str]], Path]:
    """Install arguments for a project's own pylock.toml, and the lock the check compares the
    bundle with. uv installs the file in place (its relative paths are relative to it). A lock
    from another tool may not list the project itself; then the project is installed alongside
    and added to the copy the check reads."""
    assert source.pylock is not None
    try:
        text = source.pylock.read_text(encoding="utf-8-sig")
        packages = tomllib.loads(text).get("packages", [])
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ProjectError(f"{source.pylock} isn't valid TOML: {e}") from None
    me = canonicalize_name(source.name)
    mine = [p for p in packages if canonicalize_name(str(p.get("name", ""))) == me]
    editable = next(
        (
            str(p.get("name") or source.name)
            for p in packages
            if p.get("directory", {}).get("editable")
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
        packages = tomllib.loads(text).get("packages", [])
        check.write_text(text, encoding="utf-8")
        relocate_paths(check, source.pylock.parent)
        text = check.read_text(encoding="utf-8")
        lock_for_install = check
    else:
        lock_for_install = source.pylock
    installs = [["-r", str(lock_for_install)]] if packages else []  # uv rejects an empty lock
    if not mine:
        installs.append([str(source.path)])
        text = with_project(text, source.name)
    check.write_text(text, encoding="utf-8")
    extra = _refresh_local(check)
    return [[*args, *extra] for args in installs], check


def _refresh_local(pylock: Path) -> list[str]:
    """`--refresh-package` for every directory package in `pylock`: uv keys cached builds of local
    folders on pyproject.toml alone, so without this an edit to `src/` re-bundles the old wheel."""
    packages = tomllib.loads(pylock.read_text(encoding="utf-8")).get("packages", [])
    return [
        arg
        for p in packages
        if "directory" in p and p.get("name")
        for arg in ("--refresh-package", str(p["name"]))
    ]


def with_project(pylock: str, name: str) -> str:
    """The pylock.toml text with the project itself listed, for the lock-vs-bundle check. (An
    empty `packages = []` would make the added [[packages]] table invalid TOML.)"""
    pylock = re.sub(r"(?m)^packages = \[\]\s*$", "", pylock)
    return pylock + f'\n[[packages]]\nname = "{name}"\ndirectory = {{ path = "." }}\n'


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
            if lock is None or lock.parent != source.path or not pyproject.is_file():
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
    if not isinstance(deps, list) or "path" in str(meta.get("tool", "")):
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
        r"(?ms)^dependencies\s*=\s*\[.*?\]",
        new_deps,
        toml_body,
        count=1,
    )
    if count != 1:
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
) -> Exported:
    """What to install, as `uv pip install` arguments, and the pylock.toml (PEP 751) the
    lock-vs-bundle check reads. From uv.lock: exported as a pylock.toml, which names each
    package's index and files with their hashes, and installed from that, so a bundle gets
    exactly the locked files from wherever they were locked (a company index too), never a
    same-named package from PyPI. From a project's own pylock.toml: that file (ADR-0026)."""
    if source.pylock:
        return Exported(*from_pylock(source, stage, external=external))
    if not (source.is_script and source.pep723) and not source.locked:
        # Only a requirements.txt (or an input with no dependencies) can turn out to pin
        # everything; an unlocked project can't, so --locked refuses it before resolving anything.
        can_pin = source.declared is None or source.declared.suffix == ".txt"
        exported = None
        if can_pin or lock_mode != "locked":
            exported = resolve(
                uv, source, python=python, stage=stage, progress=progress, external=external
            )
        if exported is None or (lock_mode == "locked" and not exported.pinned):
            raise NoLockfileError(
                f"{source.path.name} has no lockfile, and --locked asks for one",
                hint="lock it (`uv lock`, `pip lock .`, or pin every package in requirements.txt"
                "), or build without --locked to resolve the versions now",
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
    cache_key = _export_cache_key(uv, source, selection, mode) if locked_file else None
    cached = export_cache_dir() / f"{cache_key}.toml" if cache_key else None
    if cached is not None and cached.is_file():
        shutil.copyfile(cached, pylock)
    else:
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
            run(command, cwd=source.workdir, what="uv export", progress=progress)
        except UvError as e:
            if mode == "locked" and "needs to be updated" in (e.detail or ""):
                what = f"{source.path.name}.lock" if source.is_script else "uv.lock"
                fix = f"uv lock --script {source.path.name}" if source.is_script else "uv lock"
                against = "the script" if source.is_script else "pyproject.toml"
                raise LockfileOutdatedError(
                    f"{what} is out of date with {against}",
                    hint=f"run `{fix}`, then build again (or --frozen bundles the lock as it is)",
                    detail=e.detail,
                ) from None
            raise
        if cached is not None:
            tmp = cached.with_name(f".{cached.name}.{os.getpid()}.tmp")
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pylock, tmp)
                tmp.replace(cached)
            except OSError:
                pass
            finally:
                with contextlib.suppress(OSError):
                    tmp.unlink(missing_ok=True)
    lock = None if source.is_script else find_uv_lock(source.path)
    relocate_paths(pylock, lock.parent if lock else source.workdir)
    if external:
        pylock.write_text(
            _strip_external(pylock.read_text(encoding="utf-8"), external), encoding="utf-8"
        )
    pinned = mode is not None or (
        source.is_script and _script_pinned(source, pylock, external=external)
    )
    if lock_mode == "locked" and not pinned:
        raise NoLockfileError(
            f"{source.path.name} has no lockfile, and --locked asks for one",
            hint=f"run `uv lock --script {source.path.name}`, pin every package in "
            "`dependencies` with ==, or build without --locked",
        )
    has_pkgs = "[[packages]]" in pylock.read_text(encoding="utf-8")
    installs = [["-r", str(pylock), *_refresh_local(pylock)]] if has_pkgs else []
    return Exported(installs, pylock, pinned=pinned)


EMPTY_PYLOCK = 'lock-version = "1.0"\ncreated-by = "bundleup"\npackages = []\n'


def _strip_requirements_external(declared: Path, excluded: set[str], stage: Path) -> Path | None:
    """If `declared` is a `requirements.txt` and lists packages in `excluded`, write a staged copy
    without them so `uv pip compile` doesn't resolve them or their transitive dependencies. Returns
    None when every requirement in `declared` is external."""
    if not excluded or not declared.name.endswith(".txt"):
        return declared
    from packaging.requirements import InvalidRequirement, Requirement

    text = declared.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\\\n", " ")
    kept: list[str] = []
    kept_reqs = 0
    removed = False
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            kept.append(raw)
            continue
        if line.startswith("-"):
            if line.split()[0].split("=")[0] in INCLUDES:
                return declared
            kept.append(raw)
            continue
        spec, _, _ = line.partition(" --")
        try:
            req = Requirement(spec.strip())
        except InvalidRequirement:
            return declared
        if canonicalize_name(req.name) in excluded:
            removed = True
        else:
            kept.append(raw)
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
        cmd = [uv, "pip", "compile", "--quiet", "--universal", "--format", "pylock.toml"]
        cmd += ["--python-version", oldest, "-o", str(resolved), str(compile_input)]
        with untouched(source):  # reading a setup.py project's metadata builds it
            run(cmd, cwd=declared.parent, what="uv pip compile", progress=progress)
        relocate_paths(resolved, declared.parent)
    text = _strip_external(resolved.read_text(encoding="utf-8"), external)
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
    else:  # the project itself, built from its folder like `pip install .`, and in the check
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
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\\\n", " ")
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            if line.split()[0].split("=")[0] in INCLUDES:
                return None, False
            continue  # --index-url and friends: where from, not which version
        spec, _, options = line.partition(" --")
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
LOCAL_PATH = re.compile(r'(?P<key>\bpath = )"(?P<value>(?:[^"\\]|\\.)*)"')


def relocate_paths(pylock: Path, root: Path) -> None:
    """Make the export's local paths relative to the pylock.toml, as PEP 751 says and uv reads
    them. uv 0.12.23 writes them so; older ones write them relative to the lock's directory (the
    workspace root), which is wrong once the file is in the stage."""
    here = os.path.abspath(pylock.parent)

    def relocated(m: re.Match[str]) -> str:
        value = tomllib.loads('v = "' + m["value"] + '"')["v"]  # the TOML string, unescaped
        if Path(value).is_absolute() or _is_local(Path(here, value)):
            return m[0]
        target = os.path.abspath(root / value)
        try:
            value = os.path.relpath(target, here)
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
                run(
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
    for name in SKIP_TOP:
        p = site / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    for launcher in launchers(site):
        (site / launcher).unlink(missing_ok=True)
    for folder in _verify.SCRIPT_DIRS:
        with contextlib.suppress(OSError):  # missing, or holds files a wheel ships: keep it
            (site / folder).rmdir()
    if script:
        if (site / script).exists():
            raise ProjectError(
                f"{script} would replace a file one of the dependencies installs",
                hint="rename the script",
            )
        (site / script).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.path, site / script)
    copied = []
    if source.app:  # its modules and files at the top, where a project's packages would be
        for rel, file in app_files(source):
            if (site / rel).exists():
                raise ProjectError(
                    f"{rel} would replace a file one of the dependencies installs",
                    hint="rename it",
                )
            (site / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, site / rel)
            copied.append(rel)
    return copied


@contextlib.contextmanager
def untouched(source: Source) -> Iterator[None]:
    """Remove what building the project writes into it (setuptools' build/ and *.egg-info), and
    only what wasn't there before: bundleup never changes a project (ADR-0028)."""
    before = set() if source.is_script else _build_leftovers(source.path)
    try:
        yield
    finally:
        if not source.is_script:
            for leftover in _build_leftovers(source.path) - before:
                shutil.rmtree(leftover, ignore_errors=True)


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
