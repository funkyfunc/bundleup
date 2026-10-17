"""Target platforms for cross builds (ADR-0014): uv's names, CPU naming per OS, and wheel tags."""

from __future__ import annotations

from pathlib import Path

import pytest

from bundleup import UsageError
from bundleup import _platforms as p
from bundleup._platforms import parse


@pytest.mark.parametrize(
    ("name", "sys_platform", "machine", "musl"),
    [
        ("linux", "linux", "x86_64", False),
        ("x86_64-manylinux_2_28", "linux", "x86_64", False),
        ("aarch64-unknown-linux-gnu", "linux", "aarch64", False),
        ("x86_64-unknown-linux-musl", "linux", "x86_64", True),
        ("macos", "darwin", "arm64", False),  # macOS calls aarch64 "arm64"
        ("x86_64-apple-darwin", "darwin", "x86_64", False),
        ("windows", "win32", "AMD64", False),  # Windows calls x86_64 "AMD64"
        ("aarch64-pc-windows-msvc", "win32", "ARM64", False),
    ],
)
def test_names(name: str, sys_platform: str, machine: str, musl: bool) -> None:
    platform = parse(name)
    assert (platform.sys_platform, platform.machine, platform.musl) == (sys_platform, machine, musl)
    assert platform.name == name  # passed to uv exactly as given


@pytest.mark.parametrize(
    "name", ["wasm32-pyodide2024", "aarch64-linux-android", "sparc-sun-solaris"]
)
def test_unsupported_names_are_usage_errors(name: str) -> None:
    with pytest.raises(UsageError) as e:
        parse(name)
    assert e.value.exit_code == 2 and "x86_64-manylinux_2_28" in (e.value.hint or "")


@pytest.mark.parametrize(
    ("name", "tag", "fits"),
    [
        ("linux", "py3-none-any", True),
        ("linux", "cp311-cp311-manylinux_2_17_x86_64", True),
        ("linux", "cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64", True),
        ("linux", "cp311-cp311-musllinux_1_2_x86_64", False),
        ("x86_64-unknown-linux-musl", "cp311-cp311-musllinux_1_2_x86_64", True),
        ("linux", "cp311-cp311-manylinux_2_17_aarch64", False),
        ("linux", "cp311-cp311-macosx_11_0_arm64", False),  # built on the host by mistake
        ("macos", "cp311-cp311-macosx_11_0_arm64", True),
        ("macos", "cp311-cp311-macosx_10_9_universal2", True),
        ("macos", "cp311-cp311-macosx_10_9_x86_64", False),
        ("windows", "cp311-cp311-win_amd64", True),
        ("windows", "cp311-cp311-win32", False),
        ("aarch64-pc-windows-msvc", "cp311-cp311-win_arm64", True),
    ],
)
def test_wheel_tags(name: str, tag: str, fits: bool) -> None:
    assert parse(name).accepts(tag) is fits


def test_markers() -> None:
    markers = parse("aarch64-apple-darwin").markers(python_full_version="3.11.9")
    assert markers["sys_platform"] == "darwin"
    assert markers["platform_system"] == "Darwin"
    assert markers["platform_machine"] == "arm64"
    assert markers["python_version"] == "3.11"
    assert markers["os_name"] == "posix"
    assert parse("windows").markers(python_full_version="3.12.1")["os_name"] == "nt"


def test_runtime_needs_take_the_strictest_wheel() -> None:
    needs = p.runtime_needs(
        [
            ["cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64"],  # needs glibc 2.17
            ["cp312-cp312-manylinux_2_28_x86_64"],
            ["py3-none-any"],
        ]
    )
    assert needs == p.RuntimeNeeds(libc=("glibc", (2, 28)))
    assert p.runtime_needs([["cp39-abi3-manylinux1_x86_64"]]).libc == ("glibc", (2, 5))
    assert p.runtime_needs([["cp312-cp312-musllinux_1_2_x86_64"]]).libc == ("musl", (1, 2))
    macos = p.runtime_needs(
        [["cp312-cp312-macosx_11_0_arm64"], ["cp38-abi3-macosx_10_9_universal2"]]
    )
    assert macos == p.RuntimeNeeds(macos=(11, 0))


@pytest.mark.parametrize(
    ("release", "macos"), [("19.6.0", (10, 15)), ("24.1.0", (15, 0)), ("25.6.0", (26, 0))]
)
def test_the_macos_version_from_darwins(
    monkeypatch: pytest.MonkeyPatch, release: str, macos: tuple[int, int]
) -> None:
    from bundleup import _loader

    class Uname:
        machine = "arm64"

    Uname.release = release  # type: ignore[attr-defined]  # a stand-in for os.uname()
    monkeypatch.setattr(_loader.os, "uname", lambda: Uname, raising=False)  # none on Windows
    assert _loader._macos() == macos


@pytest.mark.parametrize(
    ("version", "machine"),
    [
        ("3.12.10 (tags/v3.12.10) [MSC v.1943 64 bit (AMD64)]", "AMD64"),
        ("3.12.10 (tags/v3.12.10) [MSC v.1943 64 bit (ARM64)]", "ARM64"),
        ("3.12.10 (tags/v3.12.10) [MSC v.1943 32 bit (Intel)]", "x86"),
    ],
)
def test_the_windows_cpu_is_the_interpreters(
    monkeypatch: pytest.MonkeyPatch, version: str, machine: str
) -> None:
    from bundleup import _loader

    monkeypatch.setattr(_loader.sys, "platform", "win32")
    monkeypatch.setattr(_loader.sys, "version", version)
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "AMD64")  # what a 32-bit process sees on x64
    assert _loader._machine() == machine


def test_tenth_review_musllinux_level_linux_tags_and_runtime_under(tmp_path: Path) -> None:
    """Tenth review: explicit musllinux_1_1 level, linux_{arch} in supported_tags, patch specifiers
    in _oldest_python, hyphenated dist-info in console_scripts, and root path in _runtime._under."""
    import os

    from bundleup import _runtime, _uv

    p_musl = parse("x86_64-musllinux_1_1")
    assert p_musl.level == (1, 1)
    assert "musllinux_1_1_x86_64" in p_musl._platform_tags()
    assert "musllinux_1_2_x86_64" not in p_musl._platform_tags()

    p_gnu = parse("x86_64-unknown-linux-gnu")
    assert "linux_x86_64" in p_gnu._platform_tags()

    assert _uv._oldest_python(">=3.12.1", (3, 13)) == "3.12"
    assert _runtime._under("/app.py", "/") is True
    if os.name == "posix":
        assert _runtime._under("/tmp/sub/app.py", "/tmp") is True
        assert _runtime._under("/tmp2/app.py", "/tmp") is False

    # Activate clears inherited BUNDLEUP_RUNTIME_SCRIPTS when switching to a different bundle
    old_site = os.environ.get(_runtime.ENV_SITE)
    old_scripts = os.environ.get(_runtime.ENV_SCRIPTS)
    try:
        os.environ[_runtime.ENV_SITE] = str(tmp_path / "bundle-a")
        os.environ[_runtime.ENV_SCRIPTS] = str(tmp_path / "bundle-a-scripts")
        site_b = tmp_path / "bundle-b-test"
        site_b.mkdir(exist_ok=True)
        try:
            _runtime.activate(str(site_b), pth=[])
            assert _runtime.ENV_SCRIPTS not in os.environ
        finally:
            if str(site_b) in _runtime.sys.path:
                _runtime.sys.path.remove(str(site_b))
    finally:
        if old_site is None:
            os.environ.pop(_runtime.ENV_SITE, None)
        else:
            os.environ[_runtime.ENV_SITE] = old_site
        if old_scripts is None:
            os.environ.pop(_runtime.ENV_SCRIPTS, None)
        else:
            os.environ[_runtime.ENV_SCRIPTS] = old_scripts


def test_eleventh_review_oldest_python_floor_aliases_entry_and_smoke(tmp_path: Path) -> None:
    """Eleventh review: _oldest_python floors at 3.9 for '>=3', parse() accepts uppercase aliases,
    resolve_entry rejects empty module/attr, smoke.parse_args catches unclosed quotes, and
    _cache.UNPACKED ignores dot-prefixed temp directories."""
    from dataclasses import replace

    from bundleup import _cache, _payload, _smoke, _uv
    from bundleup._errors import UsageError

    assert _uv._oldest_python(">=3", (3, 12)) == "3.9"
    assert replace(parse("LINUX"), name="") == replace(parse("linux"), name="")
    assert replace(parse("MacOS"), name="") == replace(parse("macos"), name="")

    from bundleup._source import Source

    src = Source(tmp_path, "app", None, is_script=False)
    with pytest.raises(UsageError, match="invalid --entry"):
        _payload.resolve_entry(src, tmp_path, entry=":main", script=None)
    with pytest.raises(UsageError, match="invalid --entry"):
        _payload.resolve_entry(src, tmp_path, entry="pkg:", script=None)
    with pytest.raises(UsageError, match="--smoke"):
        _smoke.parse_args("'unclosed quote")

    assert _cache.UNPACKED.fullmatch(".tmp-0123456789abcdef") is None
    assert _cache.UNPACKED.fullmatch("app-0123456789abcdef") is not None


def test_phase3_platform_levels_prerelease_python_runtime_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 3 audit regressions: Platform.accepts() enforces target glibc/musl/macOS level,
    uppercase tags in _levels(), invalid MACOSX_DEPLOYMENT_TARGET ignored, pre-release Python
    versions accepted by check_requires_python(), non-JSON python probe raises ProjectError,
    _runtime preserves _HOST_TAIL across module reloads and tracks sys.path[0] .pth insertions,
    _runtime.deactivate cleans child env, and _cli handles BrokenPipeError and whitespace env."""
    import sys

    from bundleup import _cli, _loader, _python, _runtime
    from bundleup._errors import ExitCode, ProjectError

    # 1. Platform.accepts() rejects wheels whose glibc/musl/macOS requirement exceeds target level
    assert parse("x86_64-manylinux_2_17").accepts("cp312-cp312-manylinux_2_28_x86_64") is False
    assert parse("x86_64-manylinux_2_28").accepts("cp312-cp312-manylinux_2_17_x86_64") is True
    assert (
        parse("x86_64-manylinux_2_17").accepts(
            "cp312-cp312-manylinux_2_17_x86_64.manylinux_2_28_x86_64"
        )
        is True
    )
    assert parse("x86_64-musllinux_1_1").accepts("cp312-cp312-musllinux_1_2_x86_64") is False
    assert parse("x86_64-musllinux_1_2").accepts("cp312-cp312-musllinux_1_1_x86_64") is True
    assert p._levels("CP312-CP312-MANYLINUX_2_28_X86_64") == {"manylinux": (2, 28)}

    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "9.0")
    assert p._level("aarch64-apple-darwin") == (13, 0)
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "-1.0")
    assert p._level("aarch64-apple-darwin") == (13, 0)
    monkeypatch.delenv("MACOSX_DEPLOYMENT_TARGET", raising=False)

    # 2. Pre-release Python accepted by check_requires_python; non-JSON probe raises ProjectError
    from bundleup._source import Source

    src = Source(tmp_path, "app", ">=3.9", is_script=False)
    pre_target = _python.Target(
        executable=sys.executable,
        version=(3, 14),
        full_version="3.14.0a1",
        platform="linux",
        machine="x86_64",
        abiflags="",
        implementation="cpython",
        cache_tag="cpython-314",
        markers={},
    )
    _python.check_requires_python(src, pre_target)

    fake_py = tmp_path / ("fake_py.bat" if sys.platform == "win32" else "fake_py")
    fake_py.write_text(
        "@echo not-json\n" if sys.platform == "win32" else "#!/bin/sh\necho not-json\n"
    )
    fake_py.chmod(0o755)
    with pytest.raises(ProjectError, match="isn't a working Python 3 interpreter"):
        _python.find_python(
            "uv", src, request=str(fake_py), python_platform=None, progress=lambda _: None
        )

    # 3. _loader._prune ignores non-hex or uppercase 16-char suffixes
    cache_root = tmp_path / "loader_cache"
    cache_root.mkdir()
    upper_dir = cache_root / "app-0123456789ABCDEF"
    upper_dir.mkdir()
    old_time = 1000.0
    import os

    os.utime(upper_dir, (old_time, old_time))
    monkeypatch.setattr(_loader, "NAME", "app")
    _loader._prune(str(cache_root))
    assert upper_dir.exists()

    # 4. _runtime: _is_py_bundle with >128B shebang, sys.path[0] .pth insertion, _HOST_TAIL reload,
    # and deactivate()
    long_shebang_bundle = tmp_path / "long_bundle.py"
    long_shebang_bundle.write_bytes(
        b"#!" + b"/nix/store/" + b"a" * 180 + b"/bin/python3\n# /// bundleup\n"
    )
    assert _runtime._is_py_bundle(str(long_shebang_bundle)) is True

    stdlib_dir = os.path.dirname(os.__file__)
    host_sp = tmp_path / "host-site-packages"
    host_sp.mkdir()
    site_a = tmp_path / "site_a"
    site_a.mkdir()
    front_dir = site_a / "front_pth"
    front_dir.mkdir()
    (site_a / "front.pth").write_text(f"import sys; sys.path.insert(0, {str(front_dir)!r})\n")
    site_b = tmp_path / "site_b"
    site_b.mkdir()

    monkeypatch.setattr(sys, "path", [stdlib_dir, str(host_sp)])
    monkeypatch.setattr(_runtime, "_HOST_TAIL", None)
    monkeypatch.delitem(sys.__dict__, "_bundleup_host_tail", raising=False)
    monkeypatch.delenv("BUNDLEUP_RUNTIME_SITE", raising=False)
    monkeypatch.delenv("BUNDLEUP_RUNTIME_PATHS", raising=False)
    monkeypatch.delenv("BUNDLEUP_RUNTIME_INHERIT", raising=False)
    monkeypatch.delenv("BUNDLEUP_INHERIT_PATH", raising=False)

    _runtime.activate(str(site_a), ["front.pth"])
    assert str(front_dir) in os.environ["BUNDLEUP_RUNTIME_PATHS"].split(os.pathsep)
    assert str(host_sp) not in sys.path

    # Simulate reloading _bundleup_runtime in child bundle_b that needs host packages (--external)
    monkeypatch.setattr(_runtime, "_HOST_TAIL", None)
    monkeypatch.setenv("BUNDLEUP_RUNTIME_INHERIT", str(site_b))
    _runtime.activate(str(site_b), [])
    assert str(front_dir) not in sys.path
    assert str(site_a) not in sys.path
    assert str(site_b) in sys.path
    assert str(host_sp) in sys.path

    shim_b = os.path.join(str(site_b), _runtime.SHIM)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([shim_b, "/custom/pp"]))
    _runtime.deactivate(shim_b)
    assert os.environ.get("PYTHONPATH") == "/custom/pp"
    assert _runtime.ENV_SITE not in os.environ

    # 5. _cli: whitespace env vars, overly long path tokens, and BrokenPipeError
    monkeypatch.setenv("BUNDLEUP_MAX_SIZE", "   ")
    monkeypatch.setenv("BUNDLEUP_SPLIT", "   ")
    monkeypatch.setenv("BUNDLEUP_OUTPUT", "   ")
    monkeypatch.setenv("BUNDLEUP_ENTRY", "   ")
    long_token = "a" * 2000
    assert _cli._looks_like_path(long_token) is False
    assert _cli._is_project_or_pep723(long_token) is False
    assert _cli._usage_error("invalid choice", [long_token]) == ExitCode.USAGE_ERROR

    def raise_broken_pipe(_opts: object) -> ExitCode:
        raise BrokenPipeError

    monkeypatch.setattr(_cli, "_run_cache", raise_broken_pipe)
    assert _cli.main(["cache", "list"]) == ExitCode.OK
