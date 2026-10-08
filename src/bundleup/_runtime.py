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


def identity() -> str:
    """Which interpreter this is: a child activates the bundle only if it's the same one
    (another venv, version or build of Python must not pick up the bundle's packages)."""
    return repr((sys.prefix, tuple(sys.version_info[:2]), getattr(sys, "abiflags", "")))


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
    if first == "-m":
        original = getattr(sys, "orig_argv", None)  # 3.10+: the full command line
        if original and "-m" in original[:-1]:
            top = original[original.index("-m") + 1].split(".")[0]
            return os.path.isdir(os.path.join(site, top)) or os.path.isfile(
                os.path.join(site, top + ".py")
            )
        return True  # 3.9 can't tell which module: assume the bundle's own (the common case)
    script = os.path.normcase(os.path.abspath(first))
    homes = [site] + [p for p in os.environ.get(ENV_SCRIPTS, "").split(os.pathsep) if p]
    return any(script.startswith(os.path.normcase(os.path.abspath(h)) + os.sep) for h in homes)


def site_packages_index() -> int:
    """Where a venv's site-packages would sit: after the standard library, before other packages."""
    for i, p in enumerate(sys.path):
        if p.endswith(("site-packages", "dist-packages")):
            return i
    return len(sys.path)


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def activate(site: str, pth: "Optional[Sequence[str]]" = None) -> None:
    """Put the payload on sys.path where a venv's site-packages would be, in place of the
    machine's own packages (unless BUNDLEUP_INHERIT_PATH=1), run its .pth files, and set up the
    environment so child processes of this same interpreter do the same (via the payload's
    sitecustomize.py on PYTHONPATH). Other Pythons the program starts ignore the bundle."""
    if any(_same(p, site) for p in sys.path if p):
        return  # already active (e.g. a multiprocessing child that got the parent's sys.path)
    # A bundle started from another bundle inherits the parent's environment: drop what the
    # parent added to sys.path and its shim from PYTHONPATH.
    parent = os.environ.get(ENV_SITE)
    parent_paths = [p for p in os.environ.get(ENV_PATHS, "").split(os.pathsep) if p]
    if parent and not _same(parent, site):
        sys.path[:] = [p for p in sys.path if p not in parent_paths]
    parent_shim = os.path.join(parent, SHIM) if parent else None
    shim = os.path.join(site, SHIM)
    pythonpath = [
        p
        for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if p and p != parent_shim and p != shim
    ]
    index = site_packages_index()
    if os.environ.get("BUNDLEUP_INHERIT_PATH", "").lower() not in ("1", "true", "yes"):
        # Isolation (ADR-0021): drop the machine's own packages (user and system site-packages,
        # and whatever their .pth files added), so nothing outside the bundle is imported by
        # accident.
        del sys.path[index:]
    sys.path.insert(index, site)
    if pth is None:  # a child process: the loader passes the list it got at build time
        pth = sorted(n for n in os.listdir(site) if n.endswith(".pth") and not n.startswith("."))
    added = []  # type: list[str]
    if pth:
        known = set(os.path.normcase(os.path.abspath(p)) for p in sys.path if p)
        before = len(sys.path)
        for name in pth:
            add_pth(site, name, known)
        added = sys.path[before:]
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
