"""What code imports, and what the standard library of each Python version has (fifth review).

A bundle can't see the machine's packages, so an import that neither the payload nor the
target's standard library satisfies fails at run time; and a pure-Python bundle that claims a
range of versions must not cover one whose standard library lacks a module it imports (`imp` is
gone in 3.12, `tomllib` arrived in 3.11).
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Sequence
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

# Common PyPI distribution names whose top-level import name differs from the package name, used
# when `--external PKG` tells `check` that the host environment provides `PKG` (ADR-0051).
EXTERNAL_ALIASES: dict[str, set[str]] = {
    "attrs": {"attr", "attrs"},
    "beautifulsoup4": {"bs4"},
    "gitpython": {"git"},
    "msgpack-python": {"msgpack"},
    "opencv-contrib-python": {"cv2"},
    "opencv-python": {"cv2"},
    "opencv-python-headless": {"cv2"},
    "pillow": {"PIL"},
    "protobuf": {"google"},
    "psycopg2-binary": {"psycopg2"},
    "pycryptodome": {"Crypto"},
    "pycryptodomex": {"Cryptodome"},
    "pyjwt": {"jwt"},
    "pymysql": {"pymysql"},
    "pynacl": {"nacl"},
    "pyopenssl": {"OpenSSL"},
    "pyserial": {"serial"},
    "python-dateutil": {"dateutil"},
    "python-dotenv": {"dotenv"},
    "python-Levenshtein": {"Levenshtein"},
    "python-pptx": {"pptx"},
    "python-docx": {"docx"},
    "pyusb": {"usb"},
    "pyyaml": {"yaml"},
    "pyzmq": {"zmq"},
    "ruamel-yaml": {"ruamel"},
    "scikit-bio": {"skbio"},
    "scikit-image": {"skimage"},
    "scikit-learn": {"sklearn"},
}


NAMESPACE_PREFIXES = (
    "azure",
    "backports",
    "google",
    "jaraco",
    "mpl-toolkits",
    "opentelemetry",
    "repoze",
    "ruamel",
    "sphinxcontrib",
    "zope",
)


def external_modules(external: Sequence[str]) -> set[str]:
    """Top-level module names that `--external` distributions provide on the host."""
    import importlib.metadata

    names: set[str] = set()
    for raw in external:
        pkg = re.split(r"[<>=!~;\[\s]", raw, maxsplit=1)[0].strip()
        if not pkg:
            continue
        canon = re.sub(r"[-_.]+", "-", pkg).lower()
        names.add(canon.replace("-", "_"))
        names.add(pkg.split(".", 1)[0].replace("-", "_"))
        for ns in NAMESPACE_PREFIXES:
            if canon.startswith(f"{ns}-"):
                names.add(ns.replace("-", "_"))
        names |= EXTERNAL_ALIASES.get(canon, set())
        names |= EXTERNAL_ALIASES.get(pkg, set())
        try:
            dist = importlib.metadata.distribution(pkg)
            top = dist.read_text("top_level.txt")
            if top:
                names.update(line.strip() for line in top.splitlines() if line.strip())
            else:
                rec = dist.read_text("RECORD") or ""
                for line in rec.splitlines():
                    rel = line.split(",", 1)[0].strip()
                    head = rel.split("/", 1)[0]
                    if head.endswith((".dist-info", ".data", ".egg-info")) or head == "..":
                        continue
                    mod = head.split(".", 1)[0]
                    if mod.isidentifier():
                        names.add(mod)
        except importlib.metadata.PackageNotFoundError:
            pass
    return names


def code_frame(path: Path, line: int | None, col: int | None = None) -> str | None:
    """A 2-line source snippet (`<line> | <code>` and a `^` underline) for a diagnostic."""
    if line is None or line < 1:
        return None
    try:
        import tokenize

        with tokenize.open(path) as f:
            text = f.read().lstrip("\ufeff")
    except (OSError, SyntaxError, LookupError, UnicodeDecodeError):
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return None
    lines = text.splitlines()
    if line > len(lines):
        return None
    raw = lines[line - 1].expandtabs(4).rstrip("\r\n")
    if not raw.strip():
        return None
    caret = (
        max(0, min(col - 1, len(raw)))
        if col is not None and col >= 1
        else len(raw) - len(raw.lstrip(" "))
    )
    if len(raw) > 120:
        raw = raw[:117] + "..."
        caret = min(caret, 116)
    pad = " " * len(str(line))
    return f"{line} | {raw}\n{pad} | {' ' * caret}^"


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
    "version_info",
    "find_spec",
    "sys.implementation",
    "python_implementation",
)
OPTIONAL_ERRORS = {None, "ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _is_type_checking(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    return isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"


def _suppresses_import_error(node: ast.With | ast.AsyncWith) -> bool:
    for item in node.items:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name == "suppress" and any(_caught(arg) in OPTIONAL_ERRORS for arg in call.args):
            return True
    return False


def _terminates(stmts: list[ast.stmt]) -> bool:
    if not stmts:
        return False
    last = stmts[-1]
    if isinstance(last, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
        return True
    if isinstance(last, ast.Expr) and isinstance(last.value, ast.Call):
        func = last.value.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name in ("exit", "skip", "fail"):
            return True
    return False


def imports_in_with_lines(tree: ast.AST) -> dict[str, int]:
    """The top-level modules a module's code imports for sure -> the first 1-based line number of
    each: not relative imports, and not those guarded by `try/except ImportError` or an `if` on
    TYPE_CHECKING, the platform or the Python version."""
    lines: dict[str, int] = {}
    branch_lines: dict[str, int] = {}
    optional_mods: set[str] = set()

    def visit_stmts(stmts: Sequence[ast.stmt], optional: bool, in_branch: bool = False) -> None:
        cur_opt = optional
        cur_branch = in_branch
        for stmt in stmts:
            visit(stmt, cur_opt, cur_branch)
            if (
                not cur_opt
                and isinstance(stmt, ast.If)
                and not stmt.orelse
                and _terminates(stmt.body)
            ):
                cur_branch = True
                unparsed = ast.unparse(stmt.test)
                if any(c in unparsed for c in CONDITIONAL):
                    cur_opt = True

    def record(top: str, lineno: int, optional: bool, in_branch: bool) -> None:
        if optional:
            optional_mods.add(top)
        elif in_branch:
            branch_lines[top] = min(branch_lines.get(top, lineno), lineno)
        else:
            lines[top] = min(lines.get(top, lineno), lineno)

    def visit(node: ast.AST, optional: bool, in_branch: bool = False) -> None:
        if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            handlers = getattr(node, "handlers", ())
            guarded = bool({_caught(h.type) for h in handlers} & OPTIONAL_ERRORS)
            visit_stmts(getattr(node, "body", ()), optional or guarded, in_branch)
            visit_stmts(getattr(node, "orelse", ()), optional or guarded, in_branch)
            for handler in handlers:
                visit(handler, optional or (_caught(handler.type) in OPTIONAL_ERRORS), in_branch)
            visit_stmts(getattr(node, "finalbody", ()), optional, in_branch)
            return
        if isinstance(node, (ast.With, ast.AsyncWith)):
            suppressed = _suppresses_import_error(node)
            for item in node.items:
                visit(item, optional, in_branch)
            visit_stmts(node.body, optional or suppressed, in_branch)
            return
        if isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Constant):
                visit_stmts(node.body, optional or not bool(test.value), in_branch)
                visit_stmts(node.orelse, optional or bool(test.value), in_branch)
                return
            if _is_type_checking(test):
                visit_stmts(node.body, True, True)
                visit_stmts(node.orelse, optional, in_branch)
                return
            if (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and _is_type_checking(test.operand)
            ):
                visit_stmts(node.body, optional, in_branch)
                visit_stmts(node.orelse, True, True)
                return
            unparsed = ast.unparse(test)
            if any(c in unparsed for c in CONDITIONAL):
                visit_stmts(node.body, True, True)
                visit_stmts(node.orelse, True, True)
                return
            visit(test, optional, in_branch)
            visit_stmts(node.body, optional, True)
            visit_stmts(node.orelse, optional, True)
            return
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for child in ast.iter_child_nodes(node):
                if child not in node.body and child not in node.orelse:
                    visit(child, optional, in_branch)
            visit_stmts(node.body, optional, in_branch)
            visit_stmts(node.orelse, optional, in_branch)
            return
        if (
            isinstance(
                node,
                (
                    ast.Module,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.ExceptHandler,
                ),
            )
            or type(node).__name__ == "match_case"
        ):
            body = getattr(node, "body", ())
            for child in ast.iter_child_nodes(node):
                if child not in body:
                    visit(child, optional, in_branch)
            visit_stmts(body, optional, in_branch)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                record(alias.name.split(".")[0], node.lineno, optional, in_branch)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            record(node.module.split(".")[0], node.lineno, optional, in_branch)
        for child in ast.iter_child_nodes(node):
            visit(child, optional, in_branch)

    visit(tree, False)
    for top, lineno in branch_lines.items():
        if top not in optional_mods:
            lines[top] = min(lines.get(top, lineno), lineno)
    return lines


def imports_in(tree: ast.AST) -> set[str]:
    """The top-level modules a module's code imports for sure."""
    return set(imports_in_with_lines(tree))


def imports_with_lines(path: Path) -> dict[str, int]:
    """What a file imports for sure -> first line number; empty if it doesn't parse."""
    try:
        return imports_in_with_lines(ast.parse(path.read_bytes()))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return {}


def imports_of(path: Path) -> set[str]:
    """What a file imports for sure; nothing if it doesn't parse (syntax-error reports that)."""
    return set(imports_with_lines(path))


def _caught(node: ast.expr | None) -> str | None:
    """The exception a handler catches, by name (None: a bare `except:`)."""
    if node is None:
        return None
    if isinstance(node, ast.Tuple):
        names = [_caught(n) for n in node.elts]
        return next((n for n in names if n in OPTIONAL_ERRORS), "")
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


_SKIP_DIRS = ("__pycache__", "__bundleup__", "__bundleup_script__")


def top_level_modules(folder: Path) -> set[str]:
    """What `import x` finds in a folder on sys.path: packages (folders, namespace ones too),
    modules and extension modules. Symlinks aren't followed."""
    names = set()
    for item in folder.iterdir() if folder.is_dir() else []:
        if item.is_symlink():
            continue
        if item.is_dir():
            if (
                item.name not in _SKIP_DIRS
                and not item.name.endswith((".dist-info", ".data", ".egg-info"))
                and item.name.isidentifier()
            ):
                names.add(item.name)
        elif item.is_file() and (item.suffix in (".py", ".so", ".pyd") or ".cpython-" in item.name):
            mod = item.name.split(".")[0]
            if mod.isidentifier():
                names.add(mod)
    return names


def search_roots(site: Path) -> list[Path]:
    """`site` and the existing subdirectories its `.pth` files add to sys.path."""
    roots = [site] if site.is_dir() else []
    for pth in sorted(site.glob("*.pth")) if site.is_dir() else []:
        if pth.name.startswith("."):
            continue
        try:
            text = pth.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "import ", "import\t")):
                sub = site / line
                if sub.is_dir():
                    roots.append(sub)
    return roots


def provided_by(site: Path) -> set[str]:
    """The modules a payload provides: its top level, the folders its .pth files add (pywin32's
    win32/, win32/lib), and `distutils` where setuptools' shim provides it on 3.12+."""
    names: set[str] = set()
    for root in search_roots(site):
        names |= top_level_modules(root)
    if (site / "_distutils_hack").is_dir():
        names.add("distutils")
    return names
