"""Regressions for ADR-0053: interpreter-free Python targets, opt-in Python downloads, private
registry 401/403 / TLS / pip.conf diagnostics, dependency range notes, optional extras vs broken
imports, multi-entry dispatch, provenance, size breakdowns, and rebuild diffs."""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from email.message import Message
from pathlib import Path

import jsonschema
import pytest

from bundleup import (
    BuildOptions,
    BundleupError,
    PythonNotFoundError,
    UvError,
    _cli,
    _exe,
    _network,
    _platforms,
    _python,
    build,
    check,
    verify,
)

ROOT = Path(__file__).parent.parent
BUILD_SCHEMA = json.loads((ROOT / "docs" / "schema" / "build-v1.json").read_text())


def _make_wheel(
    folder: Path,
    name: str,
    version: str,
    *,
    files: dict[str, bytes | str] | None = None,
    tag: str = "py3-none-any",
    requires_python: str = "",
    license_expr: str = "MIT",
) -> tuple[Path, str]:
    folder.mkdir(parents=True, exist_ok=True)
    dist = name.replace("-", "_")
    whl = folder / f"{dist}-{version}-{tag}.whl"
    req_line = f"Requires-Python: {requires_python}\n" if requires_python else ""
    lic_line = f"License-Expression: {license_expr}\n" if license_expr else ""
    payload_files: dict[str, bytes] = {
        f"{dist}.py": f'VERSION = "{version}"\n'.encode(),
    }
    if files is not None:
        payload_files = {
            k: (v.encode("utf-8") if isinstance(v, str) else v) for k, v in files.items()
        }
    meta = f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n{req_line}{lic_line}".encode()
    wheel_meta = (
        f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n".encode()
    )
    all_entries = {
        **payload_files,
        f"{dist}-{version}.dist-info/METADATA": meta,
        f"{dist}-{version}.dist-info/WHEEL": wheel_meta,
    }
    rows: list[str] = []
    with zipfile.ZipFile(whl, "w") as zf:
        for rel, raw in sorted(all_entries.items()):
            digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
            rows.append(f"{rel},sha256={digest},{len(raw)}")
            zf.writestr(rel, raw)
        rows.append(f"{dist}-{version}.dist-info/RECORD,,")
        zf.writestr(f"{dist}-{version}.dist-info/RECORD", ("\n".join(rows) + "\n").encode())
    sha = hashlib.sha256(whl.read_bytes()).hexdigest()
    return whl, sha


def test_builds_for_uninstalled_python_without_interpreter_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When `--python 3.10` or `--python 3.10-3.12` targets a Python version not installed on the
    builder, `.pyz` assembly uses the host CPython without downloading interpreters, checks AST
    and stdlib in-process, leaves `TAG = ""` when unprecompiled, and caches `.pyc` on first run."""
    proj = tmp_path / "proj"
    proj.mkdir()
    _whl, sha = _make_wheel(proj / "wheels", "acme-lib", "1.0.0")
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
        'dependencies = ["acme-lib"]\n[tool.uv]\npackage = false\n'
    )
    (proj / "main.py").write_text("import acme_lib\nprint('ok', acme_lib.VERSION)\n")
    (proj / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "hand"\nrequires-python = ">=3.9"\n'
        '[[packages]]\nname = "acme-lib"\nversion = "1.0.0"\n'
        f'wheels = [{{ path = "wheels/acme_lib-1.0.0-py3-none-any.whl", '
        f'hashes = {{ sha256 = "{sha}" }} }}]\n'
    )

    real_run = _python.run
    fetched_calls: list[str] = []

    def fake_find_run(cmd: list[str], **kw: object) -> str:
        if cmd[1:3] == ["python", "find"] and "3.9" in cmd:
            raise UvError("No interpreter found for Python 3.9")
        return real_run(cmd, **kw)  # type: ignore[arg-type]

    monkeypatch.delenv("BUNDLEUP_PYTHON_DOWNLOADS", raising=False)
    monkeypatch.delenv("UV_PYTHON_DOWNLOADS", raising=False)
    monkeypatch.setattr(_python, "run", fake_find_run)
    monkeypatch.setattr(_python, "find_interpreter", lambda *_a, **_k: None)
    monkeypatch.setattr(_python, "find_private_interpreter", lambda *_a, **_k: None)
    monkeypatch.setattr(
        _python, "fetch_interpreter", lambda *_a, **_k: fetched_calls.append("called") or None
    )

    out = tmp_path / "demo.pyz"
    res = build(BuildOptions(path=proj, output=out, python="3.9"))
    assert fetched_calls == []
    assert res.pythons is not None and res.pythons.contains((3, 9))
    assert verify(out).ok
    with zipfile.ZipFile(out) as zf:
        loader_src = zf.read("__main__.py").decode("utf-8")
    if sys.version_info[:2] != (3, 9):
        assert "TAG = ''" in loader_src

    cache = tmp_path / "cache"
    env = {**os.environ, "BUNDLEUP_CACHE": str(cache), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, env=env)
    assert (r.returncode, r.stdout.strip()) == (0, "ok 1.0.0"), r.stderr
    assert list(cache.rglob("acme_lib.*.pyc")), (
        "first run under PYTHONDONTWRITEBYTECODE cached .pyc"
    )


def test_interpreter_downloads_are_opt_in_and_surface_http_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BUNDLEUP_PYTHON_DOWNLOADS", raising=False)
    monkeypatch.delenv("UV_PYTHON_DOWNLOADS", raising=False)
    assert not _python.downloads_enabled()
    monkeypatch.setenv("BUNDLEUP_PYTHON_DOWNLOADS", "1")
    assert _python.downloads_enabled()
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
    monkeypatch.delenv("BUNDLEUP_PYTHON_DOWNLOADS", raising=False)
    assert not _python.downloads_enabled()
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "automatic")
    assert _python.downloads_enabled()

    script = tmp_path / "s.py"
    script.write_text("# /// script\n# dependencies = []\n# ///\nprint(1)\n")
    src = _python.Source(path=script, name="s", requires_python=">=3.9", is_script=True)

    def blocked_uv(cmd: list[str], **kw: object) -> str:
        if cmd[1:3] == ["python", "install"]:
            raise UvError(
                "uv python install failed",
                detail="error: Failed to download https://user:tok@github.com/astral-sh/"
                "python-build-standalone/releases/download/cpython.tar.gz\n"
                "  Caused by: HTTP status client error (403 Forbidden) for url "
                "(https://user:tok@github.com/astral-sh/cpython.tar.gz)",
            )
        raise UvError("not found")

    monkeypatch.setattr(_python, "run", blocked_uv)
    monkeypatch.setattr(_python, "find_interpreter", lambda *_a, **_k: None)
    monkeypatch.setattr(_python, "find_private_interpreter", lambda *_a, **_k: None)
    with pytest.raises(PythonNotFoundError) as exc_info:
        _python.find_python(
            "uv", src, request="3.11", python_platform=None, progress=lambda _e: None
        )
    assert "HTTP 403" in exc_info.value.message
    assert "tok" not in (exc_info.value.detail or "")
    assert exc_info.value.hint and "UV_PYTHON_INSTALL_MIRROR" in exc_info.value.hint


def test_registry_403_tls_and_pip_conf_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Registry wheel returning HTTP 403 names package, version, wheel tag, and host (redacted)
    raw_403 = UvError(
        "uv pip install failed",
        detail=(
            "  x Failed to download `pillow==12.3.0`\n"
            "  |-> HTTP status client error (403 Forbidden) for url "
            "(https://svc_user:s3cr3t@registry.example.com/api/pypi/pypi-remote/packages/"
            "Pillow-12.3.0-cp313-cp313-macosx_11_0_arm64.whl?token=hidden123)"
        ),
    )
    diag_403 = _network.diagnose_uv_error(raw_403, workdir=tmp_path, env={}, home=tmp_path)
    assert "HTTP 403" in diag_403.message
    assert "pillow 12.3.0" in diag_403.message
    assert "registry.example.com" in diag_403.message
    assert "s3cr3t" not in (diag_403.detail or "") and "hidden123" not in (diag_403.detail or "")
    assert diag_403.hint is not None
    assert "constrain `pillow`" in diag_403.hint and "do not fall back" in diag_403.hint

    # 2. Custom pip.conf + CA cert surfaced when uv lacks index / fails TLS
    pip_dir = tmp_path / ".config" / "pip"
    pip_dir.mkdir(parents=True)
    ca_pem = tmp_path / "custom-ca.pem"
    ca_pem.write_text("CERT")
    (pip_dir / "pip.conf").write_text(
        "[global]\n"
        "index-url = https://alice:hunter2@registry.example.com/api/pypi/simple\n"
        f"cert = {ca_pem}\n"
    )
    tls_err = UvError(
        "uv export failed",
        detail="error: Failed to fetch: `https://pypi.org/simple/pillow/`\n"
        "  Caused by: invalid peer certificate: UnknownIssuer",
    )
    diag_tls = _network.diagnose_uv_error(tls_err, workdir=tmp_path, env={}, home=tmp_path)
    assert "TLS certificate verification failed" in diag_tls.message
    assert diag_tls.hint is not None
    assert "UV_NATIVE_TLS=1" in diag_tls.hint
    assert f"SSL_CERT_FILE={ca_pem}" in diag_tls.hint
    assert "UV_DEFAULT_INDEX=https://registry.example.com/api/pypi/simple" in diag_tls.hint
    assert "hunter2" not in diag_tls.hint

    # 3. Launcher HTTP 403 in `--format exe` points to `.pyz` and BUNDLEUP_JUMP_MIRROR
    monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(tmp_path / "bcache"))
    monkeypatch.delenv("BUNDLEUP_JUMP_MIRROR", raising=False)

    def forbidden_urlopen(url: str, **_kw: object) -> object:
        raise urllib.error.HTTPError(url, 403, "Forbidden", Message(), io.BytesIO(b""))

    monkeypatch.setattr(_exe.urllib.request, "urlopen", forbidden_urlopen)
    with pytest.raises(BundleupError) as jump_exc:
        _exe.fetch_jump(_platforms.parse("windows"), lambda _e: None)
    assert "HTTP 403" in jump_exc.value.message
    assert jump_exc.value.hint is not None
    assert ".pyz" in jump_exc.value.hint and "BUNDLEUP_JUMP_MIRROR" in jump_exc.value.hint
    _ = http.client.HTTPException  # keep import used


def test_dependency_narrowing_python_range_is_explained(tmp_path: Path) -> None:
    proj = tmp_path / "narrow"
    proj.mkdir()
    py_minor = sys.version_info.minor
    if py_minor < 11:
        pytest.skip("requires host Python >= 3.11 to test >=3.11 dependency floor")
    _whl, sha = _make_wheel(
        proj / "wheels", "modern-dep", "2.1.0", requires_python=f">=3.{py_minor}"
    )
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "narrow"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
        'dependencies = ["modern-dep"]\n[tool.uv]\npackage = false\n'
    )
    (proj / "main.py").write_text("import modern_dep\nprint(modern_dep.VERSION)\n")
    (proj / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "hand"\nrequires-python = ">=3.9"\n'
        '[[packages]]\nname = "modern-dep"\nversion = "2.1.0"\n'
        f'wheels = [{{ path = "wheels/modern_dep-2.1.0-py3-none-any.whl", '
        f'hashes = {{ sha256 = "{sha}" }} }}]\n'
    )
    notes: list[str] = []
    check(
        BuildOptions(path=proj),
        progress=lambda e: notes.append(e.text) if e.kind == "note" else None,
    )
    assert any("modern-dep 2.1.0" in n and f"3.{py_minor - 1}" in n for n in notes), notes

    build_notes: list[str] = []
    build(
        BuildOptions(path=proj, output=tmp_path / "narrow.pyz"),
        progress=lambda e: build_notes.append(e.text) if e.kind == "note" else None,
    )
    assert any("modern-dep 2.1.0" in n for n in build_notes), build_notes


@pytest.mark.skipif(sys.version_info < (3, 10), reason="3.9 has no sys.stdlib_module_names")
def test_optional_extras_lazy_imports_and_playwright_browser_notes(tmp_path: Path) -> None:
    proj = tmp_path / "deck-skill"
    (proj / "scripts").mkdir(parents=True)
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "deck-skill"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
        "dependencies = []\n"
        '[project.optional-dependencies]\nbrowser = ["playwright>=1.40"]\n'
        "[tool.uv]\npackage = false\n"
    )
    (proj / "pylock.toml").write_text('lock-version = "1.0"\ncreated-by = "hand"\npackages = []\n')
    (proj / "scripts" / "render.py").write_text(
        "import broken_top_dep\n\n"
        "def render_browser():\n"
        "    from playwright.sync_api import sync_playwright\n"
        "    return sync_playwright\n\n"
        "def optional_chart():\n"
        "    import undeclared_lazy_chart\n"
        "    return undeclared_lazy_chart\n"
    )
    rep = check(BuildOptions(path=proj, entry="python"))
    msgs = [d for d in rep.diagnostics if d.code == "undeclared-import"]
    assert len(msgs) == 3
    by_msg = {d.message: d for d in msgs}
    assert any("imports broken_top_dep: neither" in m for m in by_msg)
    pw_diag = next(d for m, d in by_msg.items() if "playwright" in m)
    assert "optionally imports playwright (excluded optional extra [browser]" in pw_diag.message
    assert pw_diag.hint is not None and "browser binaries (`playwright install`)" in pw_diag.hint
    lazy_diag = next(d for m, d in by_msg.items() if "undeclared_lazy_chart" in m)
    assert "inside a function or branch" in lazy_diag.message

    # Also check bundled playwright driver emits the separate browser-binaries note
    site = tmp_path / "fake_site"
    (site / "playwright" / "driver" / "package").mkdir(parents=True)
    from bundleup._check import runtime_binary_notes

    assert any("browser binaries" in n for n in runtime_binary_notes(site))


def test_multiple_entry_points_support_cli_commands_and_authoring_scripts(tmp_path: Path) -> None:
    proj = tmp_path / "deck"
    (proj / "src" / "deck").mkdir(parents=True)
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "deck"\nversion = "1.0.0"\nrequires-python = ">=3.9"\n'
        "dependencies = []\n"
        '[project.scripts]\nedit = "deck:edit"\ninspect = "deck:inspect"\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    (proj / "pylock.toml").write_text('lock-version = "1.0"\ncreated-by = "hand"\n')
    (proj / "src" / "deck" / "__init__.py").write_text(
        "import sys\n"
        "def edit():\n    print('EDIT', sys.argv[1:])\n"
        "def inspect():\n    print('INSPECT', sys.argv[1:])\n"
    )
    author_script = tmp_path / "build_deck.py"
    author_script.write_text("import sys, deck\nprint('AUTHOR', deck.__name__, sys.argv[1:])\n")

    # 1. Default build preserves both [project.scripts] AND `run build_deck.py`
    multi_out = tmp_path / "deck-multi.pyz"
    res_multi = build(BuildOptions(path=proj, output=multi_out, smoke=()))
    assert res_multi.entry == "scripts"
    assert verify(multi_out).ok

    r_edit = subprocess.run(
        [sys.executable, str(multi_out), "edit", "slides.pptx"], capture_output=True, text=True
    )
    assert (r_edit.returncode, r_edit.stdout.strip()) == (0, "EDIT ['slides.pptx']"), r_edit.stderr

    r_insp = subprocess.run(
        [sys.executable, str(multi_out), "inspect", "a.pptx"], capture_output=True, text=True
    )
    assert (r_insp.returncode, r_insp.stdout.strip()) == (0, "INSPECT ['a.pptx']"), r_insp.stderr

    r_run = subprocess.run(
        [sys.executable, str(multi_out), "run", str(author_script), "--fast"],
        capture_output=True,
        text=True,
    )
    assert (r_run.returncode, r_run.stdout.strip()) == (0, "AUTHOR deck ['--fast']"), r_run.stderr

    # 2. `--entry python` also runs `[project.scripts]` commands and `run <script.py>`
    py_out = tmp_path / "deck-py.pyz"
    build(BuildOptions(path=proj, output=py_out, entry="python"))
    r_py_cmd = subprocess.run(
        [sys.executable, str(py_out), "edit", "slides.pptx"], capture_output=True, text=True
    )
    assert (r_py_cmd.returncode, r_py_cmd.stdout.strip()) == (0, "EDIT ['slides.pptx']")
    r_py_run = subprocess.run(
        [sys.executable, str(py_out), "run", str(author_script), "x"],
        capture_output=True,
        text=True,
    )
    assert (r_py_run.returncode, r_py_run.stdout.strip()) == (0, "AUTHOR deck ['x']")

    # 3. Fixed `--entry edit` supports cross-OS `--bundleup-python` and `--bundleup-entry`
    fixed_out = tmp_path / "deck-fixed.pyz"
    build(BuildOptions(path=proj, output=fixed_out, entry="edit"))
    r_bp = subprocess.run(
        [sys.executable, str(fixed_out), "--bundleup-python", str(author_script), "z"],
        capture_output=True,
        text=True,
    )
    assert (r_bp.returncode, r_bp.stdout.strip()) == (0, "AUTHOR deck ['z']")
    r_be = subprocess.run(
        [sys.executable, str(fixed_out), "--bundleup-entry", "inspect", "z.pptx"],
        capture_output=True,
        text=True,
    )
    assert (r_be.returncode, r_be.stdout.strip()) == (0, "INSPECT ['z.pptx']")


def test_provenance_size_breakdown_split_deliverables_and_rebuild_diff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    proj = tmp_path / "prov"
    proj.mkdir()
    whl1, sha1 = _make_wheel(proj / "wheels", "alpha-pkg", "1.0.0", license_expr="Apache-2.0")
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "prov"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
        'dependencies = ["alpha-pkg"]\n[tool.uv]\npackage = false\n'
    )
    (proj / "main.py").write_text("import alpha_pkg\nprint(alpha_pkg.VERSION)\n")
    (proj / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "hand"\nrequires-python = ">=3.9"\n'
        '[[packages]]\nname = "alpha-pkg"\nversion = "1.0.0"\n'
        'index = "https://token_user:supersecret@registry.example.com/api/pypi/simple"\n'
        f'wheels = [{{ path = "wheels/{whl1.name}", hashes = {{ sha256 = "{sha1}" }} }}]\n'
    )

    out_a = tmp_path / "dist" / "prov.pyz"
    out_b = tmp_path / "dist" / "prov-copy.pyz"
    res1 = build(BuildOptions(path=proj, output=out_a))
    build(BuildOptions(path=proj, output=out_b))
    assert out_a.read_bytes() == out_b.read_bytes()  # reproducible across output names
    assert res1.unpacked_bytes > 0 and res1.changes is None

    with zipfile.ZipFile(out_a) as zf:
        man1 = json.loads(zf.read("manifest.json"))
    assert man1["packages"] == [
        {
            "license": "Apache-2.0",
            "name": "alpha-pkg",
            "origin": "https://registry.example.com/api/pypi/simple",
            "version": "1.0.0",
        }
    ]

    # Upgrade alpha-pkg -> 2.0.0 and add native platform-specific wheels across macOS + Windows
    whl2, sha2 = _make_wheel(
        proj / "wheels",
        "alpha-pkg",
        "2.0.0",
        files={"alpha_pkg.py": "VERSION = '2.0.0'\n" + ("PAD = 'x' * 200\n" * 400)},
        license_expr="Apache-2.0",
    )
    blob_mac = b"".join(hashlib.sha256(f"mac-{i}".encode()).digest() for i in range(250))
    blob_win = b"".join(hashlib.sha256(f"win-{i}".encode()).digest() for i in range(300))
    whl_mac, sha_mac = _make_wheel(
        proj / "wheels",
        "nat-ext",
        "1.0.0",
        files={"nat_ext/__init__.py": "", "nat_ext/_c.so": blob_mac},
        tag="py3-none-macosx_11_0_arm64",
        license_expr="BSD-3-Clause",
    )
    whl_win, sha_win = _make_wheel(
        proj / "wheels",
        "nat-ext",
        "1.0.0",
        files={"nat_ext/__init__.py": "", "nat_ext/_c.pyd": blob_win},
        tag="py3-none-win_amd64",
        license_expr="BSD-3-Clause",
    )
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "prov"\nversion = "0.2.0"\nrequires-python = ">=3.9"\n'
        'dependencies = ["alpha-pkg", "nat-ext"]\n[tool.uv]\npackage = false\n'
    )
    (proj / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "hand"\nrequires-python = ">=3.9"\n'
        '[[packages]]\nname = "alpha-pkg"\nversion = "2.0.0"\n'
        f'wheels = [{{ path = "wheels/{whl2.name}", hashes = {{ sha256 = "{sha2}" }} }}]\n'
        '[[packages]]\nname = "nat-ext"\nversion = "1.0.0"\n'
        f"wheels = [\n"
        f'  {{ path = "wheels/{whl_mac.name}", hashes = {{ sha256 = "{sha_mac}" }} }},\n'
        f'  {{ path = "wheels/{whl_win.name}", hashes = {{ sha256 = "{sha_win}" }} }},\n'
        f"]\n"
    )

    rc = _cli.main(
        [
            "build",
            str(proj),
            "-o",
            str(out_a),
            "--python-platform",
            "aarch64-apple-darwin,x86_64-pc-windows-msvc",
            "--split",
            "80KB",
            "-v",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "sizes:" in err and "shared" in err and "ship: tar -czf" in err and "changed:" in err
    assert "added nat-ext 1.0.0" in err and "updated alpha-pkg 1.0.0" in err
    assert verify(out_a).ok

    with zipfile.ZipFile(out_a) as zf:
        man2 = json.loads(zf.read("manifest.json"))
    assert "deliverables" in man2 and man2["deliverables"][0] == "prov.pyz"

    # Validate --json output against build-v1.json schema
    rc_json = _cli.main(
        [
            "build",
            str(proj),
            "-o",
            str(out_a),
            "--python-platform",
            "aarch64-apple-darwin,x86_64-pc-windows-msvc",
            "--split",
            "80KB",
            "--json",
        ]
    )
    assert rc_json == 0
    doc = json.loads(capsys.readouterr().out)
    jsonschema.validate(doc, BUILD_SCHEMA)
    assert doc["result"]["deliverables"][0].endswith("prov.pyz")
    assert len(doc["result"]["payloads"]) == 2
    assert all("exclusive_bytes" in p and "unpacked_bytes" in p for p in doc["result"]["payloads"])
