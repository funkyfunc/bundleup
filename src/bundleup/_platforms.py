"""Other platforms as build targets (ADR-0014): uv's platform names, what they mean for the loader's
checks and for environment markers, and whether a wheel fits.

A bundle for another platform is built with a local interpreter of the same Python version: bytecode
depends only on the version, and uv selects wheels for the target (`--python-platform`).
"""

from __future__ import annotations

from dataclasses import dataclass

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
