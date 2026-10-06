"""Exit codes and the exception hierarchy (docs/cli-style-guide.md, "Errors" and "Exit codes").

Every expected failure is a BundleupError subclass with a stable `code` slug, an optional `hint`,
and the exit code the CLI uses. Scripts and agents branch on `code`, never on the message text.
"""

from __future__ import annotations

from enum import IntEnum

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


class NotABundleError(BundleupError):
    """The file isn't a bundleup bundle, or was made before bundles carried a manifest."""

    code = "not-a-bundle"
