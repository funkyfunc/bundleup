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
from ._errors import ISSUES_URL, BundleupError, CheckFailedError, Diagnostic, ExitCode
from ._term import Style
from ._text import findings, listing, plural

if TYPE_CHECKING:
    from ._build import BuildOptions, BuildResult
    from ._check import CheckReport
    from ._steps import Progress, ProgressEvent
    from ._term import StatusLine
    from ._verify import VerifyReport

SCHEMA_VERSION = 1  # of the --json document; additive changes only within a version
COMMANDS = ["build", "check", "targets", "verify", "cache"]
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
  bundleup build --python 3.11 --python-platform linux   build for Linux x86_64
  bundleup build --target lambda    an AWS Lambda .zip (`bundleup targets` lists presets)"""

CHECK_EXAMPLES = f"""\
examples:
  bundleup check                    check the project here for this machine's Python
  bundleup check --also-platform windows --also-platform linux   wheels for other platforms too

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
        description="Bundle a project (pyproject.toml + uv.lock) or a PEP 723 script.",
        epilog=BUILD_EXAMPLES,
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    _add_build_options(build, output=True)
    _add_output_options(build, verbose="-v: step timings; -vv: commands run")
    check = commands.add_parser(
        "check",
        help="report what won't survive bundling, without writing a bundle",
        description="Install and compile like `build`, then report what won't work in a bundle "
        "and how big each package is. Every build runs the same checks.",
        epilog=CHECK_EXAMPLES,
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    _add_build_options(check, output=False)
    check.add_argument(
        "--also-platform",
        action="append",
        default=[],
        metavar="OS",
        help="also check, from the lock alone, that every package has a wheel for this platform",
    )
    _add_output_options(check, verbose="-v: every package's size; -vv: commands run")
    targets = commands.add_parser(
        "targets",
        help="list the target presets and the flags each stands for",
        description="Presets are shorthands for --format, --python and --python-platform. "
        "Flags given explicitly win over a preset's.",
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    _add_output_options(targets, verbose="-v: show the traceback if bundleup crashes")
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
        type=float,
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
        "targets": targets,
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
        choices=["pyz", "dir", "lambda"],
        metavar="FORMAT",
        default=None,
        help="pyz (default), dir (a directory) or lambda (an AWS Lambda .zip)",
    )
    command.add_argument(
        "--target",
        metavar="NAME",
        default=os.environ.get("BUNDLEUP_TARGET"),
        help=_env_help("a preset: lambda, lambda-arm64, claude-api", "BUNDLEUP_TARGET"),
    )
    command.add_argument(
        "--python",
        metavar="VERSION",
        default=os.environ.get("BUNDLEUP_PYTHON"),
        help=_env_help(
            "a version (3.12) or a path; default: uv's choice",
            "BUNDLEUP_PYTHON",
        ),
    )
    command.add_argument(
        "--entry",
        metavar="NAME",
        default=os.environ.get("BUNDLEUP_ENTRY"),
        help=_env_help(
            "a script name, module:function or module",
            "BUNDLEUP_ENTRY",
        ),
    )
    command.add_argument(
        "--python-platform",
        metavar="OS",
        default=os.environ.get("BUNDLEUP_PYTHON_PLATFORM"),
        help=_env_help("another OS/CPU, uv's names (e.g. linux)", "BUNDLEUP_PYTHON_PLATFORM"),
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


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
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


def _success_lines(result: BuildResult, style: Style) -> list[str]:
    """At most two lines (rule 11): what was made and where, then the target in dim."""
    shown = _shown(result.output) + ("/" if result.format == "dir" else "")
    name = f"{result.name} {result.version}" if result.version else result.name
    path = style.link(style.bold(shown), result.output.as_uri())
    size = _size(result.size_bytes) + (" unpacked" if result.format == "dir" else "")
    first = (
        f"{style.bold('Bundled')} {name} {style.arrow} {path} "
        f"{style.dim(f'({size}) in {result.duration_s:.2f}s')}"
    )
    packages = plural(result.packages, "package")
    details = [result.target.describe(result.native, result.pythons, result.reach), packages]
    if result.format == "lambda" and result.handler:
        details.append(f"handler {result.handler}")
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

    return BuildOptions(
        path=Path(opts.path),
        output=getattr(opts, "output", None),
        python=opts.python,
        entry=opts.entry,
        lock_mode=opts.lock_mode,  # None: --locked when there's a lock (ADR-0033)
        python_platform=opts.python_platform,
        strict=opts.strict,
        format=opts.format,
        target=opts.target,
    )


def _expanded(opts: argparse.Namespace, style: Style) -> BuildOptions:
    """The options with a --target preset filled in; says what it expanded to (rule 7)."""
    from ._config import apply as apply_config
    from ._targets import apply

    options, configured = apply_config(_options(opts))
    if configured and not opts.json and opts.verbose >= 1:
        print(style.dim(f"Using [tool.bundleup]: {', '.join(configured)}"), file=sys.stderr)
    preset = options.target  # from a flag, the environment or [tool.bundleup]
    options, flags = apply(options)
    if flags and not opts.json and opts.quiet == 0:
        print(style.dim(f"Using target {preset}: {' '.join(flags)}"), file=sys.stderr)
    return options


def _run_targets(opts: argparse.Namespace) -> ExitCode:
    from ._targets import list_targets

    presets = list_targets()
    if opts.json:
        result: dict[str, object] = {"targets": [t.to_json_dict() for t in presets]}
        _emit_json("targets", ExitCode.OK, result, [])
        return ExitCode.OK
    style = Style(sys.stdout, opts.color)  # a listing: stdout, so it can be piped (rule 10)
    width = max(len(t.name) for t in presets)
    for t in presets:
        print(f"{style.bold(t.name.ljust(width))}  {t.description}")
        print(style.dim(f"{' ' * width}  {' '.join(t.expansion())}"))
    return ExitCode.OK


def _progress(opts: argparse.Namespace, style: Style) -> tuple[StatusLine, Progress]:
    """A status line for the steps (TTY only), and the uv commands with -vv."""
    from ._term import StatusLine

    human = not opts.json
    status = StatusLine(sys.stderr, style, enabled=human and opts.quiet == 0)

    def on_progress(event: ProgressEvent) -> None:
        if event.kind == "step":
            status.show(f"{event.text}…" if style.arrow == "→" else f"{event.text}...")
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
    lines = [f"{style.bold('Checked')} {name} for {target}: {verdict}"]
    packages = plural(len(report.packages), "package")
    largest = ", ".join(f"{p.name} {_size(p.size_bytes)}" for p in report.packages[:3])
    lines.append(
        style.dim(
            f"  {packages}, {_size(report.size_bytes)} unpacked {style.dot} largest: {largest}"
        )
    )
    if opts.verbose >= 1:
        width = max(len(p.name) for p in report.packages)
        for p in report.packages:
            native = "  native" if p.native else ""
            lines.append(style.dim(f"    {p.name:<{width}}  {_size(p.size_bytes):>10}{native}"))
    return lines


def _run_check(opts: argparse.Namespace) -> ExitCode:
    from ._build import check  # deferred: --help and --version stay instant

    err = sys.stderr
    style = Style(err, opts.color)
    status, on_progress = _progress(opts, style)
    try:
        options = _expanded(opts, style)
        report = check(options, progress=on_progress, also_platforms=opts.also_platform)
    except BundleupError as e:
        status.clear()
        return _failed(e, "check", opts, style)
    finally:
        status.clear()
    failed = not report.ok or (opts.strict and report.warnings)
    code = ExitCode.BUILD_FAILED if failed else ExitCode.OK
    if opts.json:
        _emit_json("check", code, report.to_json_dict(), report.diagnostics)
        return code
    _print_findings(report.diagnostics, opts, style)
    if opts.quiet == 0:
        for line in _check_lines(report, opts, style):
            print(line, file=err)
    return code


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
    from ._verify import verify  # deferred: --help and --version stay instant

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
        total = sum(b.size_bytes for b in bundles)
        count = plural(len(bundles), "unpacked bundle")
        print(style.dim(f"{count}, {_size(total)}"), file=err)
        return ExitCode.OK
    report = clean_cache(older_than_days=opts.older_than, build=opts.build, dry_run=opts.dry_run)
    if opts.json:
        _emit_json(command, ExitCode.OK, report.to_json_dict(), [])
    elif opts.quiet == 0:
        verb = "Would remove" if report.dry_run else "Removed"
        items = plural(len(report.removed), "item")
        print(f"{style.bold(verb)} {items} ({_size(report.freed_bytes)})", file=err)
        if opts.verbose >= 1:
            for path in report.removed:
                print(style.dim(f"  {path}"), file=err)
    return ExitCode.OK


def _first_word(argv: list[str]) -> str:
    words = [a for a in argv if not a.startswith("-")]
    return words[0] if words else ""


def _usage_error(message: str, argv: list[str]) -> ExitCode:
    hint = "run `bundleup --help` to see the commands and options"
    word = _first_word(argv)
    if word and word not in COMMANDS and "invalid choice" in message:
        import difflib  # only on this error path: keeps startup light (rule 35)

        # Our own wording: argparse's changes between Python releases, even patch releases.
        message = f"unknown command `{word}`"
        close = difflib.get_close_matches(word, COMMANDS, n=1)
        if close:
            hint = f"did you mean `bundleup {close[0]}`?"
    diag = Diagnostic("usage", "error", message, hint)
    if "--json" in argv:
        _emit_json(word, ExitCode.USAGE_ERROR, None, [diag])
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    top = parser()
    if not args:
        top.print_help(sys.stderr)
        return ExitCode.USAGE_ERROR
    try:
        opts = top.parse_args(args)
    except _UsageProblem as e:
        return _usage_error(str(e), args)
    try:
        if opts.command == "check":
            return _run_check(opts)
        if opts.command == "targets":
            return _run_targets(opts)
        if opts.command == "verify":
            return _run_verify(opts)
        if opts.command == "cache":
            return _run_cache(opts)
        return _run_build(opts)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except Exception as e:  # anything else is a bug: say so, with a way to report it
        return _crash(e, verbose=opts.verbose > 0)
