"""`--format exe` (ADR-0047): one file per OS and CPU that runs with nothing installed.

The file is a scie (github.com/a-scie/jump): a small launcher, scie-jump, followed by the files it
needs and a JSON manifest naming them. Here the files are a python-build-standalone interpreter
(the one uv installs) and the `.pyz`; the launcher unpacks each once into its own cache (`nce`)
and runs `python app.pyz ARGS`, from where the bundle behaves as it always does. Writing a scie
is concatenation plus the manifest, so a build for another platform only needs that platform's
launcher and interpreter as data; nothing foreign runs here.

    [ scie-jump ][ python.tar.gz ][ app.pyz ]\\n{"scie": {...}}\\n

The launcher finds the manifest after the zip end record of the last file, so the `.pyz` goes
last (docs/findings/2026-10-09-standalone-executables.md has the rules and measurements).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from ._bytecode import cache_dir
from ._errors import BundleupError, CheckFailedError, Diagnostic, UsageError
from ._formats import describe_size
from ._outputs import LARGE, check_size
from ._platforms import Platform
from ._python import Target
from ._steps import Progress, ProgressEvent, run

# scie-jump, pinned with each binary's sha256 as published beside it (release v1.13.0,
# 2026-07-27; github.com/a-scie/jump/releases). Linux uses the static (musl) build, which runs on
# glibc and musl systems alike.
JUMP_VERSION = "1.13.0"
JUMP_URL = "https://github.com/a-scie/jump/releases/download/v{version}/{asset}"
JUMPS = {
    ("darwin", "aarch64"): (
        "scie-jump-macos-aarch64",
        "a17ccad392ca4437f0c9040da9c8fc98552de4c452fc4f64b21f7d1f8099829b",
    ),
    ("darwin", "x86_64"): (
        "scie-jump-macos-x86_64",
        "1226dbf8fc6c0e045b684b816eb407433c118e0555b1cde08c5df7492b1e88e7",
    ),
    ("linux", "x86_64"): (
        "scie-jump-linux-x86_64",
        "da6d8f18fef078452e4b4942039fcb068e3571cf24f4c40c6cc6ec8dd67eb7fb",
    ),
    ("linux", "aarch64"): (
        "scie-jump-linux-aarch64",
        "08855450bc52b04f70f1e9b838b2f16e27655034989a44a74b6e062d6d8492c2",
    ),
    ("win32", "x86_64"): (
        "scie-jump-windows-x86_64.exe",
        "813d53ede4099518153edcbc97023a2afd003cad3d15d7b7af2910e797781221",
    ),
    ("win32", "aarch64"): (
        "scie-jump-windows-aarch64.exe",
        "e3aea76788a23f5dccb0daabed794c976309dd2f2005009e7b717b6c6b0bcf7d",
    ),
}
JUMP_MAGIC = 0x4A532520  # the end of a scie-jump binary: version, its length, size, this
UV_OS = {"darwin": "macos", "linux": "linux", "win32": "windows"}
TIMEOUT = 60.0  # seconds per download read


CPUS = {"arm64": "aarch64", "amd64": "x86_64", "x64": "x86_64"}  # as Pythons report them -> uv's


def host_platform(target: Target) -> Platform:
    """The platform of the interpreter a build without --python-platform used (seventh review:
    not bundleup's own process, which may run under Rosetta or be another CPU's Python)."""
    arch = CPUS.get(target.machine.lower(), target.machine.lower())
    musl = False
    if target.platform == "linux":
        try:
            musl = not os.confstr("CS_GNU_LIBC_VERSION")
        except (AttributeError, ValueError, OSError):  # not glibc: musl's confstr has no such name
            musl = True
    return Platform(name="host", sys_platform=target.platform, arch=arch, musl=musl)


def exe_cache() -> Path:
    """Launchers and interpreters for executables, kept between builds beside the bytecode cache
    (BUNDLEUP_BUILD_CACHE moves both)."""
    return cache_dir().parent / "exe"


def write_exe(
    pyz: Path,
    output: Path,
    *,
    uv: str,
    target: Target,
    platform: Platform,
    stage: Path,
    progress: Progress,
    max_size: int | None = None,
    strict: bool = False,
) -> tuple[str, list[Diagnostic]]:
    """The executable for `platform`: its launcher, an interpreter of the target's Python version
    with its standard library precompiled, and `pyz`, written next to `output` then renamed."""
    jump = fetch_jump(platform, progress)
    python = precompiled(fetch_python(uv, target, platform, stage, progress), target, stage)
    files = [
        _file(python, key="python", kind="tar.gz"),
        _file(pyz, key="app", kind="blob", name="app.pyz"),  # last: a zip (see above)
    ]
    version = f"{target.version[0]}.{target.version[1]}"
    exe = "python/python.exe" if platform.sys_platform == "win32" else f"python/bin/python{version}"
    manifest = {
        "scie": {
            "lift": {
                "name": output.name,
                "files": files,
                "boot": {
                    "commands": {
                        "": {
                            "exe": "{python}/" + exe,
                            "args": ["{app}"],
                            # The bundle's own interpreter, whatever the machine has set.
                            "env": {"PYTHONHOME": None, "PYTHONPATH": None},
                        }
                    }
                },
            },
            "jump": _jump_trailer(jump),
        }
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as out:
            for path in (jump, python, pyz):
                with open(path, "rb") as src:
                    shutil.copyfileobj(src, out, 1 << 20)
            out.write(b"\n" + json.dumps(manifest, separators=(",", ":")).encode() + b"\n")
        tmp.chmod(0o755)
        size = tmp.stat().st_size
        check_size(size, max_size, [])
        diags = [] if max_size is not None or size <= LARGE else [_large(size, python, pyz)]
        if diags and strict:  # before replacing anything, as for every other warning
            raise CheckFailedError(
                "found 1 warning, so nothing was written",
                diagnostics=diags,
                hint="--strict makes warnings fail too; build without it to allow them",
            )
        tmp.replace(output)
    finally:
        if tmp.exists():
            tmp.unlink()
    return ".".join(map(str, _patch(python))), diags


def _large(size: int, python: Path, pyz: Path) -> Diagnostic:
    return Diagnostic(
        "large-bundle",
        "warning",
        f"the executable is {describe_size(size)}: hard to ship as one file (GitHub, for one, "
        "refuses files over 100 MB)",
        hint=f"its Python is {describe_size(python.stat().st_size)} and the bundle "
        f"{describe_size(pyz.stat().st_size)}; where Python is installed, a .pyz carries only "
        "the bundle (and --split can cut it into parts)",
    )


def _file(path: Path, *, key: str, kind: str, name: str | None = None) -> dict[str, object]:
    return {
        "name": name or path.name,
        "key": key,
        "size": path.stat().st_size,
        "hash": _sha256(path),
        "type": kind,
    }


def _jump_trailer(jump: Path) -> dict[str, object]:
    """What the manifest says about the launcher: its size, version and hash, the first two read
    from the launcher's own last bytes, as scie-jump's packer does."""
    data = jump.read_bytes()
    length, size, magic = struct.unpack("<BII", data[-9:])
    if magic != JUMP_MAGIC or size != len(data):
        raise BundleupError(f"{jump} isn't a scie-jump launcher", hint=_CLEAR)
    version = data[-9 - length : -9].decode()
    return {"size": size, "version": version, "hash": hashlib.sha256(data).hexdigest()}


_CLEAR = "remove bundleup's build cache (`bundleup cache clean --build`) and build again"


def fetch_jump(platform: Platform, progress: Progress) -> Path:
    """The launcher for `platform`, downloaded once and checked against its pinned hash."""
    found = JUMPS.get((platform.sys_platform, platform.arch))
    if found is None:
        supported = ", ".join(f"{os_} {arch}" for os_, arch in JUMPS)
        raise UsageError(
            f"--format exe has no launcher for {platform.sys_platform} {platform.arch}",
            hint=f"executables can be built for {supported}",
        )
    asset, digest = found
    path = exe_cache() / "jump" / JUMP_VERSION / asset
    if path.is_file() and _sha256(path) == digest:
        return path
    url = JUMP_URL.format(version=JUMP_VERSION, asset=asset)
    progress(ProgressEvent("note", f"downloading the scie-jump {JUMP_VERSION} launcher (once)"))
    _download(url, path, digest)
    return path


def _download(url: str, path: Path, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response, open(part, "wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
        if _sha256(part) != digest:
            raise BundleupError(
                f"the download from {url} doesn't match its pinned sha256, so it wasn't used",
                hint="try again; if it keeps happening, report it: the release may have changed",
            )
        part.replace(path)
    except OSError as e:
        raise BundleupError(
            f"couldn't download {url} ({e})",
            hint="--format exe downloads its launcher once; check the network or proxy "
            "(HTTPS_PROXY)",
        ) from None
    finally:
        part.unlink(missing_ok=True)


def fetch_python(
    uv: str, target: Target, platform: Platform, stage: Path, progress: Progress
) -> Path:
    """python-build-standalone's archive of the target's Python version for `platform`, the one
    uv installs (uv checks its hash), kept in bundleup's cache. uv extracts what it downloads, so
    it installs into a throwaway folder and the archive is taken from its download cache."""
    libc = ("musl" if platform.musl else "gnu") if platform.sys_platform == "linux" else "none"
    version = f"{target.version[0]}.{target.version[1]}"
    where = f"{UV_OS[platform.sys_platform]}-{platform.arch}-{libc}"
    folder = exe_cache() / "python" / f"cpython-{version}-{where}"
    # The newest patch release uv knows, so security fixes arrive (seventh review); offline, the
    # newest one kept here.
    newest = _newest(uv, f"cpython-{version}-{where}", platform, libc, stage) or version
    wanted = tuple(int(x) for x in newest.split("."))
    found = sorted(
        (x for x in folder.glob("*.tar.gz") if _patch(x)[: len(wanted)] == wanted), key=_patch
    )
    if found:
        return found[-1]
    key = f"cpython-{newest}-{where}"
    progress(
        ProgressEvent(
            "note",
            f"downloading Python {version} for {UV_OS[platform.sys_platform]} {platform.arch} "
            "into bundleup's own folder (once); UV_PYTHON_DOWNLOADS=never turns this off",
        )
    )
    downloads, installed = stage / "python-downloads", stage / "python-installed"
    env = {
        **os.environ,
        "UV_PYTHON_CACHE_DIR": str(downloads),
        "UV_PYTHON_INSTALL_DIR": str(installed),
    }
    install = [uv, "python", "install", key, "--no-bin", "--no-registry"]
    run(install, cwd=stage, what="uv python install", progress=progress, env=env)
    archives = sorted(downloads.glob("*.tar.gz"))
    if not archives:
        raise BundleupError(
            f"uv installed {key} but kept no archive of it",
            hint="a newer uv may store downloads elsewhere; please report it",
        )
    folder.mkdir(parents=True, exist_ok=True)
    name = archives[-1].name.split("-", 1)[1]  # without uv's hash prefix
    shutil.copyfile(archives[-1], folder / f".{name}.part")
    (folder / f".{name}.part").replace(folder / name)
    shutil.rmtree(installed, ignore_errors=True)
    return folder / name


def _newest(uv: str, key: str, platform: Platform, libc: str, stage: Path) -> str | None:
    """The newest patch version uv can download for `key` ("3.12.15"), or None if uv can't say
    (offline lists still work: uv's list of downloads is built in)."""
    command = [uv, "python", "list", key, "--only-downloads", "--all-platforms", "--all-arches"]
    try:
        out = subprocess.run(
            [*command, "--output-format", "json"], capture_output=True, text=True, cwd=stage
        )
        found = json.loads(out.stdout) if out.returncode == 0 else []
    except (OSError, ValueError):
        return None
    versions = [
        tuple(entry["version_parts"][k] for k in ("major", "minor", "patch"))
        for entry in found
        if entry.get("arch") == platform.arch
        and entry.get("libc") == libc
        and entry.get("variant") == "default"
        and entry.get("implementation") == "cpython"
    ]
    return ".".join(map(str, max(versions))) if versions else None


def _patch(archive: Path) -> tuple[int, ...]:
    """(3, 12, 15) from `cpython-3.12.15-20261003-...tar.gz`, for sorting and reporting."""
    try:
        return tuple(int(x) for x in archive.name.split("-")[1].split("+")[0].split("."))
    except (IndexError, ValueError):
        return ()


def precompiled(archive: Path, target: Target, stage: Path) -> Path:
    """`archive` with its standard library compiled to bytecode, kept beside it. The macOS and
    Linux archives ship almost none (3 of 1,090 modules), so without this every run under
    PYTHONDONTWRITEBYTECODE or a read-only cache would compile the stdlib again (181 ms instead
    of 62 ms warm, measured). Bytecode depends only on the Python version, so the target's
    interpreter here compiles it for any platform; hash-based, so file times don't matter.

    Only the standard library's sources are unpacked to compile them: the archive is otherwise
    copied entry by entry (unpacking all of Linux's would collide on a case-insensitive disk:
    terminfo has names differing only in case)."""
    out = (
        archive.parent
        / "compiled"
        / f"{archive.name.removesuffix('.tar.gz')}-{target.cache_tag}.tar.gz"
    )
    if out.is_file():
        return out
    out.parent.mkdir(exist_ok=True)
    version = f"{target.version[0]}.{target.version[1]}"
    tree = stage / "python-stdlib"
    with tarfile.open(archive) as src:
        members = src.getmembers()
        names = {m.name for m in members}
        stdlib = ("python/Lib/", f"python/lib/python{version}/")  # Windows, then the others
        for m in members:
            if m.isfile() and m.name.startswith(stdlib) and m.name.endswith(".py"):
                if ".." in m.name.split("/"):
                    continue  # never outside the tree (uv checked the archive's hash anyway)
                path = tree / m.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(src.extractfile(m).read())  # type: ignore[union-attr]  # a file
    # One process, so the same bytes every time: marshal's output depends on what the process
    # compiled before (shared objects), which parallel workers split differently on each run.
    compile_all = [target.executable, "-I", "-m", "compileall", "-q"]
    # The recorded source path without this build's temporary folder (Python replaces it with
    # the real one on import): the same bytes from any build.
    compile_all += ["--invalidation-mode", "unchecked-hash", "-s", str(tree), str(tree)]
    done = subprocess.run(compile_all, capture_output=True, text=True, check=False)
    if done.returncode:  # the stdlib compiles cleanly (checked on 3.12's): a failure is real
        raise BundleupError(
            f"couldn't compile the standard library of {archive.name}",
            detail=(done.stdout + done.stderr)[-2000:],
            hint=f"{target.executable} compiled it; this is a bug, please report it",
        )
    part = out.with_name(f".{out.name}.{os.getpid()}.part")
    try:
        # No time or name in gzip's header, so a rebuilt cache gives the same bytes.
        raw = open(part, "wb")  # noqa: SIM115 (closed by the with below)
        packed = gzip.GzipFile("", "wb", compresslevel=6, fileobj=raw, mtime=0)
        with (
            raw,
            packed,
            tarfile.open(archive) as src,
            tarfile.open(fileobj=packed, mode="w") as dest,
        ):
            for m in src.getmembers():
                dest.addfile(m, src.extractfile(m) if m.isfile() else None)
            for pyc in sorted(tree.rglob("*.pyc")):
                rel = pyc.relative_to(tree).as_posix()
                if rel in names:
                    continue  # shipped already (Windows has some)
                folder = rel.rsplit("/", 1)[0]
                if folder not in names:
                    names.add(folder)
                    info = tarfile.TarInfo(folder)
                    info.type, info.mode = tarfile.DIRTYPE, 0o755
                    dest.addfile(info)
                info = tarfile.TarInfo(rel)
                info.size, info.mode = pyc.stat().st_size, 0o644
                with open(pyc, "rb") as data:
                    dest.addfile(info, data)
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(tree, ignore_errors=True)
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
