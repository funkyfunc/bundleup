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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TextIO

from . import __version__
from ._errors import ISSUES_URL, BundleupError, ExitCode
from ._term import Style

if TYPE_CHECKING:
    from ._build import BuildResult, ProgressEvent
    from ._verify import VerifyReport

SCHEMA_VERSION = 1  # of the --json document; additive changes only within a version
COMMANDS = ["build", "verify"]
DOCS_URL = "https://github.com/funkyfunc/bundleup"

DESCRIPTION = (
    "Make self-contained Python files: your code and its dependencies in one .pyz that runs "
    "with plain `python`."
)
EXAMPLES = f"""\
examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build path/to/script.py  bundle a PEP 723 script and its dependencies
  bundleup build --python 3.9       build for Python 3.9 (a bundle runs on one version)
  bundleup verify dist/app.pyz      check a bundle (and its unpacked copy) against its manifest

docs: {DOCS_URL}
bugs: {ISSUES_URL}"""


BUILD_EXAMPLES = f"""\
examples:
  bundleup build                    bundle the project here into dist/<name>.pyz
  bundleup build --python 3.11 --python-platform linux   build for Linux x86_64

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
    build.add_argument(
        "path", nargs="?", default=".", help="project directory or .py script (default: .)"
    )
    build.add_argument(
        "-o",
        "--output",
        type=Path,
        metavar="FILE",
        default=_env_path("BUNDLEUP_OUTPUT"),
        help=_env_help("output file (default: dist/<name>.pyz)", "BUNDLEUP_OUTPUT"),
    )
    build.add_argument(
        "--python",
        metavar="VERSION",
        default=os.environ.get("BUNDLEUP_PYTHON"),
        help=_env_help(
            "a version (3.12) or a path; default: uv's choice",
            "BUNDLEUP_PYTHON",
        ),
    )
    build.add_argument(
        "--entry",
        metavar="NAME",
        default=os.environ.get("BUNDLEUP_ENTRY"),
        help=_env_help(
            "a script name, module:function or module",
            "BUNDLEUP_ENTRY",
        ),
    )
    build.add_argument(
        "--python-platform",
        metavar="PLATFORM",
        default=os.environ.get("BUNDLEUP_PYTHON_PLATFORM"),
        help=_env_help(
            "another OS/CPU in uv's terms, e.g. x86_64-manylinux_2_28",
            "BUNDLEUP_PYTHON_PLATFORM",
        ),
    )
    lock = build.add_mutually_exclusive_group()
    lock.add_argument(
        "--locked",
        dest="lock_mode",
        action="store_const",
        const="locked",
        help="fail if uv.lock is out of date (as in uv; the default when CI is set)",
    )
    lock.add_argument(
        "--frozen",
        dest="lock_mode",
        action="store_const",
        const="frozen",
        help="use uv.lock as is, without checking it (as in uv)",
    )
    _add_output_options(build, verbose="-v: step timings; -vv: commands run")
    verify = commands.add_parser(
        "verify",
        help="check a bundle against its manifest",
        description="Check a bundle, and its unpacked copy on this machine, against its manifest.",
        formatter_class=_HelpFormatter,
        allow_abbrev=False,
    )
    verify.add_argument("bundle", type=Path, help="the .pyz to check")
    _add_output_options(verify, verbose="-v: show the traceback if bundleup crashes")
    return {"bundleup": top, "build": build, "verify": verify}


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


def _in_ci() -> bool:
    return os.environ.get("CI", "").lower() not in ("", "0", "false", "no")


def _has_lockfile(path: Path) -> bool:
    """uv.lock for a project, <script>.lock for a PEP 723 script (which often has none)."""
    return (
        (path / "uv.lock").exists()
        if path.is_dir()
        else path.with_name(path.name + ".lock").exists()
    )


@dataclass(frozen=True)
class Diagnostic:
    """One problem, as shown to people (stderr) and to machines (--json)."""

    code: str
    level: str  # "error" or "warning"
    message: str
    hint: str | None = None
    detail: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _diagnostic(error: BundleupError) -> Diagnostic:
    return Diagnostic(error.code, "error", error.message, error.hint, error.detail)


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
    shown = _shown(result.output)
    name = f"{result.name} {result.version}" if result.version else result.name
    path = style.link(style.bold(shown), result.output.as_uri())
    first = (
        f"{style.bold('Bundled')} {name} {style.arrow} {path} "
        f"{style.dim(f'({_size(result.size_bytes)}) in {result.duration_s:.2f}s')}"
    )
    packages = f"{result.packages} package{'s' if result.packages != 1 else ''}"
    second = style.dim(f"  {result.target.describe(result.native)} {style.dot} {packages}")
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


def _run_build(opts: argparse.Namespace) -> ExitCode:
    from ._build import BuildOptions, build  # deferred: --help and --version stay instant
    from ._term import StatusLine

    err = sys.stderr
    style = Style(err, opts.color)
    human = not opts.json
    status = StatusLine(err, style, enabled=human and opts.quiet == 0)

    def on_progress(event: ProgressEvent) -> None:
        if event.kind == "step":
            status.show(f"{event.text}…" if style.arrow == "→" else f"{event.text}...")
        elif opts.verbose >= 2 and human:
            status.clear()
            print(style.dim(f"$ {event.text}"), file=err)

    # In CI a stale lock must fail rather than silently bundle something else (rule 9). Without a
    # lockfile there's nothing to be stale, and `uv export --locked` would refuse to start.
    in_ci_with_lock = _in_ci() and _has_lockfile(Path(opts.path))
    lock_mode = opts.lock_mode or ("locked" if in_ci_with_lock else None)
    options = BuildOptions(
        path=Path(opts.path),
        output=opts.output,
        python=opts.python,
        entry=opts.entry,
        lock_mode=lock_mode,
        python_platform=opts.python_platform,
    )
    try:
        result = build(options, progress=on_progress)
    except BundleupError as e:
        status.clear()
        if human:
            _print_diagnostic(_diagnostic(e), style, err)
        else:
            _emit_json("build", e.exit_code, None, [_diagnostic(e)])
        return e.exit_code
    finally:
        status.clear()
    if opts.json:
        _emit_json("build", ExitCode.OK, result.to_json_dict(), [])
    elif opts.quiet == 0:
        for line in _success_lines(result, style):
            print(line, file=err)
        if opts.verbose >= 1:
            dot = f" {style.dot} "
            steps = dot.join(
                f"{step} {seconds * 1000:.0f}ms" for step, seconds in result.timings.items()
            )
            print(style.dim(f"  {steps}"), file=err)
    return ExitCode.OK


def _verify_diagnostics(report: VerifyReport) -> list[Diagnostic]:
    def listing(problems: list[str]) -> str:
        more = f"\n... and {len(problems) - 20} more" if len(problems) > 20 else ""
        return "\n".join(problems[:20]) + more

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
        return _run_verify(opts) if opts.command == "verify" else _run_build(opts)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except Exception as e:  # anything else is a bug: say so, with a way to report it
        return _crash(e, verbose=opts.verbose > 0)
