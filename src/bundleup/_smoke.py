"""`bundleup build --smoke`: run the finished bundle once, as a user would on a fresh machine,
before shipping it (sixth review: static checks can't see run-time failures; the gauntlet runs
bundles this way and `check` didn't).

The bundle runs with a new empty home folder, cache and working directory, none of the build
machine's Python settings (PYTHONPATH, a virtual environment), and the network blocked where the
OS allows it: `sandbox-exec` on macOS, an empty network namespace (`unshare`) on Linux; on Windows
it isn't blocked, and the result says so. It runs the author's program, so it's opt-in.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import signal
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
    """`--smoke "scripts/tool.py --help"` -> its arguments, split as a shell would: quotes group
    words, and backslashes stay as they are, so Windows paths survive (shlex's Windows mode kept
    the quotes; CI, 2026-10-09)."""
    from ._errors import UsageError

    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    try:
        return tuple(lexer)
    except ValueError as e:
        raise UsageError(f"--smoke {text!r}: {e}", hint="close any open quotes") from None


def _resolve_args(args: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            out.append(a)
            skip = False
            continue
        if a in ("-c", "-m"):
            out.append(a)
            skip = True
            continue
        if a and not a.startswith("-"):
            with contextlib.suppress(OSError):
                if Path(a).exists():
                    out.append(str(Path(a).absolute()))
                    continue
        out.append(a)
    return out


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        if proc.poll() is None:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=5,
                )
    elif hasattr(os, "killpg"):
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)


def _make_writable(root: Path) -> None:
    with contextlib.suppress(OSError):
        if not os.path.islink(root):
            os.chmod(root, os.lstat(root).st_mode | 0o700)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            p = os.path.join(dirpath, name)
            with contextlib.suppress(OSError):
                if not os.path.islink(p):
                    mode = os.lstat(p).st_mode
                    os.chmod(p, mode | 0o700)


def run(bundle: Path, python: str | None, args: tuple[str, ...]) -> SmokeResult:
    """Run `python bundle ARGS` (or `bundle ARGS` for an executable, `python` None) in a fresh
    home, cache and folder, offline where possible. Paths
    in ARGS that exist from here are made absolute (the run happens elsewhere). Raises
    CheckFailedError if it fails or doesn't finish."""
    here = _resolve_args(args)
    bundle_str = os.path.abspath(bundle)
    python_str = (
        os.path.abspath(python)
        if python
        and (os.sep in python or (os.altsep and os.altsep in python) or os.path.exists(python))
        else python
    )
    with tempfile.TemporaryDirectory(prefix="bundleup-smoke-", dir=_runnable(bundle)) as tmp:
        root = Path(tmp)
        try:
            for name in ("home", "cache", "work", "tmp"):
                (root / name).mkdir()
            env = {
                k: v for k, v in os.environ.items() if k not in DROPPED and not k.startswith("UV_")
            }
            env |= {
                "HOME": str(root / "home"),
                "USERPROFILE": str(root / "home"),
                "APPDATA": str(root / "home"),
                "BUNDLEUP_CACHE": str(root / "cache"),
                "XDG_CACHE_HOME": str(root / "cache"),
                "LOCALAPPDATA": str(root / "cache"),
                "SCIE_BASE": str(root / "nce"),  # an executable's interpreter unpacks here
                "TMPDIR": str(root / "tmp"),
                "TEMP": str(root / "tmp"),
                "TMP": str(root / "tmp"),
                "PYTHONNOUSERSITE": "1",
            }
            command = [python_str, bundle_str, *here] if python_str else [bundle_str, *here]
            wrapped, blocked = _offline(command)
            log = root / "output.log"
            started = time.perf_counter()
            with log.open("w+b") as out_file:
                proc = subprocess.Popen(
                    wrapped,
                    cwd=root / "work",
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=out_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=(os.name != "nt"),
                )
                try:
                    code = proc.wait(timeout=TIMEOUT)
                except subprocess.TimeoutExpired:
                    code = -1
                finally:
                    _kill_tree(proc)
            out = _text(log.read_bytes()) if log.exists() else ""
            result = SmokeResult(
                ["python", bundle.name, *args] if python else [f"./{bundle.name}", *args],
                code, time.perf_counter() - started, blocked,
                "\n".join(out.strip().splitlines()[-15:]),
            )  # fmt: skip
        finally:
            _make_writable(root)
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
                    hint="its output is above; --smoke 'ARGS' runs it with other arguments "
                    "(the default is --help)",
                    detail=result.output,
                )
            ],
        )
    return result


def _runnable(bundle: Path | None = None) -> str | None:
    """Where the fresh home and cache go: the temp folder, unless it's mounted noexec (a
    hardened host), where a bundle with compiled code can't run from its cache; then bundleup's
    build cache folder (eighth review: the cache is only where BUNDLEUP_CACHE says, ADR-0048)."""
    flag = getattr(os, "ST_NOEXEC", 0)
    try:
        if not flag or not os.statvfs(tempfile.gettempdir()).f_flag & flag:
            return None
    except OSError:
        return None
    from ._bytecode import cache_dir

    candidates = [cache_dir().parent / "smoke", *([bundle.parent] if bundle is not None else [])]
    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not (os.statvfs(folder).f_flag & flag):
                return str(folder)
        except OSError:
            continue
    return None


def _offline(command: list[str]) -> tuple[list[str], bool]:
    """The command with the network blocked, and whether that was possible here."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return ["sandbox-exec", "-p", SANDBOX, *command], True
    if sys.platform.startswith("linux") and shutil.which("unshare"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            probe = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=2)
            if probe.returncode == 0:  # unprivileged namespaces can be turned off
                return ["unshare", "-rn", *command], True
    return command, False


def _text(data: bytes | str | None) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data or ""
