"""Exit codes and the exception hierarchy (docs/cli-style-guide.md, "Errors" and "Exit codes").

Every expected failure is a BundleupError subclass with a stable `code` slug, an optional `hint`,
and the exit code the CLI uses. Scripts and agents branch on `code`, never on the message text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

ISSUES_URL = "https://github.com/funkyfunc/bundleup/issues"


class ExitCode(IntEnum):
    OK = 0
    BUILD_FAILED = 1  # an expected failure: stale lock, wrong Python, uv failed, ...
    USAGE_ERROR = 2  # invalid flags or command
    INTERNAL_ERROR = 3  # a bug in bundleup
    INTERRUPTED = 130  # Ctrl-C


class BundleupError(Exception):
    """A failure the user can act on. The CLI prints it without a traceback."""

    code = "build-failed"
    exit_code = ExitCode.BUILD_FAILED

    def __init__(self, message: str, *, hint: str | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail  # e.g. uv's own output, shown verbatim under the message


class UsageError(BundleupError):
    """The command line asks for something that can't work (e.g. --entry with a script)."""

    code = "usage"
    exit_code = ExitCode.USAGE_ERROR


class ProjectError(BundleupError):
    """The path isn't a project or script bundleup can read, or its metadata is invalid."""

    code = "invalid-project"


class PythonNotFoundError(BundleupError):
    code = "python-not-found"


class PythonMismatchError(BundleupError):
    """The target Python doesn't satisfy the project's requires-python."""

    code = "python-mismatch"


class LockfileOutdatedError(BundleupError):
    """uv.lock doesn't match pyproject.toml and --locked (or CI) forbids updating it."""

    code = "lock-outdated"


class UvNotFoundError(BundleupError):
    code = "uv-not-found"


class UvError(BundleupError):
    """A uv command failed; `detail` holds its output."""

    code = "uv-failed"


class EntryPointError(BundleupError):
    """bundleup can't tell what the bundle should run."""

    code = "no-entry-point"


class BundleMismatchError(BundleupError):
    """The payload doesn't match uv.lock or a wheel's RECORD. Always a bug in bundleup."""

    code = "bundle-mismatch"
    exit_code = ExitCode.INTERNAL_ERROR


class NoCompatibleWheelError(BundleupError):
    """A package has no build for the target platform (e.g. compiled code built for the host)."""

    code = "incompatible-wheel"


class NoLockfileError(BundleupError):
    """A project has no uv.lock (here or in its workspace) and no pylock.toml: bundleup bundles
    exactly a lock, and never writes one into the project (ADR-0028)."""

    code = "no-lockfile"


class NotABundleError(BundleupError):
    """The file isn't a bundleup bundle, or was made before bundles carried a manifest."""

    code = "not-a-bundle"


@dataclass(frozen=True)
class Diagnostic:
    """One finding, shown to people (stderr) and to machines (`--json`). Branch on `code`."""

    code: str  # stable slug, e.g. "syntax-error"
    level: Literal["error", "warning"]
    message: str
    hint: str | None = None
    detail: str | None = None  # e.g. uv's output or a list of files, shown under the message
    package: str | None = None  # the distribution it's about, canonical name
    file: str | None = None  # POSIX path inside the bundle
    line: int | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_error(cls, error: BundleupError) -> Diagnostic:
        return cls(error.code, "error", error.message, error.hint, error.detail)


class CheckFailedError(BundleupError):
    """The analysis found errors (or, with `strict`, warnings); nothing was written. Each finding
    is in `diagnostics`."""

    code = "check-failed"

    def __init__(
        self, message: str, *, diagnostics: list[Diagnostic], hint: str | None = None
    ) -> None:
        super().__init__(message, hint=hint)
        self.diagnostics = diagnostics
