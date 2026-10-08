# bundleup loader: the __main__.py of every bundle (docs/adr/0010-bundle-format-and-loader.md).
#
# Runs on the user's Python, before anything else in the bundle. It checks the Python version
# and platform, makes sure the payload is extracted to a cache, puts it on sys.path, then starts
# the app. The calls at the bottom are the program; `bundleup verify` imports the functions to find
# a bundle's cache the same way.
#
# Constraints that make this file look different from the rest of the codebase:
# - The warm path (already extracted) must stay a handful of stat calls: no imports beyond os and
#   sys, so os.path instead of pathlib, and no `typing` at run time (it costs 4-7 ms).
#   Annotations are quoted and the typing names are imported only for the type checker.
# - Any Python 3 must be able to compile it far enough to print the version message: no
#   f-strings, no `from __future__` imports, and variable types as `# type:` comments (variable
#   annotations need 3.6).
import os
import sys

TYPE_CHECKING = False  # the type checker treats this as True; at run time nothing is imported
if TYPE_CHECKING:
    import zipfile
    from typing import Any, BinaryIO, NoReturn

# --- config: replaced at build time ---
NAME = "app"
DIRNAME = "app-0000000000000000"
PYTHON = (3, 12)  # the oldest Python minor version it runs on
PYTHON_MAX = (3, 12)  # type: tuple[int, int] | None  # the newest; None: no limit (ADR-0030)
PLATFORM = "darwin"  # type: str | None  # None: any OS (a pure bundle, ADR-0034)
MACHINE = None  # type: str | None  # set when the bundle contains native code
ABIFLAGS = None  # type: str | None  # set when the bundle contains native code (POSIX only)
TARGET = "Python 3.12 on macOS"
# ("call", module, attr) | ("module", module, "") | ("script", path inside the payload, "")
# | ("python", "", ""): the bundle runs whatever it's given, as python does (`--entry python`)
ENTRY = ("call", "app", "main")
PTH = []  # type: list[str]  # .pth files at the payload's top level, in the order site.py reads them
# What the native wheels need (ADR-0029): ("glibc", (2, 28)) or ("musl", (1, 2)); macOS (11, 0).
LIBC = None  # type: tuple[str, tuple[int, int]] | None
MACOS = None  # type: tuple[int, int] | None
# The payload's zips inside the bundle, unpacked in order into one directory. Several when the
# bundle is for several platforms: each file is stored once, in a layer shared by the payloads
# that have it (ADR-0038).
MEMBERS = ["payload.zip"]
# A bundle for several platforms (ADR-0038): one dict per payload with the settings above in
# lower case ("members", "dirname", "python", ...); the first that fits this machine is used.
PAYLOADS = []  # type: list[dict[str, Any]]
# --- end config ---

_ARCHIVE = os.path.dirname(os.path.abspath(__file__))


def _fail(message: str) -> "NoReturn":
    sys.stderr.write("%s: %s\n" % (NAME, message))
    sys.exit(1)


RERUN = "BUNDLEUP_RUNTIME_RERUN"  # set while re-running with another Python, so it happens once
NEWEST_KNOWN = 20  # minor versions tried for an open-ended range, newest first


def _rerun_with_another_python(here: "tuple[int, int]") -> None:
    """The wrong Python started the bundle (`./app.pyz` runs whatever `python3` is): run it again
    with one the bundle allows, if one is on PATH, newest first (ADR-0036). Windows has no
    `python3.X` commands; its `py` launcher picks a version with `-3.X`."""
    top = PYTHON_MAX[1] if PYTHON_MAX else NEWEST_KNOWN
    allowed = VERSIONS or [(3, minor) for minor in range(PYTHON[1], top + 1)]
    wanted = sorted({v for v in allowed if v != here}, reverse=True)
    folders = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    for version in wanted:
        if sys.platform == "win32":
            names = ["python%d.%d.exe" % version]
        else:
            names = ["python%d.%d" % version]
        for folder in folders:
            for name in names:
                exe = os.path.join(folder, name)
                if os.path.isfile(exe) and os.access(exe, os.X_OK):
                    _rerun([exe, sys.argv[0], *sys.argv[1:]])
    if sys.platform == "win32":
        launcher = [os.path.join(d, "py.exe") for d in folders]
        found = [p for p in launcher if os.path.isfile(p)]
        if found:
            for version in wanted:
                probe = [found[0], "-%d.%d" % version, "-c", ""]
                import subprocess  # only on this rare path

                if subprocess.call(probe, stderr=subprocess.DEVNULL) == 0:
                    _rerun([found[0], "-%d.%d" % version, sys.argv[0], *sys.argv[1:]])


def _rerun(command: "list[str]") -> "NoReturn":
    os.environ[RERUN] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":  # os.execv doesn't quote arguments on Windows
        import subprocess

        sys.exit(subprocess.call(command))
    os.execv(command[0], command)


def _machine() -> str:
    """The CPU this interpreter runs as (what its compiled modules must match). On Windows, from
    the interpreter's own build string: the environment describes the OS, and a 32-bit Python on
    64-bit Windows would read as AMD64 (third review)."""
    if sys.platform == "win32":
        if "(ARM64)" in sys.version:
            return "ARM64"
        if "(AMD64)" in sys.version:
            return "AMD64"
        if "32 bit" in sys.version:
            return "x86"
        return os.environ.get("PROCESSOR_ARCHITECTURE", "")
    return os.uname().machine


def _check() -> None:
    rerun = os.environ.pop(RERUN, None)  # never left for the app's own children
    here = sys.version_info[:2]
    if here < PYTHON or (PYTHON_MAX is not None and here > PYTHON_MAX):
        want = "%d.%d" % PYTHON
        if PYTHON_MAX is None:
            wanted = "Python %s or newer" % want
        elif PYTHON_MAX == PYTHON:
            wanted = "Python %s" % want
        else:
            wanted = "Python %s to %d.%d" % (want, PYTHON_MAX[0], PYTHON_MAX[1])
        if not rerun:  # once only: then report the mismatch instead of looping
            _rerun_with_another_python(here)
        nearest = PYTHON if here < PYTHON or PYTHON_MAX is None else PYTHON_MAX
        suggest = "%d.%d" % nearest
        _fail(
            "this app was bundled for %s, but it's running on Python %d.%d (%s).\n"
            "Run it with Python %s instead, for example: python%s %s"
            % (
                wanted,
                here[0],
                here[1],
                sys.executable,
                suggest,
                suggest,
                os.path.basename(_ARCHIVE),
            )
        )
    # Only refuse a CPU that is known to differ: Windows reports it through an environment
    # variable, which a stripped-down environment may lack.
    machine = _machine() if MACHINE else ""
    if (PLATFORM and sys.platform != PLATFORM) or (machine and machine != MACHINE):
        names = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}
        _fail(
            "this app was bundled for %s, but this machine is %s %s."
            % (TARGET, names.get(sys.platform, sys.platform), _machine())
        )
    _check_system()
    if MACHINE and (
        sys.implementation.name != "cpython" or getattr(sys, "abiflags", None) != ABIFLAGS
    ):
        _fail(
            "this app was bundled for %s (CPython), but it's running on %s %s."
            % (TARGET, sys.implementation.name, sys.version.split()[0])
        )


def _libc() -> "tuple[str, tuple[int, int] | None] | None":
    """This Linux machine's C library and version, without importing anything (`platform` costs
    milliseconds): glibc reports itself through confstr, musl has its dynamic loader in /lib."""
    try:
        found = os.confstr("CS_GNU_LIBC_VERSION")  # "glibc 2.35"
    except (AttributeError, ValueError, OSError):
        found = None
    if found and found.startswith("glibc "):
        parts = found.split()[1].split(".")
        try:
            return ("glibc", (int(parts[0]), int(parts[1])))
        except (IndexError, ValueError):
            return ("glibc", None)
    if any(name.startswith("ld-musl-") for name in _listdir("/lib")):
        return ("musl", None)  # musl has no cheap way to report its version
    return None


def _listdir(path: str) -> "list[str]":
    try:
        return os.listdir(path)
    except OSError:
        return []


def _macos() -> "tuple[int, int] | None":
    """The macOS version, from the Darwin kernel's: Darwin 19 is 10.15, 20-24 are 11-15, and from
    25 Apple numbers macOS by year (Darwin 25 is macOS 26; the third review found 16)."""
    try:
        darwin = int(os.uname().release.split(".")[0])
    except (AttributeError, ValueError):
        return None
    if darwin >= 25:
        return (darwin + 1, 0)
    return (darwin - 9, 0) if darwin >= 20 else (10, darwin - 4)


def _libc_fits(libc: "tuple[str, tuple[int, int]] | None") -> bool:
    if not libc or not sys.platform.startswith("linux"):
        return True
    kind, need = libc
    have = _libc()
    return not (have and (have[0] != kind or (have[1] and tuple(have[1]) < tuple(need))))


def _macos_fits(macos: "tuple[int, int] | None") -> bool:
    if not macos or sys.platform != "darwin":
        return True
    have = _macos()
    return not (have and have < tuple(macos))


def _fits(payload: "dict[str, Any]") -> bool:
    """Whether a payload of a multi-platform bundle can run here, apart from the Python version:
    OS, CPU, interpreter build, C library, macOS version (the same checks as _check)."""
    if payload["platform"] and sys.platform != payload["platform"]:
        return False
    machine = payload["machine"]
    if machine and _machine() and _machine() != machine:
        return False
    if machine and (
        sys.implementation.name != "cpython"
        or getattr(sys, "abiflags", None) != payload["abiflags"]
    ):
        return False
    return _libc_fits(payload["libc"]) and _macos_fits(payload["macos"])


def _in_range(payload: "dict[str, Any]", here: "tuple[int, int]") -> bool:
    low, high = tuple(payload["python"]), payload["python_max"]
    return low <= here and (high is None or here <= tuple(high))


VERSIONS = []  # type: list[tuple[int, int]]  # every version the fitting payloads allow (for re-runs)


def _select() -> None:
    """Pick this machine's payload of a multi-platform bundle and use its settings. A payload for
    this platform but another Python version still gets picked, so _check explains (or re-runs
    with a matching Python); nothing for this platform at all is reported here."""
    global DIRNAME, PYTHON, PYTHON_MAX, PLATFORM, MACHINE, ABIFLAGS, TARGET, PTH, LIBC, MACOS
    global MEMBERS
    if not PAYLOADS:
        return
    here = sys.version_info[:2]
    fitting = [p for p in PAYLOADS if _fits(p)]
    if not fitting:
        names = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}
        _fail(
            "this app was bundled for %s, but this machine is %s %s."
            % (
                "; ".join(p["target"] for p in PAYLOADS),
                names.get(sys.platform, sys.platform),
                _machine(),
            )
        )
    chosen = next((p for p in fitting if _in_range(p, here)), fitting[0])
    for p in fitting:
        top = p["python_max"][1] if p["python_max"] else NEWEST_KNOWN
        VERSIONS.extend((3, m) for m in range(p["python"][1], top + 1))
    DIRNAME, MEMBERS, TARGET, PTH = (
        chosen["dirname"],
        chosen["members"],
        chosen["target"],
        chosen["pth"],
    )
    PYTHON = tuple(chosen["python"])
    PYTHON_MAX = tuple(chosen["python_max"]) if chosen["python_max"] else None
    PLATFORM, MACHINE, ABIFLAGS = chosen["platform"], chosen["machine"], chosen["abiflags"]
    LIBC, MACOS = chosen["libc"], chosen["macos"]


def _check_system() -> None:
    """The C library and macOS version the native wheels were built for (ADR-0029)."""
    if LIBC and sys.platform.startswith("linux"):
        kind, need = LIBC
        have = _libc()
        if have and (have[0] != kind or (have[1] and have[1] < need)):
            version = "%s %d.%d" % (have[0], have[1][0], have[1][1]) if have[1] else have[0]
            _fail(
                "this app was bundled for Linux with %s %d.%d or newer, but this machine has %s.\n"
                "Rebuild it for this machine's platform (bundleup build --python-platform ...)."
                % (kind, need[0], need[1], version)
            )
    if MACOS and sys.platform == "darwin":
        have = _macos()
        if have and have < MACOS:
            _fail(
                "this app needs macOS %d.%d or newer; this Mac runs macOS %d.%d."
                % (MACOS[0], MACOS[1], have[0], have[1])
            )


def _roots(archive: str) -> "list[tuple[str, bool]]":
    """Cache directories to try for `archive`, best first, each with whether it's shared with
    other users.

    Never the working directory.
    """
    roots = []
    explicit = os.environ.get("BUNDLEUP_CACHE")
    if explicit:
        roots.append((os.path.abspath(explicit), False))
    home = os.path.expanduser("~")
    user_cache = None
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        user_cache = base and os.path.join(base, "bundleup", "Cache")
    elif sys.platform == "darwin":
        user_cache = home != "~" and os.path.join(home, "Library", "Caches", "bundleup")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or (home != "~" and os.path.join(home, ".cache"))
        user_cache = base and os.path.join(base, "bundleup")
    if user_cache:
        roots.append((user_cache, False))
    tmp = os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP")
    if not tmp and os.name == "posix":
        tmp = "/tmp"
    if tmp:
        uid = os.getuid() if hasattr(os, "getuid") else 0
        roots.append((os.path.join(os.path.abspath(tmp), "bundleup-%d" % uid), True))
    # Next to the bundle: the bundle's directory may be shared (/tmp, a team drive), so this root
    # is trusted only if we own it and nobody else can write to it, like the temp root (a copy
    # planted there would otherwise run as us; second review, 2026-10-07).
    roots.append((os.path.join(os.path.dirname(archive), ".bundleup"), True))
    return roots


def _private(root: str) -> bool:
    """A shared root (the temp one, or the one next to the bundle) is only trusted if we own it
    and nobody else can write to it."""
    if not hasattr(os, "getuid"):
        return True
    try:
        st = os.lstat(root)
    except OSError:
        return False
    return st.st_uid == os.getuid() and not st.st_mode & 0o022 and os.path.isdir(root)


def _find() -> "str | None":
    for root, shared in _roots(_ARCHIVE):
        path = os.path.join(root, DIRNAME)
        try:
            found = os.stat(path)
        except OSError:
            continue
        is_dir = found.st_mode & 0o170000 == 0o040000
        if is_dir and (not shared or _private(root)):
            _mark_used(path, found.st_mtime)
            return path
    return None


USED_EVERY = 86400.0  # seconds: how often a running bundle refreshes its "last used" time


def _mark_used(path: str, mtime: float) -> None:
    """Record that this unpacked copy is in use, for `bundleup cache clean` (ADR-0022): bump the
    directory's timestamp, at most once a day, so warm starts almost never write anything."""
    import time

    if time.time() - mtime > USED_EVERY:
        try:  # noqa: SIM105 (contextlib.suppress would add an import to the loader)
            os.utime(path)
        except OSError:
            pass  # a read-only cache: it just won't look recently used


class _Window(object):
    """A read-only view of part of a file, so zipfile can read the payload in place."""

    def __init__(self, f: "BinaryIO", start: int, size: int) -> None:
        self.f, self.start, self.size, self.pos = f, start, size, 0

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = (
            offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        )
        return self.pos

    def read(self, n: "int | None" = -1) -> bytes:
        if n is None or n < 0 or n > self.size - self.pos:
            n = max(0, self.size - self.pos)
        self.f.seek(self.start + self.pos)
        data = self.f.read(n)
        self.pos += len(data)
        return data


def _pyc_path(member: str, final: str) -> "str | None":
    """Where this Python looks for a precompiled member, if not next to the source.

    With sys.pycache_prefix set (macOS's /usr/bin/python3 sets it to
    ~/Library/Caches/com.apple.python), Python ignores __pycache__ directories, so the bundle's
    .pyc files go under the prefix instead.
    """
    prefix = getattr(sys, "pycache_prefix", None)
    if not prefix or "/__pycache__/" not in member:
        return None
    head, _, name = member.rpartition("/__pycache__/")
    return os.path.join(prefix, os.path.splitdrive(final)[1].lstrip("\\/"), head, name)


def _unpack(dest: str, final: str) -> None:
    import zipfile

    with open(_ARCHIVE, "rb") as f:
        outer = zipfile.ZipFile(f)
        infos = [outer.getinfo(name) for name in MEMBERS]
        made = set()  # type: set[str]
        for info in infos:
            f.seek(info.header_offset)
            header = f.read(30)
            if header[:4] != b"PK\x03\x04":
                raise OSError("corrupt bundle: bad payload header")
            start = (
                info.header_offset
                + 30
                + int.from_bytes(header[26:28], "little")
                + int.from_bytes(header[28:30], "little")
            )
            _unpack_zip(zipfile.ZipFile(_Window(f, start, info.file_size)), dest, final, made)


def _unpack_zip(payload: "zipfile.ZipFile", dest: str, final: str, made: "set[str]") -> None:
    for member in payload.infolist():
        path = os.path.join(dest, member.filename)
        elsewhere = _pyc_path(member.filename, final)
        if elsewhere:
            # Shared with other processes, unlike our private temp tree: write, then replace.
            part = "%s.%d.tmp" % (elsewhere, os.getpid())
            try:
                _write(payload, member, part, made)
                os.replace(part, elsewhere)
                continue
            except OSError:
                pass  # prefix not writable: keep it in __pycache__, where it's harmless
        _write(payload, member, path, made)
        if (member.external_attr >> 16) & 0o111:
            os.chmod(path, 0o755)


def _write(
    payload: "zipfile.ZipFile", member: "zipfile.ZipInfo", path: str, made: "set[str]"
) -> None:
    parent = os.path.dirname(path)
    if parent not in made:
        os.makedirs(parent, exist_ok=True)
        made.add(parent)
    with payload.open(member) as src, open(path, "wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


LOCK_TIMEOUT = 120.0  # seconds to wait for another process's unpack before doing our own


def _lock(root: str) -> "BinaryIO | None":
    """Wait for, then hold, this bundle's unpack lock in `root`, so that simultaneous first runs
    (say, 1,000 cluster jobs) unpack once instead of each writing a full copy.

    Best effort: if locking isn't possible, or takes longer than LOCK_TIMEOUT, carry on without
    it; the atomic rename in _extract() is what keeps results correct. The operating system
    releases the lock if its holder dies.
    """
    import time

    try:
        # Returned open on purpose: the open file is the lock, released by closing it.
        handle = open(os.path.join(root, ".lock-" + DIRNAME), "a+b")  # noqa: SIM115
    except OSError:
        return None
    deadline = time.time() + LOCK_TIMEOUT
    while True:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if time.time() > deadline:
                handle.close()
                return None
            time.sleep(0.05)


def _extract() -> str:
    """Extract into a temporary directory, then rename it into place atomically.

    If another process wins the race, its copy is used and ours is thrown away.
    """
    problems = []  # type: list[str]
    for root, shared in _roots(_ARCHIVE):
        final = os.path.join(root, DIRNAME)
        tmp = os.path.join(root, ".tmp-%s-%d-%s" % (DIRNAME, os.getpid(), os.urandom(4).hex()))
        try:
            os.makedirs(root, mode=0o700, exist_ok=True)
            if shared and not _private(root):
                raise OSError("not private to this user")
            if os.path.isdir(final):
                return final
            lock = _lock(root)
            try:
                if os.path.isdir(final):  # another process unpacked it while we waited
                    return final
                _unpack(tmp, final)
                try:
                    os.rename(tmp, final)
                except OSError:
                    if not os.path.isdir(final):
                        raise
                    import shutil

                    shutil.rmtree(tmp, ignore_errors=True)
            finally:
                if lock is not None:
                    lock.close()  # releases the lock
            return final
        except OSError as e:
            problems.append("  %s: %s" % (root, e.strerror or e))
            if os.path.isdir(tmp):
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
    _fail(
        "couldn't unpack into any cache directory:\n%s\nSet BUNDLEUP_CACHE to a writable directory."
        % "\n".join(problems)
    )


def _activate(site: str) -> None:
    """Put the payload on sys.path (where a venv's site-packages would be) and set up child
    processes: the payload's own runtime module does both (ADR-0027), so the loader and the
    children's sitecustomize.py share one implementation."""
    if sys.path and sys.path[0] and os.path.abspath(sys.path[0]) == _ARCHIVE:
        del sys.path[0]
    sys.path.insert(0, os.path.join(site, "__bundleup__"))
    try:
        runtime = __import__("_bundleup_runtime")  # type: Any
    finally:
        del sys.path[0]
    runtime.activate(site, PTH)


def _run(site: str) -> None:
    kind, target, attr = ENTRY
    if kind == "call":
        __import__(target)
        # An attribute walk: the type is only known at run time.
        obj = sys.modules[target]  # type: Any
        for part in attr.split("."):
            obj = getattr(obj, part)
        sys.exit(obj())
    if kind == "python":
        _run_python()
        return
    import runpy

    if kind == "module":
        runpy.run_module(target, run_name="__main__", alter_sys=True)
    else:
        runpy.run_path(os.path.join(site, target), run_name="__main__")


PYTHON_USAGE = "usage: python %s [SCRIPT.py | -m MODULE | -c CODE] [ARGS...]"


def _run_python() -> None:
    """`--entry python`: the bundle is a Python with its packages, so plain scripts beside it
    (a skill's, say) run with them: `app.pyz tool.py ARGS`, `-m module`, `-c code`, or a
    prompt."""
    import runpy

    args = sys.argv[1:]
    if not args:
        import code

        code.interact(banner="Python %s with %s's packages" % (sys.version.split()[0], NAME))
        return
    if args[0] in ("-m", "-c"):
        if len(args) < 2:
            _fail("%s needs an argument\n%s" % (args[0], PYTHON_USAGE % NAME))
        if args[0] == "-m":
            sys.argv = args[1:]
            runpy.run_module(args[1], run_name="__main__", alter_sys=True)
            return
        sys.argv = ["-c", *args[2:]]
        sys.path.insert(0, "")  # as python -c does: the working directory
        exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})
        return
    if args[0].startswith("-"):
        _fail("unknown option %s\n%s" % (args[0], PYTHON_USAGE % NAME))
    sys.argv = args
    # As python does for a script: its directory comes first, so its own modules import.
    sys.path.insert(0, os.path.dirname(os.path.abspath(args[0])))
    runpy.run_path(args[0], run_name="__main__")


_IN_USE = []  # type: list[BinaryIO]  # held open for the process's life (see _hold)


def _hold(site: str) -> None:
    """Mark this unpacked copy in use while the program runs: a shared lock on its lock file,
    which `bundleup cache clean` can't take, so it never deletes files a running program needs
    (third review). POSIX only, best effort, a few microseconds."""
    if os.name == "nt":
        return
    try:
        import fcntl

        handle = open(os.path.join(os.path.dirname(site), ".lock-" + DIRNAME), "a+b")  # noqa: SIM115
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
    except (OSError, ImportError):
        return  # a read-only cache, or locks unsupported: nothing to protect it from
    _IN_USE.append(handle)


if __name__ == "__main__":
    _select()
    _check()
    _site = _find() or _extract()
    _hold(_site)
    _activate(_site)
    _run(_site)
