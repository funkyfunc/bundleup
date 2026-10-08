"""Driving uv: export the locked set (or read a pylock.toml) and install it into the payload."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from packaging.utils import canonicalize_name

from . import _toml as tomllib
from . import _verify
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


def find_uv() -> str:
    """The user's own uv if it's recent enough (it wrote their uv.lock), else the bundled one."""
    on_path = shutil.which("uv")
    if on_path:
        try:
            out = subprocess.run(
                [on_path, "--version"], capture_output=True, text=True, timeout=10
            ).stdout
            if tuple(int(x) for x in out.split()[1].split(".")[:2]) >= MIN_UV:
                return on_path
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass
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


def from_pylock(source: Source, stage: Path) -> tuple[list[list[str]], Path]:
    """Install arguments for a project's own pylock.toml, and the lock the check compares the
    bundle with. uv installs the file in place (its relative paths are relative to it). A lock
    from another tool may not list the project itself; then the project is installed alongside
    and added to the copy the check reads."""
    assert source.pylock is not None
    text = source.pylock.read_text(encoding="utf-8")
    try:
        packages = tomllib.loads(text).get("packages", [])
    except tomllib.TOMLDecodeError as e:
        raise ProjectError(f"{source.pylock} isn't valid TOML: {e}") from None
    me = canonicalize_name(source.name)
    mine = [p for p in packages if canonicalize_name(str(p.get("name", ""))) == me]
    if any(p.get("directory", {}).get("editable") for p in mine):
        raise ProjectError(
            f"{source.pylock.name} installs {source.name} as editable, which would point the "
            "bundle back at this directory",
            hint="export the lock without editable installs (uv: --no-editable)",
        )
    installs = [["-r", str(source.pylock)]] if packages else []  # uv rejects an empty lock
    check = stage / "pylock.toml"
    if not mine:
        installs.append([str(source.path)])
        text = with_project(text, source.name)
    check.write_text(text, encoding="utf-8")
    return installs, check


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
) -> Exported:
    """What to install, as `uv pip install` arguments, and the pylock.toml (PEP 751) the
    lock-vs-bundle check reads. From uv.lock: exported as a pylock.toml, which names each
    package's index and files with their hashes, and installed from that, so a bundle gets
    exactly the locked files from wherever they were locked (a company index too), never a
    same-named package from PyPI. From a project's own pylock.toml: that file (ADR-0026)."""
    if source.pylock:
        return Exported(*from_pylock(source, stage))
    if not (source.is_script and source.pep723) and not source.locked:
        # Only a requirements.txt can turn out to pin everything; a project can't, so --locked
        # refuses it before resolving anything.
        txt = source.declared is not None and source.declared.suffix == ".txt"
        exported = None
        if txt or lock_mode != "locked":
            exported = resolve(uv, source, python=python, stage=stage, progress=progress)
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
    selection = (
        ["--script", str(source.path)] if source.is_script else ["--no-dev", "--no-editable"]
    )
    # A lock is checked against pyproject.toml / the script by default: uv would otherwise
    # re-lock a stale one, rewriting uv.lock and bundling versions nobody reviewed (ADR-0033).
    # --frozen uses it as is. A script without a lock has nothing to check (uv refuses --locked).
    mode = lock_mode or ("locked" if has_lock(source) else None)
    if mode:
        selection.append(f"--{mode}")
    command = [uv, "export", "--quiet", *selection, "--format", "pylock.toml", "-o", str(pylock)]
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
    lock = None if source.is_script else find_uv_lock(source.path)
    relocate_paths(pylock, lock.parent if lock else source.workdir)
    return Exported([["-r", str(pylock)]], pylock, pinned=mode is not None)


EMPTY_PYLOCK = 'lock-version = "1.0"\ncreated-by = "bundleup"\npackages = []\n'


def resolve(
    uv: str, source: Source, *, python: tuple[int, int], stage: Path, progress: Progress
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
    oldest = _oldest_python(source.requires_python, python)
    cmd = [uv, "pip", "compile", "--quiet", "--universal", "--format", "pylock.toml"]
    cmd += ["--python-version", oldest, "-o", str(resolved), str(declared)]
    with untouched(source):  # reading a setup.py project's metadata builds it
        run(cmd, cwd=declared.parent, what="uv pip compile", progress=progress)
    relocate_paths(resolved, declared.parent)
    text = resolved.read_text(encoding="utf-8")
    installs: list[list[str]] = [["-r", str(resolved)]] if "[[packages]]" in text else []
    pinned = False
    if declared.name.endswith(".txt"):
        pins, hashed = pinned_requirements(declared)
        compiled = {canonicalize_name(str(p["name"])) for p in tomllib.loads(text)["packages"]}
        pinned = pins is not None and compiled <= set(pins)
        if pinned and hashed:
            # Every line pinned and hashed, nothing missing: install from the file itself,
            # which makes uv check the hashes it lists.
            installs = [["-r", str(declared)]]
    else:  # the project itself, built from its folder like `pip install .`, and in the check
        installs.append([str(source.path)])
        text = with_project(text, source.name)
    check.write_text(text, encoding="utf-8")
    return Exported(installs, check, pinned=pinned)


def _oldest_python(requires: str | None, python: tuple[int, int]) -> str:
    """The lowest Python the resolution covers: the project's requires-python, or the target's.
    (Resolving from the project's lowest lets a pure-Python bundle run on all of them.)"""
    if requires:
        from packaging.specifiers import InvalidSpecifier, SpecifierSet

        try:
            spec = SpecifierSet(requires)
        except InvalidSpecifier:
            spec = None
        for minor in range(0, python[1] + 1):
            if spec is not None and f"3.{minor}.0" in spec:
                return f"3.{minor}"
    return f"{python[0]}.{python[1]}"


# Options that bring in other requirements, so the file alone doesn't fix every version.
INCLUDES = ("-r", "-c", "-e", "--requirement", "--constraint", "--editable")


def pinned_requirements(path: Path) -> tuple[dict[str, str] | None, bool]:
    """The versions a requirements.txt pins (name -> version) if every requirement is pinned to
    one exact version (`name==1.2`) and none comes from elsewhere (-r, -c, -e, URLs, paths);
    else None. And whether every requirement carries a --hash."""
    from packaging.requirements import InvalidRequirement, Requirement

    pins: dict[str, str] = {}
    hashed = True
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            if line.split()[0].split("=")[0] in INCLUDES:
                return None, False
            continue  # --index-url and friends: where from, not which version
        spec, _, options = line.partition(" --")
        hashed = hashed and "hash" in options
        try:
            req = Requirement(spec.strip())
        except InvalidRequirement:
            return None, False  # a path or URL
        exact = [s for s in req.specifier if s.operator in ("==", "===") and "*" not in s.version]
        if req.url or len(exact) != 1 or len(req.specifier) != 1:
            return None, False
        pins[canonicalize_name(req.name)] = exact[0].version
    return pins, hashed and bool(pins)


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
    return path.is_file() or (path / "pyproject.toml").is_file() or (path / "setup.py").is_file()


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
    for dist_info in site.glob("*.dist-info"):
        if canonicalize_name(dist_info.name.split("-")[0]) == want:
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
