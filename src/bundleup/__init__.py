"""bundleup: make self-contained Python files.

The public API is exactly `__all__` (docs/cli-style-guide.md rule 38); everything else lives in
`_private` modules. The build machinery is imported on first use of `build` and friends, so
`import bundleup` (and so `bundleup --version`) stays cheap (rule 35, ADR-0018).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from ._errors import (
    BundleMismatchError,
    BundleupError,
    CheckFailedError,
    Diagnostic,
    EntryPointError,
    ExitCode,
    LockfileOutdatedError,
    NoCompatibleWheelError,
    NotABundleError,
    ProjectError,
    PythonMismatchError,
    PythonNotFoundError,
    UsageError,
    UvError,
    UvNotFoundError,
)

if TYPE_CHECKING:
    from ._build import BuildOptions, BuildResult, ProgressEvent, Target, build, check
    from ._cache import CachedBundle, CleanReport, clean_cache, list_cache
    from ._check import CheckReport, PackageSize
    from ._targets import Preset, list_targets
    from ._verify import VerifyReport, verify

__version__ = "0.0.1"

__all__ = [
    "BuildOptions",
    "BuildResult",
    "BundleMismatchError",
    "BundleupError",
    "CachedBundle",
    "CheckFailedError",
    "CheckReport",
    "CleanReport",
    "Diagnostic",
    "EntryPointError",
    "ExitCode",
    "LockfileOutdatedError",
    "NoCompatibleWheelError",
    "NotABundleError",
    "PackageSize",
    "Preset",
    "ProgressEvent",
    "ProjectError",
    "PythonMismatchError",
    "PythonNotFoundError",
    "Target",
    "UsageError",
    "UvError",
    "UvNotFoundError",
    "VerifyReport",
    "__version__",
    "build",
    "check",
    "clean_cache",
    "list_cache",
    "list_targets",
    "verify",
]

# Public names whose module is imported only when they're first used.
_LAZY = {
    **{
        name: "._build"
        for name in ("BuildOptions", "BuildResult", "ProgressEvent", "Target", "build", "check")
    },
    **{name: "._check" for name in ("CheckReport", "PackageSize")},
    **{name: "._targets" for name in ("Preset", "list_targets")},
    **{name: "._verify" for name in ("VerifyReport", "verify")},
    **{name: "._cache" for name in ("CachedBundle", "CleanReport", "clean_cache", "list_cache")},
}


def __getattr__(name: str) -> object:
    """Load lazily exported names on first access (PEP 562; see ADR-0018 for why)."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'bundleup' has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value  # later lookups skip this function
    return value
