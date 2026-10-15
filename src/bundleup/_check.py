"""What won't survive bundling, found before shipping: the analysis behind `bundleup check`, which
every build runs too (ADR-0024).

Bundles unpack everything to a real directory (ADR-0005, ADR-0010), so most of what breaks other
bundlers works here without a check: `__file__` paths, package metadata, plugins and imports by
name (gauntlet 04-09), executables and `.pth` files (ADR-0023). What's left:

- `syntax-error`: Python files the target interpreter can't compile, usually code that needs a
  newer Python. An error in the project's own code (the bundle would crash); a warning in a
  dependency, which may import such a file only on newer Pythons.
- `data-files`: files a wheel installs outside its packages (the `.data/data` scheme, e.g.
  `share/jupyter/...`). A venv puts them under `sys.prefix`; a bundle keeps them next to the
  packages, so code that looks under `sys.prefix` won't find them.

It also measures each package for the size report.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import _bytecode, _imports, _platforms, _verify
from ._coverage import MatrixCell
from ._errors import Diagnostic
from ._python import Portability, PythonRange
from ._text import listing, plural

if TYPE_CHECKING:
    from ._python import Target

# Runs on the target interpreter: why each listed file doesn't compile (paths relative to argv[1]).
# argv[3], if given, is an older minor version ("9") to check against with this interpreter:
# ast.parse(feature_version=) rejects syntax newer than it (best effort, documented as such).
COMPILE_ERRORS = """
import ast, json, os, sys
site, listing = sys.argv[1], sys.argv[2]
older = (3, int(sys.argv[3])) if len(sys.argv) > 3 else None
found = []
for path in open(listing, encoding="utf-8").read().splitlines():
    try:
        with open(os.path.join(site, path), "rb") as f:
            source = f.read()
        if older:
            ast.parse(source, path, feature_version=older)
        else:
            compile(source, path, "exec", dont_inherit=True)
    except SyntaxError as e:
        found.append([path, e.lineno, e.msg])
    except Exception as e:
        found.append([path, None, repr(e)])
print(json.dumps(found))
"""
# Where a wheel's `.data/data` files land with `--target`: config and shared data apps may load.
# (Headers under include/ are only for compiling against a package, never loaded at run time.)
DATA_ROOTS = ("share/", "etc/")
DOCUMENTATION = ("share/man/", "share/doc/", "share/licenses/", "share/info/")


@dataclass(frozen=True)
class PackageSize:
    """One distribution in the bundle, measured unpacked."""

    name: str  # canonical, e.g. "charset-normalizer"
    version: str | None  # None for a PEP 723 script
    size_bytes: int  # its files once unpacked, compiled bytecode included
    native: bool  # contains compiled code, built for one platform

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "size_bytes": self.size_bytes,
            "native": self.native,
        }


@dataclass(frozen=True)
class CheckReport:
    """What `bundleup check` found. `to_json_dict()` is the `result` object of its `--json`; the
    diagnostics go in the document's `diagnostics` list, as for every command."""

    name: str
    version: str | None  # the project's version; None for a script
    target: Target
    native: bool
    packages: list[PackageSize]  # largest first
    diagnostics: list[Diagnostic]
    duration_s: float
    pythons: PythonRange | None = None  # the versions a bundle would run on (ADR-0030)
    matrix: list[MatrixCell] = field(default_factory=list)  # `check --matrix` (ADR-0031)
    reach: Portability | None = None  # whether it would run on any OS / CPU (ADR-0034)
    # Extra `--python-platform` values whose wheels were checked in the lock, uv's names.
    also_platforms: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.level == "warning"]

    @property
    def ok(self) -> bool:
        """No errors (warnings allowed)."""
        return not self.errors

    @property
    def size_bytes(self) -> int:
        return sum(p.size_bytes for p in self.packages)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "target": self.target.to_json_dict(
                native=self.native, pythons=self.pythons, reach=self.reach
            ),
            "native": self.native,
            "size_bytes": self.size_bytes,
            "packages": [p.to_json_dict() for p in self.packages],
            "duration_s": round(self.duration_s, 3),
            "matrix": [cell.to_json_dict() for cell in self.matrix],
            "also_platforms": self.also_platforms,
        }


@dataclass(frozen=True)
class _Owner:
    name: str  # canonical
    version: str | None
    native: bool


def owners(
    site: Path,
    *,
    project: str,
    script: str | None = None,
    own: Sequence[str] = (),
) -> dict[str, _Owner]:
    """Each payload path (as RECORD lists it) -> the distribution that installed it. A PEP 723
    script (at `script`) or a folder app's files (`own`) belong to `project`."""
    from packaging.utils import canonicalize_name

    project = canonicalize_name(project)
    found: dict[str, _Owner] = {}
    for dist in _verify.installed_distributions(site):
        dist_info = site / dist.dist_info
        owner = _Owner(
            dist.name, dist.version, _platforms.is_native(_platforms.wheel_tags(dist_info))
        )
        for path in _verify.record_paths((dist_info / "RECORD").read_text(encoding="utf-8")):
            found[path] = owner
    if script:
        found[script] = _Owner(project, None, False)
    for rel in own:
        found.setdefault(rel, _Owner(project, None, False))
    return found


def _source_of(pyc: str) -> str:
    """pkg/__pycache__/mod.cpython-312.pyc -> pkg/mod.py"""
    head, sep, name = pyc.rpartition("__pycache__/")
    stem = name.rsplit(".", 2)[0] if sep else name.removesuffix(".pyc")
    return f"{head}{stem}.py"


def package_sizes(site: Path, owner: dict[str, _Owner]) -> list[PackageSize]:
    """Unpacked size of each distribution, largest first. Bytecode counts towards its source's."""
    sizes: dict[_Owner, int] = defaultdict(int)
    for rel, path in _bytecode.walk_files(site):
        who = owner.get(rel) or (owner.get(_source_of(rel)) if rel.endswith(".pyc") else None)
        if who:
            sizes[who] += os.lstat(path).st_size
    found = [PackageSize(o.name, o.version, size, o.native) for o, size in sizes.items()]
    return sorted(found, key=lambda p: (-p.size_bytes, p.name))


def compile_errors(
    site: Path,
    files: list[str],
    *,
    python: str,
    run: Callable[[list[str]], str],
    as_version: tuple[int, int] | None = None,
) -> list[list[str | int | None]]:
    """[path, line, message] for each of `files` that `python` can't compile, or, with
    `as_version`, whose syntax is newer than that version (checked by `python`, best effort)."""
    to_check = site.parent / "check-list.txt"
    to_check.write_text("\n".join(files), encoding="utf-8")
    older = [str(as_version[1])] if as_version else []
    return json.loads(run([python, "-I", "-c", COMPILE_ERRORS, str(site), str(to_check), *older]))


def _ast_errors(
    site: Path, files: list[str], version: tuple[int, int]
) -> list[list[str | int | None]]:
    import ast

    found: list[list[str | int | None]] = []
    for path in files:
        try:
            source = (site / path).read_bytes()
            ast.parse(source, path, feature_version=version)
        except SyntaxError as e:
            found.append([path, e.lineno, e.msg])
        except Exception as e:
            found.append([path, None, repr(e)])
    return found


def oldest_python(
    site: Path,
    *,
    project: str,
    script: str | None,
    pythons: PythonRange,
    target: Target,
    interpreters: dict[tuple[int, int], str | None] | None = None,
    run: Callable[[list[str]], str],
    own: Sequence[str] = (),
) -> tuple[PythonRange, list[Diagnostic]]:
    """A pure-Python bundle claims every version its requires-python allows (ADR-0030). Check
    that the project's own code compiles on the versions below the target: in-process with
    `ast.parse(feature_version=)` (or on an installed older interpreter if passed): the range
    starts at the oldest one that compiles."""
    import sys

    from packaging.utils import canonicalize_name

    project = canonicalize_name(project)
    if interpreters is None:
        interpreters = {(3, m): None for m in range(pythons.min[1], target.version[1])}
    below = sorted(v for v in interpreters if pythons.min <= v < target.version)
    if not below:
        return pythons, []
    mine = owners(site, project=project, script=script, own=own)
    files = sorted(
        path
        for path, who in mine.items()
        if who.name == project
        and path.endswith(".py")
        # Only what compiled for the target: anything else is already a syntax-error.
        and (site / _bytecode.pyc_path(path, target.cache_tag)).exists()
    )
    if not files:
        return pythons, []
    verified: tuple[int, int] | None = None  # the oldest version the code compiled on
    failure: list[str | int | None] | None = None  # the oldest version's first error
    failed_on: tuple[int, int] | None = None
    for version in below:
        python = interpreters[version]
        if python is None and sys.version_info[:2] >= version:
            found = _ast_errors(site, files, version)
        elif python is None:
            found = compile_errors(
                site, files, python=target.executable, run=run, as_version=version
            )
        else:
            found = compile_errors(site, files, python=python, run=run)
        if not found:
            verified = version
            break
        if failure is None:
            failure, failed_on = found[0], version
    if failure is None or failed_on is None:
        return pythons, []
    # Claim only from the oldest version that compiled, or the target's.
    narrowed = PythonRange(verified or target.version, pythons.max)
    path, line, message = failure
    lineno = line if isinstance(line, int) and not isinstance(line, bool) and line >= 1 else None
    where = f"{str(path).removeprefix(_verify.SCRIPT_DIR + '/')}{f':{lineno}' if lineno else ''}"
    return narrowed, [
        Diagnostic(
            "python-range",
            "warning",
            f"{where} doesn't compile on Python {_v(failed_on)} ({message}), which "
            f"requires-python allows, so the bundle runs on Python {narrowed} only",
            hint="raise requires-python to the oldest Python the code works on",
            package=project,
            file=str(path),
            line=lineno,
        )
    ]


def _v(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def syntax_errors(
    site: Path,
    owner: dict[str, _Owner],
    *,
    project: str,
    target: Target,
    run: Callable[[list[str]], str],
) -> list[Diagnostic]:
    """Python files the target interpreter couldn't compile. The build compiled everything
    already, so a source without its bytecode is a candidate; the target interpreter confirms
    each one and says why."""
    from packaging.utils import canonicalize_name

    project = canonicalize_name(project)
    candidates = [
        rel
        for rel, _path in _bytecode.walk_files(site)
        if rel.endswith(".py") and not (site / _bytecode.pyc_path(rel, target.cache_tag)).exists()
    ]
    if not candidates:
        return []
    found = compile_errors(site, candidates, python=target.executable, run=run)
    python = f"Python {target.version[0]}.{target.version[1]}"
    diags = []
    theirs: dict[_Owner, list[str]] = defaultdict(list)
    first: dict[_Owner, tuple[str, int | None]] = {}
    for path, line, message in found:
        assert isinstance(path, str) and isinstance(message, str)
        line = line if isinstance(line, int) and not isinstance(line, bool) and line >= 1 else None
        who = owner.get(path) or _Owner(project, None, False)
        where = f"{path.removeprefix(_verify.SCRIPT_DIR + '/')}{f':{line}' if line else ''}"
        if who.name == project:
            diags.append(
                Diagnostic(
                    "syntax-error",
                    "error",
                    f"{where} doesn't compile on {python}: {message}",
                    hint=f"if it needs a newer Python, build for one with --python and raise "
                    f"requires-python so builds for {python} are refused; otherwise fix it",
                    package=project,
                    file=path,
                    line=line,
                )
            )
        else:
            theirs[who].append(f"{where}: {message}")
            first.setdefault(who, (path, line))
    for who, files in sorted(theirs.items(), key=lambda item: item[0].name):
        them = "it" if len(files) == 1 else "them"
        verb = "doesn't" if len(files) == 1 else "don't"
        diags.append(
            Diagnostic(
                "syntax-error",
                "warning",
                f"{plural(len(files), 'file')} in {who.name} {who.version} {verb} compile on "
                f"{python}",
                hint=f"harmless if {who.name} imports {them} only on newer Pythons; if not, use a "
                f"{who.name} release that supports {python}",
                detail=listing(files),
                package=who.name,
                file=first[who][0],
                line=first[who][1],
            )
        )
    return diags


def data_files(site: Path, owner: dict[str, _Owner]) -> list[Diagnostic]:
    """Files installed outside any package, where code looking under sys.prefix won't find them."""
    theirs: dict[_Owner, list[str]] = defaultdict(list)
    for path, who in owner.items():
        data = path.startswith(DATA_ROOTS) and not path.startswith(DOCUMENTATION)
        if data and (site / path).is_file():
            theirs[who].append(path)
    diags = []
    for who, files in sorted(theirs.items(), key=lambda item: item[0].name):
        files.sort()
        diags.append(
            Diagnostic(
                "data-files",
                "warning",
                f"{who.name} {who.version} installs {plural(len(files), 'data file')} outside "
                f"its packages ({files[0].split('/')[0]}/)",
                hint=f"a venv puts them under sys.prefix and a bundle next to the packages; if "
                f"{who.name} looks for them under sys.prefix, it won't find them",
                detail=listing(files),
                package=who.name,
                file=files[0],
            )
        )
    return diags


def analyze(
    site: Path,
    *,
    project: str,
    target: Target,
    run: Callable[[list[str]], str],
    script: str | None = None,
    own: Sequence[str] = (),
) -> tuple[list[Diagnostic], list[PackageSize]]:
    """Everything `bundleup check` reports about an installed, compiled payload: the
    diagnostics (errors first) and each package's size. `project` is the canonical name of the
    project (or script, installed at `script`) being bundled."""
    owner = owners(site, project=project, script=script, own=own)
    diags = syntax_errors(site, owner, project=project, target=target, run=run)
    diags += data_files(site, owner)
    diags.sort(key=lambda d: d.level != "error")  # stable: errors first, then in found order
    return diags, package_sizes(site, owner)


def undeclared_imports(
    code: list[tuple[str, set[str], set[str]]], provided: set[str], stdlib: set[str] | None
) -> list[Diagnostic]:
    """Modules the bundled code imports that neither the payload (`provided`) nor the target's
    standard library has: the most common way a bundle fails at run time, since it can't see
    the machine's packages (fourth review). `code`: (name shown, what it imports, the modules
    beside it that count too). A warning: it reads imports, it doesn't run code. Skipped where
    the standard library is unknown (bundleup on 3.9)."""
    if stdlib is None:
        return []
    have = provided | stdlib | {"__future__", "__main__"}
    diags = []
    for shown, imported, local in code:
        missing = sorted(imported - have - local)
        if missing:
            diags.append(
                Diagnostic(
                    "undeclared-import",
                    "warning",
                    f"{shown} imports {', '.join(missing)}: neither the bundle nor the standard "
                    f"library has {'it' if len(missing) == 1 else 'them'}",
                    hint="add the packages that provide them to the dependencies (an import in "
                    "`try: ... except ImportError` counts as optional)",
                    file=shown,
                )
            )
    return diags


def stdlib_range(
    pythons: PythonRange, here: tuple[int, int], imported: set[str], provided: set[str]
) -> tuple[PythonRange, list[Diagnostic]]:
    """Narrow a pure-Python bundle's range to the versions whose standard library has every
    module its code imports from it (fifth review: `import imp` was claimed for 3.12+, where
    it's gone; `import tomllib` for 3.9, before it existed). Modules the payload provides
    (setuptools' distutils) don't count."""
    if pythons.exact:
        return pythons, []
    top = pythons.max or max(_imports.NEWEST, here)
    versions = [(3, minor) for minor in range(pythons.min[1], top[1] + 1)]
    libraries = {v: _imports.stdlib(v) for v in versions}
    if any(lib is None for lib in libraries.values()):
        return pythons, []
    ever = set().union(*(lib for lib in libraries.values() if lib is not None))
    used = (imported & ever) - provided
    ok = [v for v in versions if used <= (libraries[v] or set())]
    if ok == versions or here not in ok:
        return pythons, []
    low = high = versions.index(here)  # the stretch of versions around the target that work
    while low > 0 and versions[low - 1] in ok:
        low -= 1
    while high < len(versions) - 1 and versions[high + 1] in ok:
        high += 1
    open_ended = pythons.max is None and high == len(versions) - 1
    narrowed = PythonRange(versions[low], None if open_ended else versions[high])
    missing = sorted(m for m in used if any(m not in (libraries[v] or set()) for v in versions))
    return narrowed, [
        Diagnostic(
            "python-range",
            "warning",
            f"the code imports {', '.join(missing)}, which not every Python in {pythons} has, "
            f"so the bundle runs on Python {narrowed}",
            hint="import it conditionally (`if sys.version_info >= ...`, or `try/except "
            "ImportError`) to keep the wider range",
        )
    ]
