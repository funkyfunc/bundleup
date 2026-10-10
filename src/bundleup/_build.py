"""Build a bundle (or just check one): the steps in order, from finding the Python to writing
the output. Each step lives in its own module: _source, _python, _uv, _payload, _outputs."""

from __future__ import annotations

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

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from . import (
    _audit,
    _check,
    _config,
    _coverage,
    _imports,
    _platforms,
    _smoke,
    _target_files,
    _verify,
)
from . import _toml as tomllib
from ._check import CheckReport
from ._errors import (
    BundleupError,
    CheckFailedError,
    Diagnostic,
    NoCompatibleWheelError,
    UsageError,
)
from ._exe import host_platform, write_exe
from ._formats import FORMATS, LOADED, Format
from ._outputs import (
    LAMBDA_UNZIPPED,
    LAMBDA_UPLOAD,
    check_size,
    lambda_upload_warning,
    stage_lambda,
    write_dir,
    write_pyz,
)
from ._payload import (
    Entry,
    Prepared,
    check_wheel_platforms,
    inspect_site,
    portability,
    precompile,
    pth_files,
    python_range,
    resolve_entry,
)
from ._python import (
    Portability,
    PythonRange,
    Target,
    check_requires_python,
    fetch_interpreter,
    find_interpreter,
    find_python,
)
from ._smoke import SmokeResult
from ._source import (
    Source,
    load_source,
    looks_secret,
    project_version,
    python_files,
    safe_name,
    script_metadata,
    script_path,
)
from ._steps import Progress, ProgressEvent, Steps, ignore, run
from ._target_files import TargetFile
from ._text import findings, plural
from ._uv import add_runtime, export, find_uv, install


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
    # What to write (ADR-0025, ADR-0046): "pyz" (the default), "py", "dir" or "lambda".
    format: Format | None = None
    # The most the output may be, in bytes: over it is an error, before writing (ADR-0039).
    max_size: int | None = None
    # No file over this many bytes (`--split`): a bundle that doesn't fit in one is written as a
    # small .pyz and a folder of parts beside it (ADR-0045).
    split: int | None = None
    # A destination described as data (`--against FILE`, ADR-0044): its settings fill what isn't
    # set, and the result reports its facts.
    against: Path | None = None
    # Run the finished .pyz once with these arguments, in a fresh home folder with no network
    # (`--smoke`); None: don't; (): the default, `--help`.
    smoke: tuple[str, ...] | None = None
    # More Python versions and platforms: a .pyz gets a payload for every combination of
    # [python, *more_pythons] and [python_platform, *more_python_platforms] (ADR-0038).
    more_pythons: tuple[str, ...] = ()
    more_python_platforms: tuple[str, ...] = ()


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
    against: TargetFile | None = None  # the --against file, if one was given
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
            "against": self.against.to_json_dict() if self.against else None,
        }


def build(
    options: BuildOptions, *, progress: Callable[[ProgressEvent], None] | None = None
) -> BuildResult:
    """Bundle a project or PEP 723 script into one .pyz (or a directory, or a Lambda zip).

    Raises a BundleupError subclass for every expected failure. Never prints; reports steps
    and commands through `progress` if given.
    """
    options, fmt = _settle(options)
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
    with tempfile.TemporaryDirectory(prefix="bundleup-") as tmp:
        stage = Path(tmp)
        prepared: list[Prepared] = []
        for i, combination in enumerate(combinations):
            if _served(prepared, combination):
                continue  # an earlier pure-Python payload already runs there (ADR-0038)
            where = stage if len(combinations) == 1 else stage / f"target-{i}"
            where.mkdir(exist_ok=True)
            prepared.append(
                _prepare(
                    combination,
                    fmt=fmt,
                    stage=where,
                    steps=steps,
                    progress=report,
                    floor=_lowest(combinations),
                )
            )
        p = prepared[0]
        p_diagnostics = _merged_diagnostics(prepared)
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
        }.get(fmt, f"{name}-lambda.zip")
        output = (options.output or p.source.workdir / "dist" / default).absolute()
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
            if options.smoke is not None:
                steps.start("smoke")
                smoked, skipped = _smoke_run(prepared, output, options.smoke, exe=fmt == "exe")
                diagnostics += skipped
        elif fmt == "dir":
            check_size(sum(x.size_bytes for x in p.sizes), options.max_size, diagnostics)
            write_dir(p, output, steps=steps)
        else:
            staged = stage_lambda(p, stage=stage, steps=steps)
            check_size(staged.stat().st_size, options.max_size, diagnostics)
            if staged.stat().st_size > LAMBDA_UPLOAD:
                diagnostics.append(lambda_upload_warning(output))
                if options.strict:  # checked before writing: an earlier zip stays untouched
                    raise CheckFailedError(
                        "found 1 warning, so nothing was written",
                        diagnostics=diagnostics,
                        hint=_STRICT_HINT,
                    )
            # Next to the output, then renamed over it: never a half-written zip at `output`.
            output.parent.mkdir(parents=True, exist_ok=True)
            partial = output.with_name(f".{output.name}.tmp-{os.getpid()}")
            shutil.copyfile(staged, partial)
            partial.replace(output)
        steps.finish()
    size = output.stat().st_size if output.is_file() else sum(x.size_bytes for x in p.sizes)
    parts = output.with_name(f"{output.name}.parts")
    if fmt == "pyz" and options.split is not None and parts.is_dir():
        size += sum(x.stat().st_size for x in parts.iterdir())
    else:
        parts = None
    return BuildResult(
        output=output,
        size_bytes=size,
        parts=parts,
        name=p.source.name,
        version=p.version,
        packages=p.packages,
        native=p.native,
        target=p.target,
        project_dir=p.source.workdir,
        duration_s=time.perf_counter() - steps.started,
        timings=steps.timings,
        diagnostics=diagnostics,
        format=fmt,
        entry=str(p.entry) if p.entry else None,
        pythons=p.pythons,
        reach=p.reach,
        smoke=smoked,
        against=_target_files.load(options.against) if options.against else None,
        payloads=[
            x.target.to_json_dict(native=x.native, pythons=x.pythons, reach=x.reach)
            for x in prepared
        ]
        if len(prepared) > 1
        else [],
    )


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
CPUS = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64"}


def _smoke_run(
    prepared: list[Prepared], output: Path, args: tuple[str, ...], *, exe: bool = False
) -> tuple[SmokeResult | None, list[Diagnostic]]:
    """`--smoke`: run the bundle with the interpreter of a payload that fits this machine (the
    one the build used); a bundle only for other platforms can't run here: a warning."""
    import platform

    here = CPUS.get(platform.machine().lower(), platform.machine().lower())
    for p in prepared:
        machine = CPUS.get(p.target.machine.lower(), p.target.machine.lower())
        same_os = p.reach.any_os or p.target.platform == sys.platform
        if same_os and (p.reach.any_cpu or not p.native or machine == here):
            if p.entry is not None and p.entry.kind == "python" and not args:
                raise UsageError(
                    "--smoke needs a script to run for --entry python",
                    hint="for example: --smoke 'scripts/tool.py --help'",
                )
            python = None if exe else p.target.executable  # an executable runs itself
            return _smoke.run(output, python, args or ("--help",)), []
    return None, [
        Diagnostic(
            "smoke-skipped",
            "warning",
            "--smoke: the bundle is only for other platforms, so it can't run here",
            hint="run the smoke test on a machine it's built for (CI, say)",
        )
    ]


def _audit_lock(pylock: Path, target: Target) -> list[Diagnostic]:
    """`check --audit`: the locked packages for this target that come from PyPI, checked there."""
    text = pylock.read_text(encoding="utf-8")
    selected = {canonicalize_name(p.name) for p in _verify.locked_packages(text, target.markers)}
    return _audit.audit(_audit.from_pypi(text, selected))


def _lowest(combinations: list[BuildOptions]) -> tuple[int, int] | None:
    """The lowest Python version asked for: input without a lock is resolved from it for every
    payload, so they all bundle the same versions (fourth review: each resolved from its own)."""
    asked = [c.python for c in combinations if c.python and re.fullmatch(r"\d+\.\d+", c.python)]
    found = [(int(v.split(".")[0]), int(v.split(".")[1])) for v in asked]
    return min(found) if len(found) > 1 else None


def _served(prepared: list[Prepared], options: BuildOptions) -> bool:
    """Whether an already prepared pure-Python payload runs on this combination too, so it needs
    no payload of its own: its Python range covers the version and it runs on any OS (or on this
    one, any CPU)."""
    version = re.fullmatch(r"(\d+)\.(\d+)", options.python or "")
    if version is None:
        return False  # uv's choice or an interpreter path: can't tell before building
    wanted = (int(version[1]), int(version[2]))
    platform = _platforms.parse(options.python_platform) if options.python_platform else None
    for p in prepared:
        if p.native or not p.pythons.contains(wanted):
            continue
        if p.reach.any_os:
            return True
        if platform and p.reach.any_cpu and platform.sys_platform == p.target.platform:
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


def _settle(options: BuildOptions) -> tuple[BuildOptions, Format]:
    """What `build` and `check` start from: the --against file's settings (ADR-0044), then
    [tool.bundleup] (ADR-0032) filled in, the format checked."""
    if options.against is not None:
        options = _target_files.apply(options, _target_files.load(options.against))
    options, _configured = _config.apply(options)
    if options.smoke is not None and (options.format or "pyz") not in LOADED:
        raise UsageError(
            "--smoke runs a .pyz or .py",
            hint=f"drop --smoke: a {options.format} output's host runs it",
        )
    if options.entry == "python" and (options.format or "pyz") not in LOADED:
        raise UsageError(
            "--entry python makes a .pyz or .py that runs the scripts it's given",
            hint=f"drop --entry: a {options.format} output's host decides what runs",
        )
    if options.split is not None and (options.format or "pyz") != "pyz":
        raise UsageError(
            "--split cuts a .pyz into parts",
            hint=f"drop --split: a {options.format} output is written as it is",
        )
    if options.split is not None and options.split <= 0:
        raise UsageError("--split must be more than 0", hint="for example: --split 100MB")
    if options.max_size is not None and options.max_size <= 0:
        raise UsageError("--max-size must be more than 0", hint="for example: --max-size 30MB")
    return options, _format(options)


def _format(options: BuildOptions) -> Format:
    for fmt in FORMATS:  # the library may be given any string
        if (options.format or "pyz") == fmt:
            return fmt
    raise UsageError(f"unknown format `{options.format}`", hint=f"use one of {', '.join(FORMATS)}")


def _count(diags: list[Diagnostic]) -> str:
    errors = sum(d.level == "error" for d in diags)
    return findings(errors, len(diags) - errors)


def _wheel_coverage(pylock: Path, target: Target) -> list[Diagnostic]:
    """For another platform: refuse before installing if a locked package has no wheel for it
    (ADR-0031); warn about source-only packages, which uv builds here. Nothing for this machine:
    uv builds what it needs for it."""
    platform = target.python_platform
    if platform is None:
        return []
    lock = pylock.read_text(encoding="utf-8")
    found = _coverage.diagnostics(_coverage.gaps(lock, platform, target.version), platform, lock)
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
    """`bundleup check --also-platform`: the lock-only coverage check for more targets."""
    lock = pylock.read_text(encoding="utf-8")
    found: list[Diagnostic] = []
    for name in names:
        platform = _platforms.parse(name)
        found += _coverage.diagnostics(
            _coverage.gaps(lock, platform, target.version), platform, lock
        )
    return found


# Folders whose code doesn't run in the bundle: tests and docs import pytest, sphinx and the like.
NOT_RUN = {"tests", "test", "docs", "doc", "examples"}


def _own_code(
    source: Source, site: Path, *, script: str | None, own: list[str], entry: Entry | None
) -> list[tuple[str, Path, bool]]:
    """The code bundled from the input itself, whose imports the undeclared-import check reads:
    the script, a folder app's modules, or the project's own installed files; with `--entry
    python`, also the scripts in the input's folder that the bundle will be given (their
    neighbours import too, as when python runs a script)."""
    code = [(source.path.name, site / script, False)] if script else []
    code += [(rel, site / rel, False) for rel in own if rel.endswith(".py")]
    if not source.is_script and not source.app:
        project = canonicalize_name(source.name)
        owned = _check.owners(site, project=project)
        code += [
            (rel, site / rel, False)
            for rel, owner in sorted(owned.items())
            if owner.name == project and rel.endswith(".py") and (site / rel).is_file()
        ]
    if entry is not None and entry.kind == "python":
        # A project's or folder app's scripts anywhere under it (as git sees them); a script's
        # neighbours only: its folder may be ~/Downloads (fifth review).
        folder = source.path if source.path.is_dir() else source.path.parent
        bundled = _imports.top_level_modules(site)
        for rel, file in python_files(folder, deep=not source.is_script)[:MOST_SCRIPTS]:
            parts = rel.split("/")
            folders = set(parts[:-1])
            # Skip tests and docs, and the project's own packages anywhere (src/pkg/...): those
            # are read from the payload. (`src` itself isn't skipped; sixth review.)
            mine = (folders | {parts[0].removesuffix(".py")}) & bundled
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
        meta = script_metadata(source.path.read_text(encoding="utf-8"))
        if not meta.get("dependencies"):
            return []
        name = source.path.name
        message = f"{name} has no lockfile"
        hint = f"run `uv lock --script {name}` and keep {name}.lock next to it"
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


def _format_diagnostics(
    fmt: Format, site: Path, sizes: list[_check.PackageSize]
) -> list[Diagnostic]:
    """What only matters for `dir` and `lambda` outputs, which run without bundleup's loader."""
    diags = []
    pth = pth_files(site)
    if fmt not in LOADED and pth:
        diags.append(
            Diagnostic(
                "pth-not-run",
                "warning",
                f"{', '.join(pth)} won't run: the host puts this directory on sys.path, and Python "
                "only runs .pth files in site-packages",
                hint="a .pyz runs them (its loader does); in a directory output, whatever they set "
                "up (e.g. setuptools' distutils, pywin32's paths) is missing",
            )
        )
    unzipped = sum(x.size_bytes for x in sizes)
    if fmt == "lambda" and unzipped > LAMBDA_UNZIPPED:
        largest = ", ".join(f"{x.name} {x.size_bytes / 1e6:.0f} MB" for x in sizes[:3])
        diags.append(
            Diagnostic(
                "lambda-too-big",
                "error",
                f"the function would be {unzipped / 1e6:.0f} MB unzipped; Lambda allows 250 MB "
                "including layers",
                hint=f"largest: {largest}; use a container image for bigger functions",
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
) -> Prepared:
    """The steps `build` and `check` share: find the Python, read the lock, install, compile,
    analyze."""
    steps.start("python")
    uv = find_uv()
    source = load_source(options.path)
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
    )
    check_wheel_platforms(site, target)
    if fmt in LOADED or options.entry or script:
        entry = resolve_entry(source, site, entry=options.entry, script=script)
    else:
        # A directory or a Lambda zip is imported, and its host decides what runs. A console
        # script is a CLI, not a Lambda handler, so it's never guessed (the review found the
        # printed handler named one).
        entry = None
    packages, native = inspect_site(site)
    version = project_version(site, source)
    if fmt in LOADED:
        add_runtime(site)
    steps.start("compile")
    precompile(target, site, progress=progress, checked=fmt not in LOADED)
    steps.start("check")

    def run_python(cmd: list[str]) -> str:
        return run(cmd, what="checking the code", progress=progress, error=BundleupError)

    diagnostics, sizes = _check.analyze(
        site, project=canonicalize_name(source.name), target=target, run=run_python, script=script
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
    code = _own_code(source, site, script=script, own=own, entry=entry)
    provided = _imports.provided_by(site)
    imported = [
        (
            shown,
            _imports.imports_of(path),
            _imports.top_level_modules(path.parent) if beside else set(),
        )
        for shown, path, beside in code
    ]
    diagnostics += _check.undeclared_imports(imported, provided, _imports.stdlib(target.version))
    diagnostics += _format_diagnostics(fmt, site, sizes)
    diagnostics += coverage
    diagnostics += _unlocked(source, pinned=exported.pinned)
    pythons = python_range(site, pylock=pylock, target=target, source=source, native=native)
    interpreters = {
        (3, minor): find_interpreter(uv, f"3.{minor}", cwd=stage, progress=progress)
        for minor in range(pythons.min[1], target.version[1])
    }
    if pythons.min in interpreters and interpreters[pythons.min] is None:
        oldest = f"{pythons.min[0]}.{pythons.min[1]}"
        interpreters[pythons.min] = fetch_interpreter(uv, oldest, cwd=stage, progress=progress)
    pythons, narrowed = _check.oldest_python(
        site,
        project=canonicalize_name(source.name),
        script=script,
        pythons=pythons,
        target=target,
        interpreters=interpreters,
        run=run_python,
    )
    diagnostics += narrowed
    every_import = set().union(*(names for _shown, names, _local in imported))
    pythons, by_stdlib = _check.stdlib_range(pythons, target.version, every_import, provided)
    diagnostics += by_stdlib
    reach = portability(pylock, target=target, pythons=pythons, native=native)
    if fmt == "lambda" and target.platform != "linux" and not reach.any_os:
        diagnostics.append(
            Diagnostic(
                "lambda-not-linux",
                "error",
                "AWS Lambda runs Linux, but this was built for "
                + target.describe(native, pythons, reach),
                hint="add --python-platform x86_64-manylinux_2_34 or aarch64-manylinux_2_34 "
                "(Lambda's Python 3.12+); docs/recipes.md lists the others",
            )
        )
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
    )


def check(
    options: BuildOptions,
    *,
    progress: Callable[[ProgressEvent], None] | None = None,
    also_platforms: Sequence[str] = (),
    matrix: bool = False,
    audit: bool = False,
) -> CheckReport:
    """Install, compile and analyze like `build`, without writing anything: what won't survive
    bundling (for `options.format`), and how big each package is. Findings are in the report
    (`ok` is False when there are errors); raises a BundleupError subclass only when the build
    itself fails. `options.output` and `options.strict` are ignored. `also_platforms`: more uv
    platform names to check from the lock alone (ADR-0031), for the same Python version.
    `matrix`: wheel coverage for every platform and Python version (`report.matrix`).
    `audit`: supply-chain checks on the locked packages, from PyPI (needs the network)."""
    options, fmt = _settle(options)
    if options.more_pythons or options.more_python_platforms:
        raise UsageError(
            "check looks at one Python version and platform at a time",
            hint="--matrix shows every platform and Python version from the lock",
        )
    others = [_platforms.parse(name).name for name in also_platforms]  # bad names fail first
    report = progress or ignore
    steps = Steps(report)
    with tempfile.TemporaryDirectory(prefix="bundleup-") as tmp:
        p = _prepare(options, fmt=fmt, stage=Path(tmp), steps=steps, progress=report)
        extra = _also_platforms(p.pylock, p.target, others)
        cells = _matrix(p.pylock, p.source) if matrix else []
        if audit:
            steps.start("audit")
            extra += _audit_lock(p.pylock, p.target)
        steps.finish()
    return CheckReport(
        name=p.source.name,
        version=p.version,
        target=p.target,
        native=p.native,
        packages=p.sizes,
        diagnostics=sorted([*p.diagnostics, *extra], key=lambda d: d.level != "error"),
        duration_s=time.perf_counter() - steps.started,
        pythons=p.pythons,
        reach=p.reach,
        matrix=cells,
        against=_target_files.load(options.against) if options.against else None,
        also_platforms=others,
    )


def _matrix(pylock: Path, source: Source) -> list[_coverage.MatrixCell]:
    """`check --matrix`: wheel coverage for every platform and every Python the project allows
    (and the lock covers: one resolved at build time starts at the target's version)."""
    text = pylock.read_text(encoding="utf-8")
    covered = tomllib.loads(text).get("requires-python") or ""
    spec = SpecifierSet(source.requires_python or "") & SpecifierSet(covered)
    pythons = [v for v in _coverage.MATRIX_PYTHONS if spec.contains(f"{v[0]}.{v[1]}.0")]
    return _coverage.matrix(text, pythons)
