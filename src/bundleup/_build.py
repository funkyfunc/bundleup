"""Build a bundle (or just check one): the steps in order, from finding the Python to writing
the output. Each step lives in its own module: _source, _python, _uv, _payload, _outputs."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from . import (
    _check,
    _config,
    _coverage,
    _imports,
    _loader,
    _platforms,
    _smoke,
)
from . import _toml as tomllib
from ._check import CheckReport
from ._errors import (
    BundleupError,
    CheckFailedError,
    Diagnostic,
    EntryPointError,
    NoCompatibleWheelError,
    UsageError,
)
from ._exe import host_platform, write_exe
from ._formats import FORMATS, LOADED, Format
from ._outputs import (
    atomic_output,
    check_dir_output,
    check_size,
    stage_zip,
    write_dir,
    write_pyz,
)
from ._payload import (
    OLDEST,
    Entry,
    Prepared,
    check_wheel_platforms,
    inspect_site,
    portability,
    precompile,
    pth_files,
    python_range,
    resolve_entry,
    runtime_needs,
)
from ._python import (
    Portability,
    PythonRange,
    Target,
    check_requires_python,
    find_python,
)
from ._smoke import SmokeResult
from ._source import (
    Source,
    find_uv_lock,
    load_source,
    looks_secret,
    project_version,
    python_files,
    read_python_text,
    safe_name,
    script_metadata,
    script_path,
)
from ._steps import Progress, ProgressEvent, Steps, ignore, run
from ._text import findings, plural
from ._uv import add_runtime, export, find_uv, install, merge_native_wheels


@dataclass(frozen=True)
class BuildOptions:
    """What to bundle and how. Mirrors `bundleup build`'s flags."""

    path: Path = Path()  # a project directory (with pyproject.toml) or a PEP 723 script
    output: Path | None = None  # default: dist/<name>.pyz next to the input
    python: str | None = None  # a version ("3.12") or an interpreter path; default: uv's choice
    entry: str | None = None  # a [project.scripts] name, "module:function" or "module"
    lock_mode: Literal["locked", "frozen"] | None = None  # as uv's --locked / --frozen
    # Another OS/CPU, in uv's terms (e.g. "x86_64-manylinux_2_28"); default: this machine.
    python_platform: str | None = None
    strict: bool = False  # warnings fail the build too (errors always do)
    # What to write (ADR-0025, ADR-0046, ADR-0049): "pyz" (default), "py", "exe", "dir" or "zip".
    format: Format | None = None
    # The most the output may be, in bytes: over it is an error, before writing (ADR-0039).
    max_size: int | None = None
    # No file over this many bytes (`--split`): a bundle that doesn't fit in one is written as a
    # small .pyz and a folder of parts beside it (ADR-0045).
    split: int | None = None
    # Run the finished .pyz once with these arguments, in a fresh home folder with no network
    # (`--smoke`); None: don't; (): the default, `--help`.
    smoke: tuple[str, ...] | None = None
    # More Python versions and platforms: a .pyz gets a payload for every combination of
    # [python, *more_pythons] and [python_platform, *more_python_platforms] (ADR-0038).
    more_pythons: tuple[str, ...] = ()
    more_python_platforms: tuple[str, ...] = ()
    # Packages the host Python already provides (`--external`, ADR-0051): left out of the bundle,
    # and the runtime keeps the host's site-packages on sys.path after the bundle's.
    external: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.path, str):
            object.__setattr__(self, "path", Path(self.path))
        if isinstance(self.output, str):
            object.__setattr__(self, "output", Path(self.output))
        if self.python is not None:
            py_raw = [self.python] if isinstance(self.python, str) else list(self.python)
            py_items = _split_items([*py_raw, *self.more_pythons], check_path=True, dedup=True)
            object.__setattr__(self, "python", py_items[0] if py_items else None)
            object.__setattr__(self, "more_pythons", tuple(py_items[1:]))
        elif self.more_pythons:
            object.__setattr__(
                self,
                "more_pythons",
                tuple(_split_items(self.more_pythons, check_path=True, dedup=True)),
            )
        if self.python_platform is not None:
            plat_raw = (
                [self.python_platform]
                if isinstance(self.python_platform, str)
                else list(self.python_platform)
            )
            plat_items = _split_items(
                [*plat_raw, *self.more_python_platforms], expand_platforms=True, dedup=True
            )
            object.__setattr__(self, "python_platform", plat_items[0] if plat_items else None)
            object.__setattr__(self, "more_python_platforms", tuple(plat_items[1:]))
        elif self.more_python_platforms:
            object.__setattr__(
                self,
                "more_python_platforms",
                tuple(_split_items(self.more_python_platforms, expand_platforms=True, dedup=True)),
            )
        ext_raw = [self.external] if isinstance(self.external, str) else list(self.external)
        object.__setattr__(self, "external", tuple(_split_items(ext_raw, dedup=True)))


def _expand_python_token(token: str) -> list[str]:
    """Expand a Python version range (`3.10-3.14`, `3.10..3.14`, `3.10+`) or PEP 440 specifier
    (`>=3.10`, `>=3.10,<3.14`) into individual minor versions (`["3.10", "3.11", ...]`)."""
    m = re.fullmatch(
        r"(?:py|cp|python)?3\.?(\d+)\s*(?:-|\.\.)\s*(?:(?:py|cp|python)?3\.?)?(\d+)",
        token,
        flags=re.IGNORECASE,
    )
    if m:
        low, high = int(m[1]), int(m[2])
        if 9 <= low <= high <= 20:
            return [f"3.{v}" for v in range(low, high + 1)]
    m_plus = re.fullmatch(r"(?:py|cp|python)?3\.?(\d+)\+", token, flags=re.IGNORECASE)
    if m_plus:
        low = int(m_plus[1])
        top = _coverage.MATRIX_PYTHONS[-1][1]
        if 9 <= low <= top:
            return [f"3.{v}" for v in range(low, top + 1)]
    if re.match(r"^(?:>=|<=|~=|==|>|<|!=)", token):
        from packaging.specifiers import InvalidSpecifier

        try:
            spec = SpecifierSet(token)
        except InvalidSpecifier:
            return [token]
        matched = [
            f"{v[0]}.{v[1]}"
            for v in _coverage.MATRIX_PYTHONS
            if any(spec.contains(f"{v[0]}.{v[1]}.{p}", prereleases=True) for p in (0, 99))
        ]
        if matched:
            return matched
    return [re.sub(r"^(?:py|cp|python)(3)\.?(\d+)$", r"\1.\2", token, flags=re.IGNORECASE)]


def _split_items(
    items: Sequence[str],
    *,
    check_path: bool = False,
    expand_platforms: bool = False,
    dedup: bool = False,
) -> list[str]:
    out: list[str] = []
    for raw in items:
        stripped = raw.strip()
        if (
            check_path
            and stripped
            and re.match(r"^(?:>=|<=|~=|==|>|<|!=)", stripped)
            and not Path(raw).exists()
        ):
            expanded_spec = _expand_python_token(stripped)
            if expanded_spec != [stripped]:
                for item in expanded_spec:
                    if not dedup or item not in out:
                        out.append(item)
                continue
        if "," in raw and not (check_path and Path(raw).exists()):
            parts = [p.strip() for p in raw.split(",") if p.strip()]
        else:
            parts = [stripped] if stripped else []
        for p in parts:
            if expand_platforms and p.lower() in ("all", "universal"):
                expanded = list(_platforms.ALL_PLATFORMS)
            elif check_path and "/" not in p and "\\" not in p and not Path(p).exists():
                expanded = _expand_python_token(p)
            else:
                expanded = [p]
            for item in expanded:
                if not dedup or item not in out:
                    out.append(item)
    return out


@dataclass(frozen=True)
class BuildResult:
    """A finished bundle. `to_json_dict()` is the `result` object of `bundleup build --json`."""

    output: Path
    size_bytes: int
    name: str
    version: str | None  # the project's version; None for a script
    packages: int  # distributions in the bundle, including the project itself
    native: bool  # contains compiled code, so it's tied to one CPU
    target: Target
    project_dir: Path
    duration_s: float
    timings: dict[str, float]  # seconds per build step, keyed by the slugs in STEPS
    # Warnings from the analysis (ADR-0024); in the --json document's `diagnostics`, not `result`.
    diagnostics: list[Diagnostic] = field(default_factory=list)
    format: str = "pyz"
    entry: str | None = None  # what runs: "module:function", "module", or the script's path
    pythons: PythonRange | None = None  # the versions it runs on; None means target.version
    reach: Portability | None = None  # whether it runs on any OS / CPU (ADR-0034)
    # A bundle for several platforms: each payload's target, as in `target` (ADR-0038).
    payloads: list[dict[str, object]] = field(default_factory=list)
    smoke: SmokeResult | None = None  # what --smoke ran, if it did
    # `--split`: the folder of parts beside `output`, when the bundle didn't fit in one file;
    # size_bytes counts them too.
    parts: Path | None = None

    @property
    def handler(self) -> str | None:
        """For Lambda: the handler setting, "module.function", if the entry is a function."""
        if self.entry and ":" in self.entry:
            module, function = self.entry.split(":", 1)
            return f"{module}.{function}"
        return None

    def to_json_dict(self) -> dict[str, object]:
        try:
            output = self.output.relative_to(self.project_dir).as_posix()
        except ValueError:
            output = str(self.output)
        parts = None
        if self.parts is not None:
            try:
                parts = self.parts.relative_to(self.project_dir).as_posix()
            except ValueError:
                parts = str(self.parts)
        return {
            "output": output,
            "parts": parts,
            "size_bytes": self.size_bytes,
            "name": self.name,
            "version": self.version,
            "packages": self.packages,
            "native": self.native,
            "target": self.target.to_json_dict(
                native=self.native, pythons=self.pythons, reach=self.reach
            ),
            "duration_s": round(self.duration_s, 3),
            "timings": {step: round(seconds, 3) for step, seconds in self.timings.items()},
            "format": self.format,
            "entry": self.entry,
            "payloads": self.payloads,
            "smoke": self.smoke.to_json_dict() if self.smoke else None,
        }


def build(
    options: BuildOptions, *, progress: Callable[[ProgressEvent], None] | None = None
) -> BuildResult:
    """Bundle a project or PEP 723 script into one .pyz (or a directory, or a Lambda zip).

    Raises a BundleupError subclass for every expected failure. Never prints; reports steps
    and commands through `progress` if given.
    """
    options, fmt = _settle(options)
    if options.output is not None:
        if not str(options.output).strip() or not options.output.absolute().name.strip():
            raise UsageError(f"-o {options.output} has no file name")
        _validate_output_path(options.output, fmt, "app.pyz")
    report = progress or ignore
    steps = Steps(report)
    combinations = _combinations(options)
    if len(combinations) > 1 and fmt == "exe":
        raise UsageError(
            "an executable is for one platform and Python version: it carries that interpreter",
            hint="build one per platform, each with one --python-platform",
        )
    if len(combinations) > 1 and fmt not in LOADED:
        raise UsageError(
            f"a {fmt} output is for one platform and Python version",
            hint="give one --python and one --python-platform, or build a .pyz or .py",
        )
    smoked: SmokeResult | None = None
    merge_pythons = _merge_candidates(options, fmt)
    with tempfile.TemporaryDirectory(prefix="bundleup-") as tmp:
        stage = Path(tmp)
        prepared: list[Prepared] = []
        for i, combination in enumerate(combinations):
            if _served(prepared, combination):
                continue  # an earlier pure-Python payload already runs there (ADR-0038)
            where = stage if len(combinations) == 1 else stage / f"target-{i}"
            where.mkdir(exist_ok=True)
            first = _prepare(
                combination,
                fmt=fmt,
                stage=where,
                steps=steps,
                progress=report,
                floor=_lowest(combinations),
                merge_pythons=merge_pythons,
            )
            prepared.append(first)
            if (
                fmt in LOADED
                and fmt != "exe"
                and combination.python is None
                and not options.more_pythons
                and merge_pythons
            ):
                unmergeable = first.merge_conflict and first.pythons.min == first.pythons.max
                fork_queue = [
                    (py_ver, () if unmergeable else merge_pythons)
                    for py_ver in _lock_fork_pythons(first, merge_pythons)
                ]
                while fork_queue:
                    py_ver, sub_merge = fork_queue.pop(0)
                    fork_comb = replace(combination, python=py_ver)
                    if _served(prepared, fork_comb):
                        continue
                    rem_merge = tuple(
                        v
                        for v in sub_merge
                        if not any(
                            p.target.platform == first.target.platform
                            and p.target.machine == first.target.machine
                            and p.pythons.contains(v)
                            for p in prepared
                        )
                    )
                    fork_where = stage / f"target-{i}-py{py_ver.replace('.', '')}"
                    fork_where.mkdir(exist_ok=True)
                    try:
                        fork_prep = _prepare(
                            fork_comb,
                            fmt=fmt,
                            stage=fork_where,
                            steps=steps,
                            progress=report,
                            floor=_lowest(combinations),
                            merge_pythons=rem_merge,
                            fork_of=first,
                        )
                    except BundleupError:
                        continue
                    if not any(d.level == "error" for d in fork_prep.diagnostics):
                        prepared.append(fork_prep)
                        if fork_prep.merge_conflict:
                            sub_unmergeable = fork_prep.pythons.min == fork_prep.pythons.max
                            fork_queue.extend(
                                (v, () if sub_unmergeable else merge_pythons)
                                for v in _lock_fork_pythons(fork_prep, merge_pythons)
                            )
        p = prepared[0]
        p_diagnostics = _merged_diagnostics(prepared)
        if options.smoke is not None and fmt in LOADED:
            smoke_p = _smoke_target(prepared, exe=fmt == "exe")
            if smoke_p is None:
                p_diagnostics.append(_SMOKE_SKIPPED)
            elif smoke_p.entry is not None and smoke_p.entry.kind == "python" and not options.smoke:
                raise UsageError(
                    "--smoke needs a script to run for --entry python",
                    hint="for example: --smoke 'scripts/tool.py --help'",
                )
        failing = [d for d in p_diagnostics if d.level == "error" or options.strict]
        if failing:
            raise CheckFailedError(
                f"found {_count(failing)}, so nothing was written",
                diagnostics=p_diagnostics,
                hint=_STRICT_HINT if not any(d.level == "error" for d in failing) else None,
            )
        name = safe_name(p.source.name)
        windows = p.target.platform == "win32"
        default = {
            "pyz": f"{name}.pyz",
            "py": f"{name}.py",
            "exe": f"{name}.exe" if windows else name,
            "dir": name,
        }.get(fmt, f"{name}.zip")
        raw_path = Path(os.path.abspath(options.path))
        workdir = raw_path.parent if p.source.is_script else raw_path
        output = Path(os.path.abspath(options.output or workdir / "dist" / default))
        _validate_output_path(output, fmt, default, p.source, p.own)
        _check_writable(output)
        diagnostics = list(p_diagnostics)
        if fmt in LOADED:
            # An executable carries a .pyz (ADR-0047): written here first, then wrapped.
            pyz = stage / "app.pyz" if fmt == "exe" else output
            diagnostics += write_pyz(
                prepared,
                pyz,
                fmt="pyz" if fmt == "exe" else fmt,
                stage=stage,
                steps=steps,
                progress=report,
                max_size=None if fmt == "exe" else options.max_size,
                strict=options.strict,
                split=options.split,
                warn_large=fmt != "exe",  # an executable's own size is checked below
                diagnostics=diagnostics,
            )
            if fmt == "exe":
                steps.start("interpreter")
                platform = p.target.python_platform or host_platform(p.target)
                version, found = write_exe(
                    pyz,
                    output,
                    uv=find_uv(),
                    target=p.target,
                    platform=platform,
                    stage=stage,
                    progress=report,
                    max_size=options.max_size,
                    strict=options.strict,
                    diagnostics=diagnostics,
                )
                diagnostics += found
                # Reported as what the file is (seventh review): this OS and CPU, the Python it
                # carries, nothing else; the .pyz inside may run more widely.
                p = replace(
                    p,
                    target=replace(p.target, full_version=version or p.target.full_version),
                    native=True,
                    pythons=PythonRange(p.target.version, p.target.version),
                    reach=Portability(any_os=False, any_cpu=False),
                )
                prepared = [p]
            if options.smoke is not None and not any(
                d.code == "smoke-skipped" for d in diagnostics
            ):
                steps.start("smoke")
                smoked, skipped = _smoke_run(prepared, output, options.smoke, exe=fmt == "exe")
                diagnostics += skipped
        elif fmt == "dir":
            check_dir_output(output)
            check_size(sum(x.size_bytes for x in p.sizes), options.max_size, diagnostics)
            write_dir(p, output, steps=steps)
        else:
            staged = stage_zip(p, stage=stage, steps=steps)
            check_size(staged.stat().st_size, options.max_size, diagnostics)
            with atomic_output(output) as partial:
                shutil.copyfile(staged, partial)
        steps.finish()
    size = output.stat().st_size if output.is_file() else sum(x.size_bytes for x in p.sizes)
    parts = output.with_name(f"{output.name}.parts")
    if fmt == "pyz" and options.split is not None and parts.is_dir():
        size += sum(x.stat().st_size for x in parts.iterdir())
    else:
        parts = None
    if fmt in LOADED and fmt != "exe" and options.python is None:
        note = _floor_note(p.source, min(x.pythons.min for x in prepared), p.target.version)
        if note:
            report(ProgressEvent("note", note))
    return BuildResult(
        output=output,
        size_bytes=size,
        parts=parts,
        name=p.source.name,
        version=p.version,
        packages=p.packages,
        native=p.native,
        target=p.target,
        project_dir=workdir,
        duration_s=time.perf_counter() - steps.started,
        timings=steps.timings,
        diagnostics=diagnostics,
        format=fmt,
        entry=str(p.entry) if p.entry else None,
        pythons=_combined_pythons(prepared),
        reach=p.reach,
        smoke=smoked,
        payloads=[
            x.target.to_json_dict(native=x.native, pythons=x.pythons, reach=x.reach)
            for x in prepared
        ]
        if len(prepared) > 1
        else [],
    )


def _check_writable(output: Path) -> None:
    """Fail with what to do, before zipping anything, if the output's folder can't be written:
    a read-only folder was reported as "bundleup crashed ... this is a bug" (twelfth review)."""
    folder = output.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent  # the one it would be made in: nothing is made until it's written
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=f".{output.name}.probe-"):
            pass
    except OSError as e:
        raise UsageError(
            f"can't write {output}: {e.strerror or e}",
            hint="pass -o with a folder you can write to",
        ) from None


def _merge_candidates(options: BuildOptions, fmt: Format) -> tuple[tuple[int, int], ...]:
    """The Python versions whose compiled extensions go into one payload (ADR-0052): those asked
    for, or with no --python every version bundles run on. Only for a bundle with a loader,
    which picks its Python at run time: a `dir` or `zip` is loaded by one known Python, and an
    executable brings its own (twelfth review: zips doubled in size for nothing)."""
    if fmt not in LOADED or fmt == "exe":
        return ()
    if options.more_pythons:
        asked = [
            (int(m[1]), int(m[2]))
            for v in (options.python, *options.more_pythons)
            if v and (m := re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", v))
        ]
        return tuple(asked) if len(asked) > 1 else ()
    return tuple(_coverage.MATRIX_PYTHONS) if options.python is None else ()


def _floor_note(source: Source, lowest: tuple[int, int], building: tuple[int, int]) -> str | None:
    """Say so when requires-python is what keeps a bundle off older Pythons and looks like what
    `uv init` writes there, the Python it ran on (`>=3.13` built with 3.13): nothing said why such
    a bundle refused macOS's own 3.9 (twelfth review, which also removed ADR-0052's silent
    lowering of it). A floor below the building Python was chosen: not repeated on every build."""
    if not source.requires_python or lowest <= OLDEST or lowest != building:
        return None
    try:
        spec = SpecifierSet(source.requires_python)
    except InvalidSpecifier:
        return None
    below = f"{lowest[0]}.{lowest[1] - 1}"
    if any(spec.contains(f"{below}.{patch}", prereleases=True) for patch in (0, 99)):
        return None  # it allows older ones: something else (a package, the code) limits the bundle
    where = "the script" if source.is_script else "pyproject.toml"
    relock = f"uv lock --script {source.path.name}" if source.is_script else "uv lock"
    return (
        f'requires-python "{source.requires_python}" in {where} limits this bundle to Python '
        f"{lowest[0]}.{lowest[1]} and newer (macOS's own is 3.9); if the code runs on older ones, "
        f"lower it and run `{relock}`"
    )


def _combined_pythons(prepared: list[Prepared]) -> PythonRange:
    """Coalesce contiguous or overlapping `PythonRange`s across `prepared` into one range when
    possible (e.g. `3.10-3.11` + `3.12-3.14` -> `3.10-3.14`)."""
    ranges = sorted(
        {(p.pythons.min, p.pythons.max) for p in prepared},
        key=lambda r: (r[0], r[1] or (99, 99)),
    )
    if not ranges:
        return prepared[0].pythons
    lo, hi = ranges[0]
    for nxt_lo, nxt_hi in ranges[1:]:
        if hi is None:
            break
        if nxt_lo[0] == hi[0] and nxt_lo[1] <= hi[1] + 1:
            hi = None if nxt_hi is None else max(hi, nxt_hi)
        else:
            return prepared[0].pythons
    return PythonRange(lo, hi)


def _lock_fork_pythons(first: Prepared, candidates: Sequence[tuple[int, int]]) -> list[str]:
    """Other Python versions in `candidates` where `first.pylock` selects a distinct set of
    packages or versions (e.g. `pyee 13.0.1` for `<3.12` vs `14.0.0` for `>=3.12`), or where
    `first` had untagged native extension conflicts (`first.merge_conflict`), with full wheel
    coverage on `first`'s target platform."""
    from packaging.specifiers import InvalidSpecifier, SpecifierSet

    from . import _toml as tomllib
    from . import _verify

    if (
        not candidates
        or first.target.implementation != "cpython"
        or all(first.pythons.contains(v) for v in candidates)
        or any(d.code == "python-range" for d in first.diagnostics)
    ):
        return []
    try:
        eff_platform = first.target.python_platform or host_platform(first.target)
        lock = first.pylock.read_text(encoding="utf-8")
        parsed = tomllib.loads(lock)
    except (OSError, ValueError, UsageError):
        return []

    dists = _verify.installed_distributions(first.site)
    eff_req = first.source.requires_python or ""
    # Never wider than the lock: outside its requires-python it may lack packages (twelfth review).
    lock_req = _verify.lock_requires_python(lock)
    specs: list[SpecifierSet] = []
    for raw_spec in (eff_req, lock_req):
        if raw_spec:
            try:
                specs.append(SpecifierSet(raw_spec))
            except InvalidSpecifier:
                continue
    has_wheels = {
        canonicalize_name(str(p.get("name", "")))
        for p in parsed.get("packages", [])
        if isinstance(p, dict) and p.get("name") and p.get("wheels")
    }
    own_tags: list[str] = []
    if first.source.packaged:
        own_name = canonicalize_name(first.source.name)
        for d in dists:
            if d.name == own_name:
                own_tags = _platforms.wheel_tags(first.site / d.dist_info)
                break
        if not own_tags or not _platforms.is_native(own_tags):
            has_wheels.add(own_name)
    seen_locks = (
        set()
        if first.merge_conflict
        else {frozenset(_verify.locked_packages(lock, first.target.markers))}
    )
    extra: list[str] = []
    for major, minor in candidates:
        if first.pythons.contains((major, minor)):
            continue
        if (
            own_tags
            and _platforms.is_native(own_tags)
            and not _platforms.wheel_allows_python(
                own_tags,
                (major, minor),
                abiflags=first.target.abiflags or "",
                platform=first.target.python_platform,
            )
        ):
            continue
        if not all(
            any(spec.contains(f"{major}.{minor}.{p}", prereleases=True) for p in (0, 99))
            for spec in specs
        ):
            continue
        full = f"{major}.{minor}.0"
        env = {
            **first.target.markers,
            "python_version": f"{major}.{minor}",
            "python_full_version": full,
            "implementation_version": full,
        }
        env_locked = frozenset(_verify.locked_packages(lock, env))
        if not env_locked or env_locked in seen_locks:
            continue
        if not ({p.name for p in env_locked} <= has_wheels):
            continue
        if _coverage.gaps(lock, eff_platform, (major, minor), abiflags=first.target.abiflags or ""):
            continue
        if not first.merge_conflict:
            seen_locks.add(env_locked)
        extra.append(f"{major}.{minor}")
    return extra


def _combinations(options: BuildOptions) -> list[BuildOptions]:
    """One set of options per Python version and platform asked for (ADR-0038)."""
    pythons = [options.python, *options.more_pythons]
    platforms = [options.python_platform, *options.more_python_platforms]
    single = {"more_pythons": (), "more_python_platforms": ()}
    return [
        replace(options, python=python, python_platform=platform, **single)
        for python in pythons
        for platform in platforms
    ]


# CPU names as Python reports them -> as targets name them.
CPUS = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64", "x86": "i686", "i386": "i686"}

_SMOKE_SKIPPED = Diagnostic(
    "smoke-skipped",
    "warning",
    "--smoke: the bundle is only for other platforms, so it can't run here",
    hint="run the smoke test on a machine it's built for (CI, say)",
)


def _smoke_target(prepared: list[Prepared], *, exe: bool = False) -> Prepared | None:
    import platform

    here = CPUS.get(platform.machine().lower(), platform.machine().lower())
    for p in prepared:
        machine = CPUS.get(p.target.machine.lower(), p.target.machine.lower())
        same_os = (not exe and p.reach.any_os) or p.target.platform == sys.platform
        any_cpu = not exe and (p.reach.any_cpu or not p.native)
        needs = runtime_needs(p.site, p.target)
        libc = needs.libc
        plat = p.target.python_platform
        if exe and plat and plat.sys_platform == "linux" and libc is None:
            libc = ("musl", (1, 2)) if plat.musl else ("glibc", (2, 17))
        fits_system = _loader._libc_fits(libc) and _loader._macos_fits(needs.macos)
        if same_os and (any_cpu or machine == here) and fits_system:
            return p
    return None


def _smoke_run(
    prepared: list[Prepared], output: Path, args: tuple[str, ...], *, exe: bool = False
) -> tuple[SmokeResult | None, list[Diagnostic]]:
    """`--smoke`: run the bundle with the interpreter of a payload that fits this machine (the
    one the build used); a bundle only for other platforms can't run here: a warning."""
    p = _smoke_target(prepared, exe=exe)
    if p is not None:
        if p.entry is not None and p.entry.kind == "python" and not args:
            raise UsageError(
                "--smoke needs a script to run for --entry python",
                hint="for example: --smoke 'scripts/tool.py --help'",
            )
        python = None if exe else p.target.executable  # an executable runs itself
        return _smoke.run(output, python, args or ("--help",)), []
    return None, [_SMOKE_SKIPPED]


def _lowest(combinations: list[BuildOptions]) -> tuple[int, int] | None:
    """The lowest Python version asked for: input without a lock is resolved from it for every
    payload, so they all bundle the same versions (fourth review: each resolved from its own)."""
    asked = [
        c.python for c in combinations if c.python and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", c.python)
    ]
    found = [(int(v.split(".")[0]), int(v.split(".")[1])) for v in asked]
    return min(found) if len(found) > 1 else None


def _served(prepared: list[Prepared], options: BuildOptions) -> bool:
    """Whether an already prepared payload runs on this combination too, so it needs no payload of
    its own: its Python range covers the version and either it's pure-Python (on any OS, or this
    OS/CPU) or its native wheels are Python-agnostic (`abi3` / `py3-none-<platform>`) for this
    exact target platform."""
    import platform as host_plat

    if options.python is None and prepared:
        wanted = prepared[0].target.version
    else:
        version = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", options.python or "")
        if version is None:
            return False  # uv's choice or an interpreter path: can't tell before building
        wanted = (int(version[1]), int(version[2]))
    platform = _platforms.parse(options.python_platform) if options.python_platform else None
    wanted_os = platform.sys_platform if platform else sys.platform
    raw_cpu = platform.arch if platform else host_plat.machine().lower()
    wanted_cpu = CPUS.get(raw_cpu, raw_cpu)
    for p in prepared:
        if not p.pythons.contains(wanted):
            continue
        if p.native:
            p_plat = p.target.python_platform
            if platform is not None and p_plat is not None:
                if replace(platform, name="") == replace(p_plat, name=""):
                    return True
            elif platform is None and p_plat is None:
                p_cpu = CPUS.get(p.target.machine.lower(), p.target.machine.lower())
                if wanted_os == p.target.platform and wanted_cpu == p_cpu:
                    return True
            continue
        if p.reach.any_os:
            return True
        p_cpu = CPUS.get(p.target.machine.lower(), p.target.machine.lower())
        if wanted_os == p.target.platform and (p.reach.any_cpu or wanted_cpu == p_cpu):
            return True
    return False


def _merged_diagnostics(prepared: list[Prepared]) -> list[Diagnostic]:
    """Every payload's findings, once each; for several payloads, each says which one it's about."""
    if len(prepared) == 1:
        return list(prepared[0].diagnostics)
    found: dict[tuple[str, str], tuple[Diagnostic, list[str]]] = {}
    for p in prepared:
        label = p.target.describe(p.native, p.pythons, p.reach)
        for d in p.diagnostics:
            found.setdefault((d.code, d.message), (d, []))[1].append(label)
    merged = [  # a finding every payload has is about the bundle: no label (fourth review)
        d
        if len(labels) == len(prepared)
        else replace(d, message=f"{d.message} [{'; '.join(labels)}]")
        for d, labels in found.values()
    ]
    return sorted(merged, key=lambda d: d.level != "error")


_STRICT_HINT = "--strict makes warnings fail too; build without it to allow them"


def _input_files(source: Source, own: Sequence[str]) -> set[Path]:
    files = {x.resolve() for x in (source.path, source.declared, source.pylock) if x is not None}
    if source.is_script:
        script_lock = source.path.with_name(f"{source.path.name}.lock")
        if script_lock.is_file():
            files.add(script_lock.resolve())
    else:
        if (uv_lock := find_uv_lock(source.path)) is not None:
            files.add(uv_lock.resolve())
        for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pylock.toml"):
            if (p := source.path / name).is_file():
                files.add(p.resolve())
        for rel in own:
            if (p := source.path / rel).is_file():
                files.add(p.resolve())
    return files


def _validate_output_path(
    output: Path,
    fmt: Format,
    default_name: str,
    source: Source | None = None,
    own: Sequence[str] = (),
) -> None:
    try:
        is_dir = output.is_dir()
        resolved_out = output.resolve() if source is not None else None
    except (OSError, RuntimeError) as e:
        raise UsageError(
            f"-o {output} cannot be accessed: {getattr(e, 'strerror', None) or e}"
        ) from None
    if fmt == "dir":
        check_dir_output(Path(os.path.abspath(output)))
    elif is_dir:
        raise UsageError(
            f"{output} is a directory",
            hint=f"give a file path (for example: -o {output / default_name}), or use --format dir",
        )
    if source is not None and resolved_out in _input_files(source, own):
        what = "the input script" if source.is_script else "the project's own files"
        raise UsageError(
            f"-o {output.name} would overwrite {what}",
            hint="choose another output path",
        )


def _settle(options: BuildOptions, *, for_check: bool = False) -> tuple[BuildOptions, Format]:
    """What `build` and `check` start from: [tool.bundleup] (ADR-0032) filled in, the format
    checked."""
    options, _configured = _config.apply(options, for_check=for_check)
    if options.smoke is not None and (options.format or "pyz") not in LOADED:
        raise UsageError(
            "--smoke runs a .pyz, .py or executable",
            hint=f"drop --smoke: a {options.format} output's host runs it",
        )
    if options.entry == "python" and (options.format or "pyz") not in LOADED:
        raise UsageError(
            "--entry python makes a .pyz, .py or executable that runs the scripts it's given",
            hint=f"drop --entry: a {options.format} output's host decides what runs",
        )
    if not for_check and options.smoke == () and options.entry == "python":
        raise UsageError(
            "--smoke needs a script to run for --entry python",
            hint="for example: --smoke 'scripts/tool.py --help'",
        )
    if options.split is not None and (options.format or "pyz") != "pyz":
        raise UsageError(
            "--split cuts a .pyz into parts",
            hint=f"drop --split: a {options.format} output is written as it is",
        )
    if options.external and (options.format or "pyz") in ("exe", "scie"):
        raise UsageError(
            "--external leaves packages to the host Python, and --format exe carries its own "
            "isolated Python",
            hint="drop --external to bundle every package into the executable, or build a .pyz",
        )
    if options.split is not None and options.split <= 0:
        raise UsageError("--split must be more than 0", hint="for example: --split 100MB")
    if options.max_size is not None and options.max_size <= 0:
        raise UsageError("--max-size must be more than 0", hint="for example: --max-size 30MB")
    return options, _format(options)


_FORMAT_HINTS = {
    "scie": "exe",
    "onefile": "exe",
    "binary": "exe",
    "standalone": "exe",
    "lambda": "zip",
    "aws": "zip",
    "pex": "pyz",
    "shiv": "pyz",
    "zipapp": "pyz",
}


def _format(options: BuildOptions) -> Format:
    for fmt in FORMATS:  # the library may be given any string
        if (options.format or "pyz") == fmt:
            return fmt
    suggest = _FORMAT_HINTS.get(str(options.format or "").lower())
    prefix = f"did you mean `{suggest}`? " if suggest else ""
    raise UsageError(
        f"unknown format `{options.format}`",
        hint=f"{prefix}use one of {', '.join(FORMATS)}",
    )


def _count(diags: list[Diagnostic]) -> str:
    errors = sum(d.level == "error" for d in diags)
    return findings(errors, len(diags) - errors)


def _wheel_coverage(pylock: Path, target: Target) -> list[Diagnostic]:
    """For another platform: refuse before installing if a locked package has no wheel for it
    (ADR-0031); warn about source-only packages, which uv builds here. Nothing for this machine:
    uv builds what it needs for it."""
    expected_tag = f"cpython-{target.version[0]}{target.version[1]}"
    platform = target.python_platform
    if platform is None and target.cache_tag != expected_tag:
        with contextlib.suppress(UsageError):
            platform = host_platform(target)
    if platform is None:
        return []
    lock = pylock.read_text(encoding="utf-8")
    abiflags = target.abiflags or ""
    found = _coverage.diagnostics(
        _coverage.gaps(lock, platform, target.version, abiflags=abiflags),
        platform,
        lock,
        abiflags=abiflags,
    )
    errors = [d for d in found if d.level == "error"]
    if errors:
        raise NoCompatibleWheelError(
            f"{plural(len(errors), 'package')} {'has' if len(errors) == 1 else 'have'} no wheel "
            f"for {platform.name}",
            detail="\n".join(d.message.split(": ", 1)[1] for d in errors),
            hint=errors[0].hint,
        )
    return found


def _also_platforms(pylock: Path, target: Target, names: Sequence[str]) -> list[Diagnostic]:
    """`bundleup check` with more `--python-platform` targets: the lock-only coverage check."""
    lock = pylock.read_text(encoding="utf-8")
    abiflags = target.abiflags or ""
    found: list[Diagnostic] = []
    for name in names:
        platform = _platforms.parse(name)
        found += _coverage.diagnostics(
            _coverage.gaps(lock, platform, target.version, abiflags=abiflags),
            platform,
            lock,
            abiflags=abiflags,
        )
    return found


# Folders whose code doesn't run in the bundle: tests and docs import pytest, sphinx and the like.
NOT_RUN = {"tests", "test", "docs", "doc", "examples"}


class _NoPythonLeft(BundleupError):
    """A payload for other Python versions than the build's own that its code can't run on."""


def _imports_of(code: list[tuple[str, Path, bool]]) -> list[tuple[str, dict[str, int], set[str]]]:
    """For each file of `_own_code`: what it imports for sure (-> first line), and the modules
    beside it, which a script imports from its own folder."""
    beside_cache: dict[Path, set[str]] = {}
    return [
        (
            shown,
            _imports.imports_with_lines(path),
            beside_cache.setdefault(path.parent, _imports.top_level_modules(path.parent))
            if beside
            else set(),
        )
        for shown, path, beside in code
    ]


def _own_imports(
    code: list[tuple[str, Path, bool]],
    imported: list[tuple[str, dict[str, int], set[str]]] | None = None,
) -> set[str]:
    """Every module the project's own code imports for sure, apart from its own neighbours."""
    found = _imports_of(code) if imported is None else imported
    return set().union(*(set(names) - local for _shown, names, local in found))


def _own_code(
    source: Source,
    site: Path,
    *,
    script: str | None,
    own: list[str],
    entry: Entry | None,
    owner: dict[str, _check._Owner] | None = None,
) -> list[tuple[str, Path, bool]]:
    """The code bundled from the input itself, whose imports the undeclared-import check reads:
    the script, a folder app's modules, or the project's own installed files; with `--entry
    python`, also the scripts in the input's folder that the bundle will be given (their
    neighbours import too, as when python runs a script)."""
    is_py_entry = entry is not None and entry.kind == "python"
    script_target = entry.target if entry is not None and entry.kind == "script" else None
    script_dir = script_target.rpartition("/")[0] if script_target and "/" in script_target else ""
    code = [(source.path.name, source.path, False)] if script else []
    code += [
        (
            rel,
            site / rel,
            is_py_entry
            or rel == script_target
            or (bool(script_dir) and rel.rpartition("/")[0] == script_dir),
        )
        for rel in own
        if rel.endswith(".py")
    ]
    if not source.is_script and not source.app:
        project = canonicalize_name(source.name)
        owned = owner if owner is not None else _check.owners(site, project=project)
        code += [
            (rel, site / rel, False)
            for rel, who in sorted(owned.items())
            if who.name == project and rel.endswith(".py") and (site / rel).is_file()
        ]
    if is_py_entry and not source.app:
        # A project's scripts anywhere under it (as git sees them); a script's neighbours only:
        # its folder may be ~/Downloads (fifth review).
        folder = source.path if source.path.is_dir() else source.path.parent
        bundled = _imports.top_level_modules(site)
        for rel, file in python_files(folder, deep=not source.is_script)[:MOST_SCRIPTS]:
            parts = rel.split("/")
            folders = set(parts[:-1])
            # Skip tests and docs, and the project's own packages anywhere (src/pkg/...): those
            # are read from the payload. (`src` itself isn't skipped; sixth review.)
            top_mods = {parts[0].removesuffix(".py")}
            if parts[:1] == ["src"] and len(parts) == 2:
                top_mods.add(parts[1].removesuffix(".py"))
            mine = (folders | top_mods) & bundled
            if file == source.path or folders & NOT_RUN or mine:
                continue
            code.append((rel, file, True))
    return code


MOST_SCRIPTS = 1000  # read at most this many scripts for --entry python


def _unlocked(source: Source, *, pinned: bool) -> list[Diagnostic]:
    """Input without a lock builds (ADR-0041), but its versions were resolved just now, so a
    later build can bundle different ones: a warning, with the way to lock. `--strict` or
    `--locked` make it an error."""
    if pinned:
        return []
    if source.is_script and source.pep723:
        meta = script_metadata(read_python_text(source.path))
        if not meta.get("dependencies"):
            return []
        name = source.path.name
        message = f"{name} has no lockfile"
        hint = (
            f"run `uv lock --script {name}` and keep {name}.lock next to it, "
            "or pin every dependency with =="
        )
    elif source.declared is not None and source.declared.suffix == ".txt":
        name = source.declared.name
        message = f"{name} doesn't pin every package it needs to one version (==)"
        hint = (
            "pin them all: `uv pip compile requirements.in -o requirements.txt "
            "--generate-hashes`, or `pip freeze > requirements.txt`"
        )
    elif source.declared is not None:
        name = source.declared.name
        message = f"{source.path.name} has no lockfile (uv.lock or pylock.toml)"
        hint = "lock it: `uv lock`, or `pip lock .` (pip 25.1+, writes pylock.toml)"
        if source.declared.name != "pyproject.toml":  # uv lock needs a pyproject.toml
            hint = "lock it: `pip lock .` (pip 25.1+, writes pylock.toml)"
    else:
        return []
    return [
        Diagnostic(
            "unlocked",
            "warning",
            f"{message}, so its dependencies were resolved just now; building again later can "
            "bundle different versions",
            hint=hint,
            file=name,
        )
    ]


def _format_diagnostics(fmt: Format, site: Path) -> list[Diagnostic]:
    """What only matters for `dir` and `zip` outputs, which run without bundleup's loader."""
    diags = []
    pth = pth_files(site)
    if fmt not in LOADED and pth:
        diags.append(
            Diagnostic(
                "pth-not-run",
                "warning",
                f"{', '.join(pth)} won't run: the host puts this directory on sys.path, and Python "
                "only runs .pth files in site-packages",
                hint="a .pyz runs them (its loader does); in a directory or zip output, whatever "
                "they set up (e.g. setuptools' distutils, pywin32's paths) is missing",
            )
        )
    return diags


def _prepare(
    options: BuildOptions,
    *,
    fmt: Format,
    stage: Path,
    steps: Steps,
    progress: Progress,
    floor: tuple[int, int] | None = None,
    for_check: bool = False,
    merge_pythons: Sequence[tuple[int, int]] = (),
    fork_of: Prepared | None = None,
) -> Prepared:
    """The steps `build` and `check` share: find the Python, read the lock, install, compile,
    analyze."""
    steps.start("python")
    uv = find_uv()
    source = (
        fork_of.source
        if fork_of is not None
        else load_source(options.path, external=options.external)
    )
    if options.external and fork_of is None:
        me = canonicalize_name(source.name)
        for ext in options.external:
            if canonicalize_name(re.split(r"[<>=!~;\[\s]", ext, maxsplit=1)[0].strip()) == me:
                raise UsageError(
                    f"--external {ext}: can't exclude {source.name} itself from the bundle",
                    hint="--external is for dependencies that the host Python already provides",
                )
    if fork_of is not None and options.python:
        parts = options.python.split(".")
        ver = (int(parts[0]), int(parts[1]))
        full = f"{ver[0]}.{ver[1]}.0"
        base_t = fork_of.target
        target = replace(
            base_t,
            version=ver,
            full_version=full,
            cache_tag=f"cpython-{ver[0]}{ver[1]}",
            markers={
                **base_t.markers,
                "python_version": f"{ver[0]}.{ver[1]}",
                "python_full_version": full,
                "implementation_version": full,
            },
        )
    else:
        target = find_python(
            uv,
            source,
            request=options.python,
            python_platform=options.python_platform,
            progress=progress,
        )
    check_requires_python(source, target)
    site = stage / "site"
    script = script_path(source, fmt)
    steps.start("export")
    exported = export(
        uv,
        source,
        lock_mode=options.lock_mode,
        python=min(floor, target.version) if floor else target.version,
        stage=stage,
        progress=progress,
        external=options.external,
        markers=target.markers,
        interpreter=target.executable,
    )
    pylock = exported.pylock
    coverage = _wheel_coverage(pylock, target)  # before installing: a precise error, early
    steps.start("install")
    own = install(
        uv,
        source,
        target=target,
        reqs=exported.installs,
        site=site,
        script=script,
        progress=progress,
        entry=options.entry,
    )
    check_wheel_platforms(site, target)
    merge_conflict = (
        merge_native_wheels(
            uv,
            source,
            site=site,
            pylock=pylock,
            target=target,
            candidates=merge_pythons,
            stage=stage,
            progress=progress,
        )
        if merge_pythons and not for_check
        else False
    )
    if fork_of is not None:
        entry = fork_of.entry
    elif fmt in LOADED or options.entry or script:
        try:
            entry = resolve_entry(
                source,
                site,
                entry=options.entry,
                script=script,
                target_version=target.version,
                external=options.external,
            )
        except EntryPointError:
            if not for_check or options.entry is not None:
                raise
            entry = (
                Entry("python", "")
                if (source.path / "SKILL.md").is_file()
                or (source.path / "scripts").is_dir()
                or not source.packaged
                else None
            )
    else:
        # A directory or a flat zip is imported, and its host decides what runs. A console
        # script is a CLI, not a module handler, so it's never guessed (the review found the
        # printed handler named one).
        entry = None
    packages, native = inspect_site(site)
    version = fork_of.version if fork_of is not None else project_version(site, source)
    if fmt in LOADED:
        add_runtime(site)
    if fork_of is not None:
        diagnostics = list(fork_of.diagnostics)
        sizes = fork_of.sizes
        pythons = python_range(site, pylock=pylock, target=target, source=source, native=native)
        owners = _check.owners(site, project=canonicalize_name(source.name), script=script, own=own)
        code = _own_code(source, site, script=script, own=own, entry=entry, owner=owners)
        imported = _own_imports(code)
        provided = _imports.provided_by(site) | _imports.external_modules(options.external)
        paths = [path for _shown, path, _beside in code]
        checked = _check.fork_range(pythons, code=paths, imported=imported, provided=provided)
        if checked is None:
            raise _NoPythonLeft(f"the code runs on none of Python {pythons}")
        pythons = checked
        reach = portability(pylock, target=target, pythons=pythons, native=native)
        return Prepared(
            source=source,
            target=target,
            site=site,
            pylock=pylock,
            script=script,
            entry=entry,
            packages=packages,
            native=native,
            version=version,
            diagnostics=diagnostics,
            sizes=sizes,
            pythons=pythons,
            reach=reach,
            own=tuple(own),
            external=options.external,
            merge_conflict=merge_conflict,
        )
    steps.start("compile")
    precompile(target, site, progress=progress, checked=fmt not in LOADED)
    steps.start("check")

    def run_python(cmd: list[str]) -> str:
        return run(cmd, what="checking the code", progress=progress, error=BundleupError)

    project_name = canonicalize_name(source.name)
    site_owners = _check.owners(site, project=project_name, script=script, own=own)
    diagnostics, sizes = _check.analyze(
        site,
        project=project_name,
        target=target,
        run=run_python,
        script=script,
        own=own,
        owner=site_owners,
    )
    secrets = [rel for rel in own if looks_secret(rel)]
    if secrets:
        diagnostics.append(
            Diagnostic(
                "secret-file",
                "warning",
                f"{', '.join(secrets[:5])}{' and more' if len(secrets) > 5 else ''} would go "
                "into the bundle, and look like secrets",
                hint="anyone with the bundle can read them: add them to .gitignore (bundleup "
                "follows it in a git repository) or move them out of the folder",
                file=secrets[0],
            )
        )
    code = _own_code(source, site, script=script, own=own, entry=entry, owner=site_owners)
    provided = _imports.provided_by(site) | _imports.external_modules(options.external)
    imported = _imports_of(code)
    code_paths = {shown: path for shown, path, _beside in code}
    diagnostics += _check.undeclared_imports(
        imported, provided, _imports.stdlib(target.version), paths=code_paths
    )
    diagnostics += _format_diagnostics(fmt, site)
    diagnostics += coverage
    diagnostics += _unlocked(source, pinned=exported.pinned)
    pythons = python_range(site, pylock=pylock, target=target, source=source, native=native)
    pythons, narrowed = _check.oldest_python(
        site,
        project=project_name,
        script=script,
        own=own,
        pythons=pythons,
        target=target,
        run=run_python,
        owner=site_owners,
    )
    diagnostics += narrowed
    every_import = _own_imports(code, imported)
    pythons, by_stdlib = _check.stdlib_range(pythons, target.version, every_import, provided)
    diagnostics += by_stdlib
    reach = portability(pylock, target=target, pythons=pythons, native=native)
    diagnostics.sort(key=lambda d: d.level != "error")
    return Prepared(
        source=source,
        target=target,
        site=site,
        pylock=pylock,
        script=script,
        entry=entry,
        packages=packages,
        native=native,
        version=version,
        diagnostics=diagnostics,
        sizes=sizes,
        pythons=pythons,
        reach=reach,
        own=tuple(own),
        external=options.external,
        merge_conflict=merge_conflict,
    )


def check(
    options: BuildOptions,
    *,
    progress: Callable[[ProgressEvent], None] | None = None,
    also_platforms: Sequence[str] = (),
    matrix: bool = False,
) -> CheckReport:
    """Install, compile and analyze like `build`, without writing anything: what won't survive
    bundling (for `options.format`), and how big each package is. Findings are in the report
    (`ok` is False when there are errors); raises a BundleupError subclass only when the build
    itself fails. `options.output` and `options.strict` are ignored. `also_platforms`: more uv
    platform names to check from the lock alone (ADR-0031), for the same Python version (or pass
    multiple `python_platform` entries on `options`). `matrix`: wheel coverage for every platform
    and Python version (`report.matrix`)."""
    if options.more_pythons:
        raise UsageError(
            "check looks at one Python version at a time",
            hint="--matrix shows every platform and Python version from the lock",
        )
    options, fmt = _settle(options, for_check=True)
    if options.more_python_platforms:
        also_platforms = (*options.more_python_platforms, *also_platforms)
    options = replace(options, more_pythons=(), more_python_platforms=())
    primary = (
        replace(_platforms.parse(options.python_platform), name="")
        if options.python_platform
        else None
    )
    seen_platforms = {primary} if primary is not None else set()
    others: list[str] = []
    for name in also_platforms:  # bad names fail first
        parsed = _platforms.parse(name)
        key = replace(parsed, name="")
        if key not in seen_platforms:
            seen_platforms.add(key)
            others.append(parsed.name)
    report = progress or ignore
    steps = Steps(report)
    with tempfile.TemporaryDirectory(prefix="bundleup-") as tmp:
        p = _prepare(
            options, fmt=fmt, stage=Path(tmp), steps=steps, progress=report, for_check=True
        )
        check_pythons = (
            _check_merged_pythons(p, _coverage.MATRIX_PYTHONS)
            if options.python is None and fmt in LOADED and fmt != "exe"
            else p.pythons
        )
        extra = _also_platforms(p.pylock, p.target, others)
        cells = _matrix(p.pylock, p.source) if matrix else []
        steps.finish()
    return CheckReport(
        name=p.source.name,
        version=p.version,
        target=p.target,
        native=p.native,
        packages=p.sizes,
        diagnostics=sorted([*p.diagnostics, *extra], key=lambda d: d.level != "error"),
        duration_s=time.perf_counter() - steps.started,
        pythons=check_pythons,
        reach=p.reach,
        matrix=cells,
        also_platforms=others,
    )


def _check_merged_pythons(p: Prepared, candidates: Sequence[tuple[int, int]]) -> PythonRange:
    """In `bundleup check` (when `--python` is not pinned), report the widened `PythonRange` that
    `bundleup build` produces via `merge_native_wheels` and `_lock_fork_pythons`, computed from
    `p.pylock` without downloading additional wheels."""
    from packaging.specifiers import InvalidSpecifier

    from . import _verify

    if (
        not candidates
        or p.target.implementation != "cpython"
        or any(d.code == "python-range" for d in p.diagnostics)
    ):
        return p.pythons
    try:
        eff_platform = p.target.python_platform or host_platform(p.target)
        lock = p.pylock.read_text(encoding="utf-8")
        parsed = tomllib.loads(lock)
    except (OSError, ValueError, UsageError):
        return p.pythons
    dists = _verify.installed_distributions(p.site)
    eff_req = p.source.requires_python or ""
    # Never wider than the lock: outside its requires-python it may lack packages (twelfth review).
    lock_req = _verify.lock_requires_python(lock)
    specs: list[SpecifierSet] = []
    for raw_spec in (eff_req, lock_req):
        if raw_spec:
            try:
                specs.append(SpecifierSet(raw_spec))
            except InvalidSpecifier:
                continue
    has_wheels = {
        canonicalize_name(str(pkg.get("name", "")))
        for pkg in parsed.get("packages", [])
        if isinstance(pkg, dict) and pkg.get("name") and pkg.get("wheels")
    }
    own_tags: list[str] = []
    if p.source.packaged:
        own_name = canonicalize_name(p.source.name)
        for d in dists:
            if d.name == own_name:
                own_tags = _platforms.wheel_tags(p.site / d.dist_info)
                break
        if not own_tags or not _platforms.is_native(own_tags):
            has_wheels.add(own_name)
    covered = [v for v in candidates if p.pythons.contains(v)]
    for major, minor in candidates:
        if (major, minor) in covered:
            continue
        if (
            own_tags
            and _platforms.is_native(own_tags)
            and not _platforms.wheel_allows_python(
                own_tags,
                (major, minor),
                abiflags=p.target.abiflags or "",
                platform=p.target.python_platform,
            )
        ):
            continue
        if not all(
            any(spec.contains(f"{major}.{minor}.{patch}", prereleases=True) for patch in (0, 99))
            for spec in specs
        ):
            continue
        full = f"{major}.{minor}.0"
        env = {
            **p.target.markers,
            "python_version": f"{major}.{minor}",
            "python_full_version": full,
            "implementation_version": full,
        }
        env_locked = _verify.locked_packages(lock, env)
        if not env_locked or not ({pkg.name for pkg in env_locked} <= has_wheels):
            continue
        if _coverage.gaps(lock, eff_platform, (major, minor), abiflags=p.target.abiflags or ""):
            continue
        covered.append((major, minor))
    if not covered:
        return p.pythons
    covered.sort()
    here = p.target.version
    if here not in covered:
        return p.pythons
    idx = covered.index(here)
    lo = idx
    while lo > 0 and covered[lo - 1][1] == covered[lo][1] - 1:
        lo -= 1
    hi = idx
    while hi + 1 < len(covered) and covered[hi + 1][1] == covered[hi][1] + 1:
        hi += 1
    min_v = min(p.pythons.min, covered[lo])
    max_v = None if p.pythons.max is None else max(p.pythons.max, covered[hi])
    return PythonRange(min_v, max_v)


def _matrix(pylock: Path, source: Source) -> list[_coverage.MatrixCell]:
    """`check --matrix`: wheel coverage for every platform and every Python the project allows
    (and the lock covers: one resolved at build time starts at the target's version)."""
    from packaging.specifiers import InvalidSpecifier

    text = pylock.read_text(encoding="utf-8")
    raw_covered = tomllib.loads(text).get("requires-python")
    covered = raw_covered if isinstance(raw_covered, str) else ""
    try:
        spec = SpecifierSet(source.requires_python or "") & SpecifierSet(covered)
    except (InvalidSpecifier, TypeError):
        spec = SpecifierSet()
    pythons = [
        v
        for v in _coverage.MATRIX_PYTHONS
        if any(spec.contains(f"{v[0]}.{v[1]}.{p}", prereleases=True) for p in (0, 99))
    ]
    return _coverage.matrix(text, pythons)
