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
    from typing import Any, BinaryIO, NoReturn  # noqa: F401 (Any is used in a type comment)

# --- config: replaced at build time ---
NAME = "app"
DIRNAME = "app-0000000000000000"
PYTHON = (3, 12)
PLATFORM = "darwin"
MACHINE = None  # type: str | None  # set when the bundle contains native code
ABIFLAGS = None  # type: str | None  # set when the bundle contains native code (POSIX only)
TARGET = "Python 3.12 on macOS"
# ("call", module, attr) | ("module", module, "") | ("script", path inside the payload, "")
ENTRY = ("call", "app", "main")
PTH = []  # type: list[str]  # .pth files at the payload's top level, in the order site.py reads them
# --- end config ---

_ARCHIVE = os.path.dirname(os.path.abspath(__file__))


def _fail(message: str) -> "NoReturn":
    sys.stderr.write("%s: %s\n" % (NAME, message))
    sys.exit(1)


def _machine() -> str:
    if sys.platform == "win32":
        return os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get(
            "PROCESSOR_ARCHITECTURE", ""
        )
    return os.uname().machine


def _check() -> None:
    here = sys.version_info[:2]
    if here != PYTHON:
        want = "%d.%d" % PYTHON
        _fail(
            "this app was bundled for Python %s, but it's running on Python %d.%d (%s).\n"
            "Run it with Python %s instead, for example: python%s %s"
            % (want, here[0], here[1], sys.executable, want, want, os.path.basename(_ARCHIVE))
        )
    # Only refuse a CPU that is known to differ: Windows reports it through an environment
    # variable, which a stripped-down environment may lack.
    machine = _machine() if MACHINE else ""
    if sys.platform != PLATFORM or (machine and machine != MACHINE):
        names = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}
        _fail(
            "this app was bundled for %s, but this machine is %s %s."
            % (TARGET, names.get(sys.platform, sys.platform), _machine())
        )
    if MACHINE and (
        sys.implementation.name != "cpython" or getattr(sys, "abiflags", None) != ABIFLAGS
    ):
        _fail(
            "this app was bundled for %s (CPython), but it's running on %s %s."
            % (TARGET, sys.implementation.name, sys.version.split()[0])
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
    roots.append((os.path.join(os.path.dirname(archive), ".bundleup"), False))
    return roots


def _private(root: str) -> bool:
    """A shared temp directory is only trusted if we own it and nobody else can write to it."""
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
        info = zipfile.ZipFile(f).getinfo("payload.zip")
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
        payload = zipfile.ZipFile(_Window(f, start, info.file_size))
        made = set()  # type: set[str]
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


def _site_packages_index() -> int:
    """Where a venv's site-packages would sit: after the standard library, before other packages."""
    for i, p in enumerate(sys.path):
        if p.endswith(("site-packages", "dist-packages")):
            return i
    return len(sys.path)


def _activate(site: str) -> None:
    """Put the payload on sys.path where a venv's site-packages would be, in place of the
    machine's own packages (unless BUNDLEUP_INHERIT_PATH=1), and on PYTHONPATH so child
    interpreters (sys.executable -c/-m, multiprocessing) see the same packages."""
    if sys.path and sys.path[0] and os.path.abspath(sys.path[0]) == _ARCHIVE:
        del sys.path[0]
    # A bundle started from another bundle inherits the parent's PYTHONPATH: drop its packages.
    parent = os.environ.get("BUNDLEUP_SITE")
    pythonpath = [
        p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and p != parent
    ]
    if parent and parent != site:
        sys.path[:] = [p for p in sys.path if p != parent]
    index = _site_packages_index()
    if os.environ.get("BUNDLEUP_INHERIT_PATH", "").lower() not in ("1", "true", "yes"):
        # Isolation (ADR-0021): drop the machine's own packages (user and system site-packages,
        # and whatever their .pth files added), so nothing outside the bundle is imported by
        # accident. Children still see them: PYTHONPATH can only add to a path.
        del sys.path[index:]
    sys.path.insert(index, site)
    added = []  # type: list[str]
    if PTH:
        known = set(os.path.normcase(os.path.abspath(p)) for p in sys.path if p)
        before = len(sys.path)
        for name in PTH:
            _add_pth(site, name, known)
        added = sys.path[before:]
    # Children get the directories .pth files added, but their `import` lines don't run there.
    ours = [site, *added]
    os.environ["PYTHONPATH"] = os.pathsep.join(ours + [p for p in pythonpath if p not in ours])
    os.environ["BUNDLEUP_SITE"] = site


def _add_pth(sitedir: str, name: str, known: "set[str]") -> None:
    """Process one of the payload's .pth files as site.py would in a venv's site-packages: a line
    starting with "import" runs, any other line is a directory to append to sys.path if it exists.
    Examples: setuptools' distutils shim, pywin32's directories (gauntlet 23). The parameter keeps
    site.py's name `sitedir`, since some .pth lines read it from their caller's frame."""
    try:
        with open(os.path.join(sitedir, name), encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith(("import ", "import\t")):
            try:
                exec(line)  # what site.py does with these lines
            except Exception as e:  # as site.py: report it and skip the rest of the file
                sys.stderr.write("%s: error in %s line %d: %r\n" % (NAME, name, number, e))
                return
            continue
        path = os.path.normcase(os.path.abspath(os.path.join(sitedir, line.rstrip())))
        if path not in known and os.path.exists(path):
            sys.path.append(path)
            known.add(path)


def _run(site: str) -> None:
    kind, target, attr = ENTRY
    if kind == "call":
        __import__(target)
        # An attribute walk: the type is only known at run time.
        obj = sys.modules[target]  # type: Any
        for part in attr.split("."):
            obj = getattr(obj, part)
        sys.exit(obj())
    import runpy

    if kind == "module":
        runpy.run_module(target, run_name="__main__", alter_sys=True)
    else:
        runpy.run_path(os.path.join(site, target), run_name="__main__")


if __name__ == "__main__":
    _check()
    _site = _find() or _extract()
    _activate(_site)
    _run(_site)
