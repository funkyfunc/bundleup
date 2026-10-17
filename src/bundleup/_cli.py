"""The command line: argv -> BuildOptions -> build() -> output -> exit code.

Follows docs/cli-style-guide.md (ADR-0016): verbs, stdout only for machine output (`--json`,
`--version`, `--help`), everything for people on stderr, `error:`/`hint:` messages, and the exit
codes in `ExitCode`. Heavy modules are imported only when a command runs, so `--version` and
`--help` stay instant (rule 35).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TextIO

from . import __version__
from ._errors import ISSUES_URL, BundleupError, CheckFailedError, Diagnostic, ExitCode, UsageError
from ._term import Style
from ._text import findings, listing, plural

if TYPE_CHECKING:
    from ._build import BuildOptions, BuildResult
    from ._check import CheckReport
    from ._steps import Progress, ProgressEvent
    from ._term import StatusLine
    from ._verify import VerifyReport

SCHEMA_VERSION = 1  # of the --json document; additive changes only within a version
COMMANDS = ["build", "check", "verify", "cache"]
DOCS_URL = "https://github.com/funkyfunc/bundleup"

DESCRIPTION = (
    "Make self-contained Python files: your code and its dependencies in one .pyz that runs "
    "with plain `python`."
)
EXAMPLES = f"""\
examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build path/to/script.py  bundle a PEP 723 script and its dependencies
  bundleup build --python 3.9       build with Python 3.9 (pure Python runs on 3.9 and newer)
  bundleup check                    report what won't survive bundling, and package sizes
  bundleup verify dist/app.pyz      check a bundle (and its unpacked copy) against its manifest

docs: {DOCS_URL}
bugs: {ISSUES_URL}"""


BUILD_EXAMPLES = """\
examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build --python-platform linux --python-platform windows   one .pyz for both"""

CHECK_EXAMPLES = f"""\
examples:
  bundleup check --python-platform linux --python-platform windows   also check Windows wheels

docs: {DOCS_URL}"""


class _UsageProblem(Exception):
    """argparse found a problem with the command line."""


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Keeps examples as written, and uses up to 100 columns so help fits in ~30 lines."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=24, width=100)


class _Parser(argparse.ArgumentParser):
    """argparse, but usage errors are raised so main() can format them like every other error."""

    def error(self, message: str) -> NoReturn:
        raise _UsageProblem(message)


def _env_help(text: str, env: str) -> str:
    return f"{text} [env: {env}]"


def parser() -> argparse.ArgumentParser:
    return parsers()["bundleup"]


def parsers() -> dict[str, argparse.ArgumentParser]:
    """The top-level parser and one per command, keyed by name (the reference doc uses them)."""
    top = _Parser(
        prog="bundleup",
        description=DESCRIPTION,
        epilog=EXAMPLES,
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    top.add_argument("-V", "--version", action="version", version=f"bundleup {__version__}")
    commands = top.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
    build = commands.add_parser(
        "build",
        help="bundle a project or script into one .pyz",
        usage="%(prog)s [options] [path]",  # the options are listed below (rule 32: ~30 lines)
        description="Bundle a project, a folder of modules or a script; locked or not.",
        epilog=BUILD_EXAMPLES,
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    _add_build_options(build, output=True)
    _add_output_options(build, verbose="-v: step timings; -vv: commands run")
    check = commands.add_parser(
        "check",
        help="report what won't survive bundling, without writing a bundle",
        usage="%(prog)s [options] [path]",
        description="Install and compile like `build`, then report what won't work in a bundle "
        "and how big each package is. Every build runs the same checks.",
        epilog=CHECK_EXAMPLES,
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    _add_build_options(check, output=False)
    check.add_argument(
        "--matrix",
        action="store_true",
        help="show which OS, CPU and Python versions the lock's wheels cover",
    )
    _add_output_options(check, verbose="-v: every package's size; -vv: commands run")
    verify = commands.add_parser(
        "verify",
        help="check a bundle against its manifest",
        description="Check a bundle, and its unpacked copy on this machine, against its manifest.",
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    verify.add_argument("bundle", type=Path, help="the .pyz to check")
    _add_output_options(verify, verbose="-v: show the traceback if bundleup crashes")
    cache = commands.add_parser(
        "cache",
        help="list or clean up unpacked bundles",
        description="Bundles unpack once into a cache on the machine that runs them. "
        "List those copies, or remove the ones not used lately.",
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    cache_commands = cache.add_subparsers(
        dest="cache_command", metavar="<command>", parser_class=_Parser, required=True
    )
    listing = cache_commands.add_parser(
        "list",
        help="show unpacked bundles, their size and when each was last used",
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    _add_output_options(listing, verbose="-v: show the traceback if bundleup crashes")
    clean = cache_commands.add_parser(
        "clean",
        help="remove unpacked bundles not used lately",
        description="Remove unpacked bundles not used for --older-than days, plus leftovers of "
        "interrupted unpacks. A bundle that's removed unpacks again on its next run.",
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    clean.add_argument(
        "--older-than",
        type=_older_than,
        default=30,
        metavar="DAYS",
        help="remove copies not used for this many days (default: 30; 0 removes all)",
    )
    clean.add_argument(
        "--build", action="store_true", help="also clear the build cache (compiled bytecode)"
    )
    clean.add_argument("-n", "--dry-run", action="store_true", help="show what would be removed")
    _add_output_options(clean, verbose="-v: list each path removed")
    return {
        "bundleup": top,
        "build": build,
        "check": check,
        "verify": verify,
        "cache": cache,
        "cache list": listing,
        "cache clean": clean,
    }


def _add_build_options(command: argparse.ArgumentParser, *, output: bool) -> None:
    """What to bundle and for which Python: the same for `build` and `check`."""
    command.add_argument(
        "path", nargs="?", default=".", help="project directory or .py script (default: .)"
    )
    if output:
        command.add_argument(
            "-o",
            "--output",
            type=Path,
            metavar="FILE",
            default=_env_path("BUNDLEUP_OUTPUT"),
            help=_env_help("output file (default: dist/<name>.pyz)", "BUNDLEUP_OUTPUT"),
        )
    command.add_argument(
        "--format",
        choices=["pyz", "py", "exe", "dir", "zip"],
        metavar="FORMAT",
        default=None,
        help="pyz (default), py (one .py), exe (experimental), dir, zip",
    )
    command.add_argument(
        "--python",
        metavar="VERSION",
        action="append",
        help=_env_help(
            "a version (3.12) or a path; repeatable; default: uv's",
            "BUNDLEUP_PYTHON",
        ),
    )
    command.add_argument(
        "--entry",
        metavar="NAME",
        default=os.environ.get("BUNDLEUP_ENTRY", "").strip() or None,
        help=_env_help(
            "a script name, module:function, module or python",
            "BUNDLEUP_ENTRY",
        ),
    )
    command.add_argument(
        "--python-platform",
        metavar="OS",
        action="append",
        help=_env_help("an OS/CPU, uv's names (linux); repeatable", "BUNDLEUP_PYTHON_PLATFORM"),
    )
    command.add_argument(
        "--external",
        metavar="PKG",
        action="append",
        help=_env_help("package the host provides, left out; repeatable", "BUNDLEUP_EXTERNAL"),
    )
    lock = command.add_mutually_exclusive_group()
    lock.add_argument(
        "--locked",
        dest="lock_mode",
        action="store_const",
        const="locked",
        help="fail if the lock is out of date (as in uv; the default when there is one)",
    )
    lock.add_argument(
        "--frozen",
        dest="lock_mode",
        action="store_const",
        const="frozen",
        help="bundle the lock as it is, without checking it (as in uv)",
    )
    command.add_argument(
        "--strict",
        action="store_true",
        help="warnings fail too (errors always do)",
    )
    if output:
        command.add_argument(
            "--max-size",
            type=_max_size,
            metavar="SIZE",
            default=None,
            help=_env_help("fail if the output is bigger (30MB)", "BUNDLEUP_MAX_SIZE"),
        )
        command.add_argument(
            "--split",
            type=_max_size,
            metavar="SIZE",
            default=None,
            help=_env_help("no file bigger: a .pyz + parts folder (100MB)", "BUNDLEUP_SPLIT"),
        )
        command.add_argument(
            "--smoke",
            nargs="?",
            const="",
            metavar="ARGS",
            help="run it once, fresh home, no network (default args: --help)",
        )


def _add_output_options(command: argparse.ArgumentParser, *, verbose: str) -> None:
    """--json, -q, -v and --color, the same for every command (rules 13-16)."""
    command.add_argument("--json", action="store_true", help="print one JSON document on stdout")
    command.add_argument(
        "-q", "--quiet", action="count", default=0, help="-q: warnings and errors only; -qq: errors"
    )
    command.add_argument("-v", "--verbose", action="count", default=0, help=verbose)
    command.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        metavar="WHEN",
        default="auto",
        help="auto, always or never (default: auto; also NO_COLOR, FORCE_COLOR)",
    )


def _smoke_args(text: str | None) -> tuple[str, ...] | None:
    if text is None:
        return None
    from ._smoke import parse_args

    return parse_args(text)


def _parse_positive_size(text: str) -> int:
    from ._formats import parse_size

    size = parse_size(text)
    if size <= 0:
        raise UsageError(
            f"size must be greater than 0: {text!r}",
            hint="write a positive size like 50MB or 500KB",
        )
    return size


def _max_size(text: str) -> int:
    try:
        return _parse_positive_size(text)
    except UsageError as e:
        raise argparse.ArgumentTypeError(f"{e} ({e.hint})") from None


def _env_size(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return _parse_positive_size(value) if value else None


def _older_than(text: str) -> float:
    import math

    try:
        days = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid number of days: {text!r} (pass a non-negative number, e.g. --older-than 7)"
        ) from None
    if not math.isfinite(days) or days < 0:
        raise argparse.ArgumentTypeError(
            f"--older-than must be 0 or greater, not {text!r} "
            "(pass a non-negative number, e.g. --older-than 7)"
        )
    return days


def _env_list(name: str) -> list[str]:
    value = os.environ.get(name, "").strip()
    return [value] if value else []


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def _diagnostic(error: BundleupError) -> Diagnostic:
    return Diagnostic.from_error(error)


def _print_diagnostic(d: Diagnostic, style: Style, stream: TextIO) -> None:
    label = style.error("error") if d.level == "error" else style.warning("warning")
    print(f"{label}: {d.message}", file=stream)
    if d.detail:
        for line in d.detail.splitlines():
            print(f"  {line}", file=stream)
    if d.hint:
        print(f"{style.hint('hint')}: {d.hint}", file=stream)


def _size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def _shown(path: Path) -> str:
    """A path as people want to read it: relative if it's below the working directory."""
    try:
        relative = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)
    return str(path) if relative.startswith("..") else relative


def _payloads_line(payloads: list[dict[str, object]]) -> str:
    """A bundle for several platforms, in a few words: `4 payloads: Python 3.12 on macOS arm64,
    Windows x86_64, ...` (each payload's target JSON, ADR-0038)."""
    from ._python import PLATFORM_NAMES

    pythons = sorted(
        {str(p["python"]) for p in payloads}, key=lambda v: tuple(map(int, v.split(".")))
    )
    places = []
    for p in payloads:
        where = (
            "any OS" if p["any_os"] else PLATFORM_NAMES.get(str(p["platform"]), str(p["platform"]))
        )
        place = f"{where} {p['machine']}" if p["machine"] and not p["any_os"] else where
        if place not in places:
            places.append(place)
    return f"{len(payloads)} payloads: Python {', '.join(pythons)} on {', '.join(places)}"


def _success_lines(result: BuildResult, style: Style) -> list[str]:
    """At most two lines (rule 11): what was made and where, then the target in dim."""
    shown = _shown(result.output) + ("/" if result.format == "dir" else "")
    name = f"{result.name} {result.version}" if result.version else result.name
    path = style.link(style.bold(shown), result.output.as_uri())
    size = _size(result.size_bytes) + (
        " unpacked" if result.format == "dir" else " total" if result.parts else ""
    )
    first = (
        f"{style.bold('Bundled')} {name} {style.arrow} {path} "
        f"{style.dim(f'({size}) in {result.duration_s:.2f}s')}"
    )
    packages = plural(result.packages, "package")
    target = result.target.describe(result.native, result.pythons, result.reach)
    details = [_payloads_line(result.payloads) if result.payloads else target, packages]
    if result.format == "zip" and result.handler:
        details.append(f"handler {result.handler}")
    if result.parts:
        count = plural(sum(1 for _ in result.parts.iterdir()), "part")
        details.append(f"{count} in {_shown(result.parts)}/, ship it alongside")
    if result.smoke:
        offline = ", offline" if result.smoke.network_blocked else ""
        details.append(f"ran once in {result.smoke.seconds:.1f}s{offline}")
    second = style.dim(f"  {f' {style.dot} '.join(details)}")
    return [first, second]


def _emit_json(
    command: str, code: ExitCode, result: dict[str, object] | None, diags: list[Diagnostic]
) -> None:
    document = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "ok": code == ExitCode.OK,
        "exit_code": int(code),
        "result": result,
        "diagnostics": [d.to_json_dict() for d in diags],
    }
    print(json.dumps(document, indent=2, sort_keys=True))


def _options(opts: argparse.Namespace) -> BuildOptions:
    from ._build import BuildOptions

    for flag, values, hint in (
        ("--python", opts.python, "pass a Python version or path, e.g. --python 3.12"),
        (
            "--python-platform",
            opts.python_platform,
            "pass a platform name, e.g. --python-platform linux",
        ),
        ("--external", opts.external, "pass a package name, e.g. --external boto3"),
    ):
        if values and not [x.strip() for v in values for x in v.split(",") if x.strip()]:
            raise UsageError(f"{flag} requires a non-empty value", hint=hint)

    # Repeatable flags; the environment variable is the default when none is given.
    pythons = opts.python or _env_list("BUNDLEUP_PYTHON")
    platforms = opts.python_platform or _env_list("BUNDLEUP_PYTHON_PLATFORM")
    externals = opts.external or _env_list("BUNDLEUP_EXTERNAL")
    max_size = (
        opts.max_size or _env_size("BUNDLEUP_MAX_SIZE") if hasattr(opts, "max_size") else None
    )
    split = opts.split or _env_size("BUNDLEUP_SPLIT") if hasattr(opts, "split") else None
    return BuildOptions(
        path=Path(opts.path),
        output=getattr(opts, "output", None),
        python=pythons[0] if pythons else None,
        more_pythons=tuple(pythons[1:]),
        entry=opts.entry,
        lock_mode=opts.lock_mode,  # None: --locked when there's a lock (ADR-0033)
        python_platform=platforms[0] if platforms else None,
        more_python_platforms=tuple(platforms[1:]),
        external=tuple(externals),
        strict=opts.strict,
        format=opts.format,
        max_size=max_size,
        split=split,
        smoke=_smoke_args(getattr(opts, "smoke", None)),
    )


def _expanded(opts: argparse.Namespace, style: Style, *, for_check: bool = False) -> BuildOptions:
    """The options with [tool.bundleup] filled in; -v says what it set (rule 7)."""
    from ._config import apply as apply_config

    options = _options(opts)
    options, configured = apply_config(options, for_check=for_check)
    if configured and not opts.json and opts.verbose >= 1:
        print(style.dim(f"Using [tool.bundleup]: {', '.join(configured)}"), file=sys.stderr)
    return options


def _progress(opts: argparse.Namespace, style: Style) -> tuple[StatusLine, Progress]:
    """A status line for the steps (TTY only), and the uv commands with -vv."""
    from ._term import StatusLine

    human = not opts.json
    status = StatusLine(sys.stderr, style, enabled=human and opts.quiet == 0)

    def on_progress(event: ProgressEvent) -> None:
        if event.kind == "step":
            status.show(f"{event.text}…" if style.arrow == "→" else f"{event.text}...")
        elif event.kind == "note":
            if human and opts.quiet == 0:
                status.clear()
                print(style.dim(event.text), file=sys.stderr)
        elif opts.verbose >= 2 and human:
            status.clear()
            print(style.dim(f"$ {event.text}"), file=sys.stderr)

    return status, on_progress


def _print_findings(diags: list[Diagnostic], opts: argparse.Namespace, style: Style) -> None:
    """Warnings unless -qq; errors always (rule 15)."""
    for d in diags:
        if d.level == "error" or opts.quiet < 2:
            _print_diagnostic(d, style, sys.stderr)


def _failed(e: BundleupError, command: str, opts: argparse.Namespace, style: Style) -> ExitCode:
    """Report a failure: a check failure's findings first, then the error itself."""
    findings = e.diagnostics if isinstance(e, CheckFailedError) else []
    if opts.json:
        _emit_json(command, e.exit_code, None, [*findings, _diagnostic(e)])
    else:
        _print_findings(findings, opts, style)
        _print_diagnostic(_diagnostic(e), style, sys.stderr)
    return e.exit_code


def _run_build(opts: argparse.Namespace) -> ExitCode:
    from ._build import build  # deferred: --help and --version stay instant

    err = sys.stderr
    style = Style(err, opts.color)
    status, on_progress = _progress(opts, style)
    try:
        result = build(_expanded(opts, style), progress=on_progress)
    except BundleupError as e:
        status.clear()
        return _failed(e, "build", opts, style)
    finally:
        status.clear()
    if opts.json:
        _emit_json("build", ExitCode.OK, result.to_json_dict(), result.diagnostics)
        return ExitCode.OK
    _print_findings(result.diagnostics, opts, style)
    if opts.quiet == 0:
        for line in _success_lines(result, style):
            print(line, file=err)
        if opts.verbose >= 1:
            dot = f" {style.dot} "
            steps = dot.join(
                f"{step} {seconds * 1000:.0f}ms" for step, seconds in result.timings.items()
            )
            print(style.dim(f"  {steps}"), file=err)
    return ExitCode.OK


def _check_lines(report: CheckReport, opts: argparse.Namespace, style: Style) -> list[str]:
    """The summary: what was checked and the verdict, then sizes (every package with -v)."""
    name = f"{report.name} {report.version}" if report.version else report.name
    errors, warnings = len(report.errors), len(report.warnings)
    verdict = findings(errors, warnings) or "no problems found"
    target = report.target.describe(report.native, report.pythons, report.reach)
    if report.also_platforms:  # say what else was checked (eighth review)
        target += f", and its wheels for {', '.join(report.also_platforms)}"
    lines = [f"{style.bold('Checked')} {name} for {target}: {verdict}"]
    packages = plural(len(report.packages), "package")
    largest = ", ".join(f"{p.name} {_size(p.size_bytes)}" for p in report.packages[:3])
    more = f" {style.dot} largest: {largest}" if largest and opts.verbose == 0 else ""
    lines.append(style.dim(f"  {packages}, {_size(report.size_bytes)} unpacked{more}"))
    if opts.verbose >= 1 and report.packages:
        width = max(len(p.name) for p in report.packages)
        total = report.size_bytes or 1
        arrow = f" {style.arrow} "
        for p in report.packages:
            pct = f"{round(p.size_bytes * 100 / total)}%"
            native = "  native" if p.native else ""
            via = f"  via {arrow.join(p.required_by)}" if p.required_by else ""
            lines.append(
                style.dim(
                    f"    {p.name:<{width}}  {_size(p.size_bytes):>10}  {pct:>4}{native}{via}"
                )
            )
    return lines


def _run_check(opts: argparse.Namespace) -> ExitCode:
    from ._build import check  # deferred: --help and --version stay instant

    err = sys.stderr
    style = Style(err, opts.color)
    status, on_progress = _progress(opts, style)
    try:
        options = _expanded(opts, style, for_check=True)
        report = check(
            options,
            progress=on_progress,
            matrix=opts.matrix,
        )
    except BundleupError as e:
        status.clear()
        return _failed(e, "check", opts, style)
    finally:
        status.clear()
    failed = not report.ok or (options.strict and report.warnings)
    code = ExitCode.BUILD_FAILED if failed else ExitCode.OK
    if opts.json:
        _emit_json("check", code, report.to_json_dict(), report.diagnostics)
        return code
    _print_findings(report.diagnostics, opts, style)
    if opts.quiet == 0:
        for line in _check_lines(report, opts, style):
            print(line, file=err)
    if report.matrix:  # asked for: a listing, so stdout (rule 10)
        for line in _matrix_lines(report, Style(sys.stdout, opts.color)):
            print(line)
    return code


def _matrix_lines(report: CheckReport, style: Style) -> list[str]:
    """`check --matrix`: a grid of platforms by Python version, then what's missing where."""
    pythons = sorted({cell.python for cell in report.matrix})
    labels = list(dict.fromkeys(cell.label for cell in report.matrix))
    width = max(len(label) for label in labels)
    cells = {(cell.label, cell.python): cell for cell in report.matrix}
    head = (" " * width + "".join(f"  {v[0]}.{v[1]:<4}" for v in pythons)).rstrip()
    lines = [style.bold("Wheels for each platform, from the lock:"), head]
    for label in labels:
        row = label.ljust(width)
        for version in pythons:
            cell = cells[(label, version)]
            row += "  " + ("ok" if cell.ok else f"x {len(cell.missing)}").ljust(6)
        lines.append(row.rstrip())
    for cell in report.matrix:
        if not cell.ok:
            where = f"{cell.label}, Python {cell.python[0]}.{cell.python[1]}"
            lines.append(style.dim(f"  {where}: no wheel for {', '.join(cell.missing)}"))
    return lines


def _verify_diagnostics(report: VerifyReport) -> list[Diagnostic]:
    diags = []
    if report.problems:
        diags.append(
            Diagnostic(
                "verify-mismatch",
                "error",
                f"{_shown(report.bundle)} doesn't match its manifest",
                hint="rebuild it, or get a fresh copy from where it came from",
                detail=listing(report.problems),
            )
        )
    if report.cache and report.cache_problems:
        diags.append(
            Diagnostic(
                "cache-mismatch",
                "error",
                f"the unpacked copy at {report.cache} doesn't match the manifest",
                hint=f"delete {report.cache}; the bundle unpacks again on its next run",
                detail=listing(report.cache_problems),
            )
        )
    return diags


def _run_verify(opts: argparse.Namespace) -> ExitCode:
    from ._verify import unpacks, verify  # deferred: --help and --version stay instant

    err = sys.stderr
    style = Style(err, opts.color)
    try:
        report = verify(opts.bundle)
    except BundleupError as e:
        if opts.json:
            _emit_json("verify", e.exit_code, None, [_diagnostic(e)])
        else:
            _print_diagnostic(_diagnostic(e), style, err)
        return e.exit_code
    diags = _verify_diagnostics(report)
    code = ExitCode.OK if report.ok else ExitCode.BUILD_FAILED
    if opts.json:
        _emit_json("verify", code, report.to_json_dict(), diags)
    elif diags:
        for diag in diags:
            _print_diagnostic(diag, style, err)
    elif opts.quiet == 0:
        files = f"{report.files:,} files match its manifest"
        print(f"{style.bold('Verified')} {_shown(report.bundle)}: {files}", file=err)
        if unpacks(report.bundle):
            cache = f"matches ({report.cache})" if report.cache else "not unpacked on this machine"
            print(style.dim(f"  unpacked copy: {cache}"), file=err)
    return code


def _ago(seconds: float) -> str:
    days = seconds / 86400
    if days >= 1:
        return f"{plural(round(days), 'day')} ago"
    hours = seconds / 3600
    return f"{plural(round(hours), 'hour')} ago" if hours >= 1 else "just now"


def _run_cache(opts: argparse.Namespace) -> ExitCode:
    import time

    from ._cache import clean_cache, list_cache  # deferred: --help and --version stay instant

    err = sys.stderr
    style = Style(err, opts.color)
    command = f"cache {opts.cache_command}"
    if opts.cache_command == "list":
        bundles = list_cache()
        if opts.json:
            result: dict[str, object] = {"bundles": [b.to_json_dict() for b in bundles]}
            _emit_json(command, ExitCode.OK, result, [])
            return ExitCode.OK
        now = time.time()
        out = Style(sys.stdout, opts.color)  # the listing: stdout, so it can be piped (rule 10)
        for b in bundles:
            when = out.dim(f"last used {_ago(now - b.last_used)}")
            print(f"{out.bold(b.name)}  {_size(b.size_bytes)}  {when}  {b.path}")
        if opts.quiet == 0:
            total = sum(b.size_bytes for b in bundles)
            count = plural(len(bundles), "unpacked bundle")
            print(style.dim(f"{count}, {_size(total)}"), file=err)
        return ExitCode.OK
    try:
        report = clean_cache(
            older_than_days=opts.older_than, build=opts.build, dry_run=opts.dry_run
        )
    except BundleupError as e:
        return _failed(e, command, opts, style)
    if opts.json:
        _emit_json(command, ExitCode.OK, report.to_json_dict(), [])
    elif opts.quiet == 0:
        verb = "Would remove" if report.dry_run else "Removed"
        shown = [p for p in report.removed if not p.name.startswith(".lock-")]
        items = plural(len(shown), "item")
        print(f"{style.bold(verb)} {items} ({_size(report.freed_bytes)})", file=err)
        if report.in_use:
            kept = len(report.in_use)
            which = "a copy" if kept == 1 else f"{kept} copies"
            print(style.dim(f"  kept {which} a running program still uses"), file=err)
        if opts.verbose >= 1:
            for path in shown:
                print(style.dim(f"  {path}"), file=err)
    return ExitCode.OK


_FLAG_ALIASES: dict[str, str] = {
    "--platform": "--python-platform",
    "--platforms": "--python-platform",
    "--target": "--python",
    "--outfile": "-o / --output",
    "--out": "-o / --output",
    "--outdir": "-o / --output",
    "--out-dir": "-o / --output",
    "-e": "--entry",
    "--entrypoint": "-e / --entry",
    "--entry-point": "-e / --entry",
    "--main": "-e / --entry",
    "--externals": "--external",
    "--onefile": "--format scie",
    "--scie": "--format exe",
    "--standalone": "--format exe",
    "--analyze": "bundleup check -v",
    "--metafile": "bundleup check --json",
}


def _usage_error(message: str, argv: list[str]) -> ExitCode:
    words = [a for a in argv if not a.startswith("-")]
    word = words[0] if words else ""
    all_parsers = parsers()
    sub_name = (
        f"cache {words[1]}"
        if word == "cache" and len(words) > 1 and f"cache {words[1]}" in all_parsers
        else word
    )
    help_cmd = f"bundleup {sub_name} --help" if sub_name in all_parsers else "bundleup --help"
    hint = f"run `{help_cmd}` to see the commands and options"
    if word and word not in COMMANDS and "invalid choice" in message:
        import difflib  # only on this error path: keeps startup light (rule 35)

        # Our own wording: argparse's changes between Python releases, even patch releases.
        message = f"unknown command `{word}`"
        if word.endswith((".pyz", ".pex", ".scie")):
            hint = f"did you mean `bundleup verify {word}`?"
        elif word == "." or word.endswith((".py", ".toml", ".txt")) or "/" in word or "\\" in word:
            hint = f"did you mean `bundleup build {word}`?"
        elif close := difflib.get_close_matches(word, COMMANDS, n=1):
            hint = f"did you mean `bundleup {close[0]}`?"
        elif _safe_exists(word):
            hint = f"did you mean `bundleup build {word}`?"
    elif (
        word == "cache"
        and len(words) > 1
        and words[1] not in ("list", "clean")
        and "invalid choice" in message
    ):
        import difflib

        bad_sub = words[1]
        message = f"unknown command `cache {bad_sub}`"
        close = difflib.get_close_matches(bad_sub, ("list", "clean"), n=1)
        if close:
            hint = f"did you mean `bundleup cache {close[0]}`?"
    elif "argument --format: invalid choice:" in message:
        if any(k in message.lower() for k in ("'scie'", "'onefile'", "'binary'", "'standalone'")):
            hint = f"did you mean `--format exe`? (see `{help_cmd}`)"
        elif any(k in message.lower() for k in ("'lambda'", "'aws'")):
            hint = f"did you mean `--format zip`? (see `{help_cmd}`)"
        elif any(k in message.lower() for k in ("'pex'", "'shiv'", "'zipapp'")):
            hint = f"did you mean `--format pyz`? (see `{help_cmd}`)"
    elif "unrecognized arguments:" in message:
        import difflib

        bad = message.split("unrecognized arguments:", 1)[1].strip().split()[0].split("=", 1)[0]
        if bad in _FLAG_ALIASES:
            alias = _FLAG_ALIASES[bad]
            verb = "try" if alias.startswith("bundleup ") else "did you mean"
            q = "" if alias.startswith("bundleup ") else "?"
            hint = f"{verb} `{alias}`{q} (see `{help_cmd}`)"
        elif bad.startswith("-"):
            sub = all_parsers.get(sub_name) or all_parsers["bundleup"]
            other = [
                name
                for name, p in all_parsers.items()
                if name not in ("bundleup", sub_name) and bad in p._option_string_actions
            ]
            if other and sub_name in all_parsers:
                hint = f"`{bad}` is an option for `bundleup {other[0]}`, not `bundleup {sub_name}`"
            else:
                flags = [opt for opt in sub._option_string_actions if opt.startswith("--")]
                close = difflib.get_close_matches(bad, flags, n=1)
                if close:
                    hint = f"did you mean `{close[0]}`? (see `{help_cmd}`)"
    diag = Diagnostic("usage", "error", message, hint)
    if "--json" in argv:
        _emit_json(sub_name, ExitCode.USAGE_ERROR, None, [diag])
    else:
        _print_diagnostic(diag, Style(sys.stderr, "auto"), sys.stderr)
    return ExitCode.USAGE_ERROR


def _crash(error: BaseException, *, verbose: bool) -> ExitCode:
    style = Style(sys.stderr, "auto")
    print(
        f"{style.error('error')}: bundleup crashed: {type(error).__name__}: {error}",
        file=sys.stderr,
    )
    if verbose:
        import traceback

        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
    print(f"{style.hint('hint')}: this is a bug; please report it: {ISSUES_URL}", file=sys.stderr)
    if not verbose:
        print(f"{style.hint('hint')}: rerun with -v to see the traceback", file=sys.stderr)
    return ExitCode.INTERNAL_ERROR


def _is_build_flag(token: str, options: set[str]) -> bool:
    """Whether `token` after `--smoke` is another `bundleup build` option rather than the smoke
    command's own flags (`--smoke "--version"`, `--smoke "-V"`)."""
    if token.split("=", 1)[0] in options:
        return True
    return len(token) > 1 and token[0] == "-" and set(token[1:]) <= {"q", "v"}


def _positional_count(args: list[str], takes_value: set[str]) -> int:
    count = 0
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            count += len(args) - i - 1
            break
        if token in takes_value:
            i += 2
            continue
        if not token.startswith("-"):
            count += 1
        i += 1
    return count


def _safe_exists(token: str) -> bool:
    try:
        return Path(token).exists()
    except OSError:
        return False


def _looks_like_path(token: str) -> bool:
    if " " in token:
        return False
    return (
        token == "."
        or token.endswith(".py")
        or "/" in token
        or "\\" in token
        or _safe_exists(token)
    )


def _is_entry_python(args: list[str]) -> bool:
    for idx, tok in enumerate(args):
        if tok == "--entry=python":
            return True
        if tok == "--entry" and idx + 1 < len(args) and args[idx + 1] == "python":
            return True
    return os.environ.get("BUNDLEUP_ENTRY", "").strip() == "python"


def _is_project_or_pep723(token: str) -> bool:
    p = Path(token)
    try:
        if p.is_dir():
            return True
        if p.is_file():
            return "# /// script" in p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return False


def _join_smoke(args: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """`argparse` treats a token starting with `-` after `nargs="?"` as one of its own options,
    so `bundleup build --smoke "--version"` (docs/recipes.md) would fail without joining `=`.
    And `bundleup build --smoke app.py` should treat `app.py` as `path`, not `--smoke`'s arg."""
    actions = parser._option_string_actions
    options = set(actions)
    takes_value = {opt for opt, act in actions.items() if act.nargs not in (0, "?", "*")}
    positionals = _positional_count(args[1:], takes_value) if args and args[0] == "build" else 0
    entry_python = _is_entry_python(args)
    out: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            out.extend(args[i:])
            break
        if token in takes_value and i + 1 < len(args):
            out.extend(args[i : i + 2])
            i += 2
        elif (
            token == "--smoke"
            and i + 1 < len(args)
            and args[i + 1].startswith("-")
            and args[i + 1] != "--"
            and not _is_build_flag(args[i + 1], options)
        ):
            out.append(f"--smoke={args[i + 1]}")
            i += 2
        elif (
            token == "--smoke"
            and i + 1 < len(args)
            and not args[i + 1].startswith("-")
            and positionals == 1
            and _looks_like_path(args[i + 1])
            and not (entry_python and not _is_project_or_pep723(args[i + 1]))
        ):
            out.append("--smoke=")
            i += 1
        else:
            out.append(token)
            i += 1
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    all_parsers = parsers()
    top = all_parsers["bundleup"]
    if not args:
        top.print_help(sys.stderr)
        return ExitCode.USAGE_ERROR
    try:
        opts = top.parse_args(_join_smoke(args, all_parsers["build"]))
    except _UsageProblem as e:
        return _usage_error(str(e), args)
    try:
        if opts.command == "check":
            return _run_check(opts)
        if opts.command == "verify":
            return _run_verify(opts)
        if opts.command == "cache":
            return _run_cache(opts)
        return _run_build(opts)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except BrokenPipeError:
        return ExitCode.OK
    except Exception as e:  # anything else is a bug: say so, with a way to report it
        return _crash(e, verbose=opts.verbose > 0)
