"""The target: which Python and platform a bundle is built for, found and probed through uv."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from . import _platforms
from ._errors import (
    ProjectError,
    PythonMismatchError,
    PythonNotFoundError,
    UsageError,
    UvError,
)

if sys.version_info >= (3, 11):
    pass
else:
    pass
from ._source import Source
from ._steps import Progress, run

PLATFORM_NAMES = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}


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

    def describe(self, native: bool) -> str:
        where = PLATFORM_NAMES.get(self.platform, self.platform)
        return f"Python {self.version[0]}.{self.version[1]} on {where}" + (
            f" {self.machine}" if native else ""
        )

    def to_json_dict(self, *, native: bool) -> dict[str, object]:
        return {
            "python": f"{self.version[0]}.{self.version[1]}",
            "python_full_version": self.full_version,
            "implementation": self.implementation,
            "platform": self.platform,
            "machine": self.machine if native else None,  # None: runs on any CPU
            "python_platform": self.python_platform.name if self.python_platform else None,
        }


def find_python(
    uv: str,
    source: Source,
    *,
    request: str | None,
    python_platform: str | None,
    progress: Progress,
) -> Target:
    """The target: --python if given, else what uv would use for the project; on another platform
    if `python_platform` is set (then this interpreter only compiles bytecode for the version)."""
    platform = _platforms.parse(python_platform) if python_platform else None
    if request and Path(request).is_file():
        exe = request  # a path: no need to ask uv (which would run the interpreter to inspect it)
    else:
        cmd = _find_cmd(uv, source, request=request)
        try:
            exe = run(cmd, cwd=source.workdir, what="finding a Python", progress=progress).strip()
        except UvError as e:
            wanted = f"Python {request}" if request else "a Python for this project"
            install = f"uv python install {request}" if request else "uv python install"
            raise PythonNotFoundError(
                f"couldn't find {wanted}", hint=f"install it with `{install}`", detail=e.detail
            ) from None
    probe = [exe, "-I", "-S", "-c", PROBE]
    info = json.loads(run(probe, what=f"inspecting {exe}", progress=progress, error=ProjectError))
    major, minor = info["version"]
    if platform is not None:
        if info["markers"]["implementation_name"] != "cpython":
            raise UsageError(
                "building for another platform needs a CPython interpreter of the target version",
                hint=f"pass --python {major}.{minor}",
            )
        full = info["markers"]["python_full_version"]
        return Target(
            executable=info["executable"] or exe,
            version=(major, minor),
            full_version=full,
            platform=platform.sys_platform,
            machine=platform.machine,
            abiflags=None if platform.sys_platform == "win32" else "",  # no sys.abiflags on Windows
            implementation="cpython",
            cache_tag=info["cache_tag"],
            markers=platform.markers(python_full_version=full),
            python_platform=platform,
        )
    return Target(
        # Use the real interpreter from here on: uv re-inspects shims like macOS's
        # /usr/bin/python3 on every call, but caches what it learns about a real interpreter.
        executable=info["executable"] or exe,
        version=(major, minor),
        full_version=info["markers"]["python_full_version"],
        platform=info["markers"]["sys_platform"],
        machine=info["markers"]["platform_machine"],
        abiflags=info["abiflags"],
        implementation=info["markers"]["implementation_name"],
        cache_tag=info["cache_tag"],
        markers=info["markers"],
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


def _find_cmd(uv: str, source: Source, *, request: str | None) -> list[str]:
    cmd = [uv, "python", "find"]
    if request:
        cmd.append(request)
        if source.is_script:
            # A script next to a project shouldn't pick up the project's venv.
            cmd.append("--no-project")
    elif source.is_script:
        cmd += ["--script", str(source.path)]  # honours the script's requires-python
    return cmd


def check_requires_python(source: Source, target: Target) -> None:
    if not source.requires_python:
        return
    try:
        spec = SpecifierSet(source.requires_python)
    except InvalidSpecifier:
        raise ProjectError(
            f"{source.name} has an invalid requires-python: {source.requires_python!r}"
        ) from None
    if target.full_version not in spec:
        raise PythonMismatchError(
            f"{source.name} needs Python {source.requires_python}, but the target is Python "
            f"{target.full_version} ({target.executable})",
            hint=f"build for a matching Python: bundleup build --python {_suggest(spec)}",
        )


def _suggest(spec: SpecifierSet) -> str:
    for minor in range(8, 30):
        if spec.contains(f"3.{minor}.0") or spec.contains(f"3.{minor}.99"):
            return f"3.{minor}"
    return "<version>"
