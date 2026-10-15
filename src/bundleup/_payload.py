"""The payload: the installed tree, its entry point, bytecode, and the checks against the lock."""

from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Literal, NamedTuple

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from . import _bytecode, _check, _imports, _platforms, _verify, _zipwriter
from ._errors import (
    ISSUES_URL,
    BundleMismatchError,
    BundleupError,
    Diagnostic,
    EntryPointError,
    NoCompatibleWheelError,
    UsageError,
)
from ._formats import describe_size
from ._python import Portability, PythonRange, Target
from ._source import APP_MAINS, Source
from ._steps import Progress, run
from ._text import listing
from ._uv import console_scripts, launchers


class Entry(NamedTuple):
    """What a bundle runs. A plain tuple in the loader's config and the manifest."""

    kind: Literal["call", "module", "script", "python"]
    target: str  # the module, or the script's path inside the payload
    attr: str = ""  # the function, for "call"

    def __str__(self) -> str:
        """ "module:function", "module", the script's path, or "python"."""
        if self.kind == "python":
            return "python"
        return f"{self.target}:{self.attr}" if self.kind == "call" else self.target


def resolve_entry(
    source: Source,
    site: Path,
    *,
    entry: str | None,
    script: str | None,
    target_version: tuple[int, int] | None = None,
) -> Entry:
    """What the loader runs: --entry, the project's console script, or the script itself.
    `--entry python` runs whatever script it's given, with the bundle's packages."""
    if entry == "python":
        return Entry("python", "")
    if source.app:  # a folder of modules (ADR-0041): its main file, or what --entry names
        if entry is None:
            entry = next((m for m in APP_MAINS if _exact_file(site, m) is not None), None)
            if entry is None:
                raise EntryPointError(
                    f"{source.name} has no {', '.join(APP_MAINS)}, so bundleup doesn't know "
                    "what to run",
                    hint="pass --entry main.py, --entry module:function, or --entry python",
                )
        if entry.endswith(".py"):
            norm = Path(entry.replace("\\", "/")).as_posix().removeprefix("./")
            exact = _exact_file(site, *norm.split("/"))
            if (
                ".." in norm.split("/")
                or exact is None
                or not exact.resolve().is_relative_to(site.resolve())
            ):
                raise EntryPointError(f"--entry {entry}: there's no such file in {source.name}")
            return Entry("script", norm)
    if script:
        if entry:
            raise UsageError(
                "--entry is for projects; a script bundle runs the script",
                hint="drop --entry",
            )
        return Entry("script", script)
    scripts = console_scripts(site, source.name)
    by_canon = {canonicalize_name(k): v for k, v in scripts.items()}
    roots = _imports.search_roots(site)
    if entry is None:
        if len(scripts) == 1:
            entry = next(iter(scripts.values()))
        elif canonicalize_name(source.name) in by_canon:
            entry = by_canon[canonicalize_name(source.name)]
        elif not scripts:
            pkg = canonicalize_name(source.name).replace("-", "_")
            if _locate_module(roots, pkg).has_main:
                return Entry("module", pkg)
            raise EntryPointError(
                f"{source.name} defines no [project.scripts], so bundleup doesn't know what to run",
                hint="add one to pyproject.toml, pass --entry module:function, or --entry "
                "python to run any script with these packages",
            )
        else:
            raise EntryPointError(
                f"{source.name} defines several commands ({', '.join(sorted(scripts))})",
                hint=f"pick one: --entry {sorted(scripts)[0]}",
            )
    elif entry in scripts:
        entry = scripts[entry]
    elif (
        canonicalize_name(entry) in by_canon
        and ":" not in entry
        and "." not in entry
        and not ((m := _locate_module(roots, entry)).found and (not m.is_pkg or m.has_main))
    ):
        entry = by_canon[canonicalize_name(entry)]
    raw = entry
    module, sep, attr = entry.partition(":")
    module = module.strip()
    attr = attr.split("[")[0].strip()  # drop legacy "extras" syntax: "mod:func [extra]"
    if (
        not module
        or (sep and not attr)
        or not all(p.isidentifier() for p in module.split("."))
        or (attr and not all(p.isidentifier() for p in attr.split(".")))
    ):
        raise UsageError(
            f"invalid --entry {raw!r}",
            hint="give a script name, module:function, module, or python",
        )
    _validate_entry(
        site,
        raw=raw,
        module=module,
        attr=attr,
        scripts=scripts,
        target_version=target_version,
    )
    return Entry("call", module, attr) if attr else Entry("module", module)


@dataclass(frozen=True)
class _ModuleMatch:
    found: bool
    is_pkg: bool = False
    has_main: bool = False
    has_compiled_init: bool = False
    py_file: Path | None = None
    pkg_dirs: tuple[Path, ...] = ()


def _exact_path(root: Path, *parts: str) -> Path | None:
    """Resolve `parts` under `root` with strict case-sensitivity on every OS (APFS/NTFS too)."""
    cur = root
    for part in parts:
        if not part or not cur.is_dir():
            return None
        try:
            entries = os.listdir(cur)
        except OSError:
            return None
        if part not in entries:
            return None
        cur = cur / part
    return cur


def _exact_file(root: Path, *parts: str) -> Path | None:
    p = _exact_path(root, *parts)
    return p if p is not None and p.is_file() else None


def _exact_dir(root: Path, *parts: str) -> Path | None:
    p = _exact_path(root, *parts)
    return p if p is not None and p.is_dir() else None


def _has_compiled(folder: Path, stem: str) -> bool:
    if not folder.is_dir():
        return False
    if any(
        p.name.startswith(f"{stem}.") and p.suffix in (".so", ".pyd", ".pyc")
        for p in folder.iterdir()
    ):
        return True
    pycache = folder / "__pycache__"
    return pycache.is_dir() and any(
        p.name.startswith(f"{stem}.") and p.suffix == ".pyc" for p in pycache.iterdir()
    )


def _locate_module(
    roots: list[Path],
    module: str,
    target_version: tuple[int, int] | None = None,
) -> _ModuleMatch:
    import sys

    parts = module.split(".")
    pkg_dirs = tuple(d for r in roots if (d := _exact_dir(r, *parts)) is not None)
    regular_pkg = any(
        _exact_file(d, "__init__.py") is not None or _has_compiled(d, "__init__") for d in pkg_dirs
    )
    if regular_pkg:
        return _ModuleMatch(
            found=True,
            is_pkg=True,
            has_main=any(
                _exact_file(d, "__main__.py") is not None or _has_compiled(d, "__main__")
                for d in pkg_dirs
            ),
            has_compiled_init=any(_has_compiled(d, "__init__") for d in pkg_dirs),
            py_file=next(
                (f for d in pkg_dirs if (f := _exact_file(d, "__init__.py")) is not None),
                None,
            ),
            pkg_dirs=pkg_dirs,
        )
    for root in roots:
        parent = _exact_dir(root, *parts[:-1]) if len(parts) > 1 else root
        if parent is not None:
            if (py := _exact_file(parent, f"{parts[-1]}.py")) is not None:
                return _ModuleMatch(found=True, py_file=py, pkg_dirs=pkg_dirs)
            if _has_compiled(parent, parts[-1]):
                return _ModuleMatch(found=True, pkg_dirs=pkg_dirs)
    if pkg_dirs:
        return _ModuleMatch(
            found=True,
            is_pkg=True,
            has_main=any(
                _exact_file(d, "__main__.py") is not None or _has_compiled(d, "__main__")
                for d in pkg_dirs
            ),
            pkg_dirs=pkg_dirs,
        )
    in_site = any(
        _exact_dir(r, parts[0]) is not None
        or _exact_file(r, f"{parts[0]}.py") is not None
        or _has_compiled(r, parts[0])
        for r in roots
    )
    py_ver = target_version or sys.version_info[:2]
    std_names = _imports.stdlib(py_ver) or set()
    host_std = _imports.stdlib(sys.version_info[:2]) or set()
    if not in_site and parts[0] in std_names:
        if parts[0] not in host_std:
            return _ModuleMatch(found=True)
        import importlib.util

        try:
            spec = importlib.util.find_spec(module)
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is not None:
            py_file = (
                Path(spec.origin)
                if spec.origin and spec.origin.endswith(".py") and Path(spec.origin).is_file()
                else None
            )
            is_pkg = spec.submodule_search_locations is not None
            has_main = False
            if is_pkg:
                try:
                    has_main = importlib.util.find_spec(f"{module}.__main__") is not None
                except (ModuleNotFoundError, ValueError):
                    has_main = False
            return _ModuleMatch(found=True, is_pkg=is_pkg, has_main=has_main, py_file=py_file)
    return _ModuleMatch(found=False)


def _close_match(name: str, candidates: list[str]) -> str | None:
    import difflib

    ci = [c for c in candidates if c.lower() == name.lower() and c != name]
    if ci:
        return ci[0]
    close = difflib.get_close_matches(name, candidates, n=1)
    return close[0] if close else None


def _missing_module_error(
    site: Path,
    roots: list[Path],
    *,
    raw: str,
    module: str,
    attr: str,
    scripts: dict[str, str],
    target_version: tuple[int, int] | None,
) -> EntryPointError:
    parts = module.split(".")
    provided = sorted(_imports.provided_by(site))
    if not attr and scripts and len(parts) == 1:
        close = _close_match(raw, [*scripts, *provided])
        names = ", ".join(sorted(scripts))
        hint = (
            f"did you mean --entry {close}? (scripts: {names})"
            if close
            else f"available scripts: {names}"
        )
        return EntryPointError(
            f"entry point {raw!r}: no script or module {module!r} in the bundle", hint=hint
        )
    submodules: set[str] = set()
    parent_mod = ".".join(parts[:-1])
    parent_match = _locate_module(roots, parent_mod, target_version) if len(parts) > 1 else None
    if len(parts) > 1:
        for r in roots:
            pdir = _exact_dir(r, *parts[:-1])
            if pdir is not None:
                for item in pdir.iterdir():
                    if (
                        item.is_file()
                        and item.suffix == ".py"
                        and item.stem not in ("__init__", "__main__")
                    ):
                        submodules.add(item.stem)
                    elif item.is_dir() and not item.name.startswith((".", "__")):
                        submodules.add(item.name)
    if submodules:
        sub_close = _close_match(parts[-1], sorted(submodules))
        if sub_close:
            prefix = ".".join([*parts[:-1], sub_close])
            hint = f"did you mean {prefix}:{attr}?" if attr else f"did you mean {prefix}?"
        else:
            prefix = ".".join(parts[:-1])
            hint = f"available in {prefix}: {', '.join(sorted(submodules)[:5])}"
    elif parent_match is not None and parent_match.found and not parent_match.is_pkg:
        if parts[-1] == "py":
            hint = f"did you mean {parent_mod}:{attr}?" if attr else f"did you mean {parent_mod}?"
        else:
            rest = f"{parts[-1]}.{attr}" if attr else parts[-1]
            hint = f"did you mean {parent_mod}:{rest}?"
    else:
        candidates = [p for p in provided if p != parts[0]] if len(parts) > 1 else provided
        close = _close_match(parts[0], candidates)
        if close:
            suffix = f":{attr}" if attr and len(parts) == 1 else ""
            hint = f"did you mean {close}{suffix}?"
        else:
            hint = "check [project.scripts] or --entry module:function"
    return EntryPointError(f"entry point {raw!r}: module {module!r} isn't in the bundle", hint=hint)


def _missing_attr_error(
    m: _ModuleMatch,
    *,
    raw: str,
    module: str,
    top_attr: str,
    attr: str,
    callables: list[str],
    defined: list[str],
) -> EntryPointError:
    if m.is_pkg and any(
        _exact_file(d, f"{top_attr}.py") is not None
        or _exact_dir(d, top_attr) is not None
        or _has_compiled(d, top_attr)
        for d in (m.pkg_dirs or ([m.py_file.parent] if m.py_file else ()))
    ):
        rest = attr.split(".", 1)[1] if "." in attr else ""
        hint = (
            f"did you mean {module}.{top_attr}:{rest}?"
            if rest
            else f"did you mean {module}.{top_attr}?"
        )
    else:
        pool = [
            *callables,
            *(d for d in defined if d not in callables and not d.startswith("__")),
        ]
        close = _close_match(top_attr, pool)
        if close:
            hint = f"did you mean {module}:{close}?"
        elif callables:
            hint = f"available in {module}: {', '.join(callables[:5])}"
        else:
            hint = f"check the function name in {module}"
    return EntryPointError(f"entry point {raw!r}: {module} has no {top_attr!r}", hint=hint)


def _validate_entry(
    site: Path,
    *,
    raw: str,
    module: str,
    attr: str,
    scripts: dict[str, str],
    target_version: tuple[int, int] | None = None,
) -> None:
    if not site.is_dir() or not any(site.iterdir()):
        return
    roots = _imports.search_roots(site)
    rel = Path(*module.split("."))
    m = _locate_module(roots, module, target_version)
    if not m.found:
        raise _missing_module_error(
            site,
            roots,
            raw=raw,
            module=module,
            attr=attr,
            scripts=scripts,
            target_version=target_version,
        )
    if not attr and m.is_pkg and not m.has_main:
        raise EntryPointError(
            f"entry point {raw!r}: package {module!r} has no __main__.py, so it can't be run "
            "as a module",
            hint=f"pass --entry {module}:function, or add {rel.as_posix()}/__main__.py",
        )
    if attr and (
        m.py_file is not None or (m.is_pkg and not m.has_compiled_init and bool(m.pkg_dirs))
    ):
        top_attr = attr.split(".")[0]
        ok, callables, defined = (
            _has_attr(m.py_file, top_attr) if m.py_file is not None else (False, [], [])
        )
        if not ok:
            raise _missing_attr_error(
                m,
                raw=raw,
                module=module,
                top_attr=top_attr,
                attr=attr,
                callables=callables,
                defined=defined,
            )


def _module_nodes(tree: object) -> list[object]:
    """Walk module-scope AST nodes without descending into function, class, lambda, or
    comprehension target scopes."""
    import ast

    assert isinstance(tree, ast.AST)
    out: list[object] = []
    stack = list(ast.iter_child_nodes(tree))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, ast.comprehension):
            stack.extend([node.iter, *node.ifs])
        elif not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            stack.extend(ast.iter_child_nodes(node))
    return out


def _has_attr(py_file: Path, top_attr: str) -> tuple[bool, list[str], list[str]]:
    import ast

    try:
        tree = ast.parse(py_file.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return True, [], []
    defined: set[str] = {
        "__name__",
        "__doc__",
        "__package__",
        "__loader__",
        "__spec__",
        "__file__",
        "__cached__",
        "__builtins__",
        "__all__",
        "__path__",
    }
    callables: set[str] = set()
    for node in _module_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
            callables.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
            # e.g. sys.modules[__name__] = ... or globals()[...] = ...
            if isinstance(node.value, ast.Attribute) and node.value.attr == "modules":
                return True, [], []
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            defined.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            defined.add(node.rest)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    return True, [], []
                defined.add(alias.asname or alias.name.split(".")[0])
                if (
                    isinstance(node, ast.Import)
                    and not alias.asname
                    and py_file.name == "__init__.py"
                    and alias.name.startswith(f"{py_file.parent.name}.")
                ):
                    defined.add(alias.name.split(".")[1])
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if name in ("globals", "vars", "setattr", "exec"):
                return True, [], []
    if "__getattr__" in defined:
        return True, [], []
    return top_attr in defined, sorted(callables), sorted(defined)


def check_wheel_platforms(site: Path, target: Target) -> None:
    """For another platform, every installed wheel must be built for it. uv builds source-only
    packages on this machine, so a compiled one would otherwise ship this machine's binaries."""
    platform = target.python_platform
    if platform is None:
        return
    wrong = []
    for dist_info in sorted(site.glob("*.dist-info")):
        tags = _platforms.wheel_tags(dist_info)
        if tags and not any(platform.accepts(tag) for tag in tags):
            wrong.append(f"{dist_info.name.removesuffix('.dist-info')}: {', '.join(tags)}")
    if wrong:
        raise NoCompatibleWheelError(
            f"{len(wrong)} package(s) have no build for {platform.name}",
            detail="\n".join(wrong),
            hint="these were probably built from source on this machine; build on the target "
            "platform, or pin versions that publish wheels for it",
        )


def inspect_site(site: Path) -> tuple[int, bool]:
    """(number of distributions, whether any of them is platform-specific)."""
    tags = [_platforms.wheel_tags(dist_info) for dist_info in site.glob("*.dist-info")]
    return len(tags), any(_platforms.is_native(t) for t in tags)


def runtime_needs(site: Path) -> _platforms.RuntimeNeeds:
    """What a machine needs to run the native wheels in `site` (checked by the loader)."""
    return _platforms.runtime_needs(
        _platforms.wheel_tags(dist_info) for dist_info in site.glob("*.dist-info")
    )


# Set literals are stored in .pyc files in hash order, and string hashes are randomised per process,
# so compiling twice can give different bytes. A fixed seed keeps builds reproducible; host PYTHON*
# variables are stripped so compiling with `-s -S` (which honours PYTHONHASHSEED, unlike `-I`) is
# still isolated from the caller's environment.
def compile_env() -> dict[str, str]:
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("PYTHON")},
        "PYTHONHASHSEED": "0",
    }


COMPILE_ENV = compile_env()


def precompile(target: Target, site: Path, *, progress: Progress, checked: bool = False) -> None:
    """Compile everything with the target's interpreter, reusing cached bytecode (_bytecode)."""

    def compile_with(cmd: list[str]) -> None:
        run(
            cmd,
            what="compiling bytecode",
            progress=progress,
            error=BundleupError,
            env=compile_env(),
        )

    identity = (
        f"{_bytecode.FORMAT}-{target.implementation}-{target.full_version}-{target.cache_tag}"
    )
    _bytecode.precompile(
        site,
        python=target.executable,
        python_identity=identity,
        cache_tag=target.cache_tag,
        run=compile_with,
        checked=checked,
    )


def write_payload(site: Path, payload: Path) -> tuple[str, dict[str, str]]:
    """Zip the installed tree reproducibly, compressing on several threads.

    Returns the archive's sha256, and each zipped file's RECORD-style hash, for the integrity
    check and the manifest.
    """
    members = [
        _zipwriter.Member(rel, Path(path).read_bytes, os.stat(path).st_mode)
        for rel, path in _bytecode.walk_files(site)
    ]
    workers = min(8, os.cpu_count() or 1)
    # Level 6 (zlib's default): with compression spread over threads it costs ~5% more time than
    # level 1 on a large tree and saves ~8-13% of the size (findings 2026-10-05-faster-builds).
    return _zipwriter.write_zip(
        payload, members, level=6, workers=workers, hasher=_verify.record_hash
    )


@dataclass(frozen=True)
class Layer:
    """A zip inside a .pyz: the whole payload, or, in a bundle for several platforms, the files
    shared by exactly the payloads in `owners`, each stored once (ADR-0038)."""

    member: str  # its name in the bundle
    path: Path  # the staged zip
    digest: str  # its sha256
    files: dict[str, str]  # each file's RECORD-style hash
    owners: tuple[int, ...]  # the payloads that unpack it


def write_layers(sites: list[Path], stage: Path) -> list[Layer]:
    """Zip several payloads so that each distinct file (same path, contents and executable bit)
    is stored once: in the layer of the payloads that have it. Pure-Python packages land in a
    layer every payload shares, a stable-ABI extension (abi3) in one per platform."""
    owners: dict[tuple[str, str, int], list[int]] = {}
    sources: dict[tuple[str, str, int], str] = {}
    for i, site in enumerate(sites):
        for rel, path in _bytecode.walk_files(site):
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            key = (rel, digest, os.stat(path).st_mode & 0o111)
            owners.setdefault(key, []).append(i)
            sources.setdefault(key, path)
    groups: dict[tuple[int, ...], list[tuple[str, str, int]]] = {}
    for key, who in owners.items():
        groups.setdefault(tuple(who), []).append(key)
    layers = []
    workers = min(8, os.cpu_count() or 1)
    for n, (who, keys) in enumerate(sorted(groups.items())):
        staged = stage / f"layer-{n}.zip"
        paths = {key[0]: sources[key] for key in keys}  # a payload has each path once
        members = [
            _zipwriter.Member(rel, Path(path).read_bytes, os.stat(path).st_mode)
            for rel, path in sorted(paths.items())
        ]
        digest, written = _zipwriter.write_zip(
            staged, members, level=6, workers=workers, hasher=_verify.record_hash
        )
        layers.append(Layer(f"layer-{digest[:16]}.zip", staged, digest, written, who))
    return layers


# What a zip adds per file beyond its compressed bytes: a local header (30 bytes) and a central
# directory entry (46), each with the name, plus room for ZIP64 extras.
PER_FILE = 30 + 46 + 40
END = 1024  # the end-of-central-directory records, with room to spare


def split_layer(layer: Layer, budget: int, stage: Path) -> list[Layer]:
    """`layer` as zips of at most `budget` bytes each, cutting between files in name order, so
    each piece is an ordinary zip the loader unpacks in turn (`--split`). A layer that fits is
    only renamed for its hash. Raises UsageError when one file alone is over the budget."""
    with zipfile.ZipFile(layer.path) as zf:
        infos = zf.infolist()
        too_big = [i for i in infos if END + _cost(i) > budget]
        if too_big:
            biggest = max(too_big, key=lambda i: i.compress_size)
            raise UsageError(
                f"{biggest.filename} is {describe_size(biggest.compress_size)} compressed, too "
                f"big for a part of at most {describe_size(budget)} (--split)",
                hint="a file can't be cut in two: give --split a bigger size",
            )
        if layer.path.stat().st_size <= budget:
            pieces = [infos]
        else:
            pieces: list[list[zipfile.ZipInfo]] = [[]]
            size = END
            for info in infos:
                if size + _cost(info) > budget and pieces[-1]:
                    pieces.append([])
                    size = END
                pieces[-1].append(info)
                size += _cost(info)
        if len(pieces) == 1:
            return [replace(layer, member=f"layer-{layer.digest[:16]}.zip")]
        out = []
        workers = min(8, os.cpu_count() or 1)
        for n, piece in enumerate(pieces):
            staged = stage / f"{layer.path.stem}-part-{n}.zip"
            members = [
                _zipwriter.Member(i.filename, partial(zf.read, i), i.external_attr >> 16)
                for i in piece
            ]
            digest, written = _zipwriter.write_zip(
                staged, members, level=6, workers=workers, hasher=_verify.record_hash
            )
            out.append(Layer(f"layer-{digest[:16]}.zip", staged, digest, written, layer.owners))
        return out


def _cost(info: zipfile.ZipInfo) -> int:
    return info.compress_size + PER_FILE + 2 * len(info.filename.encode())


def verify_payload(
    site: Path,
    *,
    pylock: Path,
    target: Target,
    written: dict[str, str],
    script: str | None,
    own: tuple[str, ...] = (),
) -> list[_verify.LockedPackage]:
    """Fail the build if the payload doesn't match uv.lock and the wheels' RECORD files exactly.

    Returns the locked packages that apply to the target, for the manifest.
    """
    locked = _verify.locked_packages(pylock.read_text(encoding="utf-8"), target.markers)
    problems = _verify.check_lock(locked, _verify.installed_distributions(site))
    problems += _verify.check_records(
        site, written, removed=launchers(site), added=[*([script] if script else []), *own]
    )
    if problems:
        raise BundleMismatchError(
            "the bundle wouldn't match uv.lock exactly, so it wasn't written",
            detail=listing(problems),
            hint=f"this is a bug in bundleup; please report it: {ISSUES_URL}",
        )
    return locked


def pth_files(site: Path) -> list[str]:
    """The payload's .pth files, which the loader processes like a venv's site-packages: sorted,
    hidden ones skipped, as site.py does."""
    return sorted(p.name for p in site.glob("*.pth") if not p.name.startswith("."))


# The range a pure-Python bundle can claim (ADR-0030): from the oldest Python bundles are tested on;
# lock markers are evaluated up to NEWEST_KNOWN, and a range still open there stays open.
OLDEST = (3, 9)
NEWEST_KNOWN = (3, 20)


# One of each OS and CPU bundleup builds for: a pure bundle runs on all of them if the lock
# selects the same packages for each (ADR-0034).
SURVEY = [
    "x86_64-unknown-linux-gnu",
    "aarch64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc",
    "aarch64-pc-windows-msvc",
]


def portability(pylock: Path, *, target: Target, pythons: PythonRange, native: bool) -> Portability:
    """Whether a pure-Python payload runs on any OS and any CPU: the lock's markers, evaluated
    for each OS and CPU and every Python in the range, select exactly the packages bundled.
    `colorama; sys_platform == "win32"` ties a bundle to its OS; a CPU marker to its CPU."""
    if native:
        return Portability()
    lock = pylock.read_text(encoding="utf-8")
    selected = set(_verify.locked_packages(lock, target.markers))
    newest = pythons.max or NEWEST_KNOWN
    versions = {target.full_version} | {f"3.{m}.0" for m in range(pythons.min[1], newest[1] + 1)}

    def same(name: str) -> bool:
        platform = _platforms.parse(name)
        return all(
            set(_verify.locked_packages(lock, platform.markers(python_full_version=v))) == selected
            for v in versions
        )

    results = {name: same(name) for name in SURVEY}
    any_os = all(results.values())
    own = [n for n in SURVEY if _platforms.parse(n).sys_platform == target.platform]
    return Portability(any_os=any_os, any_cpu=any_os or all(results[n] for n in own))


def python_range(
    site: Path, *, pylock: Path, target: Target, source: Source, native: bool
) -> PythonRange:
    """The minor versions this payload runs on: the target's only, if anything is compiled;
    otherwise every neighbouring version for which the lock selects the same packages and the
    project and every package allow that Python."""
    here = target.version
    if native:
        return PythonRange(here, here)
    lock = pylock.read_text(encoding="utf-8")
    selected = set(_verify.locked_packages(lock, target.markers))
    texts = [source.requires_python or ""]
    texts += [d.requires_python for d in _verify.installed_distributions(site)]
    specs = []
    for text in texts:
        try:
            specs.append(SpecifierSet(text))
        except InvalidSpecifier:
            continue  # unreadable metadata: the installer accepted it, so does this

    def same(minor: int) -> bool:
        full = f"3.{minor}.0"
        if not all(
            any(spec.contains(f"3.{minor}.{p}", prereleases=True) for p in (0, 99))
            for spec in specs
        ):
            return False
        environment = {
            **target.markers,
            "python_version": f"3.{minor}",
            "python_full_version": full,
            "implementation_version": full,
        }
        return set(_verify.locked_packages(lock, environment)) == selected

    low = here[1]
    while low - 1 >= OLDEST[1] and same(low - 1):
        low -= 1
    high = here[1]
    while high + 1 <= NEWEST_KNOWN[1] and same(high + 1):
        high += 1
    return PythonRange((3, low), None if high == NEWEST_KNOWN[1] else (3, high))


@dataclass(frozen=True)
class Prepared:
    """A project installed and compiled in a staging directory, and what the analysis found."""

    source: Source
    target: Target
    site: Path
    pylock: Path
    script: str | None  # where a PEP 723 script is in the payload
    entry: Entry | None  # None only for `dir` and `zip`, where it's optional
    packages: int
    native: bool
    version: str | None
    diagnostics: list[Diagnostic]
    sizes: list[_check.PackageSize]
    pythons: PythonRange  # the minor versions the bundle runs on (ADR-0030)
    reach: Portability  # whether it runs on any OS and CPU (ADR-0034)
    own: tuple[str, ...] = ()  # a folder app's files, copied in rather than installed (ADR-0041)
