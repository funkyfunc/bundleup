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

from . import _bytecode, _verify
from ._errors import Diagnostic

if TYPE_CHECKING:
    from ._build import Target

# Runs on the target interpreter: why each listed file doesn't compile (paths relative to argv[1]).
COMPILE_ERRORS = """
import json, os, sys
site, listing = sys.argv[1], sys.argv[2]
found = []
for path in open(listing, encoding="utf-8").read().splitlines():
    try:
        with open(os.path.join(site, path), "rb") as f:
            compile(f.read(), path, "exec", dont_inherit=True)
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
SHOWN = 20  # files listed in a diagnostic's detail


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
            "target": self.target.to_json_dict(native=self.native),
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


def owners(site: Path, *, project: str) -> dict[str, _Owner]:
    """Each payload path (as RECORD lists it) -> the distribution that installed it. A PEP 723
    script's files belong to `project`."""
    found: dict[str, _Owner] = {}
    for dist in _verify.installed_distributions(site):
        dist_info = site / dist.dist_info
        tags = (dist_info / "WHEEL").read_text(encoding="utf-8").splitlines()
        native = any(t.startswith("Tag:") and not t.rstrip().endswith("-any") for t in tags)
        owner = _Owner(dist.name, dist.version, native)
        for path in _verify.record_paths((dist_info / "RECORD").read_text(encoding="utf-8")):
            found[path] = owner
    script = site / _verify.SCRIPT_DIR
    if script.is_dir():
        for name in os.listdir(script):
            found[f"{_verify.SCRIPT_DIR}/{name}"] = _Owner(project, None, False)
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


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _listing(items: list[str]) -> str:
    more = [f"... and {len(items) - SHOWN} more"] if len(items) > SHOWN else []
    return "\n".join(items[:SHOWN] + more)


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
    listing = site.parent / "check-list.txt"
    listing.write_text("\n".join(candidates), encoding="utf-8")
    found: list[list[str | int | None]] = json.loads(
        run([target.executable, "-I", "-c", COMPILE_ERRORS, str(site), str(listing)])
    )
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
                f"{_plural(len(files), 'file')} in {who.name} {who.version} {verb} compile on "
                f"{python}",
                hint=f"harmless if {who.name} imports {them} only on newer Pythons; if not, use a "
                f"{who.name} release that supports {python}",
                detail=_listing(files),
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
                f"{who.name} {who.version} installs {_plural(len(files), 'data file')} outside "
                f"its packages ({files[0].split('/')[0]}/)",
                hint=f"a venv puts them under sys.prefix and a bundle next to the packages; if "
                f"{who.name} looks for them under sys.prefix, it won't find them",
                detail=_listing(files),
                package=who.name,
                file=files[0],
            )
        )
    return diags


def analyze(
    site: Path, *, project: str, target: Target, run: Callable[[list[str]], str]
) -> tuple[list[Diagnostic], list[PackageSize]]:
    """Everything `bundleup check` reports about an installed, compiled payload: the
    diagnostics (errors first) and each package's size. `project` is the canonical name of the
    project (or script) being bundled."""
    owner = owners(site, project=project)
    diags = syntax_errors(site, owner, project=project, target=target, run=run)
    diags += data_files(site, owner)
    diags.sort(key=lambda d: d.level != "error")  # stable: errors first, then in found order
    return diags, package_sizes(site, owner)
