"""Build a bundle (or just check one): the steps in order, from finding the Python to writing
the output. Each step lives in its own module: _source, _python, _uv, _payload, _outputs."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Literal

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from . import _check, _config, _coverage, _platforms, _targets
from ._check import CheckReport
from ._errors import (
    BundleupError,
    CheckFailedError,
    Diagnostic,
    NoCompatibleWheelError,
    UsageError,
)
from ._outputs import (
    LAMBDA_UNZIPPED,
    LAMBDA_UPLOAD,
    lambda_upload_warning,
    stage_lambda,
    write_dir,
    write_pyz,
)
from ._payload import (
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
from ._source import Source, load_source, project_version, safe_name, script_metadata, script_path
from ._steps import Progress, ProgressEvent, Steps, ignore, run
from ._targets import FORMATS, Format
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
    # What to write (ADR-0025): "pyz" (the default), "dir" or "lambda".
    format: Format | None = None
    target: str | None = None  # a preset such as "lambda" (`bundleup targets`); flags win
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
        return {
            "output": output,
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
        }


def build(
    options: BuildOptions, *, progress: Callable[[ProgressEvent], None] | None = None
) -> BuildResult:
    """Bundle a project or PEP 723 script into one .pyz (or a directory, or a Lambda zip).

    Raises a BundleupError subclass for every expected failure. Never prints; reports steps
    and commands through `progress` if given.
    """
    options, fmt, preset = _settle(options)
    report = progress or ignore
    steps = Steps(report)
    combinations = _combinations(options)
    if len(combinations) > 1 and fmt != "pyz":
        raise UsageError(
            f"a {fmt} output is for one platform and Python version",
            hint="give one --python and one --python-platform, or build a .pyz",
        )
    with tempfile.TemporaryDirectory(prefix="bundleup-") as tmp:
        stage = Path(tmp)
        prepared: list[Prepared] = []
        for i, combination in enumerate(combinations):
            if _served(prepared, combination):
                continue  # an earlier pure-Python payload already runs there (ADR-0038)
            where = stage if len(combinations) == 1 else stage / f"target-{i}"
            where.mkdir(exist_ok=True)
            prepared.append(
                _prepare(combination, fmt=fmt, stage=where, steps=steps, progress=report)
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
        default = {"pyz": f"{name}.pyz", "dir": name, "lambda": f"{name}-lambda.zip"}[fmt]
        output = (options.output or p.source.workdir / "dist" / default).absolute()
        diagnostics = list(p_diagnostics)
        if fmt == "pyz":
            limit = preset.size_limit if preset else None
            diagnostics += write_pyz(
                prepared,
                output,
                stage=stage,
                steps=steps,
                progress=report,
                size_limit=limit,
                strict=options.strict,
            )
        elif fmt == "dir":
            write_dir(p, output, steps=steps)
        else:
            staged = stage_lambda(p, stage=stage, steps=steps)
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
    return BuildResult(
        output=output,
        size_bytes=size,
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
    seen: dict[tuple[str, str], Diagnostic] = {}
    for p in prepared:
        label = p.target.describe(p.native, p.pythons, p.reach)
        for d in p.diagnostics:
            seen.setdefault((d.code, d.message), replace(d, message=f"{d.message} [{label}]"))
    return sorted(seen.values(), key=lambda d: d.level != "error")


_STRICT_HINT = "--strict makes warnings fail too; build without it to allow them"


def _settle(options: BuildOptions) -> tuple[BuildOptions, Format, _targets.Preset | None]:
    """What `build` and `check` start from: [tool.bundleup] filled in (ADR-0032), the preset
    expanded (ADR-0025), the format checked."""
    options, _configured = _config.apply(options)
    preset = _targets.find(options.target) if options.target else None
    options, _flags = _targets.apply(options)
    return options, _format(options), preset


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


def _unlocked_script(source: Source) -> list[Diagnostic]:
    """A script with dependencies but no lock is resolved afresh on every build (ADR-0028)."""
    if not source.is_script or source.path.with_name(source.path.name + ".lock").exists():
        return []
    meta = script_metadata(source.path.read_text(encoding="utf-8"))
    if not meta.get("dependencies"):
        return []
    name = source.path.name
    return [
        Diagnostic(
            "unlocked",
            "warning",
            f"{name} has no lockfile, so its dependencies were resolved just now; building again "
            "later can bundle different versions",
            hint=f"run `uv lock --script {name}` and keep {name}.lock next to it",
            file=name,
        )
    ]


def _format_diagnostics(
    fmt: Format, site: Path, sizes: list[_check.PackageSize]
) -> list[Diagnostic]:
    """What only matters for `dir` and `lambda` outputs, which run without bundleup's loader."""
    diags = []
    pth = pth_files(site)
    if fmt != "pyz" and pth:
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
    options: BuildOptions, *, fmt: Format, stage: Path, steps: Steps, progress: Progress
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
    reqs, pylock = export(uv, source, lock_mode=options.lock_mode, stage=stage, progress=progress)
    coverage = _wheel_coverage(pylock, target)  # before installing: a precise error, early
    steps.start("install")
    install(uv, source, target=target, reqs=reqs, site=site, script=script, progress=progress)
    check_wheel_platforms(site, target)
    if fmt == "pyz" or options.entry or script:
        entry = resolve_entry(source, site, entry=options.entry, script=script)
    else:
        # A directory or a Lambda zip is imported, and its host decides what runs. A console
        # script is a CLI, not a Lambda handler, so it's never guessed (the review found the
        # printed handler named one).
        entry = None
    packages, native = inspect_site(site)
    version = project_version(site, source)
    if fmt == "pyz":
        add_runtime(site)
    steps.start("compile")
    precompile(target, site, progress=progress, checked=fmt != "pyz")
    steps.start("check")

    def run_python(cmd: list[str]) -> str:
        return run(cmd, what="checking the code", progress=progress, error=BundleupError)

    diagnostics, sizes = _check.analyze(
        site, project=canonicalize_name(source.name), target=target, run=run_python, script=script
    )
    diagnostics += _format_diagnostics(fmt, site, sizes)
    diagnostics += coverage
    diagnostics += _unlocked_script(source)
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
    platform names to check from the lock alone (ADR-0031), for the same Python version.
    `matrix`: wheel coverage for every platform and Python version (`report.matrix`)."""
    options, fmt, _preset = _settle(options)
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
    )


def _matrix(pylock: Path, source: Source) -> list[_coverage.MatrixCell]:
    """`check --matrix`: wheel coverage for every platform and every Python the project allows."""
    spec = SpecifierSet(source.requires_python or "")
    pythons = [v for v in _coverage.MATRIX_PYTHONS if spec.contains(f"{v[0]}.{v[1]}.0")]
    return _coverage.matrix(pylock.read_text(encoding="utf-8"), pythons)
