"""`--split SIZE`: a bundle too big for one file becomes a small .pyz and a folder of parts beside
it, none over SIZE (ADR-0045)."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build, verify

APP = """\
# /// script
# requires-python = ">=3.9"
# dependencies = ["colorama==0.4.6", "idna==3.10"]
# ///
import colorama
import idna  # big enough to need several parts
print("split OK", colorama.__version__)
"""
HERE = f"{sys.version_info[0]}.{sys.version_info[1]}"


def run(bundle: Path, cache: Path) -> subprocess.CompletedProcess[str]:
    env = {"BUNDLEUP_CACHE": str(cache), "PATH": "", "SYSTEMROOT": "C:\\Windows"}
    return subprocess.run([sys.executable, str(bundle)], capture_output=True, text=True, env=env)


@pytest.fixture
def app(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(APP)
    return tmp_path / "app.py"


def test_a_split_bundle_runs_verifies_and_keeps_every_file_under_the_size(
    app: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out" / "app.pyz"
    result = build(BuildOptions(path=app, output=out, python=HERE, split=100_000))
    parts = out.with_name("app.pyz.parts")
    assert result.parts == parts and len(list(parts.iterdir())) > 1
    assert all(p.stat().st_size <= 100_000 for p in [out, *parts.iterdir()])
    assert result.size_bytes == sum(p.stat().st_size for p in [out, *parts.iterdir()])
    with zipfile.ZipFile(out) as zf:  # the .pyz keeps only the loader and the manifest
        assert sorted(zf.namelist()) == ["__main__.py", "__main__.pyc", "manifest.json"]
        assert json.loads(zf.read("manifest.json"))["parts"] == "app.pyz.parts"
    assert result.to_json_dict()["parts"] == "out/app.pyz.parts"  # relative to the project
    r = run(out, tmp_path / "cache")
    assert r.returncode == 0 and r.stdout.startswith("split OK"), r.stderr
    assert verify(out).ok
    # Ninth review: a symlink in ~/bin/ pointing to the .pyz finds .parts beside the real file.
    (tmp_path / "bin").mkdir()
    link = tmp_path / "bin" / "app.pyz"
    try:
        link.symlink_to(out)
    except OSError:
        return
    r = run(link, tmp_path / "cache2")
    assert r.returncode == 0 and r.stdout.startswith("split OK"), r.stderr


def test_a_missing_or_foreign_part_is_refused_by_name(app: Path, tmp_path: Path) -> None:
    out = tmp_path / "app.pyz"
    build(BuildOptions(path=app, output=out, python=HERE, split=100_000))
    part = sorted(out.with_name("app.pyz.parts").iterdir())[0]
    data = part.read_bytes()
    part.write_bytes(data + b"x")
    r = run(out, tmp_path / "cache")
    assert r.returncode == 1 and "doesn't match it" in r.stderr and "Traceback" not in r.stderr
    assert any(part.name in p for p in verify(out).problems)
    part.unlink()
    r = run(out, tmp_path / "cache")
    assert r.returncode == 1 and f"part {part.name} is missing" in r.stderr
    assert not any((tmp_path / "cache").glob("app-*"))  # nothing unpacked under its name
    assert any("missing file" in p for p in verify(out).problems)


def test_a_bundle_that_fits_stays_one_file_and_replaces_a_stale_parts_folder(
    app: Path, tmp_path: Path
) -> None:
    out = tmp_path / "app.pyz"
    build(BuildOptions(path=app, output=out, python=HERE, split=100_000))
    assert out.with_name("app.pyz.parts").is_dir()
    result = build(BuildOptions(path=app, output=out, python=HERE, split=100_000_000))
    assert result.parts is None and not out.with_name("app.pyz.parts").exists()
    with zipfile.ZipFile(out) as zf:
        assert "payload.zip" in zf.namelist()
    r = run(out, tmp_path / "cache")
    assert r.returncode == 0, r.stderr


def test_split_mistakes_are_usage_errors(app: Path, tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="too big for a part"):
        build(BuildOptions(path=app, output=tmp_path / "a.pyz", python=HERE, split=30_000))
    with pytest.raises(UsageError, match=r"--split cuts a \.pyz"):
        build(BuildOptions(path=app, output=tmp_path / "d", python=HERE, split=10**6, format="dir"))
    (tmp_path / "b.pyz.parts").mkdir()
    (tmp_path / "b.pyz.parts" / "notes.txt").write_text("mine")
    with pytest.raises(UsageError, match="isn't a parts folder"):
        build(BuildOptions(path=app, output=tmp_path / "b.pyz", python=HERE, split=100_000))
    assert (tmp_path / "b.pyz.parts" / "notes.txt").exists()


def test_split_layer_exact_budget_boundary(tmp_path: Path) -> None:
    """Phase 3 audit: `split_layer` returns `[layer]` without raising when `layer.path` already
    fits in `budget` (even within 1 KiB of the limit), and uses exact ZIP overhead bytes."""
    from bundleup import _payload, _verify, _zipwriter

    layer_zip = tmp_path / "layer-0.zip"
    members = [
        _zipwriter.Member("big.bin", lambda: b"x" * 2048),
        _zipwriter.Member("small.py", lambda: b"y = 1\n"),
    ]
    digest, written = _zipwriter.write_zip(
        layer_zip, members, level=6, workers=1, hasher=_verify.record_hash
    )
    exact_size = layer_zip.stat().st_size
    layer = _payload.Layer(f"layer-{digest[:16]}.zip", layer_zip, digest, written, (0,))
    # 1. Layer already fits within exact_size -> returned unchanged without false UsageError
    assert _payload.split_layer(layer, exact_size, tmp_path / "stage1") == [layer]

    # 2. Budget just enough for the larger single entry (header + compressed data + CD + EOCD)
    with zipfile.ZipFile(layer_zip) as zf:
        big_comp = zf.getinfo("big.bin").compress_size
    single_min = 30 + len("big.bin") + big_comp + 46 + len("big.bin") + 22
    stage2 = tmp_path / "stage2"
    stage2.mkdir()
    parts = _payload.split_layer(layer, single_min, stage2)
    assert len(parts) == 2
    assert all(p.path.stat().st_size <= single_min for p in parts)

    # 3. Exact ZIP64 budget boundary when file_size >= LIMIT but compress_size < LIMIT
    orig_limit = _zipwriter.LIMIT
    try:
        _zipwriter.LIMIT = 500
        z64_all = tmp_path / "z64-all.zip"
        z64_one = tmp_path / "z64-one.zip"
        m1 = _zipwriter.Member("a.bin", lambda: b"x" * 600)
        m2 = _zipwriter.Member("b.bin", lambda: b"y" * 100)
        d_all, w_all = _zipwriter.write_zip(z64_all, [m1, m2], level=6, hasher=_verify.record_hash)
        _zipwriter.write_zip(z64_one, [m1], level=6, hasher=_verify.record_hash)
        exact_one = z64_one.stat().st_size
        z64_layer = _payload.Layer("layer-z64.zip", z64_all, d_all, w_all, (0,))
        stage3 = tmp_path / "stage3"
        stage3.mkdir()
        z64_parts = _payload.split_layer(z64_layer, exact_one, stage3)
        assert len(z64_parts) == 2
        assert z64_parts[0].path.stat().st_size == exact_one
        assert all(p.path.stat().st_size <= exact_one for p in z64_parts)
    finally:
        _zipwriter.LIMIT = orig_limit

    # 4. Non-ASCII, spaces, quotes, and % in member filenames across split_layer
    weird_names = [
        "café/naïve_🚀.py",
        "dir with spaces/file 'quoted' 100%.txt",
    ]
    weird_zip = tmp_path / "weird.zip"
    weird_members = [_zipwriter.Member(n, lambda: b"hello" * 80) for n in weird_names]
    w_digest, w_written = _zipwriter.write_zip(
        weird_zip, weird_members, level=6, hasher=_verify.record_hash
    )
    with zipfile.ZipFile(weird_zip) as zf:
        assert zf.getinfo("café/naïve_🚀.py").flag_bits & 0x800
    w_layer = _payload.Layer("layer-weird.zip", weird_zip, w_digest, w_written, (0,))
    stage4 = tmp_path / "stage4"
    stage4.mkdir()
    w_parts = _payload.split_layer(w_layer, weird_zip.stat().st_size - 10, stage4)
    assert len(w_parts) == 2
    unpacked_names = []
    for part in w_parts:
        with zipfile.ZipFile(part.path) as zf:
            unpacked_names.extend(zf.namelist())
    assert unpacked_names == weird_names


def test_zip64_formats_and_outer_zip_gap_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug 1 & Bug 2 regressions:
    - Building `--format zip`, `--format pyz`, and `--format py` with lowered `_zipwriter.LIMIT`
      preserves ZIP64 EOCD records (`PK\\x06\\x06`) and passes `verify()`.
    - Injecting unreferenced gap bytes into `.pyz`/`.zip` or prepending `PK\\x03\\x04` inside a
      `--format py` base64 zip is caught by `verify()`.
    - Path traversal in `manifest.json` (`cache_dir` or `parts`) raises `NotABundleError`.
    """
    import base64
    import struct

    from bundleup import NotABundleError, _loader, _zipwriter

    script = tmp_path / "hello.py"
    script.write_text('print("hello zip64")\n', encoding="utf-8")

    monkeypatch.setattr(_zipwriter, "LIMIT", 50)
    out_zip = tmp_path / "out" / "hello.zip"
    out_pyz = tmp_path / "out" / "hello.pyz"
    out_py = tmp_path / "out" / "hello.py"
    build(BuildOptions(path=script, output=out_zip, python=HERE, format="zip"))
    build(BuildOptions(path=script, output=out_pyz, python=HERE, format="pyz"))
    build(BuildOptions(path=script, output=out_py, python=HERE, format="py"))

    # Bug 2: stage_zip preserves _zipwriter's ZIP64 EOCD and Locator
    raw_zip = out_zip.read_bytes()
    assert b"PK\x06\x06" in raw_zip and b"PK\x06\x07" in raw_zip
    assert verify(out_zip).ok
    assert verify(out_pyz).ok
    assert verify(out_py).ok
    monkeypatch.undo()

    # Bug 1A: Inject unreferenced bytes between local entries and Central Directory in .pyz
    raw_pyz = out_pyz.read_bytes()
    with zipfile.ZipFile(out_pyz) as zf:
        start_dir = zf.start_dir
    cd_offset = struct.unpack("<I", raw_pyz[-6:-2])[0]
    injected = b"UNVERIFIED_GAP_BYTES"
    new_eocd = raw_pyz[-22:-6] + struct.pack("<I", cd_offset + len(injected)) + raw_pyz[-2:]
    tampered_pyz = tmp_path / "tampered_gap.pyz"
    tampered_pyz.write_bytes(raw_pyz[:start_dir] + injected + raw_pyz[start_dir:-22] + new_eocd)
    rep_pyz = verify(tampered_pyz)
    assert not rep_pyz.ok
    assert any("trailing data after the zip archive" in p for p in rep_pyz.problems)

    # Bug 1B: Prepend PK\x03\x04 before embedded zip in --format py base64 block
    raw_py = out_py.read_bytes()
    s_idx = raw_py.rfind(_loader.DATA_START)
    e_idx = raw_py.rfind(_loader.DATA_END)
    body = raw_py[s_idx + len(_loader.DATA_START) : e_idx]
    b64_bytes = b"".join(line[1:] for line in body.splitlines() if line.startswith(b"#"))
    inner_zip = base64.b64decode(b64_bytes)
    prefixed_zip = b"PK\x03\x04HIDDEN_PREFIX" + inner_zip
    new_lines = b"".join(
        b"#" + line + b"\n" for line in base64.encodebytes(prefixed_zip).splitlines()
    )
    tampered_py = tmp_path / "tampered_prefix.py"
    tampered_py.write_bytes(
        raw_py[: s_idx + len(_loader.DATA_START)] + b"\n" + new_lines + raw_py[e_idx:]
    )
    rep_py = verify(tampered_py)
    assert not rep_py.ok
    assert any("the code before its data" in p for p in rep_py.problems)

    # Bug 1C: Path traversal in manifest.json cache_dir / parts
    bad_manifest_pyz = tmp_path / "bad_manifest.pyz"
    with zipfile.ZipFile(out_pyz) as src_zf, zipfile.ZipFile(bad_manifest_pyz, "w") as dst_zf:
        for item in src_zf.infolist():
            data = src_zf.read(item.filename)
            if item.filename == "manifest.json":
                doc = json.loads(data)
                doc["cache_dir"] = "../escape"
                data = json.dumps(doc).encode("utf-8")
            dst_zf.writestr(item, data)
    with pytest.raises(NotABundleError, match="incomplete"):
        verify(bad_manifest_pyz)
