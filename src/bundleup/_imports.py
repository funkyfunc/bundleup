"""What code imports, and what the standard library of each Python version has (fifth review).

A bundle can't see the machine's packages, so an import that neither the payload nor the
target's standard library satisfies fails at run time; and a pure-Python bundle that claims a
range of versions must not cover one whose standard library lacks a module it imports (`imp` is
gone in 3.12, `tomllib` arrived in 3.11).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Top-level standard-library modules added and removed in each release, from the "What's new"
# pages (checked 2026-10-08). Applied to the list of the Python bundleup runs on, they give any
# other version's.
ADDED: dict[tuple[int, int], set[str]] = {
    (3, 9): {"graphlib", "zoneinfo"},
    (3, 11): {"tomllib"},
    (3, 14): {"annotationlib", "compression"},
}
REMOVED: dict[tuple[int, int], set[str]] = {
    (3, 9): {"_dummy_thread", "dummy_threading"},
    (3, 10): {"formatter", "parser", "symbol"},
    (3, 11): {"binhex"},
    (3, 12): {"asynchat", "asyncore", "distutils", "imp", "smtpd"},
    (3, 13): {
        "aifc", "audioop", "cgi", "cgitb", "chunk", "crypt", "imghdr", "lib2to3", "mailcap",
        "msilib", "nis", "nntplib", "ossaudiodev", "pipes", "sndhdr", "spwd", "sunau", "telnetlib",
        "uu", "xdrlib",
    },
}  # fmt: skip
NEWEST = (3, 14)  # the newest version the tables describe


def stdlib(version: tuple[int, int]) -> set[str] | None:
    """The standard library's top-level modules on `version`; None when this Python can't tell
    (3.9 has no sys.stdlib_module_names)."""
    host = getattr(sys, "stdlib_module_names", None)
    if host is None:
        return None
    names = set(host)
    here = sys.version_info[:2]
    for minor in range(version[1] + 1, here[1] + 1):  # back from here: undo each release
        names = (names - ADDED.get((3, minor), set())) | REMOVED.get((3, minor), set())
    for minor in range(here[1] + 1, version[1] + 1):  # forward from here: apply each release
        names = (names | ADDED.get((3, minor), set())) - REMOVED.get((3, minor), set())
    return names


def stdlib_ever() -> set[str] | None:
    """Every module any version 3.9+ has had: an import of one isn't a third-party package."""
    names = stdlib(sys.version_info[:2])
    if names is None:
        return None
    return names.union(*ADDED.values(), *REMOVED.values())


# An `if` on these runs only somewhere (a platform, a Python version): its imports are optional.
CONDITIONAL = (
    "TYPE_CHECKING",
    "sys.platform",
    "platform.system",
    "platform.machine",
    "os.name",
    "sys.version_info",
)
OPTIONAL_ERRORS = {None, "ImportError", "ModuleNotFoundError", "Exception"}


def imports_in(tree: ast.AST) -> set[str]:
    """The top-level modules a module's code imports for sure: not relative imports, and not
    those guarded by `try/except ImportError` or an `if` on TYPE_CHECKING, the platform or the
    Python version."""
    names: set[str] = set()

    def visit(node: ast.AST, optional: bool) -> None:
        if isinstance(node, ast.Try):
            guarded = bool({_caught(h.type) for h in node.handlers} & OPTIONAL_ERRORS)
            for child in node.body:
                visit(child, optional or guarded)
            for child in [*node.handlers, *node.orelse, *node.finalbody]:
                visit(child, optional)
            return
        if isinstance(node, ast.If) and any(c in ast.unparse(node.test) for c in CONDITIONAL):
            for child in [*node.body, *node.orelse]:
                visit(child, True)
            return
        if not optional and isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif not optional and isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
        for child in ast.iter_child_nodes(node):
            visit(child, optional)

    visit(tree, False)
    return names


def imports_of(path: Path) -> set[str]:
    """What a file imports for sure; nothing if it doesn't parse (syntax-error reports that)."""
    try:
        return imports_in(ast.parse(path.read_text(encoding="utf-8")))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return set()


def _caught(node: ast.expr | None) -> str | None:
    """The exception a handler catches, by name (None: a bare `except:`)."""
    if node is None:
        return None
    if isinstance(node, ast.Tuple):
        names = [_caught(n) for n in node.elts]
        return next((n for n in names if n in ("ImportError", "ModuleNotFoundError")), "")
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def top_level_modules(folder: Path) -> set[str]:
    """What `import x` finds in a folder on sys.path: packages (folders, namespace ones too),
    modules and extension modules. Symlinks aren't followed."""
    names = set()
    for item in folder.iterdir() if folder.is_dir() else []:
        if item.is_dir() and not item.is_symlink():
            if not item.name.endswith((".dist-info", ".data")) and item.name.isidentifier():
                names.add(item.name)
        elif item.suffix in (".py", ".so", ".pyd") or ".cpython-" in item.name:
            names.add(item.name.split(".")[0])
    return names


def provided_by(site: Path) -> set[str]:
    """The modules a payload provides: its top level, the folders its .pth files add (pywin32's
    win32/, win32/lib), and `distutils` where setuptools' shim provides it on 3.12+."""
    names = top_level_modules(site)
    for pth in site.glob("*.pth"):
        for line in pth.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "import ", "import\t")):
                names |= top_level_modules(site / line)
    if (site / "_distutils_hack").is_dir():
        names.add("distutils")
    return names
