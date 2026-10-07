"""Driving uv: export the locked set (or read a pylock.toml) and install it into the payload."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from packaging.utils import canonicalize_name

from . import _verify
from ._errors import (
    LockfileOutdatedError,
    NoCompatibleWheelError,
    ProjectError,
    UvError,
    UvNotFoundError,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib
from ._python import Target
from ._source import Source, find_uv_lock
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
        text += f'\n[[packages]]\nname = "{source.name}"\ndirectory = {{ path = "." }}\n'
    check.write_text(text, encoding="utf-8")
    return installs, check


def has_lock(source: Source) -> bool:
    """A uv lock to check: the project's (or its workspace's) uv.lock, or `<script>.lock`."""
    if source.is_script:
        return source.path.with_name(source.path.name + ".lock").is_file()
    return find_uv_lock(source.path) is not None


def export(
    uv: str, source: Source, *, lock_mode: str | None, stage: Path, progress: Progress
) -> tuple[list[list[str]], Path]:
    """What to install, as `uv pip install` arguments, and the pylock.toml (PEP 751) the
    lock-vs-bundle check reads. From uv.lock: exported twice in parallel, as requirements and as
    pylock.toml. From a project's own pylock.toml: that file (ADR-0026)."""
    if source.pylock:
        return from_pylock(source, stage)
    reqs, pylock = stage / "requirements.txt", stage / "pylock.toml"
    selection = (
        ["--script", str(source.path)] if source.is_script else ["--no-dev", "--no-editable"]
    )
    # A lock is checked against pyproject.toml / the script by default: uv would otherwise
    # re-lock a stale one, rewriting uv.lock and bundling versions nobody reviewed (ADR-0033).
    # --frozen uses it as is. A script without a lock has nothing to check (uv refuses --locked).
    mode = lock_mode or ("locked" if has_lock(source) else None)
    if mode:
        selection.append(f"--{mode}")
    as_requirements = ["--no-hashes", "--no-header", "--no-annotate", "-o", str(reqs)]
    as_pylock = ["--format", "pylock.toml", "-o", str(pylock)]
    commands = [[uv, "export", "--quiet", *selection, *fmt] for fmt in (as_requirements, as_pylock)]
    try:
        with ThreadPoolExecutor(2) as pool:  # independent reads of the same lock
            futures = [
                pool.submit(run, c, cwd=source.workdir, what="uv export", progress=progress)
                for c in commands
            ]
            for future in futures:
                future.result()
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
    return [["-r", str(reqs)]], pylock


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
) -> None:
    """Install the exported set into `site`, the directory that becomes the payload. `reqs` is
    one `uv pip install` argument list per call (uv takes a pylock.toml only on its own)."""
    # The export is the complete, pinned set, so --no-deps installs exactly the lock. Relative
    # paths in it (the project itself, workspace members) resolve against the working directory.
    platform = ["--python-platform", target.python_platform.name] if target.python_platform else []
    common = ["--quiet", "--no-deps", "--target", str(site), "--python", target.executable]
    try:
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
