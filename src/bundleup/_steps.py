"""Progress reporting, the build steps, and running commands (uv, the target Python)."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ._errors import (
    BundleupError,
    UvError,
)


@dataclass(frozen=True)
class ProgressEvent:
    """Reported while building: a step starting, or a command about to run."""

    kind: Literal["step", "command"]
    text: str


Progress = Callable[[ProgressEvent], None]


def ignore(event: ProgressEvent) -> None:
    pass


def run(
    cmd: list[str],
    *,
    progress: Progress,
    cwd: Path | None = None,
    what: str = "",
    error: type[BundleupError] = UvError,
    env: dict[str, str] | None = None,
) -> str:
    """Run a command and return its stdout, or raise `error` with its output as the detail."""
    progress(ProgressEvent("command", " ".join(cmd)))
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    except OSError as e:  # the program doesn't exist, or can't be run
        raise error(f"{what or cmd[0]} failed: couldn't run {cmd[0]}", detail=str(e)) from None
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise error(f"{what or cmd[0]} failed", detail=detail)
    return proc.stdout


# Build steps: a stable slug (the keys of BuildResult.timings) and what people see while it runs.
STEPS = {
    "python": "finding the Python",
    "export": "reading uv.lock",
    "install": "installing",
    "compile": "compiling",
    "check": "checking",
    "zip": "zipping",
    "verify": "verifying",
    "write": "writing",
    "smoke": "running it once (--smoke)",
}


class Steps:
    """Announces each build step through `progress` and times it."""

    def __init__(self, progress: Progress) -> None:
        self.progress = progress
        self.timings: dict[str, float] = {}
        self.current: str | None = None
        self.started = self.mark = time.perf_counter()

    def start(self, name: str) -> None:
        self.finish()
        self.current, self.mark = name, time.perf_counter()
        self.progress(ProgressEvent("step", STEPS[name]))

    def finish(self) -> None:
        if self.current is not None:
            elapsed = time.perf_counter() - self.mark  # summed: several payloads repeat steps
            self.timings[self.current] = self.timings.get(self.current, 0.0) + elapsed
            self.current = None
