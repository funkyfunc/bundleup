"""The target: which Python and platform a bundle is built for, found and probed through uv."""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from . import _imports, _network, _platforms
from . import _toml as tomllib
from ._errors import (
    ProjectError,
    PythonMismatchError,
    PythonNotFoundError,
    UsageError,
    UvError,
)
from ._source import Source
from ._steps import Progress, ProgressEvent, run

PLATFORM_NAMES = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}


@dataclass(frozen=True)
class PythonRange:
    """The Python minor versions a bundle runs on (ADR-0030): exactly one when it has compiled
    code, otherwise every version the lock and the packages allow. `max` None: no upper limit."""

    min: tuple[int, int]
    max: tuple[int, int] | None

    @property
    def exact(self) -> bool:
        return self.max == self.min

    def __str__(self) -> str:
        """'3.12', '3.10+' or '3.10-3.12'."""
        low = f"{self.min[0]}.{self.min[1]}"
        if self.exact:
            return low
        return f"{low}+" if self.max is None else f"{low}-{self.max[0]}.{self.max[1]}"

    def contains(self, version: tuple[int, int]) -> bool:
        return self.min <= version and (self.max is None or version <= self.max)

    def to_json_dict(self) -> dict[str, object]:
        def text(v: tuple[int, int] | None) -> str | None:
            return f"{v[0]}.{v[1]}" if v else None

        return {"min": text(self.min), "max": text(self.max)}


@dataclass(frozen=True)
class Portability:
    """Whether a bundle runs on any OS and any CPU (ADR-0034): only without compiled code, and
    only when the lock selects the same packages everywhere."""

    any_os: bool = False
    any_cpu: bool = False


@dataclass(frozen=True)
class Target:
    """What a bundle is built for: this machine's interpreter, or another platform (ADR-0014)."""

    executable: str
    version: tuple[int, int]
    full_version: str
    platform: str
    machine: str
    abiflags: str | None
    implementation: str
    cache_tag: str  # names .pyc files, e.g. "cpython-312" (from the compiling interpreter)
    markers: dict[str, str]  # the PEP 508 environment uv.lock's markers are evaluated against
    python_platform: _platforms.Platform | None = None  # set when building for another platform
    # False when assembled using a host CPython of another minor version (ADR-0053): wheels and
    # AST/stdlib are checked for `version`, and payload bytecode compiles on first run.
    has_interpreter: bool = True

    def describe(
        self,
        native: bool,
        pythons: PythonRange | None = None,
        reach: Portability | None = None,
    ) -> str:
        python = str(pythons) if pythons else f"{self.version[0]}.{self.version[1]}"
        if reach and reach.any_os:
            return f"Python {python} on any OS"
        where = PLATFORM_NAMES.get(self.platform, self.platform)
        pinned = native or bool(reach and not reach.any_cpu)
        return f"Python {python} on {where}" + (f" {self.machine}" if pinned else "")

    def to_json_dict(
        self,
        *,
        native: bool,
        pythons: PythonRange | None = None,
        reach: Portability | None = None,
    ) -> dict[str, object]:
        exact = PythonRange(self.version, self.version)
        pinned = native or bool(reach and not reach.any_cpu)
        return {
            # Runs on Linux, macOS and Windows alike (added within schema version 1, ADR-0034).
            "any_os": bool(reach and reach.any_os),
            "python": f"{self.version[0]}.{self.version[1]}",
            # Every version the bundle runs on (added within schema version 1, ADR-0030).
            "python_range": (pythons or exact).to_json_dict(),
            "python_full_version": self.full_version,
            "implementation": self.implementation,
            "platform": self.platform,
            "machine": self.machine if pinned else None,  # None: runs on any CPU
            "python_platform": self.python_platform.name if self.python_platform else None,
        }


_OPT_IN_VALUES = frozenset({"1", "true", "yes", "automatic", "auto"})


def downloads_enabled() -> bool:
    """Interpreter downloads are explicitly opt-in (ADR-0053): `.pyz`/`.py` builds assemble wheels
    without extra interpreters, and restricted networks often block external binary downloads."""
    for var in ("BUNDLEUP_PYTHON_DOWNLOADS", "UV_PYTHON_DOWNLOADS"):
        val = os.environ.get(var, "").strip().lower()
        if val in ("0", "false", "no", "never", "manual"):
            return False
        if val in _OPT_IN_VALUES:
            return True
    return False


def find_private_interpreter(uv: str, version: str, *, cwd: Path, progress: Progress) -> str | None:
    """An interpreter of `version` that an earlier build cached under `private_pythons()`, without
    touching the network."""
    pythons_dir = private_pythons()
    if not pythons_dir.is_dir():
        return None
    env = {**_clean_venv_env(), "UV_PYTHON_INSTALL_DIR": str(pythons_dir)}
    find = [uv, "python", "find", "--no-project", version, "--managed-python"]
    try:
        return _real(run(find, cwd=cwd, what="uv python find", progress=progress, env=env))
    except UvError:
        return None


def _find_host_cpython(uv: str, source: Source, *, progress: Progress) -> str | None:
    """Any locally installed CPython interpreter (>=3.9) on this machine, without downloading."""
    import sys

    outside = Path(tempfile.gettempdir())
    for req in ("cpython", None):
        cmd = [uv, "python", "find", "--no-project", "--no-python-downloads"]
        if req:
            cmd.append(req)
        try:
            exe = _real(
                run(
                    cmd,
                    cwd=outside,
                    what="finding a host Python",
                    progress=progress,
                    env=_clean_venv_env(),
                )
            )
            if exe:
                return exe
        except UvError:
            continue
    if sys.implementation.name == "cpython" and sys.version_info >= (3, 9):
        return _real(sys.executable) or sys.executable
    return None


def find_python(
    uv: str,
    source: Source,
    *,
    request: str | None,
    python_platform: str | None,
    progress: Progress,
    allow_host_assembly: bool = False,
) -> Target:
    """The target: --python if given, else what uv would use for the project; on another platform
    if `python_platform` is set. When `allow_host_assembly` is True (`.pyz`/`.py` builds) and the
    requested CPython minor version isn't installed locally, a host CPython assembles the wheels
    and checks syntax/stdlib in-process while deferring `.pyc` compilation to first run."""
    platform = _platforms.parse(python_platform) if python_platform else None
    synthesized: tuple[int, int, str] | None = None
    if request and Path(request).is_file():
        exe = request  # a path: no need to ask uv (which would run the interpreter to inspect it)
    else:
        cmd = _find_cmd(uv, source, request=request)
        find_env = _find_env(source.workdir, is_script=source.is_script)
        try:
            try:
                exe = run(
                    cmd,
                    cwd=source.workdir,
                    what="finding a Python",
                    progress=progress,
                    env=find_env,
                ).strip()
            except UvError:
                clean_env = _clean_venv_env()
                if clean_env == (find_env if find_env is not None else os.environ):
                    raise
                exe = run(
                    cmd,
                    cwd=source.workdir,
                    what="finding a Python",
                    progress=progress,
                    env=clean_env,
                ).strip()
        except UvError as e:
            eff_req = request or _script_lock_python(source)
            outside = Path(tempfile.gettempdir())  # uv answers a project's venv from inside it
            fetched = None
            dl_errors: list[UvError] = []
            ver_match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+)(?:(?:a|b|rc)\d+)?)?", eff_req or "")
            too_old = bool(ver_match and (int(ver_match[1]), int(ver_match[2])) < (3, 9))
            if ver_match and not too_old and eff_req:
                fetched = find_private_interpreter(uv, eff_req, cwd=outside, progress=progress)
                if not fetched and downloads_enabled():
                    fetched = fetch_interpreter(
                        uv, eff_req, cwd=outside, progress=progress, errors=dl_errors
                    )
            host_exe_found: str | None = None
            if not fetched and allow_host_assembly and ver_match and not too_old and not dl_errors:
                req_ver = (int(ver_match[1]), int(ver_match[2]))
                if req_ver[0] == 3 and req_ver <= _imports.NEWEST:
                    host_exe = _find_host_cpython(uv, source, progress=progress)
                    if host_exe:
                        patch = ver_match[3] or "0"
                        synthesized = (req_ver[0], req_ver[1], f"{req_ver[0]}.{req_ver[1]}.{patch}")
                        host_exe_found = host_exe
            if fetched:
                exe = fetched
            elif host_exe_found is not None:
                exe = host_exe_found
            else:
                if dl_errors and eff_req:
                    msg, dl_hint = _network.diagnose_runtime_download(
                        eff_req, dl_errors[-1].detail or str(dl_errors[-1]), kind="interpreter"
                    )
                    raise PythonNotFoundError(
                        msg, hint=dl_hint, detail=_network.redact_text(dl_errors[-1].detail or "")
                    ) from None
                wanted = f"Python {request}" if request else "a Python for this project"
                install = f"uv python install {request}" if request else "uv python install"
                hint = (
                    f"install it with `{install}` (or set BUNDLEUP_PYTHON_DOWNLOADS=1 to "
                    "download missing interpreters automatically)"
                )
                if too_old:
                    hint = "bundles run on Python 3.9 and newer: pass --python 3.9 or later"
                raise PythonNotFoundError(
                    f"couldn't find {wanted}", hint=hint, detail=e.detail
                ) from None
    probe = [exe, "-I", "-S", "-c", PROBE]
    raw = run(probe, what=f"inspecting {exe}", progress=progress, error=ProjectError)
    try:
        info = json.loads(raw)
        major, minor = info["version"]
    except (ValueError, KeyError, TypeError) as e:
        raise ProjectError(
            f"{exe} isn't a working Python 3 interpreter",
            detail=raw[-500:] if raw else None,
        ) from e
    has_interpreter = True
    if synthesized is not None:
        if info["markers"]["implementation_name"] != "cpython":
            raise PythonNotFoundError(
                f"couldn't find Python {synthesized[0]}.{synthesized[1]}",
                hint=f"install CPython with `uv python install {synthesized[0]}.{synthesized[1]}`",
            )
        has_interpreter = (major, minor) == (synthesized[0], synthesized[1])
        major, minor, synth_full = synthesized
        cache_tag = info["cache_tag"] if has_interpreter else f"cpython-{major}{minor}"
        full = info["markers"]["python_full_version"] if has_interpreter else synth_full
    else:
        cache_tag = info["cache_tag"]
        full = info["markers"]["python_full_version"]
    if platform is not None:
        if info["markers"]["implementation_name"] != "cpython":
            raise UsageError(
                "building for another platform needs a CPython interpreter of the target version",
                hint=f"pass --python {major}.{minor}",
            )
        return Target(
            executable=info["executable"] or exe,
            version=(major, minor),
            full_version=full,
            platform=platform.sys_platform,
            machine=platform.machine,
            abiflags=None
            if platform.sys_platform == "win32"
            else (info.get("abiflags") or ""),  # no sys.abiflags on Windows
            implementation="cpython",
            cache_tag=cache_tag,
            markers=platform.markers(python_full_version=full),
            python_platform=platform,
            has_interpreter=has_interpreter,
        )
    markers = (
        info["markers"]
        if has_interpreter
        else {
            **info["markers"],
            "python_version": f"{major}.{minor}",
            "python_full_version": full,
            "implementation_version": full,
        }
    )
    return Target(
        # Use the real interpreter from here on: uv re-inspects shims like macOS's
        # /usr/bin/python3 on every call, but caches what it learns about a real interpreter.
        executable=info["executable"] or exe,
        version=(major, minor),
        full_version=full,
        platform=info["markers"]["sys_platform"],
        machine=info["markers"]["platform_machine"],
        abiflags=info["abiflags"],
        implementation=info["markers"]["implementation_name"],
        cache_tag=cache_tag,
        markers=markers,
        has_interpreter=has_interpreter,
    )


# Runs on the target Python (any version bundleup supports) and prints what the build needs.
# The marker environment follows PEP 508; on POSIX it's read from os.uname() because importing
# `platform` costs ~30 ms on macOS's system Python.
PROBE = """
import json, os, sys
def full(v):
    s = "%d.%d.%d" % (v.major, v.minor, v.micro)
    return s if v.releaselevel == "final" else s + v.releaselevel[0] + str(v.serial)
if hasattr(os, "uname"):
    u = os.uname()
    system, release, version, machine = u.sysname, u.release, u.version, u.machine
else:
    import platform
    system, release = platform.system(), platform.release()
    version, machine = platform.version(), platform.machine()
impl = sys.implementation.name
markers = {
    "implementation_name": impl,
    "implementation_version": full(sys.implementation.version),
    "os_name": os.name,
    "platform_machine": machine,
    "platform_release": release,
    "platform_system": system,
    "platform_version": version,
    "python_full_version": sys.version.split()[0],
    "platform_python_implementation": {"cpython": "CPython", "pypy": "PyPy"}.get(impl, impl),
    "python_version": "%d.%d" % sys.version_info[:2],
    "sys_platform": sys.platform,
}
print(json.dumps({"version": sys.version_info[:2], "abiflags": getattr(sys, "abiflags", None),
                  "executable": sys.executable, "markers": markers,
                  "cache_tag": sys.implementation.cache_tag}))
"""


def _script_lock_python(source: Source) -> str | None:
    """For a locked script that names no requires-python: the Python its lock was made for (the
    oldest its `requires-python` allows). uv stamps its default Python there and calls the lock
    out of date for any other, so an active virtualenv, or a newer Python installed since, made
    a fresh lock "stale" (twelfth review)."""
    if not source.is_script or source.requires_python:
        return None
    try:
        text = source.path.with_name(source.path.name + ".lock").read_text(encoding="utf-8")
        spec = SpecifierSet(str(tomllib.loads(text).get("requires-python") or ""))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, InvalidSpecifier):
        return None
    if not str(spec):
        return None
    for minor in range(9, 30):
        if any(spec.contains(f"3.{minor}.{p}", prereleases=True) for p in (0, 99)):
            return f"3.{minor}"
    return None


def _find_cmd(uv: str, source: Source, *, request: str | None) -> list[str]:
    cmd = [uv, "python", "find"]
    locked_for = None if request else _script_lock_python(source)
    if locked_for:
        return [*cmd, locked_for, "--no-project"]
    if request:
        cmd.append(request)
    if source.is_script and source.pep723 and not request:
        cmd += ["--script", str(source.path)]  # honours the script's requires-python
    elif source.is_script or source.app:
        # A script next to a project shouldn't pick up the project's venv; a folder app isn't a
        # project at all (its own venv/ or .venv is for development).
        cmd.append("--no-project")
    return cmd


def _belongs_to(val: str, workdir: Path) -> bool:
    try:
        if Path(os.path.normcase(os.path.abspath(val))).is_relative_to(
            Path(os.path.normcase(os.path.abspath(workdir)))
        ):
            return True
        resolved = Path(os.path.normcase(str(Path(val).resolve())))
        if resolved.is_relative_to(Path(os.path.normcase(str(workdir.resolve())))):
            return True
        venv = workdir / ".venv"
        return venv.exists() and resolved == Path(os.path.normcase(str(venv.resolve())))
    except (OSError, RuntimeError):
        return False


def _usable_venv(val: str) -> bool:
    try:
        root = Path(os.path.abspath(val))
        if root.is_symlink() and not root.exists():
            return False
        return not (
            root.is_dir()
            and any(
                (p := root / rel).is_symlink() and not p.exists()
                for rel in ("bin/python", "bin/python3", "Scripts/python.exe", "python.exe")
            )
        )
    except OSError:
        return False


def _find_env(workdir: Path, *, is_script: bool = False) -> dict[str, str] | None:
    """Environment for `uv python find`: drop broken VIRTUAL_ENV / CONDA_PREFIX entries, and when
    `workdir` (or its uv workspace root) has its own `.venv` or `.python-version`, drop an active
    VIRTUAL_ENV / CONDA_PREFIX that belongs to another folder."""
    from ._source import find_uv_lock

    has_local = False
    roots = [workdir]
    if not is_script:
        lock = find_uv_lock(workdir) if workdir.is_dir() else None
        roots = [workdir, *([lock.parent] if lock and lock.parent != workdir else [])]
        try:
            has_local = any(
                ((r / ".venv").exists() and _usable_venv(str(r / ".venv")))
                or (r / ".python-version").is_file()
                for r in roots
            )
        except OSError:
            has_local = False
    drop: set[str] = set()
    updates: dict[str, str] = {}
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        val = os.environ.get(var)
        if not val:
            continue
        if not _usable_venv(val) or (has_local and not any(_belongs_to(val, r) for r in roots)):
            drop.add(var)
        elif not os.path.isabs(val):
            updates[var] = os.path.abspath(val)
    if not drop and not updates:
        return None
    return {**{k: v for k, v in os.environ.items() if k not in drop}, **updates}


def _clean_venv_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "CONDA_PREFIX")}


def find_interpreter(uv: str, version: str, *, cwd: Path, progress: Progress) -> str | None:
    """An installed interpreter of `version`, or None; never downloads one. Run from `cwd` outside
    any project, or uv answers with the project's venv."""
    try:
        found = run(
            [uv, "python", "find", "--no-project", version],
            cwd=cwd,
            what="uv python find",
            progress=progress,
            env=_clean_venv_env(),
        )
    except UvError:
        return None
    return _real(found)


def private_pythons() -> Path:
    """Where bundleup installs interpreters it needs only to check code (ADR-0035): its own
    directory, so the user's uv-managed Pythons are never changed under a running program."""
    from ._bytecode import cache_dir  # the build cache's location rules

    return cache_dir().parent / "pythons"


@contextlib.contextmanager
def _install_lock(folder: Path) -> Iterator[None]:
    """One install into `folder` at a time. The lock file sits beside the folder, not in it:
    `uv python install` locks `<install dir>/.lock` itself, so holding that one made uv wait on
    its own parent until it timed out, five minutes later (twelfth review)."""
    handle = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handle = open(folder.with_name(folder.name + ".lock"), "a+b")  # noqa: SIM115
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:
        if handle is not None:
            handle.close()
            handle = None
    try:
        yield
    finally:
        if handle is not None:
            if os.name == "nt":
                with contextlib.suppress(OSError):
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            handle.close()


def fetch_interpreter(
    uv: str,
    version: str,
    *,
    cwd: Path,
    progress: Progress,
    errors: list[UvError] | None = None,
) -> str | None:
    """An interpreter of `version`: an installed one, one bundleup installed before, or one
    installed now into bundleup's private directory. None if that's impossible (offline, or
    UV_PYTHON_DOWNLOADS=never); appends any `uv python install` failure to `errors`."""
    found = find_interpreter(uv, version, cwd=cwd, progress=progress)
    if found:
        return found
    pythons_dir = private_pythons()
    env = {**_clean_venv_env(), "UV_PYTHON_INSTALL_DIR": str(pythons_dir)}
    find = [uv, "python", "find", "--no-project", version, "--managed-python"]
    try:  # installed by an earlier build: no download, nothing to say
        existing = _real(run(find, cwd=cwd, what="uv python find", progress=progress, env=env))
        if existing:
            return existing
    except UvError:
        pass
    with _install_lock(pythons_dir):
        try:
            existing = _real(run(find, cwd=cwd, what="uv python find", progress=progress, env=env))
            if existing:
                return existing
        except UvError:
            pass
        # Said, not done silently (the owner, accepting ADR-0035): a build that downloads something
        # should tell you, and how to stop it.
        progress(
            ProgressEvent(
                "note",
                f"downloading Python {version} into bundleup's own folder (once); "
                "UV_PYTHON_DOWNLOADS=never turns this off",
            )
        )
        install = [uv, "python", "install", version, "--no-bin", "--no-registry"]
        try:
            run(install, cwd=cwd, what="uv python install", progress=progress, env=env)
        except UvError as err:
            if errors is not None:
                errors.append(err)
        try:
            return _real(run(find, cwd=cwd, what="uv python find", progress=progress, env=env))
        except UvError:
            return None


def _real(found: str) -> str | None:
    """The real path: uv's per-minor-version link can be repointed by a later install while this
    interpreter is in use (on Windows that broke a running Python in the gauntlet)."""
    found = found.strip()
    if not found:
        return None
    real = os.path.realpath(found)
    return real if os.path.isfile(real) else None


def check_requires_python(source: Source, target: Target) -> None:
    if not source.requires_python:
        return
    try:
        spec = SpecifierSet(source.requires_python)
    except (InvalidSpecifier, TypeError):
        raise ProjectError(
            f"{source.name} has an invalid requires-python: {source.requires_python!r}",
            hint='write a PEP 440 version specifier, e.g. `requires-python = ">=3.12"`',
        ) from None
    if not spec.contains(target.full_version, prereleases=True):
        raise PythonMismatchError(
            f"{source.name} needs Python {source.requires_python}, but the target is Python "
            f"{target.full_version} ({target.executable})",
            hint=f"build for a matching Python: bundleup build --python {_suggest(spec)}",
        )


def _suggest(spec: SpecifierSet) -> str:
    for minor in range(8, 30):
        if spec.contains(f"3.{minor}.0", prereleases=True) or spec.contains(
            f"3.{minor}.99", prereleases=True
        ):
            return f"3.{minor}"
    return "<version>"
