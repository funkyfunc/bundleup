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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import _bytecode, _platforms, _verify
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
    reach: Portability | None = None  # whether it would run on any OS / CPU (ADR-0034)

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
        }


@dataclass(frozen=True)
class _Owner:
    name: str  # canonical
    version: str | None
    native: bool


def owners(site: Path, *, project: str, script: str | None = None) -> dict[str, _Owner]:
    """Each payload path (as RECORD lists it) -> the distribution that installed it. A PEP 723
    script (at `script`) belongs to `project`."""
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
    return found


def _source_of(pyc: str) -> str:
    """pkg/__pycache__/mod.cpython-312.pyc -> pkg/mod.py"""
    head, _, name = pyc.rpartition("__pycache__/")
    return f"{head}{name.split('.', 1)[0]}.py"


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


def oldest_python(
    site: Path,
    *,
    project: str,
    script: str | None,
    pythons: PythonRange,
    target: Target,
    interpreters: dict[tuple[int, int], str | None],
    run: Callable[[list[str]], str],
) -> tuple[PythonRange, list[Diagnostic]]:
    """A pure-Python bundle claims every version its requires-python allows (ADR-0030). Check
    that the project's own code compiles on the versions below the target, using whichever of
    them are installed here (`interpreters`: version -> interpreter or None): the range starts at
    the oldest one that compiles. A version that isn't installed is checked by the target's
    interpreter with `ast.parse(feature_version=)`, so no claim goes unchecked (second review,
    2026-10-07; ADR-0035)."""
    below = sorted(v for v in interpreters if pythons.min <= v < target.version)
    if not below:
        return pythons, []
    mine = owners(site, project=project, script=script)
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
        if python is None:  # not installed: the target's interpreter checks the syntax for it
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
        if interpreters.get(pythons.min) is None:  # checked with ast only: say so
            return pythons, [
                Diagnostic(
                    "python-range-approximate",
                    "warning",
                    f"Python {_v(pythons.min)} couldn't be installed to check the code, so only "
                    "its syntax was checked, roughly; the bundle claims Python "
                    f"{pythons} from requires-python",
                    hint=f"install it to check exactly: uv python install {_v(pythons.min)}",
                    package=project,
                )
            ]
        return pythons, []
    # Claim only from the oldest version that compiled, or the target's.
    narrowed = PythonRange(verified or target.version, pythons.max)
    path, line, message = failure
    where = f"{str(path).removeprefix(_verify.SCRIPT_DIR + '/')}{f':{line}' if line else ''}"
    return narrowed, [
        Diagnostic(
            "python-range",
            "warning",
            f"{where} doesn't compile on Python {_v(failed_on)} ({message}), which "
            f"requires-python allows, so the bundle runs on Python {narrowed} only",
            hint="raise requires-python to the oldest Python the code works on",
            package=project,
            file=str(path),
            line=line if isinstance(line, int) else None,
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
        line = line if isinstance(line, int) else None
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
) -> tuple[list[Diagnostic], list[PackageSize]]:
    """Everything `bundleup check` reports about an installed, compiled payload: the
    diagnostics (errors first) and each package's size. `project` is the canonical name of the
    project (or script, installed at `script`) being bundled."""
    owner = owners(site, project=project, script=script)
    diags = syntax_errors(site, owner, project=project, target=target, run=run)
    diags += data_files(site, owner)
    diags.sort(key=lambda d: d.level != "error")  # stable: errors first, then in found order
    return diags, package_sizes(site, owner)
