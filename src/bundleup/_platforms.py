"""Other platforms as build targets (ADR-0014): uv's platform names, what they mean for the loader's
checks and for environment markers, and whether a wheel fits.

A bundle for another platform is built with a local interpreter of the same Python version: bytecode
depends only on the version, and uv selects wheels for the target (`--python-platform`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ._errors import UsageError

ALIASES = {
    "linux": "x86_64-unknown-linux-gnu",
    "macos": "aarch64-apple-darwin",
    "windows": "x86_64-pc-windows-msvc",
}
# How each OS names a CPU (what the loader compares at start-up): os.uname().machine on Linux and
# macOS, PROCESSOR_ARCHITECTURE on Windows.
MACHINES = {
    "linux": {"x86_64": "x86_64", "aarch64": "aarch64", "i686": "i686"},
    "darwin": {"x86_64": "x86_64", "aarch64": "arm64"},
    "win32": {"x86_64": "AMD64", "aarch64": "ARM64", "i686": "x86"},
}
SYSTEMS = {"linux": "Linux", "darwin": "Darwin", "win32": "Windows"}
# Words in a wheel's platform tag for each OS, and for each CPU.
TAG_OS = {"linux": ("linux",), "darwin": ("macosx",), "win32": ("win",)}
TAG_CPU = {
    "x86_64": ("x86_64", "amd64", "universal2", "intel"),
    "aarch64": ("aarch64", "arm64", "universal2"),
    "i686": ("i686", "win32"),
}
EXAMPLES = (
    "x86_64-manylinux_2_28, aarch64-unknown-linux-gnu, aarch64-apple-darwin, x86_64-pc-windows-msvc"
)


@dataclass(frozen=True)
class Platform:
    """A target platform from one of uv's `--python-platform` names."""

    name: str  # as given, passed on to uv
    sys_platform: str  # linux | darwin | win32
    arch: str  # x86_64 | aarch64 | i686
    musl: bool

    @property
    def machine(self) -> str:
        return MACHINES[self.sys_platform][self.arch]

    def markers(self, *, python_full_version: str) -> dict[str, str]:
        """The PEP 508 environment uv.lock's markers are evaluated against for this target."""
        major_minor = ".".join(python_full_version.split(".")[:2])
        return {
            "implementation_name": "cpython",
            "implementation_version": python_full_version,
            "os_name": "nt" if self.sys_platform == "win32" else "posix",
            "platform_machine": self.machine,
            "platform_release": "",
            "platform_system": SYSTEMS[self.sys_platform],
            "platform_version": "",
            "python_full_version": python_full_version,
            "platform_python_implementation": "CPython",
            "python_version": major_minor,
            "sys_platform": self.sys_platform,
        }

    def accepts(self, tag: str) -> bool:
        """Whether a wheel tag ("cp311-cp311-manylinux_2_17_x86_64") can run on this platform."""
        platform_tag = tag.rsplit("-", 1)[-1].lower()
        if platform_tag == "any":
            return True
        parts = platform_tag.split(
            "."
        )  # compressed tag sets: "manylinux1_x86_64.manylinux2014_x86_64"
        return any(self._accepts_one(p) for p in parts)

    def _accepts_one(self, platform_tag: str) -> bool:
        if not any(word in platform_tag for word in TAG_OS[self.sys_platform]):
            return False
        if self.sys_platform == "linux" and ("musllinux" in platform_tag) != self.musl:
            return False
        if self.sys_platform == "win32" and platform_tag == "win32":
            return self.arch == "i686"
        return any(word in platform_tag for word in TAG_CPU[self.arch])


def parse(name: str) -> Platform:
    """Read a uv platform name. Raises UsageError for names bundleup can't target."""
    full = ALIASES.get(name, name).lower()
    arch = full.split("-", 1)[0]
    if "windows" in full:
        sys_platform = "win32"
    elif "apple-darwin" in full:
        sys_platform = "darwin"
    elif "linux" in full and "android" not in full:
        sys_platform = "linux"
    else:
        sys_platform = ""
    if not sys_platform or arch not in MACHINES.get(sys_platform, {}):
        raise UsageError(
            f"bundleup can't build for {name!r}",
            hint=f"use one of uv's platform names for Linux, macOS or Windows, e.g. {EXAMPLES}",
        )
    return Platform(name, sys_platform, arch, musl="musl" in full)


def wheel_tags(dist_info: Path) -> list[str]:
    """The tags an installed distribution's WHEEL file lists ("cp312-cp312-manylinux_2_17_x86_64").
    Empty if it has none (not installed from a wheel)."""
    wheel = dist_info / "WHEEL"
    if not wheel.is_file():
        return []
    lines = wheel.read_text(encoding="utf-8").splitlines()
    return [line.split(":", 1)[1].strip() for line in lines if line.startswith("Tag:")]


def is_native(tags: list[str]) -> bool:
    """Built for one platform: any tag other than "...-any"."""
    return any(not tag.endswith("-any") for tag in tags)


LEGACY_MANYLINUX = {"manylinux1": (2, 5), "manylinux2010": (2, 12), "manylinux2014": (2, 17)}
LEVEL = re.compile(r"(?P<kind>manylinux|musllinux|macosx)_(?P<major>\d+)_(?P<minor>\d+)_")


@dataclass(frozen=True)
class RuntimeNeeds:
    """What the machine running a bundle must have, from its native wheels' tags: the C library
    (and minimum version) on Linux, the minimum macOS version. The loader checks both at
    start-up, so a mismatch is one sentence instead of an ImportError (ADR-0029)."""

    libc: tuple[str, tuple[int, int]] | None = None  # ("glibc", (2, 28)) or ("musl", (1, 2))
    macos: tuple[int, int] | None = None


def _levels(tag: str) -> dict[str, tuple[int, int]]:
    """Each kind of platform level one wheel tag can run with: the lowest of its alternatives
    ("manylinux_2_17_x86_64.manylinux2014_x86_64" needs glibc 2.17)."""
    found: dict[str, tuple[int, int]] = {}
    for platform in tag.rsplit("-", 1)[-1].split("."):
        legacy = next((v for k, v in LEGACY_MANYLINUX.items() if platform.startswith(k)), None)
        if legacy:
            kind, level = "manylinux", legacy
        else:
            match = LEVEL.match(platform)
            if match is None:
                continue
            kind, level = match["kind"], (int(match["major"]), int(match["minor"]))
        if kind not in found or level < found[kind]:
            found[kind] = level
    return found


def runtime_needs(wheels: Iterable[list[str]]) -> RuntimeNeeds:
    """The strictest requirement across all wheels (each given as its list of tags)."""
    need: dict[str, tuple[int, int]] = {}
    for tags in wheels:
        per_wheel: dict[str, tuple[int, int]] = {}
        for tag in tags:
            for kind, level in _levels(tag).items():
                if kind not in per_wheel or level < per_wheel[kind]:
                    per_wheel[kind] = level
        for kind, level in per_wheel.items():
            need[kind] = max(need.get(kind, level), level)
    libc = None
    if "manylinux" in need:
        libc = ("glibc", need["manylinux"])
    elif "musllinux" in need:
        libc = ("musl", need["musllinux"])
    return RuntimeNeeds(libc, need.get("macosx"))
