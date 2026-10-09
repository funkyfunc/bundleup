"""`bundleup build --smoke`: run the finished bundle once, as a user would on a fresh machine,
before shipping it (sixth review: static checks can't see run-time failures; the gauntlet runs
bundles this way and `check` didn't).

The bundle runs with a new empty home folder, cache and working directory, none of the build
machine's Python settings (PYTHONPATH, a virtual environment), and the network blocked where the
OS allows it: `sandbox-exec` on macOS, an empty network namespace (`unshare`) on Linux; on Windows
it isn't blocked, and the result says so. It runs the author's program, so it's opt-in.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ._errors import CheckFailedError, Diagnostic

TIMEOUT = 120.0  # seconds; a program that waits for input or serves forever fails, with a hint
DROPPED = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "VIRTUAL_ENV", "PYTHONUSERBASE")
# macOS: everything allowed except connections to other machines (local sockets still work).
SANDBOX = "(version 1)(allow default)(deny network-outbound (remote ip))"


@dataclass(frozen=True)
class SmokeResult:
    """What `--smoke` ran and how it went. `to_json_dict()` is `result.smoke` in `--json`."""

    command: list[str]
    exit_code: int
    seconds: float
    network_blocked: bool
    output: str  # the last lines of stdout and stderr

    def to_json_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "seconds": round(self.seconds, 2),
            "network_blocked": self.network_blocked,
        }


def parse_args(text: str) -> tuple[str, ...]:
    """`--smoke "scripts/tool.py --help"` -> its arguments, split as a shell would."""
    return tuple(shlex.split(text, posix=os.name != "nt"))


def run(bundle: Path, python: str, args: tuple[str, ...]) -> SmokeResult:
    """Run `python bundle ARGS` in a fresh home, cache and folder, offline where possible. Paths
    in ARGS that exist from here are made absolute (the run happens elsewhere). Raises
    CheckFailedError if it fails or doesn't finish."""
    here = [str(Path(a).absolute()) if a and not a.startswith("-") and Path(a).exists() else a
            for a in args]  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="bundleup-smoke-") as tmp:
        root = Path(tmp)
        for name in ("home", "cache", "work", "tmp"):
            (root / name).mkdir()
        env = {k: v for k, v in os.environ.items() if k not in DROPPED and not k.startswith("UV_")}
        env |= {
            "HOME": str(root / "home"),
            "USERPROFILE": str(root / "home"),
            "BUNDLEUP_CACHE": str(root / "cache"),
            "TMPDIR": str(root / "tmp"),
            "PYTHONNOUSERSITE": "1",
        }
        command = [python, str(bundle), *here]
        wrapped, blocked = _offline(command)
        started = time.perf_counter()
        try:
            done = subprocess.run(
                wrapped,
                cwd=root / "work",
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=TIMEOUT,
            )
            code, out = done.returncode, (done.stdout + done.stderr)
        except subprocess.TimeoutExpired as e:
            code, out = -1, _text(e.stdout) + _text(e.stderr)
        result = SmokeResult(
            ["python", bundle.name, *args], code, time.perf_counter() - started, blocked,
            "\n".join(out.strip().splitlines()[-15:]),
        )  # fmt: skip
    if code != 0:
        shown = " ".join(result.command)
        why = f"didn't finish in {TIMEOUT:.0f} s" if code == -1 else f"exited with {code}"
        raise CheckFailedError(
            f"the bundle was written, but running it ({shown}) {why}",
            diagnostics=[
                Diagnostic(
                    "smoke-failed",
                    "error",
                    f"`{shown}` {why} in a fresh home folder"
                    + (" with no network" if blocked else ""),
                    hint="its output is below; --smoke 'ARGS' runs it with other arguments "
                    "(the default is --help)",
                    detail=result.output,
                )
            ],
        )
    return result


def _offline(command: list[str]) -> tuple[list[str], bool]:
    """The command with the network blocked, and whether that was possible here."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return ["sandbox-exec", "-p", SANDBOX, *command], True
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        probe = subprocess.run(["unshare", "-rn", "true"], capture_output=True)
        if probe.returncode == 0:  # unprivileged namespaces can be turned off
            return ["unshare", "-rn", *command], True
    return command, False


def _text(data: bytes | str | None) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data or ""
