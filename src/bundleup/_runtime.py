# bundleup runtime: puts a bundle's packages on sys.path (ADR-0010, ADR-0021, ADR-0023, ADR-0027).
#
# Copied into every .pyz payload as __bundleup__/_bundleup_runtime.py. The loader (__main__.py)
# calls activate() once the payload is unpacked; so does the payload's sitecustomize.py in child
# processes started with the bundle's own interpreter. Same constraints as the loader: any
# Python 3 must be able to compile it (no f-strings, `# type:` comments for variables), and it
# imports nothing beyond os and sys.
import os
import sys

TYPE_CHECKING = False  # the type checker treats this as True; at run time nothing is imported
if TYPE_CHECKING:
    from typing import Optional, Sequence

SHIM = "__bundleup__"  # in the payload: this module and the children's sitecustomize.py
# Internal: set by a running bundle for its children. A namespace of their own, so they never
# collide with the CLI's settings (BUNDLEUP_PYTHON is --python; second review, 2026-10-07).
ENV_SITE = "BUNDLEUP_RUNTIME_SITE"  # the active bundle's unpacked payload
ENV_PATHS = (
    "BUNDLEUP_RUNTIME_PATHS"  # everything activate() added to sys.path, os.pathsep-separated
)
ENV_PYTHON = "BUNDLEUP_RUNTIME_PYTHON"  # identity() of the bundle's interpreter
# `--entry python` (ADR-0040): the folder of the script it was given. Scripts under it are the
# bundle's code too, so a skill script that runs a sibling with sys.executable shares the bundle.
ENV_SCRIPTS = "BUNDLEUP_RUNTIME_SCRIPTS"
# `--external` (ADR-0051): the active bundle's `site` when it relies on host packages, so its own
# child processes keep the host's site-packages without leaking inheritance to another bundle.
ENV_INHERIT = "BUNDLEUP_RUNTIME_INHERIT"


def identity() -> str:
    """Which interpreter this is: a child activates the bundle only if it's the same one
    (another venv, version or build of Python must not pick up the bundle's packages)."""
    return repr((sys.prefix, tuple(sys.version_info[:2]), getattr(sys, "abiflags", "")))


STDLIB_RUNNERS = ("cProfile", "doctest", "pdb", "profile", "timeit", "trace", "unittest")


def _has_module(folder: str, top: str) -> bool:
    if os.path.isdir(os.path.join(folder, top)) or os.path.isfile(
        os.path.join(folder, top + ".py")
    ):
        return True
    try:
        entries = os.listdir(folder)
    except OSError:
        return False
    prefix = top + "."
    return any(n.startswith(prefix) and n.endswith((".so", ".pyd")) for n in entries)


def _under(path: str, home: str) -> bool:
    for fn in (os.path.abspath, os.path.realpath):
        p = os.path.normcase(fn(path))
        h = os.path.normcase(fn(home))
        prefix = h if h.endswith(os.sep) else h + os.sep
        if p.startswith(prefix):
            return True
    return False


_HOST_TAIL = None  # type: Optional[list[str]]


def _is_py_bundle(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(128)
        return b"# /// bundleup" in head
    except OSError:
        return False


def _orig_module(original: "Sequence[str]") -> "Optional[str]":
    for i, arg in enumerate(original[1:]):
        if arg == "--" or not arg.startswith("-"):
            break
        if arg == "-m" and i + 2 < len(original):
            return original[i + 2].split(".")[0]
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:].split(".")[0]
    return None


def runs_bundle_code(site: str) -> bool:
    """For a child process of the bundle's own interpreter: whether it runs the bundle's code
    (then it sees the bundle) or something else installed with that Python, such as a console
    script (then it's left alone: activating would hide that tool's own packages; third review,
    2026-10-07). sys.argv is already set when sitecustomize runs."""
    argv = getattr(sys, "argv", None) or [""]
    first = argv[0]
    if first in ("-c", "-", ""):
        # sys.executable -c ... (also multiprocessing's spawn and forkserver children), a program
        # on stdin (`python -`, or piped with no arguments) or a prompt: code the bundle's program
        # hands its own interpreter. (click's test suite runs `python -`; a console script, which
        # mustn't see the bundle, always has its path here.)
        return True
    scripts = [p for p in os.environ.get(ENV_SCRIPTS, "").split(os.pathsep) if p]
    if first == "-m":
        inherit_site = os.environ.get(ENV_INHERIT, "")
        if inherit_site and _same(inherit_site, site):
            return True
        original = getattr(sys, "orig_argv", None)  # 3.10+: the full command line
        top = _orig_module(original) if original else None
        if top is not None:
            if top in STDLIB_RUNNERS:
                return True
            paths = [p for p in os.environ.get(ENV_PATHS, "").split(os.pathsep) if p] or [site]
            return any(_has_module(d, top) for d in [*paths, *scripts])
        return True  # 3.9 can't tell which module: assume the bundle's own (the common case)
    if _under(first, site):
        return True
    if os.path.normcase(first).endswith(".py") and not _is_py_bundle(first):
        # A console script (no .py) or another bundleup .py bundle never counts as this bundle's.
        return any(_under(first, h) for h in scripts)
    return False


def _is_site_entry(p: str) -> bool:
    if not p:
        return False
    norm = os.path.normcase(os.path.abspath(p)).rstrip(os.sep)
    if norm.endswith(("site-packages", "dist-packages")):
        return True
    for marker in (os.sep + "site-packages" + os.sep, os.sep + "dist-packages" + os.sep):
        if marker in (norm + os.sep):
            return True
    return False


def _stdlib_end() -> int:
    stdlib_dir = os.path.normcase(os.path.abspath(os.path.dirname(os.__file__))).rstrip(os.sep)
    last = -1
    for i, p in enumerate(sys.path):
        if not p or _is_site_entry(p):
            continue
        norm = os.path.normcase(os.path.abspath(p)).rstrip(os.sep)
        if norm == stdlib_dir or norm.startswith(stdlib_dir + os.sep):
            last = i
    return last


def site_packages_index() -> int:
    """Where a venv's site-packages would sit: after the standard library, before other packages."""
    after = _stdlib_end()
    for i, p in enumerate(sys.path):
        if i > after and _is_site_entry(p):
            return i
    return len(sys.path)


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(
        os.path.abspath(b)
    ) or os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def activate(site: str, pth: "Optional[Sequence[str]]" = None) -> None:
    """Put the payload on sys.path where a venv's site-packages would be, in place of the
    machine's own packages (unless BUNDLEUP_INHERIT_PATH=1 or the bundle was built with
    --external), run its .pth files, and set up the environment so child processes of this same
    interpreter do the same (via the payload's sitecustomize.py on PYTHONPATH). Other Pythons the
    program starts ignore the bundle."""
    global _HOST_TAIL
    if any(_same(p, site) for p in sys.path if p):
        return  # already active (e.g. a multiprocessing child that got the parent's sys.path)
    # A bundle started from another bundle inherits the parent's environment: drop what the
    # parent added to sys.path and its shim from PYTHONPATH.
    parent = os.environ.get(ENV_SITE)
    parent_paths = [p for p in os.environ.get(ENV_PATHS, "").split(os.pathsep) if p]
    if parent and not _same(parent, site):
        sys.path[:] = [p for p in sys.path if p not in parent_paths]
        for mod_name, mod in list(sys.modules.items()):
            mod_file = getattr(mod, "__file__", None)
            if isinstance(mod_file, str) and _under(mod_file, parent):
                sys.modules.pop(mod_name, None)
        os.environ.pop(ENV_SCRIPTS, None)
        if not (os.environ.get(ENV_INHERIT) and _same(os.environ.get(ENV_INHERIT, ""), site)):
            os.environ.pop(ENV_INHERIT, None)
    parent_shim = os.path.join(parent, SHIM) if parent else None
    shim = os.path.join(site, SHIM)
    after = _stdlib_end()
    early_site = [p for i, p in enumerate(sys.path) if i < after and _is_site_entry(p)]
    if early_site:
        sys.path[:] = [p for i, p in enumerate(sys.path) if not (i < after and _is_site_entry(p))]
    raw_inherit = os.environ.get("BUNDLEUP_INHERIT_PATH", "").lower()
    if raw_inherit in ("0", "false", "no"):
        inherit = False
    else:
        inherit_site = os.environ.get(ENV_INHERIT, "")
        inherit = raw_inherit in ("1", "true", "yes") or (
            bool(inherit_site) and _same(inherit_site, site)
        )
    pythonpath = [
        p
        for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if p and p != parent_shim and p != shim and (not _is_site_entry(p) or inherit)
    ]
    index = site_packages_index()
    if _HOST_TAIL is None:
        _HOST_TAIL = list(early_site + sys.path[index:])
    # Isolation (ADR-0021): drop the machine's own packages (user and system site-packages, and
    # whatever their .pth files added) unless inheriting; when inheriting, re-append them after
    # the bundle's own .pth directories so the bundle always comes first.
    current_tail = early_site + sys.path[index:]
    tail = (current_tail or list(_HOST_TAIL or ())) if inherit else []
    del sys.path[index:]
    sys.path.append(site)
    if pth is None:  # a child process: the loader passes the list it got at build time
        pth = sorted(n for n in os.listdir(site) if n.endswith(".pth") and not n.startswith("."))
    known = set(os.path.normcase(os.path.abspath(p)) for p in sys.path if p)
    for name in pth or ():
        add_pth(site, name, known)
    added = sys.path[index + 1 :]
    for p in tail:
        norm = os.path.normcase(os.path.abspath(p)) if p else ""
        if not norm or norm not in known:
            sys.path.append(p)
            if norm:
                known.add(norm)
    # Children see the bundle through the shim (ADR-0027), never through the payload itself.
    os.environ["PYTHONPATH"] = os.pathsep.join([shim, *pythonpath])
    os.environ[ENV_SITE] = site
    os.environ[ENV_PATHS] = os.pathsep.join([site, *added])
    os.environ[ENV_PYTHON] = identity()


def add_pth(sitedir: str, name: str, known: "set[str]") -> None:
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
                sys.stderr.write("bundleup: error in %s line %d: %r\n" % (name, number, e))
                return
            continue
        path = os.path.normcase(os.path.abspath(os.path.join(sitedir, line.rstrip())))
        if path not in known and os.path.exists(path):
            sys.path.append(path)
            known.add(path)
