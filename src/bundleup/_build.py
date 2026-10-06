"""Build a bundle: resolve and install with uv, precompile, and write a two-layer .pyz.

Layout of the output (see docs/adr/0010-bundle-format-and-loader.md):

    #!/usr/bin/env python3
    zip:
      payload.zip    stored, not compressed: the installed packages (itself a deflated zip)
      __main__.py    the loader (_loader.py with its config filled in)
      __main__.pyc   the loader compiled for the target Python, so it isn't recompiled on each run
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from . import __version__, _verify
from ._errors import (
    ISSUES_URL,
    BundleMismatchError,
    BundleupError,
    EntryPointError,
    LockfileOutdatedError,
    ProjectError,
    PythonMismatchError,
    PythonNotFoundError,
    UsageError,
    UvError,
    UvNotFoundError,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

LOADER = Path(__file__).with_name("_loader.py")
MANIFEST = "manifest.json"  # in the outer zip, next to __main__.py
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # reproducible zips: same inputs, same bytes, same cache key
# uv's lock file, and console-script launchers that point at the build machine's Python.
SKIP_TOP = {".lock", "bin"}
PLATFORM_NAMES = {"darwin": "macOS", "linux": "Linux", "win32": "Windows"}
PEP723 = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")


@dataclass(frozen=True)
class BuildOptions:
    """What to bundle and how. Mirrors `bundleup build`'s flags."""

    path: Path = Path()  # a project directory (with pyproject.toml) or a PEP 723 script
    output: Path | None = None  # default: dist/<name>.pyz next to the input
    python: str | None = None  # a version ("3.12") or an interpreter path; default: uv's choice
    entry: str | None = None  # a [project.scripts] name, "module:function" or "module"
    lock_mode: Literal["locked", "frozen"] | None = None  # as uv's --locked / --frozen


@dataclass(frozen=True)
class ProgressEvent:
    """Reported while building: a step starting, or a command about to run."""

    kind: Literal["step", "command"]
    text: str


Progress = Callable[[ProgressEvent], None]


def _ignore(event: ProgressEvent) -> None:
    pass


@dataclass(frozen=True)
class Target:
    """The interpreter a bundle is built for, as reported by that interpreter."""

    executable: str
    version: tuple[int, int]
    full_version: str
    platform: str
    machine: str
    abiflags: str | None
    implementation: str
    markers: dict[str, str]  # the PEP 508 environment uv.lock's markers are evaluated against

    def describe(self, native: bool) -> str:
        where = PLATFORM_NAMES.get(self.platform, self.platform)
        return f"Python {self.version[0]}.{self.version[1]} on {where}" + (
            f" {self.machine}" if native else ""
        )

    def to_json_dict(self, *, native: bool) -> dict[str, object]:
        return {
            "python": f"{self.version[0]}.{self.version[1]}",
            "python_full_version": self.full_version,
            "implementation": self.implementation,
            "platform": self.platform,
            "machine": self.machine if native else None,  # None: runs on any CPU
        }


@dataclass(frozen=True)
class Source:
    """What's being bundled: a project directory or a PEP 723 script."""

    path: Path  # project directory or script file
    name: str
    requires_python: str | None
    is_script: bool

    @property
    def workdir(self) -> Path:
        """Where uv commands run: relative paths in the lock resolve against it."""
        return self.path.parent if self.is_script else self.path


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
            "target": self.target.to_json_dict(native=self.native),
            "duration_s": round(self.duration_s, 3),
            "timings": {step: round(seconds, 3) for step, seconds in self.timings.items()},
        }


def run(
    cmd: list[str],
    *,
    progress: Progress,
    cwd: Path | None = None,
    what: str = "",
    error: type[BundleupError] = UvError,
) -> str:
    """Run a command and return its stdout, or raise `error` with its output as the detail."""
    progress(ProgressEvent("command", " ".join(cmd)))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise error(f"{what or cmd[0]} failed", detail=detail)
    return proc.stdout


MIN_UV = (0, 9)  # oldest uv whose CLI we rely on (export --no-editable, python find --script)


def find_uv() -> str:
    """The user's own uv if it's recent enough (it wrote their uv.lock), else the bundled one."""
    on_path = shutil.which("uv")
    if on_path:
        try:
            out = subprocess.run(
                [on_path, "--version"], capture_output=True, text=True, timeout=10
            ).stdout
            if tuple(int(x) for x in out.split()[1].split(".")[:2]) >= MIN_UV:
                return on_path
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass
    try:
        from uv import find_uv_bin

        return find_uv_bin()
    except (ImportError, FileNotFoundError):
        pass
    if on_path:
        return on_path  # too old or unrecognised, but better than nothing: uv's errors will say why
    raise UvNotFoundError(
        "bundleup needs uv to resolve and install dependencies, and couldn't find it",
        hint="reinstall bundleup, or install uv: "
        "https://docs.astral.sh/uv/getting-started/installation/",
    )


def load_source(path: Path) -> Source:
    """Read what's being bundled. Raises ProjectError if it isn't a project or a script."""
    path = path.resolve()
    if path.is_file() and path.suffix == ".py":
        meta = script_metadata(path.read_text(encoding="utf-8"))
        return Source(path, path.stem, meta.get("requires-python"), is_script=True)
    if path.is_dir():
        pyproject = path / "pyproject.toml"
        if not pyproject.exists():
            raise ProjectError(
                f"{path} has no pyproject.toml",
                hint="point bundleup at a project directory or a .py script",
            )
        try:
            project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project") or {}
        except tomllib.TOMLDecodeError as e:
            raise ProjectError(f"{pyproject} isn't valid TOML: {e}") from None
        if "name" not in project:
            raise ProjectError(
                f"{pyproject} has no [project] name", hint='add `name = "..."` under [project]'
            )
        return Source(path, project["name"], project.get("requires-python"), is_script=False)
    raise ProjectError(
        f"{path} is not a project directory or a .py script",
        hint="pass a directory with pyproject.toml, or a PEP 723 script",
    )


def script_metadata(text: str) -> dict[str, Any]:  # Any: TOML values have no fixed type
    """The PEP 723 `script` block, parsed as TOML (empty if there is none)."""
    blocks = [m for m in PEP723.finditer(text) if m.group("type") == "script"]
    if len(blocks) > 1:
        raise ProjectError("the script has more than one `# /// script` block")
    if not blocks:
        return {}
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in blocks[0].group("content").splitlines(keepends=True)
    )
    return tomllib.loads(content)


def find_python(uv: str, source: Source, *, request: str | None, progress: Progress) -> Target:
    """The interpreter to build for: --python if given, else what uv would use for the project."""
    if request and Path(request).is_file():
        exe = request  # a path: no need to ask uv (which would run the interpreter to inspect it)
    else:
        cmd = _find_cmd(uv, source, request=request)
        try:
            exe = run(cmd, cwd=source.workdir, what="finding a Python", progress=progress).strip()
        except UvError as e:
            wanted = f"Python {request}" if request else "a Python for this project"
            install = f"uv python install {request}" if request else "uv python install"
            raise PythonNotFoundError(
                f"couldn't find {wanted}", hint=f"install it with `{install}`", detail=e.detail
            ) from None
    probe = [exe, "-I", "-S", "-c", PROBE]
    info = json.loads(run(probe, what=f"inspecting {exe}", progress=progress, error=ProjectError))
    major, minor = info["version"]
    return Target(
        # Use the real interpreter from here on: uv re-inspects shims like macOS's
        # /usr/bin/python3 on every call, but caches what it learns about a real interpreter.
        executable=info["executable"] or exe,
        version=(major, minor),
        full_version=info["markers"]["python_full_version"],
        platform=info["markers"]["sys_platform"],
        machine=info["markers"]["platform_machine"],
        abiflags=info["abiflags"],
        implementation=info["markers"]["implementation_name"],
        markers=info["markers"],
    )


# Runs on the target Python (any version bundleup supports) and prints what the build needs.
# The marker environment follows PEP 508; on POSIX it's read from os.uname() because importing
# `platform` costs ~30 ms on macOS's system Python.
PROBE = """
import json, os, sys
def full(v):
    s = "%d.%d.%d" % (v.major, v.minor, v.micro)
    return s if v.releaselevel == "final" else s + v.releaselevel[0] + str(v.serial)
if hasattr(os, "uname"):
    u = os.uname()
    system, release, version, machine = u.sysname, u.release, u.version, u.machine
else:
    import platform
    system, release = platform.system(), platform.release()
    version, machine = platform.version(), platform.machine()
impl = sys.implementation.name
markers = {
    "implementation_name": impl,
    "implementation_version": full(sys.implementation.version),
    "os_name": os.name,
    "platform_machine": machine,
    "platform_release": release,
    "platform_system": system,
    "platform_version": version,
    "python_full_version": sys.version.split()[0],
    "platform_python_implementation": {"cpython": "CPython", "pypy": "PyPy"}.get(impl, impl),
    "python_version": "%d.%d" % sys.version_info[:2],
    "sys_platform": sys.platform,
}
print(json.dumps({"version": sys.version_info[:2], "abiflags": getattr(sys, "abiflags", None),
                  "executable": sys.executable, "markers": markers}))
"""


def _find_cmd(uv: str, source: Source, *, request: str | None) -> list[str]:
    cmd = [uv, "python", "find"]
    if request:
        cmd.append(request)
        if source.is_script:
            # A script next to a project shouldn't pick up the project's venv.
            cmd.append("--no-project")
    elif source.is_script:
        cmd += ["--script", str(source.path)]  # honours the script's requires-python
    return cmd


def check_requires_python(source: Source, target: Target) -> None:
    if not source.requires_python:
        return
    try:
        spec = SpecifierSet(source.requires_python)
    except InvalidSpecifier:
        raise ProjectError(
            f"{source.name} has an invalid requires-python: {source.requires_python!r}"
        ) from None
    if target.full_version not in spec:
        raise PythonMismatchError(
            f"{source.name} needs Python {source.requires_python}, but the target is Python "
            f"{target.full_version} ({target.executable})",
            hint=f"build for a matching Python: bundleup build --python {_suggest(spec)}",
        )


def _suggest(spec: SpecifierSet) -> str:
    for minor in range(8, 30):
        if spec.contains(f"3.{minor}.0") or spec.contains(f"3.{minor}.99"):
            return f"3.{minor}"
    return "<version>"


def export(
    uv: str, source: Source, *, lock_mode: str | None, stage: Path, progress: Progress
) -> tuple[Path, Path]:
    """Export the locked runtime dependencies (and the project itself) twice from one lock:
    as requirements, which `uv pip install` takes, and as pylock.toml (PEP 751), which the
    lock-vs-bundle check reads (uv only installs pylock.toml as a preview feature)."""
    reqs, pylock = stage / "requirements.txt", stage / "pylock.toml"
    selection = (
        ["--script", str(source.path)] if source.is_script else ["--no-dev", "--no-editable"]
    )
    if lock_mode:
        selection.append(f"--{lock_mode}")
    as_requirements = ["--no-hashes", "--no-header", "--no-annotate", "-o", str(reqs)]
    as_pylock = ["--format", "pylock.toml", "-o", str(pylock)]
    commands = [[uv, "export", "--quiet", *selection, *fmt] for fmt in (as_requirements, as_pylock)]
    try:
        with ThreadPoolExecutor(2) as pool:  # independent reads of the same lock
            futures = [
                pool.submit(run, c, cwd=source.workdir, what="uv export", progress=progress)
                for c in commands
            ]
            for future in futures:
                future.result()
    except UvError as e:
        if lock_mode == "locked" and "needs to be updated" in (e.detail or ""):
            raise LockfileOutdatedError(
                "uv.lock is out of date with pyproject.toml",
                hint="run `uv lock`, then build again",
                detail=e.detail,
            ) from None
        raise
    return reqs, pylock


def install(
    uv: str, source: Source, *, target: Target, reqs: Path, site: Path, progress: Progress
) -> None:
    """Install the exported set into `site`, the directory that becomes the payload."""
    # The export is the complete, pinned set, so --no-deps installs exactly the lock. Relative
    # paths in it (the project itself, workspace members) resolve against the working directory.
    run(
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(site),
            "--python",
            target.executable,
            "-r",
            str(reqs),
        ],
        cwd=source.workdir,
        what="uv pip install",
        progress=progress,
    )
    for name in SKIP_TOP:
        p = site / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    if source.is_script:
        dest = site / "__bundleup_script__"
        dest.mkdir()
        shutil.copy2(source.path, dest / source.path.name)


def resolve_entry(source: Source, site: Path, *, entry: str | None) -> tuple[str, str, str]:
    """What the loader runs: --entry, the project's console script, or the script itself."""
    if source.is_script:
        if entry:
            raise UsageError(
                "--entry is for projects; a script bundle runs the script",
                hint="drop --entry",
            )
        return ("script", f"__bundleup_script__/{source.path.name}", "")
    scripts = console_scripts(site, source.name)
    if entry is None:
        if len(scripts) == 1:
            entry = next(iter(scripts.values()))
        elif canonicalize_name(source.name) in scripts:
            entry = scripts[canonicalize_name(source.name)]
        elif not scripts:
            raise EntryPointError(
                f"{source.name} defines no [project.scripts], so bundleup doesn't know what to run",
                hint="add one to pyproject.toml, or pass --entry module:function",
            )
        else:
            raise EntryPointError(
                f"{source.name} defines several commands ({', '.join(sorted(scripts))})",
                hint=f"pick one: --entry {sorted(scripts)[0]}",
            )
    elif entry in scripts:
        entry = scripts[entry]
    module, _, attr = entry.partition(":")
    attr = attr.split("[")[0].strip()  # drop legacy "extras" syntax: "mod:func [extra]"
    return ("call", module.strip(), attr) if attr else ("module", module.strip(), "")


def console_scripts(site: Path, name: str) -> dict[str, str]:
    """Console and GUI scripts from the project's installed metadata (dynamic scripts too)."""
    want = canonicalize_name(name)
    for dist_info in site.glob("*.dist-info"):
        if canonicalize_name(dist_info.name.split("-")[0]) != want:
            continue
        ep = dist_info / "entry_points.txt"
        if not ep.exists():
            return {}
        scripts: dict[str, str] = {}
        section = None
        for line in ep.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]").strip()
            elif "=" in line and section in ("console_scripts", "gui_scripts"):
                key, value = line.split("=", 1)
                scripts[key.strip()] = value.strip()
        return scripts
    return {}


def inspect_site(site: Path) -> tuple[int, bool]:
    """(number of distributions, whether any of them is platform-specific)."""
    count, native = 0, False
    for wheel in site.glob("*.dist-info/WHEEL"):
        count += 1
        for line in wheel.read_text(encoding="utf-8").splitlines():
            if line.startswith("Tag:") and not line.rstrip().endswith("-any"):
                native = True
    return count, native


COMPILE_SITE = """
import compileall, py_compile, sys
compileall.compile_dir(sys.argv[1], ddir="", quiet=2, workers=int(sys.argv[2]),
                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
"""
# In .py files. Below this, spawning worker interpreters costs more than it saves.
PARALLEL_COMPILE_FROM = 300
COMPILE_LOADER = """
import py_compile, sys
py_compile.compile(sys.argv[1], cfile=sys.argv[2], dfile="__main__.py", doraise=True,
                   invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
"""


def precompile(target: Target, site: Path, *, progress: Progress) -> None:
    """Compile everything with the target Python.

    Unchecked-hash .pycs never consult the source's mtime, which suits an immutable,
    content-addressed cache and survives extraction (mtimes aren't kept).
    """
    workers = 0 if sum(1 for _ in site.rglob("*.py")) >= PARALLEL_COMPILE_FROM else 1
    run(
        [target.executable, "-I", "-c", COMPILE_SITE, str(site), str(workers)],
        what="compiling bytecode",
        progress=progress,
        error=BundleupError,
    )


def write_payload(site: Path, payload: Path) -> tuple[str, dict[str, str]]:
    """Zip the installed tree reproducibly.

    Returns the archive's sha256, and each zipped file's RECORD-style hash, for the integrity
    check and the manifest.
    """
    files = sorted(p for p in site.rglob("*") if p.is_file() or p.is_symlink())
    written: dict[str, str] = {}
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for path in files:
            rel = path.relative_to(site).as_posix()
            data = path.read_bytes()
            written[rel] = _verify.record_hash(data)
            info = zipfile.ZipInfo(rel, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = path.stat().st_mode
            info.external_attr = ((0o755 if mode & 0o111 else 0o644) | 0o100000) << 16
            zf.writestr(info, data)
    digest = hashlib.sha256()
    with open(payload, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest(), written


def verify_payload(
    site: Path, *, pylock: Path, target: Target, written: dict[str, str]
) -> list[_verify.LockedPackage]:
    """Fail the build if the payload doesn't match uv.lock and the wheels' RECORD files exactly.

    Returns the locked packages that apply to the target, for the manifest.
    """
    locked = _verify.locked_packages(pylock.read_text(encoding="utf-8"), target.markers)
    problems = _verify.check_lock(locked, _verify.installed_distributions(site))
    problems += _verify.check_records(site, written)
    if problems:
        shown = "\n".join(problems[:20])
        more = f"\n... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise BundleMismatchError(
            "the bundle wouldn't match uv.lock exactly, so it wasn't written",
            detail=f"{shown}{more}",
            hint=f"this is a bug in bundleup; please report it: {ISSUES_URL}",
        )
    return locked


def render_loader(config: dict[str, object]) -> str:
    """The loader's source with its config block replaced by this bundle's values."""
    text = LOADER.read_text(encoding="utf-8")
    head, rest = text.split("# --- config: replaced at build time ---\n", 1)
    _, tail = rest.split("# --- end config ---\n", 1)
    lines = "".join(f"{k} = {v!r}\n" for k, v in config.items())
    return f"{head}# --- config (generated by bundleup) ---\n{lines}# --- end config ---\n{tail}"


def manifest(
    *,
    source: Source,
    version: str | None,
    target: Target,
    native: bool,
    entry: tuple[str, str, str],
    cache_dir: str,
    payload: Path,
    payload_sha256: str,
    locked: list[_verify.LockedPackage],
    files: dict[str, str],
    loader: dict[str, str],
) -> bytes:
    """What's inside the bundle, with hashes: read by `bundleup verify` and by reviewers
    (`unzip -p app.pyz manifest.json`). Sorted, so the same inputs give the same bytes."""
    document = {
        "manifest_version": 1,
        "bundleup_version": __version__,
        "name": source.name,
        "version": version,
        "target": target.to_json_dict(native=native),
        "entry": list(entry),
        "cache_dir": cache_dir,
        "payload": {"sha256": payload_sha256, "size": payload.stat().st_size},
        "loader": loader,  # __main__.py and __main__.pyc: they run first, so they're checked too
        "packages": [
            {"name": p.name, "version": p.version} for p in sorted(locked, key=lambda p: p.name)
        ],
        "files": files,
    }
    return json.dumps(document, indent=1, sort_keys=True).encode("utf-8") + b"\n"


def write_bundle(
    output: Path, *, payload: Path, loader: Path, loader_pyc: Path, manifest_json: bytes
) -> None:
    """Write shebang + outer zip to a temporary file, then rename it over `output`."""
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as f:
            f.write(b"#!/usr/bin/env python3\n")
            with zipfile.ZipFile(f, "w", zipfile.ZIP_STORED) as zf:
                info = zipfile.ZipInfo("payload.zip", FIXED_TIME)
                info.external_attr = 0o100644 << 16
                with (
                    open(payload, "rb") as src,
                    zf.open(info, "w", force_zip64=payload.stat().st_size > 0x7FFFFFFF) as dest,
                ):
                    shutil.copyfileobj(src, dest, 1 << 20)
                for path, name in ((loader, "__main__.py"), (loader_pyc, "__main__.pyc")):
                    info = zipfile.ZipInfo(name, FIXED_TIME)
                    info.external_attr = 0o100644 << 16
                    zf.writestr(info, path.read_bytes())
                info = zipfile.ZipInfo(MANIFEST, FIXED_TIME)
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED  # can be MBs for big bundles
                zf.writestr(info, manifest_json)
        tmp.chmod(0o755)
        tmp.replace(output)
    finally:
        if tmp.exists():
            tmp.unlink()


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "app"


def project_version(site: Path, source: Source) -> str | None:
    """The project's version as installed (so dynamic versions work); None for a script."""
    if source.is_script:
        return None
    want = canonicalize_name(source.name)
    for dist in _verify.installed_distributions(site):
        if dist.name == want:
            return dist.version
    return None


# Build steps: a stable slug (the keys of BuildResult.timings) and what people see while it runs.
STEPS = {
    "python": "finding the Python",
    "export": "reading uv.lock",
    "install": "installing",
    "compile": "compiling",
    "zip": "zipping",
    "verify": "verifying",
    "write": "writing",
}


class _Steps:
    """Announces each build step through `progress` and times it."""

    def __init__(self, progress: Progress) -> None:
        self.progress = progress
        self.timings: dict[str, float] = {}
        self.current: str | None = None
        self.started = self.mark = time.perf_counter()

    def start(self, name: str) -> None:
        self.finish()
        self.current, self.mark = name, time.perf_counter()
        self.progress(ProgressEvent("step", STEPS[name]))

    def finish(self) -> None:
        if self.current is not None:
            self.timings[self.current] = time.perf_counter() - self.mark
            self.current = None


def build(
    options: BuildOptions, *, progress: Callable[[ProgressEvent], None] | None = None
) -> BuildResult:
    """Bundle a project or PEP 723 script into one .pyz.

    Raises a BundleupError subclass for every expected failure. Never prints; reports steps
    and commands through `progress` if given.
    """
    report = progress or _ignore
    steps = _Steps(report)
    steps.start("python")
    uv = find_uv()
    source = load_source(options.path)
    target = find_python(uv, source, request=options.python, progress=report)
    check_requires_python(source, target)
    with tempfile.TemporaryDirectory(prefix="bundleup-") as tmp:
        stage = Path(tmp)
        site = stage / "site"
        steps.start("export")
        reqs, pylock = export(uv, source, lock_mode=options.lock_mode, stage=stage, progress=report)
        steps.start("install")
        install(uv, source, target=target, reqs=reqs, site=site, progress=report)
        entry_spec = resolve_entry(source, site, entry=options.entry)
        packages, native = inspect_site(site)
        version = project_version(site, source)
        steps.start("compile")
        precompile(target, site, progress=report)
        steps.start("zip")
        payload = stage / "payload.zip"
        digest, written = write_payload(site, payload)
        steps.start("verify")
        locked = verify_payload(site, pylock=pylock, target=target, written=written)
        steps.start("write")
        name = safe_name(source.name)
        cache_dir = f"{name}-{digest[:16]}"
        config = {
            "NAME": source.name,
            "DIRNAME": cache_dir,
            "PYTHON": target.version,
            "PLATFORM": target.platform,
            "MACHINE": target.machine if native else None,
            "ABIFLAGS": target.abiflags if native else None,
            "TARGET": target.describe(native),
            "ENTRY": entry_spec,
        }
        loader, loader_pyc = stage / "__main__.py", stage / "__main__.pyc"
        loader.write_text(render_loader(config), encoding="utf-8")
        run(
            [target.executable, "-I", "-c", COMPILE_LOADER, str(loader), str(loader_pyc)],
            what="compiling the loader",
            progress=report,
            error=BundleupError,
        )
        output = (options.output or source.workdir / "dist" / f"{name}.pyz").absolute()
        manifest_json = manifest(
            source=source,
            version=version,
            target=target,
            native=native,
            entry=entry_spec,
            cache_dir=cache_dir,
            payload=payload,
            payload_sha256=digest,
            locked=locked,
            files=written,
            loader={
                "__main__.py": _verify.record_hash(loader.read_bytes()),
                "__main__.pyc": _verify.record_hash(loader_pyc.read_bytes()),
            },
        )
        write_bundle(
            output,
            payload=payload,
            loader=loader,
            loader_pyc=loader_pyc,
            manifest_json=manifest_json,
        )
        steps.finish()
    return BuildResult(
        output=output,
        size_bytes=output.stat().st_size,
        name=source.name,
        version=version,
        packages=packages,
        native=native,
        target=target,
        project_dir=source.workdir,
        duration_s=time.perf_counter() - steps.started,
        timings=steps.timings,
    )
