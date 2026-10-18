"""`[tool.bundleup]` configuration (ADR-0032)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bundleup import BuildOptions, UsageError, build
from bundleup._config import apply

SCRIPT = """\
# /// script
# requires-python = ">=3.9"
# dependencies = []
# [tool.bundleup]
# format = "dir"
# output = "out"
# ///
print("hi")
"""


def project(tmp_path: Path, table: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "app"\n\n[tool.bundleup]\n{table}')
    return tmp_path


def test_a_scripts_table_applies_and_paths_are_relative_to_it(tmp_path: Path) -> None:
    (tmp_path / "tool.py").write_text(SCRIPT)
    result = build(BuildOptions(path=tmp_path / "tool.py"))
    assert result.format == "dir" and result.output == tmp_path / "out"


def test_flags_and_environment_win(tmp_path: Path) -> None:
    table = 'format = "dir"\npython = "3.11"\nstrict = true\nmax-size = "30MB"\n'
    options, used = apply(BuildOptions(path=project(tmp_path, table), format="zip"))
    assert (options.format, options.python, options.strict) == ("zip", "3.11", True)
    assert options.max_size == 30_000_000
    assert used == ['python = "3.11"', "strict = true", 'max-size = "30MB"']


@pytest.mark.parametrize(
    ("table", "message", "hint"),
    [
        ('formt = "dir"\n', "unknown key `formt`", "did you mean `format`?"),
        ('max-size = "big"\n', "can't read the size `big`", "a number with an optional unit"),
        ("json = true\n", "`json` is a per-run setting", "pass --json on the command line"),
        ("strict = 1\n", "`strict` must be true or false", "for example: strict = true"),
        ('format = "msi"\n', "unknown format `msi`", "use one of pyz, py, exe, dir, zip"),
    ],
)
def test_mistakes_are_usage_errors(tmp_path: Path, table: str, message: str, hint: str) -> None:
    with pytest.raises(UsageError, match=message) as e:
        apply(BuildOptions(path=project(tmp_path, table)))
    assert e.value.hint is not None and e.value.hint.startswith(hint)


def test_check_allows_multi_target_lists_in_tool_bundleup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ninth & tenth reviews: a project with `python-platform = [...]` in `[tool.bundleup]` can
    still run `bundleup check` and `bundleup check --matrix`, folds the extra configured platforms
    into `also_platforms` in both the API and the CLI without duplicates, and rejects multiple CLI
    `--python-platform` flags before printing 'Building for ...'."""
    from bundleup import _cli, check
    from bundleup._errors import ProjectError
    from bundleup._source import load_source
    from bundleup._uv import pinned_requirements

    (tmp_path / "tool.py").write_text(
        SCRIPT.replace('format = "dir"', 'python-platform = ["linux", "macos"]')
    )
    report = check(BuildOptions(path=tmp_path / "tool.py"), matrix=True)
    assert report.ok and report.also_platforms == ["macos"]
    report2 = check(
        BuildOptions(path=tmp_path / "tool.py"), also_platforms=["macos", "linux", "macos"]
    )
    assert report2.also_platforms == ["macos"]

    assert _cli.main(["check", str(tmp_path / "tool.py")]) == 0
    err = capsys.readouterr().err
    assert "and its wheels for macos" in err

    assert (
        _cli.main(
            [
                "check",
                "--python-platform",
                "linux",
                "--python-platform",
                "macos",
                str(tmp_path / "tool.py"),
            ]
        )
        == 0
    )
    err = capsys.readouterr().err
    assert "and its wheels for macos" in err

    assert (
        _cli.main(
            [
                "check",
                "--python",
                "3.11",
                "--python",
                "3.12",
                str(tmp_path / "tool.py"),
            ]
        )
        != 0
    )
    err = capsys.readouterr().err
    assert "Building for" not in err
    assert "one Python version at a time" in err

    # UTF-8 BOM in PEP 723 script, pyproject.toml, and requirements.txt
    bom_script = tmp_path / "bom_script.py"
    bom_script.write_bytes(("\ufeff" + SCRIPT).encode("utf-8"))
    assert load_source(bom_script).pep723 is True
    options, _ = apply(BuildOptions(path=bom_script))
    assert options.format == "dir"

    req = tmp_path / "requirements.txt"
    req.write_bytes("\ufeffclick==8.1.7\n".encode("utf-8"))
    assert pinned_requirements(req) == ({"click": "8.1.7"}, False)

    bad_pep723 = tmp_path / "bad_pep723.py"
    bad_pep723.write_text("# /// script\n# dependencies = [\n# ///\nprint(1)\n")
    with pytest.raises(ProjectError, match="isn't valid TOML"):
        load_source(bad_pep723)
    assert apply(BuildOptions(path=bad_pep723))[1] == []


def test_eleventh_review_pep263_script_empty_env_vars_and_canonical_also_platforms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eleventh review: PEP 263 latin-1 scripts build and check cleanly, `-o` cannot overwrite the
    source script, empty BUNDLEUP_* env vars are ignored, and `also_platforms` deduplicates aliases
    against their expanded platform names."""
    from bundleup import _cli, build, check
    from bundleup._errors import UsageError

    latin1 = tmp_path / "latin1_app.py"
    code = '# -*- coding: latin-1 -*-\n# café\nimport json\nprint(json.dumps("café"))\n'
    latin1.write_bytes(code.encode("latin-1"))
    res = build(BuildOptions(path=latin1, output=tmp_path / "latin1.pyz"))
    assert res.output.is_file()

    with pytest.raises(UsageError, match="overwrite"):
        build(BuildOptions(path=latin1, output=latin1))

    monkeypatch.setenv("BUNDLEUP_MAX_SIZE", "")
    monkeypatch.setenv("BUNDLEUP_SPLIT", "")
    monkeypatch.setenv("BUNDLEUP_ENTRY", "")
    assert _cli.main(["check", str(latin1)]) == 0

    report = check(
        BuildOptions(path=latin1, python_platform="macos"),
        also_platforms=["aarch64-apple-darwin"],
    )
    assert report.also_platforms == []


def test_proposals_entry_validation_venv_pinning_and_ux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    private_index: str,
) -> None:
    """P1/P7/P8/P9/P10: `--entry` validation on module/callable, `VIRTUAL_ENV` stripping for
    outside environments, fully-pinned PEP 723 script under `--locked`, exact `--max-size` on `.pyz`
    and `.py`, `BuildOptions` sequence normalization, and CLI flag typo hints."""
    from bundleup import (
        CheckFailedError,
        EntryPointError,
        NoLockfileError,
        _cli,
        build,
        check,
    )
    from bundleup._python import _find_env

    # P10: BuildOptions accepts sequences for python and python_platform
    opts = BuildOptions(python=["3.11", "3.12"], python_platform=["linux", "macos"])  # type: ignore[arg-type]
    assert opts.python == "3.11" and opts.more_pythons == ("3.12",)
    assert opts.python_platform == "linux" and opts.more_python_platforms == ("macos",)

    # P10: CLI flag typo suggests close match and subcommand help
    assert _cli.main(["build", "--formt", "pyz"]) == 2
    err = capsys.readouterr().err
    assert "did you mean `--format`?" in err and "bundleup build --help" in err

    # P7: _find_env strips VIRTUAL_ENV outside workdir when workdir has .venv or .python-version
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    with monkeypatch.context() as mp:
        mp.delenv("CONDA_PREFIX", raising=False)
        mp.setenv("VIRTUAL_ENV", str(tmp_path / "outside-venv"))
        assert _find_env(proj_dir) is None  # no .venv or .python-version yet
        (proj_dir / ".python-version").write_text("3.12\n")
        stripped = _find_env(proj_dir)
        assert stripped is not None and "VIRTUAL_ENV" not in stripped
        mp.setenv("VIRTUAL_ENV", str(proj_dir / ".venv"))
        assert _find_env(proj_dir) is None

    # P1: --entry validates module and callable in a project
    (proj_dir / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '[project]\nname = "proj"\nversion = "0.1.0"\n'
    )
    pkg = proj_dir / "proj"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def run_app() -> None:\n    print('ok')\n")
    with pytest.raises(EntryPointError, match="has no 'missing_fn'") as exc_info:
        check(BuildOptions(path=proj_dir, entry="proj:missing_fn"))
    assert exc_info.value.hint and "run_app" in exc_info.value.hint
    with pytest.raises(EntryPointError, match="isn't in the bundle"):
        check(BuildOptions(path=proj_dir, entry="nonexistent_mod:main"))
    with pytest.raises(EntryPointError, match=r"has no __main__\.py"):
        check(BuildOptions(path=proj_dir, entry="proj"))

    # P8: PEP 723 script with `==` pinned dependency counts as pinned and passes --locked
    pinned_script = tmp_path / "pinned.py"
    pinned_script.write_text(
        private_index.replace('"acme-private"', '"acme-private==1.0"') + "import acme_private\n"
    )
    rep = check(BuildOptions(path=pinned_script, lock_mode="locked"))
    assert rep.ok and not any(d.code == "unlocked" for d in rep.diagnostics)

    unpinned_script = tmp_path / "unpinned.py"
    unpinned_script.write_text(private_index + "import acme_private\n")
    with pytest.raises(NoLockfileError, match=r"unpinned\.py has no lockfile"):
        check(BuildOptions(path=unpinned_script, lock_mode="locked"))

    # P9: --max-size checks exact final .pyz and .py file size
    simple = tmp_path / "simple.py"
    simple.write_text('print("hello")\n')
    res = build(BuildOptions(path=simple, output=tmp_path / "simple.pyz"))
    actual_pyz = res.output.stat().st_size
    with pytest.raises(CheckFailedError) as size_err:
        build(
            BuildOptions(path=simple, output=tmp_path / "too_small.pyz", max_size=actual_pyz - 10)
        )
    assert not (tmp_path / "too_small.pyz").exists()
    assert any(d.code == "max-size" for d in size_err.value.diagnostics)


def test_pass1_hardening_regressions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pass 1 regressions:
    - `_has_attr` rejects unimported submodules (`pkg:sub.fn`) and function-local names, while
      accepting module-level `except ... as e:` and `vars()[...]` / imported `__getattr__`.
    - `_validate_entry` checks `site` before stdlib, rejects `xml` (no `__main__`) and
      `http.nonexistent:main`, and suggests `pkg.cli` for `pkg.cli_typo:main`.
    - `resolve_entry` rejects `.py` path traversal (`../outside.py`) and matches normalized
      console-script names (`my_tool` -> `my-tool`).
    - `--max-size` preserves pre-build warnings in `CheckFailedError.diagnostics` and removes
      newly created output parent directories (`new_dist/`) on failure.
    - `_script_pinned` rejects non-list `dependencies`.
    - `_find_env` preserves symlinked `.venv` inside `workdir`.
    - `_cli` suggests `bundleup cache clean` on `cache clear` and emits `"command": "cache list"`
      on `cache list --bad --json`.
    - `_config.apply` preserves explicit `more_pythons`."""
    import json

    from bundleup import CheckFailedError, EntryPointError, _cli, _config, build
    from bundleup._payload import _has_attr, _validate_entry, resolve_entry
    from bundleup._python import _find_env
    from bundleup._source import Source
    from bundleup._uv import _script_pinned

    site = tmp_path / "site"
    pkg = site / "mypkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "def helper():\n    local_only = 1\n    return local_only\n"
        "try:\n    top_ok = 2\nexcept Exception as top_err:\n    pass\n"
    )
    (pkg / "cli.py").write_text("def run():\n    pass\n")

    # 1. _has_attr: unimported submodule `mypkg:cli.run` and function-local `local_only` are False
    ok, _, _ = _has_attr(pkg / "__init__.py", "cli")
    assert not ok
    ok, calls, defs = _has_attr(pkg / "__init__.py", "local_only")
    assert not ok and "local_only" not in calls and "local_only" not in defs
    ok, _, _ = _has_attr(pkg / "__init__.py", "top_err")
    assert ok

    dyn = site / "dyn.py"
    dyn.write_text("vars()['made'] = 1\n")
    assert _has_attr(dyn, "anything")[0]

    # 2. _validate_entry: submodule typo hint and stdlib checks
    with pytest.raises(EntryPointError) as sub_err:
        _validate_entry(site, raw="mypkg.clii:run", module="mypkg.clii", attr="run", scripts={})
    assert sub_err.value.hint == "did you mean mypkg.cli:run?"
    with pytest.raises(EntryPointError) as avail_err:
        _validate_entry(
            site, raw="mypkg.cli_typo:run", module="mypkg.cli_typo", attr="run", scripts={}
        )
    assert avail_err.value.hint == "available in mypkg: cli"

    with pytest.raises(EntryPointError, match=r"xml.*has no __main__\.py"):
        _validate_entry(site, raw="xml", module="xml", attr="", scripts={})
    with pytest.raises(EntryPointError, match=r"http\.nonexistent"):
        _validate_entry(
            site, raw="http.nonexistent:main", module="http.nonexistent", attr="main", scripts={}
        )

    # 3. resolve_entry: blocks `../` traversal on .py entry and normalizes console script names
    outside = tmp_path / "outside.py"
    outside.write_text("print('hi')\n")
    app_src = Source(
        path=tmp_path,
        name="app",
        requires_python=None,
        is_script=False,
        pep723=False,
        pylock=None,
        declared=None,
        app=True,
    )
    with pytest.raises(EntryPointError, match="no such file"):
        resolve_entry(app_src, site, entry="../outside.py", script=None)

    dist_info = site / "mypkg-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: mypkg\nVersion: 0.1.0\n")
    (dist_info / "entry_points.txt").write_text("[console_scripts]\nmy-tool = mypkg.cli:run\n")
    (dist_info / "RECORD").write_text("")
    proj_src = Source(
        path=tmp_path,
        name="mypkg",
        requires_python=None,
        is_script=False,
        pep723=False,
        pylock=None,
        declared=tmp_path / "pyproject.toml",
        app=False,
    )
    resolved = resolve_entry(proj_src, site, entry="my_tool", script=None)
    assert str(resolved) == "mypkg.cli:run"

    # 4. --max-size preserves pre-build warnings and removes newly created parent directory
    warn_script = tmp_path / "warn_script.py"
    warn_script.write_text(
        "# /// script\n# dependencies = []\n# ///\nimport nonexistent_xyz_pkg\nprint('hi')\n"
    )
    new_dist = tmp_path / "brand_new_dist"
    with pytest.raises(CheckFailedError) as max_err:
        build(BuildOptions(path=warn_script, output=new_dist / "out.pyz", max_size=100))
    codes = [d.code for d in max_err.value.diagnostics]
    assert "undeclared-import" in codes and "max-size" in codes
    assert not new_dist.exists()

    # 5. _script_pinned returns False on non-list dependencies
    bad_pep = tmp_path / "bad_pep.py"
    bad_pep.write_text('# /// script\n# dependencies = "click"\n# ///\n')
    bad_src = Source(
        path=bad_pep,
        name="bad_pep",
        requires_python=None,
        is_script=True,
        pep723=True,
        pylock=None,
        declared=None,
    )
    pylock = tmp_path / "pylock.toml"
    pylock.write_text("packages = []\n")
    assert not _script_pinned(bad_src, pylock)

    # 6. _find_env preserves symlinked .venv inside workdir
    ext_venv = tmp_path / "ext_venv"
    ext_venv.mkdir()
    sym_proj = tmp_path / "sym_proj"
    sym_proj.mkdir()
    (sym_proj / ".venv").symlink_to(ext_venv, target_is_directory=True)
    with monkeypatch.context() as mp:
        mp.delenv("CONDA_PREFIX", raising=False)
        mp.setenv("VIRTUAL_ENV", str(sym_proj / ".venv"))
        assert _find_env(sym_proj) is None
        mp.setenv("VIRTUAL_ENV", str(ext_venv))
        assert _find_env(sym_proj) is None

    # 7. CLI cache typo and cache list --json usage error
    assert _cli.main(["cache", "clear"]) == 2
    assert "did you mean `bundleup cache clean`?" in capsys.readouterr().err
    assert _cli.main(["cache", "list", "--bad-flag", "--json"]) == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["command"] == "cache list" and doc["result"] is None

    # 8. _config.apply does not overwrite explicit more_pythons
    cfg_proj = tmp_path / "cfg_proj"
    cfg_proj.mkdir()
    (cfg_proj / "pyproject.toml").write_text('[tool.bundleup]\npython = ["3.10", "3.11"]\n')
    applied, _ = _config.apply(BuildOptions(path=cfg_proj, more_pythons=("3.12",)))
    assert applied.more_pythons == ("3.12",)


def test_pass2_hardening_regressions(tmp_path: Path) -> None:
    """Pass 2 regressions:
    - Cross-version stdlib `--entry` accepts dotted stdlib modules (`http.server`) and rejects
      non-runnable stdlib packages (`xml`) even when `target_version != sys.version_info[:2]`.
    - Namespace packages without `__init__.py` reject `--entry ns_pkg:main` with a hint when
      a submodule matches, and multi-root packages find `__init__.py` / `__main__.py` across roots.
    - `_has_attr` does not leak list/dict/set/generator comprehension target variables
      (`[x for x in ...]`) into module attributes, while preserving `:=` walrus bindings.
    - `pinned_requirements` handles Windows CRLF (`\\r\\n`) backslash line continuations.
    - `_config.apply` rejects falsy non-table `[tool] bundleup = false / []` with `ProjectError`.
    - `resolve_entry` does not let a hyphenated console script shadow a real `<entry>.py` module.
    - `BuildOptions` coerces `str` `path` and `output` to `Path`.
    - `write_dir` and `_replace_parts` reject dangling symlinks at output paths with
      `UsageError`."""
    from bundleup import EntryPointError, ProjectError, UsageError, _config, build
    from bundleup._outputs import _replace_parts
    from bundleup._payload import _has_attr, _validate_entry, resolve_entry
    from bundleup._source import Source
    from bundleup._uv import pinned_requirements

    site = tmp_path / "site"
    site.mkdir()
    (site / "dummy.py").write_text("x = 1\n")

    # 1. Cross-version stdlib --entry validation
    _validate_entry(
        site,
        raw="http.server:test",
        module="http.server",
        attr="test",
        scripts={},
        target_version=(3, 10),
    )
    with pytest.raises(EntryPointError, match=r"xml.*has no __main__\.py"):
        _validate_entry(
            site,
            raw="xml",
            module="xml",
            attr="",
            scripts={},
            target_version=(3, 10),
        )

    # 2. Namespace package with :attr and multi-root package resolution
    ns_dir = site / "ns_pkg"
    ns_dir.mkdir()
    (ns_dir / "cli.py").write_text("def main():\n    pass\n")
    with pytest.raises(EntryPointError) as ns_err:
        _validate_entry(site, raw="ns_pkg:cli.main", module="ns_pkg", attr="cli.main", scripts={})
    assert ns_err.value.hint == "did you mean ns_pkg.cli:main?"

    extra_root = site / "extra_root"
    (extra_root / "ns_pkg").mkdir(parents=True)
    (extra_root / "ns_pkg" / "__init__.py").write_text("def exported():\n    pass\n")
    (site / "extra.pth").write_text("extra_root\n")
    _validate_entry(site, raw="ns_pkg:exported", module="ns_pkg", attr="exported", scripts={})

    # 3. Comprehension loop variable does not leak into module-scope attributes
    comp_py = site / "comp_mod.py"
    comp_py.write_text("items = [leaked_var for leaked_var in range(3)]\n")
    ok, _, defs = _has_attr(comp_py, "leaked_var")
    assert not ok and "leaked_var" not in defs
    walrus_py = site / "walrus_mod.py"
    walrus_py.write_text("items = [(bound_var := i) for i in range(3)]\n")
    assert _has_attr(walrus_py, "bound_var")[0]

    # 4. CRLF backslash line continuations in requirements.txt
    crlf_req = tmp_path / "crlf_requirements.txt"
    crlf_req.write_bytes(b"click==8.1.7 \\\r\n    --hash=sha256:abcdef\r\n")
    assert pinned_requirements(crlf_req) == ({"click": "8.1.7"}, True)

    # 5. Falsy non-table [tool] bundleup = false / [] raises ProjectError
    falsy_proj = tmp_path / "falsy_proj"
    falsy_proj.mkdir()
    (falsy_proj / "pyproject.toml").write_text("[tool]\nbundleup = false\n")
    with pytest.raises(
        ProjectError, match=r"\[tool\.bundleup\] in pyproject\.toml must be a table"
    ):
        _config.apply(BuildOptions(path=falsy_proj))

    # 6. Top-level <entry>.py is not shadowed by canonicalized script name
    (site / "my_tool.py").write_text("def run():\n    pass\n")
    dist_info = site / "mypkg-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: mypkg\nVersion: 0.1.0\n")
    (dist_info / "entry_points.txt").write_text("[console_scripts]\nmy-tool = dummy:x\n")
    (dist_info / "RECORD").write_text("")
    proj_src = Source(
        path=tmp_path,
        name="mypkg",
        requires_python=None,
        is_script=False,
        pep723=False,
        pylock=None,
        declared=tmp_path / "pyproject.toml",
        app=False,
    )
    assert resolve_entry(proj_src, site, entry="my_tool", script=None) == ("module", "my_tool", "")

    # 7. BuildOptions coerces str path and output to Path
    str_opts = BuildOptions(path="some/dir", output="dist/app.pyz")  # type: ignore[arg-type]
    assert isinstance(str_opts.path, Path) and isinstance(str_opts.output, Path)

    # 8. Dangling symlink at _replace_parts or write_dir output raises UsageError
    dangling_parts = tmp_path / "dangling.parts"
    dangling_parts.symlink_to(tmp_path / "nonexistent_target")
    with pytest.raises(UsageError, match="already exists and isn't a parts folder"):
        _replace_parts(dangling_parts, {"layer-0123456789abcdef.zip": comp_py})

    simple = tmp_path / "simple2.py"
    simple.write_text("print('ok')\n")
    dangling_dir = tmp_path / "dangling_out"
    dangling_dir.symlink_to(tmp_path / "nonexistent_target")
    with pytest.raises(UsageError, match="already exists and isn't a directory"):
        build(BuildOptions(path=simple, output=dangling_dir, format="dir"))


def test_pass3_hardening_regressions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass 3 regressions:
    - `-o` overwrite guard protects `pyproject.toml`, `uv.lock`, `<script>.lock`, and folder-app
      source files (`main.py`).
    - `_locate_module` and `resolve_entry` enforce strict case-sensitivity on macOS/Windows
      filesystems, normalize `./main.py` and `sub\\worker.py` in folder apps, give regular
      packages precedence over `.py` files, and suggest `mod:main` for `mod.main` / `mod.py:main`.
    - `_has_attr` recognizes `import pkg.sub` inside `pkg/__init__.py` and includes imported
      callables in typo hints even when local functions exist.
    - Folder apps with scripts in a subdirectory (`scripts/tool.py` importing sibling
      `scripts/helper.py`) run and pass `--strict` without false or duplicate `undeclared-import`
      warnings.
    - Zero-dependency scripts without a PEP 723 block succeed under `--locked`.
    - `[tool.bundleup]` settings for `.pyz` (`split`, `python = [...]`) do not break CLI
      `--format dir` overrides or `for_check=True`.
    - `_find_env` detects `.venv` at a uv workspace root when building a workspace member."""
    import subprocess
    import sys

    from bundleup import EntryPointError, _config, build, check
    from bundleup._build import _input_files
    from bundleup._payload import _has_attr, _validate_entry, resolve_entry
    from bundleup._python import _find_env
    from bundleup._source import Source

    # 1. _input_files protects pyproject.toml, uv.lock, script.lock, and folder-app own files
    locked_proj = tmp_path / "locked_proj"
    locked_proj.mkdir()
    (locked_proj / "pyproject.toml").write_text('[project]\nname = "p"\nversion = "0.1.0"\n')
    (locked_proj / "uv.lock").write_text("version = 1\n")
    (locked_proj / "main.py").write_text("print(1)\n")
    src_proj = Source(
        path=locked_proj,
        name="p",
        requires_python=None,
        is_script=False,
        pep723=False,
        pylock=None,
        declared=None,
        app=True,
    )
    protected = _input_files(src_proj, ["main.py"])
    assert (locked_proj / "pyproject.toml").resolve() in protected
    assert (locked_proj / "uv.lock").resolve() in protected
    assert (locked_proj / "main.py").resolve() in protected

    # 2. Case-sensitive module/script lookup, package precedence, import pkg.sub, and hints
    site = tmp_path / "site3"
    pkg = site / "my_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        "import my_pkg.sub\nfrom .cli import run_cli\ndef _helper():\n    pass\n"
    )
    (pkg / "sub.py").write_text("def go():\n    pass\n")
    (pkg / "cli.py").write_text("def run_cli():\n    pass\n")
    (site / "single_mod.py").write_text("def main():\n    pass\n")

    # Wrong-case module name rejected even on case-insensitive APFS/NTFS
    with pytest.raises(EntryPointError) as case_err:
        _validate_entry(site, raw="My_Pkg:run_cli", module="My_Pkg", attr="run_cli", scripts={})
    assert case_err.value.hint == "did you mean my_pkg:run_cli?"

    # `import my_pkg.sub` inside `my_pkg/__init__.py` binds `sub` on `my_pkg`
    assert _has_attr(pkg / "__init__.py", "sub")[0]
    _validate_entry(site, raw="my_pkg:sub.go", module="my_pkg", attr="sub.go", scripts={})

    # Imported `run_cli` is suggested even when `_helper` is in `callables`
    with pytest.raises(EntryPointError) as imp_err:
        _validate_entry(site, raw="my_pkg:run_clii", module="my_pkg", attr="run_clii", scripts={})
    assert imp_err.value.hint == "did you mean my_pkg:run_cli?"

    # Single-file module `single_mod.main` and `single_mod.py` hints
    with pytest.raises(EntryPointError) as dot_err:
        _validate_entry(site, raw="single_mod.main", module="single_mod.main", attr="", scripts={})
    assert dot_err.value.hint == "did you mean single_mod:main?"
    with pytest.raises(EntryPointError) as py_err:
        _validate_entry(
            site, raw="single_mod.py:main", module="single_mod.py", attr="main", scripts={}
        )
    assert py_err.value.hint == "did you mean single_mod:main?"

    # Folder app normalizes `./` and `\` and enforces exact case on `.py` entry
    (site / "sub_dir").mkdir()
    (site / "sub_dir" / "worker.py").write_text("print('work')\n")
    app_src = Source(
        path=site,
        name="app",
        requires_python=None,
        is_script=False,
        pep723=False,
        pylock=None,
        declared=None,
        app=True,
    )
    assert resolve_entry(app_src, site, entry="./sub_dir\\worker.py", script=None) == (
        "script",
        "sub_dir/worker.py",
        "",
    )
    with pytest.raises(EntryPointError, match="no such file"):
        resolve_entry(app_src, site, entry="sub_dir/Worker.py", script=None)

    # 3. Folder app with subdirectory script importing sibling helper + zero-dep --locked
    folder_app = tmp_path / "folder_app"
    (folder_app / "scripts").mkdir(parents=True)
    (folder_app / "main.py").write_text("print('root')\n")
    (folder_app / "scripts" / "helper.py").write_text("VAL = 42\n")
    (folder_app / "scripts" / "tool.py").write_text("import helper\nprint(helper.VAL)\n")
    app_pyz = tmp_path / "folder_app.pyz"
    res = build(
        BuildOptions(
            path=folder_app,
            entry="scripts/tool.py",
            output=app_pyz,
            lock_mode="locked",
            strict=True,
        )
    )
    out = subprocess.check_output([sys.executable, str(res.output)], text=True)
    assert out.strip() == "42"

    # Also check folder app with `--entry python` and non-identifier subdir has no duplicate warning
    (folder_app / "requirements.txt").write_text("")
    (folder_app / "my-scripts").mkdir()
    (folder_app / "my-scripts" / "bad.py").write_text("import missing_mod_xyz\n")
    rep = check(BuildOptions(path=folder_app, entry="python"))
    undec = [d for d in rep.diagnostics if d.code == "undeclared-import"]
    assert len(undec) == 1 and undec[0].file == "my-scripts/bad.py"

    # 4. [tool.bundleup] split / multi-python with CLI --format override and for_check=True
    cfg_dir = tmp_path / "cfg_override"
    cfg_dir.mkdir()
    (cfg_dir / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\n'
        'python = ["3.11", "3.12"]\nsplit = "50MB"\nentry = "python"\n'
    )
    applied_dir, _ = _config.apply(BuildOptions(path=cfg_dir, format="dir"))
    assert applied_dir.split is None
    assert applied_dir.more_pythons == ()
    assert applied_dir.entry is None
    applied_chk, used_chk = _config.apply(BuildOptions(path=cfg_dir), for_check=True)
    assert applied_chk.more_pythons == () and 'python = "3.11"' in used_chk

    # 5. _find_env detects .venv at a uv workspace root
    ws_root = tmp_path / "ws"
    ws_member = ws_root / "packages" / "member"
    ws_member.mkdir(parents=True)
    (ws_root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["packages/*"]\n')
    (ws_root / "uv.lock").write_text("version = 1\n")
    (ws_root / ".venv").mkdir()
    with monkeypatch.context() as mp:
        mp.delenv("CONDA_PREFIX", raising=False)
        mp.setenv("VIRTUAL_ENV", str(tmp_path / "foreign-venv"))
        env = _find_env(ws_member)
        assert env is not None and "VIRTUAL_ENV" not in env
        mp.setenv("VIRTUAL_ENV", str(ws_root / ".venv"))
        assert _find_env(ws_member) is None


def test_adr0051_js_bundler_learnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    private_index: str,
) -> None:
    """ADR-0051 learnings from JS bundlers:
    1. `--external` (CLI, `BuildOptions`, `[tool.bundleup]`, `BUNDLEUP_EXTERNAL`), suppressing
       `undeclared-import`, stripping from PEP 723 / `requirements.txt` / `pylock.toml`, and setting
       `EXTERNAL = True` so the `.pyz` runtime defaults `BUNDLEUP_INHERIT_PATH=1`.
    2. Comma-separated list flags (`--python-platform linux,macos`, `--python 3.11,3.12`,
       `--external torch,cuda`).
    3. Muscle-memory CLI hints (`bundleup app.py`, `bundleup dist/app.pyz`, `--platform`,
       `--target`, `--outfile`, `--entrypoint`, `--externals`, `--onefile`, `--analyze`,
       `--metafile`).
    4. 2-line diagnostic code frames on `syntax-error`, `python-range`, `undeclared-import`
       (including `line`), and `[tool.bundleup]` config errors.
    5. `check -v` and `check --json` `required_by` dependency chains (`via a → b`) and percentage
       share of total unpacked size.
    6. Lock-keyed `uv export` cache (`export_cache_dir()`, `_export_cache_key()`,
       `clean_cache(build=True)`)."""
    import subprocess
    import sys
    import zipfile

    from bundleup import UsageError, _cache, _check, _cli, _config, _uv, build, check
    from bundleup._python import PythonRange, Target
    from bundleup._source import Source
    from bundleup._verify import record_hash

    # 1. Comma-separated list flags in BuildOptions and CLI
    opts = BuildOptions(
        python="3.11,3.12",
        python_platform="linux,macos",
        external="torch,cuda,torch",  # type: ignore[arg-type]
    )
    assert opts.python == "3.11" and opts.more_pythons == ("3.12",)
    assert opts.python_platform == "linux" and opts.more_python_platforms == ("macos",)
    assert opts.external == ("torch", "cuda")

    # 2. Muscle-memory CLI hints
    assert _cli.main(["app.py"]) == 2
    assert "did you mean `bundleup build app.py`?" in capsys.readouterr().err
    assert _cli.main(["dist/app.pyz"]) == 2
    assert "did you mean `bundleup verify dist/app.pyz`?" in capsys.readouterr().err
    for bad_flag, expected in [
        ("--platform=linux", "did you mean `--python-platform`?"),
        ("--target=3.12", "did you mean `--python`?"),
        ("--outfile=out.pyz", "did you mean `-o / --output`?"),
        ("--entrypoint=app:main", "did you mean `-e / --entry`?"),
        ("--externals=torch", "did you mean `--external`?"),
        ("--onefile", "did you mean `--format scie`?"),
        ("--analyze", "try `bundleup check -v`"),
        ("--metafile", "try `bundleup check --json`"),
    ]:
        assert _cli.main(["build", bad_flag]) == 2
        assert expected in capsys.readouterr().err

    # 3. [tool.bundleup] external configuration + 2-line code frame on config error
    cfg_dir = tmp_path / "cfg_ext"
    cfg_dir.mkdir()
    (cfg_dir / "pyproject.toml").write_text(
        '[project]\nname = "app"\n\n[tool.bundleup]\nexternal = ["torch", "pyyaml"]\n'
    )
    applied, used = _config.apply(BuildOptions(path=cfg_dir))
    assert applied.external == ("torch", "pyyaml")
    assert "external = ['torch', 'pyyaml']" in used

    bad_cfg = tmp_path / "bad_cfg"
    bad_cfg.mkdir()
    (bad_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\nstrict = 1\n'
    )
    with pytest.raises(UsageError) as cfg_err:
        _config.apply(BuildOptions(path=bad_cfg))
    assert cfg_err.value.detail is not None and "4 | strict = 1" in cfg_err.value.detail

    # 4. --external on PEP 723 script: prunes declared dep (`acme-private`), suppresses
    # `undeclared-import` for `host-only-mod`, and sets `EXTERNAL = True` in `.pyz` `__main__.py`
    # so host site-packages remain importable at runtime
    host_site = tmp_path / "host_site"
    host_site.mkdir()
    (host_site / "host_only_mod.py").write_text("GREETING = 'from-host'\n")
    ext_script = tmp_path / "ext_app.py"
    ext_script.write_text(
        private_index
        + "import host_only_mod\n"
        + "import undeclared_host_pkg\n"
        + "print(host_only_mod.GREETING)\n"
    )
    rep_without = check(BuildOptions(path=ext_script, external=("acme-private", "host-only-mod")))
    assert [p.name for p in rep_without.packages] == ["ext-app"]
    undec = [d for d in rep_without.diagnostics if d.code == "undeclared-import"]
    assert len(undec) == 1 and undec[0].line == 13
    assert undec[0].detail is not None and "13 | import undeclared_host_pkg" in undec[0].detail

    # With only host_only_mod imported, strict build succeeds and runs with PYTHONPATH=host_site
    ext_script.write_text(
        private_index.replace('"acme-private"', '"acme-private==1.0"')
        + "import host_only_mod\nprint(host_only_mod.GREETING)\n"
    )
    ext_pyz = tmp_path / "ext_app.pyz"
    res = build(
        BuildOptions(
            path=ext_script,
            output=ext_pyz,
            external=("acme-private", "host-only-mod"),
            strict=True,
        )
    )
    assert res.packages == 0  # acme-private was pruned from the bundle
    with zipfile.ZipFile(res.output) as zf:
        main_src = zf.read("__main__.py").decode("utf-8")
    assert "EXTERNAL = True" in main_src
    env = {"PYTHONPATH": str(host_site), "BUNDLEUP_CACHE": str(tmp_path / "cache"), "PATH": ""}
    out = subprocess.check_output([sys.executable, str(res.output)], text=True, env=env)
    assert out.strip() == "from-host"

    # Also test _uv._strip_external and from_pylock with external
    pylock_file = tmp_path / "pylock.toml"
    pylock_file.write_text(
        'lock-version = "1.0"\n'
        '[[packages]]\nname = "torch"\nversion = "2.2.0"\n'
        '[[packages.wheels]]\nurl = "https://example.com/torch-2.2.0-py3-none-any.whl"\n'
        '[[packages]]\nname = "six"\nversion = "1.16.0"\n'
        '[[packages.wheels]]\nurl = "https://example.com/six-1.16.0-py3-none-any.whl"\n'
    )
    stripped_text = _uv._strip_external(pylock_file.read_text(), ("torch",))
    assert 'name = "torch"' not in stripped_text and 'name = "six"' in stripped_text

    target = Target(
        executable=sys.executable,
        version=(3, 12),
        full_version="3.12.0",
        platform="linux",
        machine="x86_64",
        abiflags=None,
        implementation="cpython",
        cache_tag="cpython-312",
        markers={},
    )
    pylock_src = Source(
        path=tmp_path,
        name="app",
        requires_python=None,
        is_script=False,
        pep723=False,
        pylock=pylock_file,
        declared=None,
    )
    work_stage = tmp_path / "work"
    work_stage.mkdir()
    _, check_lock = _uv.from_pylock(pylock_src, work_stage, external=("torch",))
    pylock_reqs = check_lock.read_text()
    assert 'name = "torch"' not in pylock_reqs and 'name = "six"' in pylock_reqs

    # 5. PackageSize.required_by dependency chains and check -v percentage + via output
    site = tmp_path / "chain_site"
    for pkg_name, ver, deps, body in [
        ("app", "0.1.0", ["rich>=13.0"], "x = 1\n" * 10),
        ("rich", "13.7.0", ["markdown-it-py>=2.2"], "x = 1\n" * 40),
        ("markdown_it_py", "3.0.0", ["mdurl~=0.1"], "x = 1\n" * 30),
        ("mdurl", "0.1.2", [], "x = 1\n" * 20),
    ]:
        dinfo = site / f"{pkg_name}-{ver}.dist-info"
        dinfo.mkdir(parents=True)
        req_lines = "".join(f"Requires-Dist: {d}\n" for d in deps)
        meta_name = pkg_name.replace("_", "-")
        (dinfo / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {meta_name}\nVersion: {ver}\n{req_lines}"
        )
        (dinfo / "WHEEL").write_text("Wheel-Version: 1.0\nTag: py3-none-any\n")
        mod_file = f"{pkg_name}.py"
        (site / mod_file).write_text(body)
        h = record_hash(body.encode())
        (dinfo / "RECORD").write_text(f"{mod_file},{h},{len(body)}\n")
    owned = _check.owners(site, project="app")
    sizes = _check.package_sizes(site, owned, project="app")
    by_name = {p.name: p for p in sizes}
    assert by_name["app"].required_by == ()
    assert by_name["rich"].required_by == ()
    assert by_name["markdown-it-py"].required_by == ("rich",)
    assert by_name["mdurl"].required_by == ("rich", "markdown-it-py")

    import argparse

    from bundleup._term import Style

    rep = _check.CheckReport(
        name="app",
        version="0.1.0",
        target=target,
        native=False,
        packages=sizes,
        diagnostics=[],
        duration_s=0.1,
    )
    lines = _cli._check_lines(rep, argparse.Namespace(verbose=1), Style(sys.stderr, "never"))
    joined = "\n".join(lines)
    assert "%" in joined
    assert "via rich" in joined
    assert "medium" not in joined

    # Also check python-range code frame
    from bundleup import _bytecode

    (site / "app.py").write_text("match 1:\n    case 1:\n        pass\n")
    pyc = site / _bytecode.pyc_path("app.py", target.cache_tag)
    pyc.parent.mkdir(parents=True, exist_ok=True)
    pyc.write_bytes(b"")
    _, range_diags = _check.oldest_python(
        site,
        project="app",
        script=None,
        pythons=PythonRange((3, 9), None),
        target=target,
        interpreters={(3, 9): None},
        run=lambda cmd: "",
    )
    assert (
        range_diags[0].detail is not None
        and "pass" in range_diags[0].detail
        and "^" in range_diags[0].detail
    )

    # 6. Lock-keyed uv export cache and clean_cache(build=True)
    monkeypatch.setenv("BUNDLEUP_CACHE", str(tmp_path / "bcache"))
    exp_dir = _uv.export_cache_dir()
    exp_dir.mkdir(parents=True, exist_ok=True)
    cached_entry = exp_dir / "deadbeef.txt"
    cached_entry.write_text("six==1.16.0\n")
    clean_rep = _cache.clean_cache(build=True)
    assert exp_dir in clean_rep.removed and not cached_entry.exists()


def test_pass4_iteration1_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pass 1 regressions: external stripping in scripts/requirements, markers in required_by,
    config line scan, and CLI hints."""
    from bundleup import _check, _cli, _config, _imports, _uv
    from bundleup._source import load_source
    from bundleup._verify import record_hash

    # 1. external_modules strips version specifiers/extras and code_frame truncates long lines
    assert "torch" in _imports.external_modules(("torch[cuda]>=2.0",))
    assert "yaml" in _imports.external_modules(("PyYAML==6.0",))
    long_py = tmp_path / "long.py"
    long_py.write_text("x = " + ("a" * 200) + "\n")
    frame = _imports.code_frame(long_py, 1)
    assert frame is not None and "..." in frame.splitlines()[0]
    assert len(frame.splitlines()[0]) <= 135

    # 2. _strip_script_external and _strip_requirements_external + pinned checks ignoring external
    stage = tmp_path / "stage"
    stage.mkdir()
    script = tmp_path / "script.py"
    script.write_text(
        "# /// script\n"
        "# dependencies = [\n"
        '#   "host_only_pkg>=1.0",\n'
        '#   "click==8.1.7",\n'
        "# ]\n"
        "# ///\n"
        "print(1)\n"
    )
    pylock = tmp_path / "script.pylock.toml"
    pylock.write_text('lock-version = "1.0"\n[[packages]]\nname = "click"\nversion = "8.1.7"\n')
    src = load_source(script, external=("host-only-pkg",))
    assert _uv._script_pinned(src, pylock, external=("host-only-pkg",)) is True
    assert _uv._script_pinned(src, pylock, external=()) is False
    staged_script = _uv._strip_script_external(script, {"host-only-pkg"}, stage)
    text = staged_script.read_text()
    assert "host_only_pkg" not in text
    assert "click==8.1.7" in text

    req = tmp_path / "requirements.txt"
    req.write_text("host-only-pkg>=1.0\nclick==8.1.7\n")
    pins_ext, _ = _uv.pinned_requirements(req, external=("host_only_pkg",))
    pins_no_ext, _ = _uv.pinned_requirements(req, external=())
    assert pins_ext == {"click": "8.1.7"}
    assert pins_no_ext is None
    staged_req = _uv._strip_requirements_external(req, {"host-only-pkg"}, stage)
    assert staged_req is not None
    assert "host-only-pkg" not in staged_req.read_text()
    assert "click==8.1.7" in staged_req.read_text()
    assert _uv._strip_requirements_external(req, {"host-only-pkg", "click"}, stage) is None

    # 3. _dependency_chains respects target markers (e.g. sys_platform)
    markers = {"sys_platform": "linux", "os_name": "posix", "platform_system": "Linux"}
    site = tmp_path / "site_markers"
    site.mkdir()
    for pkg_name, ver, req_lines in [
        (
            "app",
            "0.1.0",
            (
                "Requires-Dist: winpkg; sys_platform == 'win32'\n"
                "Requires-Dist: linpkg; sys_platform == 'linux'\n"
            ),
        ),
        ("winpkg", "1.0.0", "Requires-Dist: subpkg; sys_platform == 'win32'\n"),
        ("linpkg", "1.0.0", ""),
        ("subpkg", "1.0.0", ""),
    ]:
        dinfo = site / f"{pkg_name}-{ver}.dist-info"
        dinfo.mkdir()
        (dinfo / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {pkg_name}\nVersion: {ver}\n{req_lines}"
        )
        (dinfo / "WHEEL").write_text("Wheel-Version: 1.0\nTag: py3-none-any\n")
        body = b"x = 1\n"
        (site / f"{pkg_name}.py").write_bytes(body)
        (dinfo / "RECORD").write_text(f"{pkg_name}.py,{record_hash(body)},{len(body)}\n")
    owned = _check.owners(site, project="app")
    sizes = _check.package_sizes(site, owned, project="app", markers=markers)
    by_name = {p.name: p for p in sizes}
    assert by_name["linpkg"].required_by == ()
    assert by_name["subpkg"].required_by == ()

    # 4. _key_line handles multiline arrays with leading `[` inside [tool.bundleup]
    raw_toml = tmp_path / "key_line_pyproject.toml"
    raw_toml.write_text(
        '[tool.bundleup]\ninclude = [\n  "[a-z].txt",\n]\nbad_key = 1\n[other]\nbad_key = 2\n'
    )
    assert _config._key_line(raw_toml, "bad_key") == 5

    # 5. _usage_error suggests subcommand for cross-command flags and existing project directories
    proj_dir = tmp_path / "my_service"
    proj_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    assert _cli.main(["my_service"]) == _cli.ExitCode.USAGE_ERROR
    err1 = capsys.readouterr().err
    assert "did you mean `bundleup build my_service`?" in err1

    assert _cli.main(["check", "--max-size", "10MB"]) == _cli.ExitCode.USAGE_ERROR
    err2 = capsys.readouterr().err
    assert "`--max-size` is an option for `bundleup build`, not `bundleup check`" in err2


def test_pass4_iteration2_regressions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass 2 regressions: BUNDLEUP_RUNTIME_INHERIT isolation + .pth ordering, --entry with
    --external, --external + --format exe rejection, _export_cache_key with local path deps,
    and py_header external."""
    import os
    import sys

    from bundleup import BuildOptions, UsageError, _build, _outputs, _payload, _runtime, _uv
    from bundleup._python import Portability, PythonRange, Target
    from bundleup._source import Source

    # 1. _runtime.activate keeps bundle .pth directories BEFORE inherited host site-packages,
    # respects BUNDLEUP_INHERIT_PATH=0, and does not leak BUNDLEUP_RUNTIME_INHERIT to another bundle
    bundle_a = tmp_path / "bundle_a"
    bundle_a.mkdir()
    pth_sub = bundle_a / "win32_extra"
    pth_sub.mkdir()
    (bundle_a / "extra.pth").write_text("win32_extra\n")
    host_sp = tmp_path / "host-site-packages"
    host_sp.mkdir()

    for var in (
        "PYTHONPATH",
        _runtime.ENV_SITE,
        _runtime.ENV_PATHS,
        _runtime.ENV_PYTHON,
        _runtime.ENV_SCRIPTS,
        _runtime.ENV_INHERIT,
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(_runtime, "_HOST_TAIL", None)
    monkeypatch.delitem(sys.__dict__, "_bundleup_host_tail", raising=False)
    monkeypatch.setattr(sys, "path", ["/stdlib", str(host_sp)])
    monkeypatch.setenv("BUNDLEUP_RUNTIME_INHERIT", str(bundle_a))
    monkeypatch.delenv("BUNDLEUP_INHERIT_PATH", raising=False)
    _runtime.activate(str(bundle_a), ["extra.pth"])
    # Order must be: /stdlib, bundle_a, bundle_a/win32_extra, host_sp
    assert sys.path == ["/stdlib", str(bundle_a), os.path.normcase(str(pth_sub)), str(host_sp)]

    # Child bundle_b without EXTERNAL should NOT inherit host_sp from bundle_a
    bundle_b = tmp_path / "bundle_b"
    bundle_b.mkdir()
    _runtime.activate(str(bundle_b), [])
    assert str(host_sp) not in sys.path
    assert "BUNDLEUP_RUNTIME_INHERIT" not in _runtime.os.environ

    # BUNDLEUP_INHERIT_PATH=0 overrides BUNDLEUP_RUNTIME_INHERIT
    bundle_c = tmp_path / "bundle_c"
    bundle_c.mkdir()
    monkeypatch.setattr(sys, "path", ["/stdlib", str(host_sp)])
    monkeypatch.setenv("BUNDLEUP_RUNTIME_INHERIT", str(bundle_c))
    monkeypatch.setenv("BUNDLEUP_INHERIT_PATH", "0")
    _runtime.activate(str(bundle_c), [])
    assert str(host_sp) not in sys.path

    # 2. resolve_entry allows --entry pointing to a module provided by --external
    site = tmp_path / "entry_site"
    site.mkdir()
    (site / "app.py").write_text("x = 1\n")
    src = Source(path=tmp_path, name="app", requires_python=None, is_script=False, pep723=False)
    entry = _payload.resolve_entry(
        src, site, entry="uvicorn:main", script=None, target_version=(3, 12), external=("uvicorn",)
    )
    assert entry == _payload.Entry("call", "uvicorn", "main")

    # 3. --external + --format exe raises UsageError in _settle
    with pytest.raises(UsageError, match="--external leaves packages to the host Python"):
        _build._settle(BuildOptions(path=tmp_path, format="exe", external=("torch",)))

    # 4. _export_cache_key returns None when uv.lock references an external local path dependency
    proj = tmp_path / "proj_local_dep"
    proj.mkdir()
    (proj / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n')
    (proj / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "helper"\nsource = { directory = "../helper" }\n'
    )
    local_src = Source(path=proj, name="app", requires_python=None, is_script=False, pep723=False)
    assert _uv._export_cache_key("uv", local_src, ["--no-dev"], "locked") is None
    (proj / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "app"\nsource = { editable = "." }\n'
    )
    assert _uv._export_cache_key("uv", local_src, ["--no-dev"], "locked") is not None

    # 5. py_header records # external = [...] when --external is set
    target = Target(
        executable=sys.executable,
        version=(3, 12),
        full_version="3.12.0",
        platform="linux",
        machine="x86_64",
        abiflags=None,
        implementation="cpython",
        cache_tag="cpython-312",
        markers={},
    )
    prep = _payload.Prepared(
        source=local_src,
        target=target,
        site=site,
        pylock=proj / "uv.lock",
        script=None,
        entry=_payload.Entry("call", "app", "main"),
        packages=1,
        native=False,
        version="0.1.0",
        diagnostics=[],
        sizes=[],
        pythons=PythonRange((3, 12), (3, 12)),
        reach=Portability(),
        external=("torch", "pyyaml"),
    )
    header = _outputs.py_header([prep], [[]], "app.py")
    assert '# external = ["torch", "pyyaml"]' in header


def test_pass4_iteration3_regressions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Pass 3 regressions: platform spelling hints, Python version shorthand normalization,
    and format/flag alias hints."""
    from bundleup import BuildOptions, UsageError, _build, _cli, _platforms

    # 1. PLATFORM_HINTS in _platforms.parse
    for bad, expected in [
        ("linux-arm64", "aarch64-unknown-linux-gnu"),
        ("darwin", "macos"),
        ("macos-x86_64", "x86_64-apple-darwin"),
        ("alpine", "x86_64-unknown-linux-musl"),
        ("win64", "windows"),
    ]:
        with pytest.raises(UsageError) as exc:
            _platforms.parse(bad)
        assert exc.value.hint is not None
        assert f"did you mean `{expected}`?" in exc.value.hint

    # 2. Python version shorthand normalization (py312, cp313, python3.11) in BuildOptions
    settled, _ = _build._settle(BuildOptions(path=tmp_path, python="py312,cp313,python3.11"))
    assert settled.python == "3.12"
    assert settled.more_pythons == ("3.13", "3.11")

    # 3. _FORMAT_HINTS in programmatic API and CLI
    with pytest.raises(UsageError) as fmt_exc:
        _build._format(BuildOptions(path=tmp_path, format="scie"))  # type: ignore[arg-type]
    assert fmt_exc.value.hint is not None
    assert "did you mean `exe`?" in fmt_exc.value.hint

    assert _cli.main(["build", "--format", "lambda"]) == _cli.ExitCode.USAGE_ERROR
    err1 = capsys.readouterr().err
    assert "did you mean `--format zip`?" in err1

    assert _cli.main(["build", "--scie"]) == _cli.ExitCode.USAGE_ERROR
    err2 = capsys.readouterr().err
    assert "did you mean `--format exe`?" in err2

    assert _cli.main(["build", "-e", "pkg:main"]) == _cli.ExitCode.USAGE_ERROR
    err3 = capsys.readouterr().err
    assert "did you mean `--entry`?" in err3


def test_blackbox_and_whitebox_audit_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regressions from the 3-subagent black-box campaign and white-box audit across config,
    CLI, TOML/PEP 723 parsing, pylock.toml, setup.cfg, verify, and cache."""
    import json
    import zipfile

    from bundleup import (
        BuildOptions,
        LockfileOutdatedError,
        NoLockfileError,
        NotABundleError,
        ProjectError,
        UsageError,
        _bytecode,
        _cache,
        _cli,
        _config,
        _source,
        _uv,
        build,
        check,
        verify,
    )

    # 1. Config per-run keys (`smoke`, `matrix`, `dry-run`), non-table [tool.bundleup],
    # commented-out _key_line, and config value validation with code frames.
    p_cfg = tmp_path / "cfg_proj"
    p_cfg.mkdir()
    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n[tool.bundleup]\n'
        '# max-size = "10MB"\nsmoke = true\n'
    )
    with pytest.raises(UsageError, match="`smoke` is a per-run setting") as exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert exc.value.detail is not None and "smoke = true" in exc.value.detail

    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n[tool.bundleup]\ndry-run = true\n'
    )
    with pytest.raises(UsageError) as exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert exc.value.hint == "only 'bundleup cache clean' takes --dry-run"

    (p_cfg / "pyproject.toml").write_text('[project]\nname = "app"\n[tool]\nbundleup = "fast"\n')
    with pytest.raises(ProjectError, match="must be a table") as p_tbl_exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert p_tbl_exc.value.hint is not None and p_tbl_exc.value.detail is not None

    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\n# max-size = "10MB"\nmax-size = "0MB"\n'
    )
    assert _config._key_line(p_cfg / "pyproject.toml", "max-size") == 5
    with pytest.raises(UsageError, match="must be greater than 0") as exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert exc.value.detail is not None and 'max-size = "0MB"' in exc.value.detail

    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\npython-platform = [123]\n'
    )
    with pytest.raises(UsageError) as exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert exc.value.hint is not None and '["linux", "macos"]' in exc.value.hint

    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\npython-platform = ["solaris"]\n'
    )
    with pytest.raises(UsageError, match="invalid \\[tool\\.bundleup\\]") as exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert exc.value.detail is not None and "solaris" in exc.value.detail

    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\nentry = "a:b:c"\n'
    )
    with pytest.raises(UsageError, match="invalid \\[tool\\.bundleup\\]") as exc:
        _config.apply(BuildOptions(path=p_cfg))
    assert exc.value.detail is not None and "a:b:c" in exc.value.detail

    # Comma-separated python in [tool.bundleup] works with `for_check=True`
    (p_cfg / "pyproject.toml").write_text(
        '[project]\nname = "app"\n[tool.bundleup]\npython = ["3.11,3.12"]\n'
    )
    checked_opts, _ = _config.apply(BuildOptions(path=p_cfg), for_check=True)
    assert checked_opts.python == "3.11" and checked_opts.more_pythons == ()

    # 2. Deduplication of python & python_platform in BuildOptions, and empty flag rejection
    deduped = BuildOptions(
        path=tmp_path,
        python="3.12,3.12",
        more_pythons=("3.12", "3.11"),
        python_platform="linux,linux",
        more_python_platforms=("linux", "macos"),
    )
    assert deduped.python == "3.12" and deduped.more_pythons == ("3.11",)
    assert deduped.python_platform == "linux" and deduped.more_python_platforms == ("macos",)

    for flag in ("--python", "--python-platform", "--external"):
        assert _cli.main(["build", flag, " , "]) == _cli.ExitCode.USAGE_ERROR
        capsys.readouterr()

    # 3. `bundleup build --smoke <path>` does not swallow the positional project path
    smoke_script = tmp_path / "smoke_pos.py"
    smoke_script.write_text('# /// script\n# dependencies = []\n# ///\nprint("ok")\n')
    assert (
        _cli.main(["build", "--smoke", str(smoke_script), "-o", str(tmp_path / "sp.pyz"), "-q"])
        == 0
    )
    capsys.readouterr()

    # 4. `cache clean --older-than` validation and `cache list -q`
    for bad_days in ("-5", "nan", "inf"):
        assert (
            _cli.main(["cache", "clean", "--older-than", bad_days, "--json"])
            == _cli.ExitCode.USAGE_ERROR
        )
        doc = json.loads(capsys.readouterr().out)
        assert not doc["ok"] and doc["diagnostics"][0]["code"] == "usage"
    with pytest.raises(UsageError):
        _cache.clean_cache(older_than_days=-1)

    monkeypatch.setenv("BUNDLEUP_CACHE", str(tmp_path / "qcache"))
    (tmp_path / "qcache" / f"app-{'ab' * 8}").mkdir(parents=True)
    (tmp_path / "qcache" / f"app-{'ab' * 8}" / "m.py").write_bytes(b"123")
    assert _cli.main(["cache", "list", "-q"]) == 0
    out_q, err_q = capsys.readouterr()
    assert "app" in out_q and err_q == ""

    # 5. Bytecode cache_dir falls back to $BUNDLEUP_CACHE/build/bytecode when
    # BUNDLEUP_BUILD_CACHE is unset
    monkeypatch.delenv("BUNDLEUP_BUILD_CACHE", raising=False)
    monkeypatch.setenv("BUNDLEUP_CACHE", str(tmp_path / "custom_cache"))
    assert _bytecode.cache_dir() == tmp_path / "custom_cache" / "build" / "bytecode"

    # 6. Malformed TOML / PEP 723 metadata types and PEP 723 TOML error line offset
    bad_pep = tmp_path / "bad_pep.py"
    bad_pep.write_text("# line 1\n# line 2\n# /// script\n# dependencies = [1 2]\n# ///\n")
    with pytest.raises(ProjectError, match="line 4") as p_exc:
        _source.load_source(bad_pep)
    assert p_exc.value.detail is not None and p_exc.value.hint is not None

    bad_pep.write_text("# /// script\n# requires-python = 312\n# ///\n")
    with pytest.raises(ProjectError, match="must be a string"):
        _source.load_source(bad_pep)

    bad_pep.write_text('# /// script\n# dependencies = "click"\n# ///\n')
    with pytest.raises(ProjectError, match="must be a list of strings"):
        _source.load_source(bad_pep)

    # 7. pylock.toml validation, freshness check, and --external with directory = "."
    pylock_proj = tmp_path / "pylock_proj"
    (pylock_proj / "src" / "papp").mkdir(parents=True)
    (pylock_proj / "src" / "papp" / "__init__.py").write_text('def main(): print("papp")\n')
    (pylock_proj / "pyproject.toml").write_text(
        '[project]\nname = "papp"\nversion = "0.1.0"\ndependencies = ["click>=8.0"]\n'
        '[project.scripts]\npapp = "papp:main"\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    (pylock_proj / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "hand"\n[[packages]]\nname = "papp"\n'
        'directory = { path = ".", editable = false }\n'
    )
    with pytest.raises(LockfileOutdatedError, match="out of date") as lock_exc:
        build(BuildOptions(path=pylock_proj, output=tmp_path / "papp.pyz"))
    assert lock_exc.value.detail is not None and "click>=8.0" in lock_exc.value.detail
    # With --external click, click is external AND directory = "." builds from stage without failing
    res_ext = build(
        BuildOptions(path=pylock_proj, output=tmp_path / "papp.pyz", external=("click",))
    )
    assert res_ext.output.exists()

    (pylock_proj / "pylock.toml").write_text('lock-version = "1.0"\npackages = "bad"\n')
    with pytest.raises(ProjectError, match="`packages` must be a list of tables"):
        build(BuildOptions(path=pylock_proj, output=tmp_path / "papp2.pyz", lock_mode="frozen"))

    # 8. --frozen on unlocked project raises NoLockfileError
    unlocked_proj = tmp_path / "unlocked_proj"
    unlocked_proj.mkdir()
    (unlocked_proj / "pyproject.toml").write_text('[project]\nname = "u"\nversion = "0.1.0"\n')
    (unlocked_proj / "u.py").write_text("print(1)\n")
    with pytest.raises(NoLockfileError):
        build(BuildOptions(path=unlocked_proj, lock_mode="frozen"))

    # 9. _strip_pyproject_external strips external deps from unlocked pyproject.toml in stage
    stage_ext = tmp_path / "stage_ext"
    stage_ext.mkdir()
    (stage_ext / "pyproject.toml").write_text(
        '[project]\nname = "u"\nversion = "0.1.0"\ndependencies = ["torch>=2.0", "click>=8.0"]\n'
    )
    staged_py = _uv._strip_pyproject_external(stage_ext / "pyproject.toml", {"torch"}, stage_ext)
    assert staged_py is not None
    assert "torch" not in staged_py.read_text()
    assert "click>=8.0" in staged_py.read_text()

    # 10. setup.cfg-only project builds cleanly without leaving setup.py behind
    cfg_only = tmp_path / "cfg_only"
    (cfg_only / "capp").mkdir(parents=True)
    (cfg_only / "capp" / "__init__.py").write_text('def main(): print("from setup.cfg")\n')
    (cfg_only / "setup.cfg").write_text(
        "[metadata]\nname = capp\nversion = 0.2.0\n[options]\npackages = capp\n"
        "[options.entry_points]\nconsole_scripts =\n    capp = capp:main\n"
    )
    cfg_res = build(BuildOptions(path=cfg_only, output=tmp_path / "capp.pyz", smoke=()))
    assert (cfg_res.name, cfg_res.version) == ("capp", "0.2.0")
    assert cfg_res.smoke is not None and cfg_res.smoke.output.strip() == "from setup.cfg"
    assert not (cfg_only / "setup.py").exists()

    # 11. verify nonexistent path, extra file in --split .parts/, and symlinked split bundle
    with pytest.raises(NotABundleError, match="does not exist"):
        verify(tmp_path / "does_not_exist.pyz")

    split_out = tmp_path / "split_app.pyz"
    build(BuildOptions(path=smoke_script, output=split_out, split=65536))
    sym_split = tmp_path / "sub_sym" / "link.pyz"
    sym_split.parent.mkdir()
    sym_split.symlink_to(split_out)
    assert verify(sym_split).ok

    parts_dir = tmp_path / "split_app.pyz.parts"
    extra_part = parts_dir / "extra.zip"
    with zipfile.ZipFile(extra_part, "w") as zf:
        zf.writestr("evil.py", "x = 1\n")
    rep_split = verify(split_out)
    assert not rep_split.ok and any("extra.zip" in p for p in rep_split.problems)

    # 12. Single-script undeclared sibling import hint suggests bundling the folder
    sib_dir = tmp_path / "sib_dir"
    sib_dir.mkdir()
    (sib_dir / "helper_mod.py").write_text("X = 1\n")
    (sib_dir / "run_me.py").write_text(
        "# /// script\n# dependencies = []\n# ///\nimport helper_mod\nprint(helper_mod.X)\n"
    )
    chk_sib = check(BuildOptions(path=sib_dir / "run_me.py"))
    und = [d for d in chk_sib.diagnostics if d.code == "undeclared-import"]
    assert len(und) == 1 and und[0].hint is not None and "--entry run_me.py" in und[0].hint


def test_runtime_and_loader_audit_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressions from the Hostile Runtime subagent and loader/runtime white-box audit."""
    import os
    import subprocess
    import sys

    from bundleup import BuildOptions, _runtime, build

    # 1. PYTHONPATH ending in `site-packages` before stdlib must NOT cause site_packages_index()
    # to delete the stdlib from sys.path!
    fake_pp = str(tmp_path / "custom" / "site-packages")
    fake_stdlib = (os.__file__ and os.path.dirname(os.__file__)) or "/stdlib"
    fake_host_sp = str(tmp_path / "venv" / "lib" / "python3.12" / "site-packages")
    with monkeypatch.context() as mp:
        for var in (
            "PYTHONPATH",
            _runtime.ENV_SITE,
            _runtime.ENV_PATHS,
            _runtime.ENV_PYTHON,
            _runtime.ENV_SCRIPTS,
            _runtime.ENV_INHERIT,
            "BUNDLEUP_INHERIT_PATH",
        ):
            mp.delenv(var, raising=False)
        mp.setattr(_runtime, "_HOST_TAIL", None)
        mp.delitem(sys.__dict__, "_bundleup_host_tail", raising=False)
        mp.setattr(sys, "path", [fake_pp, fake_stdlib, fake_host_sp])
        idx = _runtime.site_packages_index()
        assert idx == 2  # after fake_stdlib, never 0!

        bundle_site = tmp_path / "b_site"
        bundle_site.mkdir()
        _runtime.activate(str(bundle_site), [])
        assert fake_stdlib in sys.path
        assert fake_pp not in sys.path and fake_host_sp not in sys.path

        # 2. Nested bundle activation evicts parent bundle's modules from sys.modules
        parent_site = tmp_path / "parent_site"
        parent_site.mkdir()
        child_site = tmp_path / "child_site"
        child_site.mkdir()
        dummy_mod = type(sys)("dummy_shared_pkg")
        dummy_mod.__file__ = str(parent_site / "dummy_shared_pkg" / "__init__.py")
        mp.setitem(sys.modules, "dummy_shared_pkg", dummy_mod)
        mp.setenv("BUNDLEUP_RUNTIME_SITE", str(parent_site))
        _runtime.activate(str(child_site), [])
        assert "dummy_shared_pkg" not in sys.modules

        # 3. runs_bundle_code recognizes attached -m<mod> and skips child `--format py` bundles
        py_bundle_file = tmp_path / "child_bundle.py"
        py_bundle_file.write_text("#!/usr/bin/env python3\n# /// bundleup\nEMBEDDED = True\n")
        normal_script = tmp_path / "normal_script.py"
        normal_script.write_text("print(1)\n")
        mp.setenv(_runtime.ENV_SCRIPTS, str(tmp_path))
        if hasattr(sys, "orig_argv"):
            mp.setattr(sys, "argv", ["-m"])
            mp.setattr(sys, "orig_argv", ["python3", "-munittest"])
            assert _runtime.runs_bundle_code(str(bundle_site)) is True
            mp.setattr(sys, "argv", [str(py_bundle_file)])
            mp.setattr(sys, "orig_argv", ["python3", str(py_bundle_file)])
            assert _runtime.runs_bundle_code(str(bundle_site)) is False
            mp.setattr(sys, "argv", [str(normal_script)])
            mp.setattr(sys, "orig_argv", ["python3", str(normal_script)])
            assert _runtime.runs_bundle_code(str(bundle_site)) is True

    # 4. End-to-end runtime checks:
    # - `--format py` with hostile `fcntl.py` and `zipfile.py` in the bundle's directory
    # - `_exec_file` preserving `sys.argv[0]`, absolute `__file__`, `atexit` reading globals,
    #   and `os.chdir` before importing bundled code
    # - `--entry python` with attached `-c` / `-m` and `<stdin>`
    hostile_dir = tmp_path / "hostile"
    hostile_dir.mkdir()
    (hostile_dir / "fcntl.py").write_text('raise RuntimeError("PAY_NO_ATTENTION_TO_FCNTL")\n')
    (hostile_dir / "zipfile.py").write_text('raise RuntimeError("PAY_NO_ATTENTION_TO_ZIPFILE")\n')
    app_src = tmp_path / "src_app"
    app_src.mkdir()
    (app_src / "helper_pkg.py").write_text('VAL = "from_bundle"\n')
    (app_src / "requirements.txt").write_text("")
    (app_src / "main.py").write_text(
        "import atexit, os, sys\n"
        "os.chdir('/')\n"
        "import helper_pkg\n"
        "GREETING = helper_pkg.VAL\n"
        "def _on_exit():\n"
        "    print('EXIT:' + GREETING + ':' + str(os.path.isabs(__file__)))\n"
        "atexit.register(_on_exit)\n"
        "print('ARGV0:' + os.path.basename(sys.argv[0]))\n"
    )
    py_out = hostile_dir / "app_bundle.py"
    build(BuildOptions(path=app_src, format="py", output=py_out))
    for _ in range(2):  # cold run + warm run
        proc = subprocess.run(
            [sys.executable, str(py_out)],
            cwd=hostile_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "ARGV0:app_bundle.py" in proc.stdout
        assert "EXIT:from_bundle:True" in proc.stdout

    # `--entry python` with `-cCODE`, `-mjson.tool`, and `-` stdin `__file__`
    py_entry_out = tmp_path / "py_entry.pyz"
    build(BuildOptions(path=app_src, entry="python", output=py_entry_out))
    r_c = subprocess.run(
        [sys.executable, str(py_entry_out), "-cimport helper_pkg; print(helper_pkg.VAL)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_c.stdout.strip() == "from_bundle"

    r_stdin = subprocess.run(
        [sys.executable, str(py_entry_out), "-"],
        input="import sys; print(__file__, sys.argv)\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_stdin.stdout.strip() == "<stdin> ['-']"


def test_blackbox_subagent_and_whitebox_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regressions for bugs found across the 3 parallel black-box subagents and white-box audit."""
    import os
    import subprocess
    import sys

    from bundleup import (
        BuildOptions,
        EntryPointError,
        ProjectError,
        UsageError,
        _cli,
        _config,
        _loader,
        _runtime,
        _source,
        _uv,
        build,
        verify,
    )

    # 1. Host .pth entries after stdlib are stripped even without a site-packages folder
    with monkeypatch.context() as mp:
        for var in (
            "PYTHONPATH",
            _runtime.ENV_SITE,
            _runtime.ENV_PATHS,
            _runtime.ENV_PYTHON,
            _runtime.ENV_SCRIPTS,
            _runtime.ENV_INHERIT,
            "BUNDLEUP_INHERIT_PATH",
        ):
            mp.delenv(var, raising=False)
        mp.setattr(_runtime, "_HOST_TAIL", None)
        mp.delitem(sys.__dict__, "_bundleup_host_tail", raising=False)
        fake_stdlib = (os.__file__ and os.path.dirname(os.__file__)) or "/stdlib"
        leaked_editable = str(tmp_path / "some_editable_src")
        mp.setattr(sys, "path", [fake_stdlib, leaked_editable])
        assert _runtime.site_packages_index() == 1

        # 2. PEP 420 namespace packages from parent bundle are evicted when child bundle activates
        parent_site = tmp_path / "p_site"
        parent_site.mkdir()
        child_site = tmp_path / "c_site"
        child_site.mkdir()
        ns_mod = type(sys)("ns_shared")
        ns_mod.__file__ = None
        ns_mod.__path__ = [str(parent_site / "ns_shared")]  # type: ignore[attr-defined]
        mp.setitem(sys.modules, "ns_shared", ns_mod)
        mp.setenv("BUNDLEUP_RUNTIME_SITE", str(parent_site))
        _runtime.activate(str(child_site), [])
        assert "ns_shared" not in sys.modules

    # 3. _orig_module skips value args of -W, -X, and --check-hash-based-pycs
    assert (
        _runtime._orig_module(
            [
                "python3",
                "-W",
                "ignore",
                "-X",
                "dev",
                "--check-hash-based-pycs",
                "always",
                "-m",
                "my_mod",
            ]
        )
        == "my_mod"
    )

    # 4. _loader._roots() resolves relative HOME / XDG_CACHE_HOME and ignores empty HOME=""
    saved_home = os.environ.get("HOME")
    monkeypatch.delenv("BUNDLEUP_CACHE_DIR", raising=False)
    monkeypatch.delenv("BUNDLEUP_CACHE", raising=False)
    monkeypatch.setenv("HOME", "")
    monkeypatch.setenv("XDG_CACHE_HOME", "rel_xdg_cache")
    roots = _loader._roots(str(tmp_path / "app.pyz"))
    assert all(os.path.isabs(r) for r, _ in roots)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    if saved_home is not None:
        monkeypatch.setenv("HOME", saved_home)
    monkeypatch.setenv("BUNDLEUP_CACHE_DIR", str(tmp_path / "cache"))

    # 5. _cli._join_smoke with --entry python and implicit "." project path passes script to --smoke
    joined = _cli._join_smoke(
        ["build", "--entry", "python", "--smoke", "scripts/tool.py"], _cli.parsers()["build"]
    )
    parsed = _cli.parser().parse_args(joined)
    assert parsed.smoke == "scripts/tool.py" and parsed.path == "."

    # 6. `bundleup check` honors `strict = true` in `[tool.bundleup]`
    strict_script = tmp_path / "strict_script.py"
    strict_script.write_text(
        "# /// script\n"
        '# requires-python = ">=3.11"\n'
        "# dependencies = []\n"
        "# [tool.bundleup]\n"
        "# strict = true\n"
        "# ///\n"
        "import nonexistent_mod_xyz_for_strict_test\n"
    )
    assert _cli.main(["check", str(strict_script)]) == 1
    capsys.readouterr()

    # 7. _strip_script_external handles bracketed extras in PEP 723 deps and output = "path/..."
    pep723_ext = tmp_path / "pep723_ext.py"
    pep723_ext.write_text(
        "# /// script\n"
        '# requires-python = ">=3.11"\n'
        "# dependencies = [\n"
        '#   "rich[jupyter]>=13.0",\n'
        "# ]\n"
        "# [tool.bundleup]\n"
        '# output = "dist/path/out.pyz"\n'
        "# ///\n"
        "print('ok')\n"
    )
    stage_dir = tmp_path / "stage_ext"
    stage_dir.mkdir()
    stripped_script = _uv._strip_script_external(pep723_ext, {"rich"}, stage_dir)
    text = stripped_script.read_text()
    assert "dependencies = []" in text
    assert 'output = "dist/path/out.pyz"' in text

    # 8. _strip_requirements_external and pinned_requirements handle tab-preceded comments
    req_dir = tmp_path / "req_tab"
    req_dir.mkdir()
    req_file = req_dir / "requirements.txt"
    req_file.write_text("my-ext-pkg==1.0.0\t# inline comment after tab\nother-pkg==2.0.0\t# keep\n")
    (req_dir / "app.py").write_text("print(1)\n")
    pins, _ = _uv.pinned_requirements(req_file)
    assert pins == {"my-ext-pkg": "1.0.0", "other-pkg": "2.0.0"}
    stripped_req = _uv._strip_requirements_external(req_file, {"my-ext-pkg"}, stage_dir)
    assert stripped_req is not None
    assert "my-ext-pkg" not in stripped_req.read_text()
    assert "other-pkg==2.0.0" in stripped_req.read_text()

    # 9. Empty/whitespace output rejected and [[tool.bundleup]] array-of-tables shows code frame
    with pytest.raises(UsageError, match="has no file name"):
        build(BuildOptions(path=req_dir, output=Path("   ")))
    aot_dir = tmp_path / "aot_cfg"
    aot_dir.mkdir()
    (aot_dir / "pyproject.toml").write_text(
        '[project]\nname = "a"\n[[tool.bundleup]]\nformat = "pyz"\n'
    )
    with pytest.raises(ProjectError) as aot_err:
        _config.apply(BuildOptions(path=aot_dir))
    assert aot_err.value.detail is not None and "[[tool.bundleup]]" in aot_err.value.detail

    # 10. Source scanner skips nested `--format dir`, `.parts/`, and `--format py` outputs
    nested_proj = tmp_path / "nested_proj"
    nested_proj.mkdir()
    (nested_proj / "requirements.txt").write_text("")
    (nested_proj / "main.py").write_text("print('hi')\n")
    (nested_proj / "my_mod.py").write_text("X = 1\n")
    fake_dir_bundle = nested_proj / "out_dir"
    fake_dir_bundle.mkdir()
    (fake_dir_bundle / "bundleup-manifest.json").write_text("{}")
    (fake_dir_bundle / "bad.py").write_text("import nonexistent_dir_pkg\n")
    fake_parts = nested_proj / "app.pyz.parts"
    fake_parts.mkdir()
    (fake_parts / "part.py").write_text("import nonexistent_parts_pkg\n")
    (nested_proj / "bundled_out.py").write_text(
        "#!/usr/bin/env python3\n# /// bundleup\nimport nonexistent_py_pkg\n"
    )
    scanned_names = {rel for rel, _ in _source.python_files(nested_proj)}
    assert scanned_names == {"main.py", "my_mod.py"}

    # 11. Hyphenated `--entry my-mod` gives EntryPointError with suggestion
    with pytest.raises(EntryPointError) as ep_err:
        build(BuildOptions(path=nested_proj, entry="my-mod", output=tmp_path / "hyphen.pyz"))
    assert ep_err.value.hint is not None and "my_mod" in ep_err.value.hint

    # 12. `--entry <module>` preserves sys.argv[0] as bundle path and keeps __main__ for atexit
    mod_proj = tmp_path / "mod_proj"
    mod_proj.mkdir()
    (mod_proj / "requirements.txt").write_text("")
    (mod_proj / "runner.py").write_text(
        "import atexit, os, sys\n"
        "STATE = 'alive'\n"
        "atexit.register(lambda: print('ATEXIT:' + STATE + ':' + os.path.basename(sys.argv[0])))\n"
    )
    mod_pyz = tmp_path / "mod_runner.pyz"
    build(BuildOptions(path=mod_proj, entry="runner", output=mod_pyz))
    r_mod = subprocess.run(
        [sys.executable, str(mod_pyz)], capture_output=True, text=True, check=True
    )
    assert r_mod.stdout.strip() == "ATEXIT:alive:mod_runner.pyz"

    # 13. `--entry python` runs `.pyz` zipapps, handles `-- -dash.py`, and honors PYTHONSAFEPATH=1
    py_bundle = tmp_path / "py_runtime.pyz"
    build(BuildOptions(path=mod_proj, entry="python", output=py_bundle))
    r_zip = subprocess.run(
        [sys.executable, str(py_bundle), str(mod_pyz)], capture_output=True, text=True, check=True
    )
    assert r_zip.stdout.strip() == "ATEXIT:alive:mod_runner.pyz"

    dash_script = tmp_path / "-dash.py"
    dash_script.write_text("import os, sys; print('DASH:' + os.path.basename(sys.argv[0]))\n")
    r_dash = subprocess.run(
        [sys.executable, str(py_bundle), "--", "-dash.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_dash.stdout.strip() == "DASH:-dash.py"

    safe_dir = tmp_path / "safe_dir"
    safe_dir.mkdir()
    (safe_dir / "runner.py").write_text("STATE = 'hijacked'\n")
    (safe_dir / "check_safe.py").write_text("import runner; print(runner.STATE)\n")
    env_safe = {**os.environ, "PYTHONSAFEPATH": "1"}
    r_safe = subprocess.run(
        [sys.executable, "-P", str(py_bundle), str(safe_dir / "check_safe.py")],
        cwd=safe_dir,
        env=env_safe,
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_safe.stdout.splitlines()[0] == "alive"

    # 14. `verify` ignores extra `.pyc` in `--format dir` and checks all unpacked caches
    dir_out = tmp_path / "dir_bundle"
    build(BuildOptions(path=mod_proj, entry="runner", format="dir", output=dir_out))
    (dir_out / "extra_foreign.pyc").write_bytes(b"0123")
    v_dir = verify(dir_out)
    assert v_dir.ok and v_dir.files > 0
    (dir_out / "tampered.py").write_text("x = 1\n")
    assert not verify(dir_out).ok


def test_systems_correctness_audit_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression suite for concurrency/cache, multi-target/verify, lockfile/import analysis,
    and multiprocessing/runtime edge cases."""
    import ast
    import contextlib
    import os
    import shutil
    import subprocess
    import sys
    import time
    import zipfile

    from bundleup import (
        LockfileOutdatedError,
        _cache,
        _check,
        _coverage,
        _errors,
        _imports,
        _loader,
        _payload,
        _platforms,
        _runtime,
        _source,
        _uv,
        _verify,
        check,
        verify,
    )

    # 1. Package `__main__.py` entry with multiprocessing `spawn` and relative imports
    mp_proj = tmp_path / "mp_proj"
    pkg_dir = mp_proj / "mypkg"
    pkg_dir.mkdir(parents=True)
    (mp_proj / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "[project]\n"
        'name = "mypkg"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.9"\n'
    )
    (pkg_dir / "__init__.py").write_text(" MULT = 3\n".lstrip())
    (pkg_dir / "helper.py").write_text("OFFSET = 7\n")
    (pkg_dir / "__main__.py").write_text(
        "import concurrent.futures as cf, multiprocessing as mp\n"
        "from . import MULT\n"
        "from .helper import OFFSET\n"
        "def work(x):\n"
        "    return x * MULT + OFFSET\n"
        "if __name__ == '__main__':\n"
        "    ctx = mp.get_context('spawn')\n"
        "    with cf.ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:\n"
        "        print('MP_OUT:', list(ex.map(work, [2, 4])))\n"
    )
    mp_pyz = tmp_path / "mp_app.pyz"
    build(BuildOptions(path=mp_proj, output=mp_pyz))
    mp_cache = tmp_path / "mp_cache"
    r_mp = subprocess.run(
        [sys.executable, str(mp_pyz)],
        env={**os.environ, "BUNDLEUP_CACHE": str(mp_cache)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_mp.stdout.strip() == "MP_OUT: [13, 19]"

    # 2. `export()` cache relocation across single-target `check()` and multi-target `build()`
    uv_bin = _uv.find_uv()
    subprocess.run([uv_bin, "lock"], cwd=mp_proj, check=True, capture_output=True)
    exp_cache = tmp_path / "build_cache"
    monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(exp_cache))
    chk_rep = check(BuildOptions(path=mp_proj))
    assert chk_rep.ok
    other_plat = "linux" if sys.platform == "win32" else "windows"
    multi_res = build(
        BuildOptions(
            path=mp_proj,
            output=tmp_path / "mp_multi.pyz",
            more_python_platforms=(other_plat,),
        )
    )
    assert multi_res.output.is_file()
    # Pure-Python multi-platform build without explicit `--python` deduplicates payloads
    assert multi_res.payloads == []

    # 3. `clean_cache()` and `_loader._rmtree()` remove 0o555/0o444/0o000 subdirectories cleanly
    #    and never chmod external symlink targets
    monkeypatch.setenv("BUNDLEUP_CACHE", str(mp_cache))
    unpacked_dirs = [p for p in mp_cache.iterdir() if p.is_dir() and not p.name.startswith(".")]
    assert len(unpacked_dirs) == 1
    ext_target = tmp_path / "external_symlink_target.txt"
    ext_target.write_text("do not chmod")
    ext_target.chmod(0o644)
    ro_sub = unpacked_dirs[0] / "readonly_sub"
    ro_sub.mkdir()
    ro_file = ro_sub / "data.txt"
    ro_file.write_text("locked")
    ro_file.chmod(0o444)
    with contextlib.suppress(OSError):
        (ro_sub / "link.txt").symlink_to(ext_target)
    zero_sub = ro_sub / "zero_sub"
    zero_sub.mkdir()
    (zero_sub / "inner.txt").write_text("inner")
    zero_sub.chmod(0o000)
    ro_sub.chmod(0o444)
    clean_rep = _cache.clean_cache(older_than_days=0)
    assert unpacked_dirs[0] in clean_rep.removed
    assert not unpacked_dirs[0].exists()
    assert not [p for p in mp_cache.iterdir() if p.name.startswith(".tmp-")]
    if os.name != "nt":
        assert (ext_target.stat().st_mode & 0o777) == 0o644

    # 3b. Thundering-herd concurrent cold extraction stress test (12 processes)
    herd_cache = tmp_path / "herd_cache"
    procs = [
        subprocess.Popen(
            [sys.executable, str(mp_pyz)],
            env={**os.environ, "BUNDLEUP_CACHE": str(herd_cache)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(12)
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    assert all(
        p.returncode == 0 and out.strip() == "MP_OUT: [13, 19]" for p, (out, _) in zip(procs, outs)
    )
    assert not [p for p in herd_cache.iterdir() if p.name.startswith(".tmp-")]

    # 4. `_loader._lock()` returns immediately when `final` already exists while lock is held,
    #    and `_loader._hold()` closes its file handle if `flock` fails
    if os.name != "nt":
        import fcntl

        lock_root = tmp_path / "lock_root"
        lock_root.mkdir()
        target_site = lock_root / _loader.DIRNAME
        target_site.mkdir()
        lock_file = lock_root / f".lock-{_loader.DIRNAME}"
        with open(lock_file, "a+b") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            t0 = time.monotonic()
            assert _loader._lock(str(lock_root)) is None
            assert time.monotonic() - t0 < 1.0
            before_in_use = len(_loader._IN_USE)
            _loader._hold(str(target_site))
            assert len(_loader._IN_USE) == before_in_use
            # Active extraction lock older than LEFTOVER_AGE while `unpacked` does not exist yet
            # must NOT be unlinked by `clean_cache`
            active_lock = lock_root / ".lock-extracting-0123456789abcdef"
            active_lock.write_bytes(b"")
            old_ts = time.time() - _cache.LEFTOVER_AGE - 100
            os.utime(active_lock, (old_ts, old_ts))
            with open(active_lock, "r+b") as active_held:
                fcntl.flock(active_held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                monkeypatch.setenv("BUNDLEUP_CACHE", str(lock_root))
                _cache.clean_cache(older_than_days=30)
                assert active_lock.is_file()
            _cache.clean_cache(older_than_days=30)
            assert not active_lock.exists()

    # 5. `verify()` catches trailing code, uncommented lines, trailing base64 after EOCD,
    #    non-base64 chars in `--format py`, extra zip members, and duplicate zip entries
    py_out = tmp_path / "script_bundle.py"
    build(BuildOptions(path=mp_proj, format="py", output=py_out))
    assert verify(py_out).ok
    r_py_mp = subprocess.run(
        [sys.executable, str(py_out)],
        env={**os.environ, "BUNDLEUP_CACHE": str(tmp_path / "py_mp_cache")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_py_mp.stdout.strip() == "MP_OUT: [13, 19]"
    # `--entry python` with `-m mypkg` and multiprocessing `spawn`
    py_entry_pyz = tmp_path / "py_entry_app.pyz"
    build(BuildOptions(path=mp_proj, entry="python", output=py_entry_pyz))
    r_py_entry = subprocess.run(
        [sys.executable, str(py_entry_pyz), "-m", "mypkg"],
        env={**os.environ, "BUNDLEUP_CACHE": str(tmp_path / "py_entry_cache")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_py_entry.stdout.strip() == "MP_OUT: [13, 19]"
    orig_bytes = py_out.read_bytes()
    for bad_replacement in (
        orig_bytes + b"print('unhashed trailing code')\n",
        orig_bytes.replace(_loader.DATA_END, b"print('injected')\n" + _loader.DATA_END),
        orig_bytes.replace(_loader.DATA_END, b"#AAAA\n" + _loader.DATA_END),
        orig_bytes.replace(_loader.DATA_END, b"# $$$$\n" + _loader.DATA_END),
    ):
        py_out.write_bytes(bad_replacement)
        v_bad = verify(py_out)
        assert not v_bad.ok and any("the code before its data" in p for p in v_bad.problems)
    py_out.write_bytes(orig_bytes)

    extra_pyz = tmp_path / "extra_member.pyz"
    shutil.copyfile(mp_pyz, extra_pyz)
    with zipfile.ZipFile(extra_pyz, "a") as zf:
        zf.writestr("unexpected.txt", "extra")
    v_extra = verify(extra_pyz)
    assert not v_extra.ok and "extra file: unexpected.txt isn't in the manifest" in v_extra.problems

    import warnings

    dup_pyz = tmp_path / "dup_member.pyz"
    shutil.copyfile(mp_pyz, dup_pyz)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(dup_pyz, "a") as zf:
            zf.writestr("manifest.json", zf.read("manifest.json"))
    v_dup = verify(dup_pyz)
    assert not v_dup.ok and "corrupted: duplicate zip entry manifest.json" in v_dup.problems

    # 6. Forked `[[packages]]` entries & PEP 751 `dependency_groups`/`extras` markers in
    #    `pylock.toml`, plus URL query/fragment/backslash wheel names in `_coverage`
    forked_pylock = (
        'lock-version = "1.0"\n'
        "[[packages]]\n"
        'name = "demo-pkg"\n'
        'version = "1.0.0"\n'
        "marker = \"python_version < '3.10'\"\n"
        'wheels = [{ name = "demo_pkg-1.0.0-cp39-cp39-win_amd64.whl" }]\n'
        "[[packages]]\n"
        'name = "demo-pkg"\n'
        'version = "2.0.0"\n'
        'wheels = [{ url = "https://example.com/'
        'demo_pkg-2.0.0-py3-none-any.whl?token=abc#sha256=1" }]\n'
        "[[packages]]\n"
        'name = "dev-only-pkg"\n'
        'version = "1.0.0"\n'
        "marker = \"'dev' in dependency_groups\"\n"
        'wheels = [{ path = "dist\\\\dev_only_pkg-1.0.0-cp39-cp39-win_amd64.whl" }]\n'
    )
    # Multi-payload `_loader._select()` falls back to OS/CPU match when macOS/libc version is newer
    monkeypatch.setattr(
        _loader,
        "PAYLOADS",
        [
            {
                "dirname": "other-os-0000000000000000",
                "members": ["other.zip"],
                "target": "other OS",
                "pth": [],
                "python": [3, 9],
                "python_max": None,
                "platform": "nonexistent_os",
                "machine": None,
                "abiflags": None,
                "libc": None,
                "macos": None,
            },
            {
                "dirname": "this-os-1111111111111111",
                "members": ["this.zip"],
                "target": "this OS with high version",
                "pth": [],
                "python": [3, 9],
                "python_max": None,
                "platform": sys.platform,
                "machine": None,
                "abiflags": None,
                "libc": ["glibc", [99, 0]] if sys.platform == "linux" else None,
                "macos": [99, 0] if sys.platform == "darwin" else None,
            },
        ],
    )
    _loader._select()
    assert _loader.DIRNAME == "this-os-1111111111111111"
    monkeypatch.setattr(_loader, "PAYLOADS", [])
    linux_plat = _platforms.parse("x86_64-unknown-linux-gnu")
    assert _coverage.gaps(forked_pylock, linux_plat, (3, 9)) == []
    env_39 = linux_plat.markers(python_full_version="3.9.0")
    locked_39 = _verify.locked_packages(forked_pylock, env_39)
    assert [p.name for p in locked_39] == ["demo-pkg"]
    fork_proj = tmp_path / "fork_proj"
    fork_proj.mkdir()
    (fork_proj / "pyproject.toml").write_text(
        '[project]\nname = "fork-proj"\nversion = "0.1.0"\n'
        'dependencies = ["demo-pkg>=2.0", "opt-pkg; extra == \'dev\'"]\n'
    )
    gated_pylock = forked_pylock.replace(
        'name = "demo-pkg"\nversion = "2.0.0"\n',
        'name = "demo-pkg"\nversion = "2.0.0"\nmarker = "python_version >= \'3.10\'"\n',
    )
    (fork_proj / "pylock.toml").write_text(gated_pylock)
    pkgs = _uv._load_pylock_packages(gated_pylock, fork_proj / "pylock.toml")
    _uv._check_pylock_freshness(
        _source.load_source(fork_proj),
        pkgs,
        markers=linux_plat.markers(python_full_version="3.12.0"),
    )
    with pytest.raises(LockfileOutdatedError):
        _uv._check_pylock_freshness(_source.load_source(fork_proj), pkgs, markers=env_39)

    # 7. Import analysis guards (`if False/True/TYPE_CHECKING/not TYPE_CHECKING`, `suppress`,
    #    early-return platform guards, `try/except ImportError` flag guards), namespace
    #    `--external`, nested `_has_attr`, `_orig_module`
    tree = ast.parse(
        "if False:\n    import dead_a\nelse:\n    import live_a\n"
        "if True:\n    import live_b\nelse:\n    import dead_b\n"
        "if TYPE_CHECKING:\n    import dead_tc\nelse:\n    import live_tc\n"
        "if not TYPE_CHECKING:\n    import live_ntc\nelse:\n    import dead_ntc\n"
        "if version_info >= (3, 11):\n    import fake_ver_mod\n"
        "if sys.implementation.name == 'pypy':\n    import pypy_only_mod\n"
        "if importlib.util.find_spec('fake_spec_mod'):\n    import fake_spec_mod\n"
        "with contextlib.suppress(ImportError):\n    import suppressed_mod\n"
        "try:\n    import opt_pkg\n    HAS_OPT = True\nexcept ImportError:\n    HAS_OPT = False\n"
        "if HAS_OPT:\n    from opt_pkg.sub import thing\n"
        "def f():\n"
        "    if sys.platform != 'win32':\n        return\n"
        "    import win_only_mod\n"
        "def g():\n"
        "    if not HAS_OPT:\n        raise RuntimeError('no opt_pkg')\n"
        "    from opt_pkg.other import helper\n"
    )
    assert _imports.imports_in(tree) == {"live_a", "live_b", "live_tc", "live_ntc"}
    ext_mods = _imports.external_modules(
        ["google-cloud-storage", "zope-interface", "opentelemetry-api"]
    )
    assert {"google", "zope", "opentelemetry"} <= ext_mods

    nested_init = tmp_path / "a" / "b" / "__init__.py"
    nested_init.parent.mkdir(parents=True)
    nested_init.write_text("import a.b.c\n")
    ok_attr, _, defined_attrs = _payload._has_attr(nested_init, "c", module="a.b")
    assert ok_attr and "c" in defined_attrs

    assert _runtime._orig_module(["python", "-um", "pkg.sub", "arg"]) == "pkg"
    assert _runtime._orig_module(["python", "-uBmpkg.sub", "arg"]) == "pkg"
    assert _runtime._orig_module(["python", "-uc", "import os", "-m", "ignored"]) is None

    # 8. `_check._dependency_chains` resolves cyclic `Requires-Dist` graphs and extras in O(V+E)
    cycle_site = tmp_path / "cycle_site"
    cycle_site.mkdir()
    for dname, ver, reqs_lines in (
        ("pkg_a", "1.0", ["Requires-Dist: pkg-b", "Requires-Dist: pkg-ext[fast]"]),
        ("pkg_b", "1.0", ["Requires-Dist: pkg-a", "Requires-Dist: pkg-c"]),
        ("pkg_c", "1.0", []),
        ("pkg_ext", "1.0", ["Provides-Extra: fast", "Requires-Dist: pkg-fast ; extra == 'fast'"]),
        ("pkg_fast", "1.0", []),
    ):
        di = cycle_site / f"{dname}-{ver}.dist-info"
        di.mkdir()
        (di / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {dname.replace('_', '-')}\nVersion: {ver}\n"
            + "".join(f"{r}\n" for r in reqs_lines)
            + "\n"
        )
    chains = _check._dependency_chains(
        cycle_site, "", {"pkg-a", "pkg-b", "pkg-c", "pkg-ext", "pkg-fast"}
    )
    assert chains["pkg-a"] == ()
    assert chains["pkg-b"] == ("pkg-a",)
    assert chains["pkg-c"] == ("pkg-a", "pkg-b")
    assert chains["pkg-fast"] == ("pkg-a", "pkg-ext")

    # 9. Bit-for-bit reproducibility across distinct paths, timestamps, and cold/warm caches
    repro_a = tmp_path / "repro_a"
    repro_b = tmp_path / "repro_b"
    for p_dir, ts in ((repro_a, 1_700_000_000), (repro_b, 1_750_000_000)):
        (p_dir / "src" / "rpkg").mkdir(parents=True)
        (p_dir / "pyproject.toml").write_text(
            '[project]\nname = "rpkg"\nversion = "0.1.0"\nrequires-python = ">=3.9"\n'
            'dependencies = []\n[project.scripts]\nrpkg = "rpkg:main"\n'
            '[build-system]\nrequires = ["uv_build>=0.12,<0.13"]\nbuild-backend = "uv_build"\n'
        )
        init_f = p_dir / "src" / "rpkg" / "__init__.py"
        init_f.write_text("def main():\n    return 0\n")
        os.utime(p_dir / "pyproject.toml", (ts, ts))
        os.utime(init_f, (ts, ts))
    monkeypatch.setenv("BUNDLEUP_BUILD_CACHE", str(tmp_path / "repro_bcache_1"))
    out_a = build(BuildOptions(path=repro_a, output=tmp_path / "repro_a.pyz")).output.read_bytes()
    # Warm build from a different directory path and different mtimes
    out_b = build(BuildOptions(path=repro_b, output=tmp_path / "repro_b.pyz")).output.read_bytes()
    assert out_a == out_b

    # 10. Symlink loop handling in `load_source`, `verify`, and `build -o`
    if os.name != "nt":
        loop_link = tmp_path / "loop.py"
        loop_link.symlink_to(loop_link)
        with pytest.raises(_errors.ProjectError):
            _source.load_source(loop_link)
        with pytest.raises(_errors.NotABundleError):
            verify(loop_link)
        with pytest.raises(_errors.UsageError):
            build(BuildOptions(path=repro_a, output=loop_link))

    # 11. Relative imports in guarded and unguarded `__main__.py` under `-W error`, and
    #     unguarded `__main__.py` spawning multiprocessing workers without infinite fork-bomb
    r_mp_werr = subprocess.run(
        [sys.executable, "-W", "error", str(mp_pyz)],
        env={**os.environ, "BUNDLEUP_CACHE": str(tmp_path / "mp_werr_cache")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert r_mp_werr.stdout.strip() == "MP_OUT: [13, 19]" and r_mp_werr.stderr == ""

    ug_proj = tmp_path / "ug_proj"
    ug_pkg = ug_proj / "ugpkg"
    ug_pkg.mkdir(parents=True)
    (ug_proj / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "[project]\n"
        'name = "ugpkg"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.9"\n'
    )
    (ug_pkg / "__init__.py").write_text("SCALE = 5\n")
    (ug_pkg / "worker.py").write_text("from . import SCALE\ndef double(x):\n    return x * SCALE\n")
    # Intentionally no `if __name__ == "__main__":` guard (standard for `__main__.py`)
    (ug_pkg / "__main__.py").write_text(
        "import multiprocessing as mp\n"
        "from .worker import double\n"
        "ctx = mp.get_context('spawn')\n"
        "with ctx.Pool(1) as pool:\n"
        "    print('UG_OUT:', pool.map(double, [3, 4]))\n"
    )
    ug_pyz = build(BuildOptions(path=ug_proj, output=tmp_path / "ug_app.pyz")).output
    r_ug = subprocess.run(
        [sys.executable, "-W", "error", str(ug_pyz)],
        env={**os.environ, "BUNDLEUP_CACHE": str(tmp_path / "ug_cache")},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert r_ug.stdout.strip() == "UG_OUT: [15, 20]" and r_ug.stderr == ""

    # 12. `verify()` catches tampered shebangs and trailing data on `.pyz` and `--format zip`
    raw_mp_pyz = mp_pyz.read_bytes()
    bad_shebang_pyz = tmp_path / "bad_shebang.pyz"
    bad_shebang_pyz.write_bytes(
        b"#!/bin/sh\necho pwned\n" + raw_mp_pyz[raw_mp_pyz.index(b"\n") + 1 :]
    )
    v_shebang = verify(bad_shebang_pyz)
    assert not v_shebang.ok and "changed file: __main__.py (the loader)" in v_shebang.problems

    trailing_pyz = tmp_path / "trailing.pyz"
    trailing_pyz.write_bytes(raw_mp_pyz + b"trailing unverified bytes")
    v_trail = verify(trailing_pyz)
    assert not v_trail.ok and any("trailing data" in p for p in v_trail.problems)

    zip_out = build(BuildOptions(path=ug_proj, format="zip", output=tmp_path / "ug.zip")).output
    assert verify(zip_out).ok
    raw_zip = zip_out.read_bytes()
    prefix_zip = tmp_path / "prefix_ug.zip"
    prefix_zip.write_bytes(b"#!/usr/bin/env python3\n" + raw_zip)
    assert not verify(prefix_zip).ok
    trailing_zip = tmp_path / "trailing_ug.zip"
    trailing_zip.write_bytes(raw_zip + b"trailing bytes")
    assert not verify(trailing_zip).ok

    # 13. `_build._served` deduplicates OS-specific pure-Python payloads when `python_platform` is
    #     None, `_loader._fits_os_cpu` ignores ABI mismatch, `_loader._hold` handles deleted site,
    #     and `_imports.imports_in_with_lines` handles loop guards & order-independent optionals
    from bundleup import _build, _python

    dummy_target = _python.Target(
        executable=sys.executable,
        version=(3, 11),
        full_version="3.11.0",
        implementation="cpython",
        platform=sys.platform,
        machine="x86_64",
        abiflags="",
        cache_tag="cpython-311",
        markers={},
    )
    dummy_prep = _payload.Prepared(
        source=_source.load_source(ug_proj),
        version="0.1.0",
        target=dummy_target,
        pylock=ug_proj / "pylock.toml",
        site=ug_proj,
        packages=0,
        native=False,
        entry=None,
        script=None,
        diagnostics=[],
        sizes=[],
        pythons=_python.PythonRange((3, 9), None),
        reach=_python.Portability(any_os=False, any_cpu=True),
    )
    assert _build._served([dummy_prep], BuildOptions(path=ug_proj, python="3.12"))

    payload_cfg = {
        "platform": sys.platform,
        "machine": _loader._machine(),
        "abiflags": "nonexistent_abi",
        "libc": None,
        "macos": None,
    }
    assert _loader._fits_os_cpu(payload_cfg)
    assert not _loader._fits(payload_cfg)

    if os.name != "nt":
        gone_site = tmp_path / "lock_root" / "gone_site"
        assert not _loader._hold(str(gone_site))

    loop_tree = ast.parse(
        "def use_early():\n"
        "    if HAS_EARLY:\n"
        "        import early_opt\n"
        "try:\n"
        "    import early_opt\n"
        "    HAS_EARLY = True\n"
        "except ImportError:\n"
        "    HAS_EARLY = False\n"
        "for item in [1, 2]:\n"
        "    if sys.platform == 'win32':\n"
        "        continue\n"
        "    import posix_in_loop\n"
    )
    assert _imports.imports_in(loop_tree) == set()
    assert _check._source_of("pkg/__pycache__/mod.cpython-312.opt-1.pyc") == "pkg/mod.py"


def test_phase3_reviewer_audit_regressions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressions for all bugs found and fixed during the Phase 3 reviewer audit across
    Tracks 1, 2, 3, and 4."""
    import gzip
    import io
    import os
    import sys
    import tarfile
    import unicodedata

    from bundleup import (
        _coverage,
        _exe,
        _loader,
        _payload,
        _platforms,
        _python,
        _runtime,
        _smoke,
        _source,
        _toml,
        _uv,
    )

    # Track 1: _valid_gzip rejects truncated .tar.gz and accepts valid .tar.gz
    trunc_gz = tmp_path / "truncated.tar.gz"
    trunc_gz.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 16)
    assert not _exe._valid_gzip(trunc_gz)
    valid_gz = tmp_path / "valid.tar.gz"
    with gzip.open(valid_gz, "wb") as gz_out, tarfile.open(fileobj=gz_out, mode="w") as tf:
        info = tarfile.TarInfo("python/Lib/hello.py")
        data = b"x = 1\n"
        info.size = len(data)
        info.mode = 0o444  # read-only in source archive
        tf.addfile(info, io.BytesIO(data))
    assert _exe._valid_gzip(valid_gz)

    # Track 1: precompiled() ensures regular files in repacked tarball have owner-write bit (0o600)
    target = _python.Target(
        executable=sys.executable,
        version=sys.version_info[:2],
        full_version=".".join(map(str, sys.version_info[:3])),
        implementation="cpython",
        platform=sys.platform,
        machine="aarch64",
        abiflags="",
        cache_tag=sys.implementation.cache_tag,
        markers={},
    )
    stage_dir = tmp_path / "exe_stage"
    stage_dir.mkdir()
    compiled_tar = _exe.precompiled(valid_gz, target, stage_dir)
    with tarfile.open(compiled_tar) as tf:
        member = tf.getmember("python/Lib/hello.py")
        assert member.mode & 0o600 == 0o600

    monkeypatch.setattr(_loader, "_SCIE", "/usr/local/bin/my_exe/")
    assert _loader._me() == "my_exe"
    monkeypatch.setattr(_loader, "_SCIE", None)

    # Track 2: relocate_paths handles triple-quoted and single-quoted TOML strings with quotes
    ws_root = tmp_path / "ws_quote"
    dep_name = "dep 'single' %s café" if os.name == "nt" else "dep \"quote\" 'single' %s café"
    dep_dir = ws_root / dep_name
    dep_dir.mkdir(parents=True)
    (dep_dir / "pyproject.toml").write_text('[project]\nname = "dep"\nversion = "0.1.0"\n')
    stage_lock_dir = tmp_path / "stage_lock"
    stage_lock_dir.mkdir()
    pylock_file = stage_lock_dir / "pylock.toml"
    pylock_file.write_text(
        'lock-version = "1.0"\n'
        "[[packages]]\n"
        'name = "dep"\n'
        f'directory = {{ path = """{dep_name}""" }}\n',
        encoding="utf-8",
    )
    _uv.relocate_paths(pylock_file, ws_root)
    parsed_lock = _toml.loads(pylock_file.read_text(encoding="utf-8"))
    relocated_path = parsed_lock["packages"][0]["directory"]["path"]
    assert (stage_lock_dir / relocated_path).resolve() == dep_dir.resolve()

    # Track 2: _legacy_name handles % in setup.cfg without InterpolationSyntaxError
    legacy_dir = tmp_path / "legacy_pct"
    legacy_dir.mkdir()
    (legacy_dir / "setup.cfg").write_text("[metadata]\nname = my_pkg\ndescription = 100% pure\n")
    assert _source._legacy_name(legacy_dir) == "my_pkg"

    # Track 2: NFC/NFD normalization in _git_files and _exact_path
    nfd_name = unicodedata.normalize("NFD", "café.py")
    nfc_name = unicodedata.normalize("NFC", "café.py")
    nfc_dir = tmp_path / "nfc_test"
    nfc_dir.mkdir()
    (nfc_dir / nfd_name).write_text("print('ok')\n")
    if sys.platform == "darwin":
        matched_p = _payload._exact_file(nfc_dir, nfc_name)
        assert matched_p is not None and matched_p.is_file()
        assert _payload._exact_file(nfc_dir, "Café.py") is None  # still case-sensitive

    # Track 3: MACOSX_DEPLOYMENT_TARGET=10.15 floors aarch64-apple-darwin at (11, 0)
    with monkeypatch.context() as mp:
        mp.setenv("MACOSX_DEPLOYMENT_TARGET", "10.15")
        arm_mac = _platforms.parse("aarch64-apple-darwin")
        x86_mac = _platforms.parse("x86_64-apple-darwin")
        assert arm_mac.level == (11, 0)
        assert x86_mac.level == (10, 15)
        assert arm_mac.accepts("cp312-cp312-macosx_11_0_arm64")
        assert any("arm64" in t.platform for t in arm_mac.supported_tags((3, 12)))
        mp.setenv("MACOSX_DEPLOYMENT_TARGET", "14.")
        assert _platforms.parse("aarch64-apple-darwin").level == (14, 0)

    # Track 3: wheel-tag algebra for abi3 across Python versions, free-threaded abiflags="t",
    # and multi-arch / multi-libc runtime_needs
    linux_gnu = _platforms.parse("x86_64-unknown-linux-gnu")
    linux_musl = _platforms.parse("x86_64-unknown-linux-musl")
    assert not linux_gnu.accepts("cp312-abi3-manylinux_2_17_x86_64", python=(3, 11))
    assert linux_gnu.accepts("cp312-abi3-manylinux_2_17_x86_64", python=(3, 12))
    assert linux_gnu.accepts("cp313-cp313t-manylinux_2_28_x86_64", python=(3, 13), abiflags="t")
    assert not linux_gnu.accepts("cp313-cp313-manylinux_2_28_x86_64", python=(3, 13), abiflags="t")
    assert not linux_gnu.accepts("cp312-abi3-manylinux_2_28_x86_64", python=(3, 13), abiflags="t")
    assert any(t.abi == "cp313t" for t in linux_gnu.supported_tags((3, 13), abiflags="t"))
    assert not any(t.abi == "abi3" for t in linux_gnu.supported_tags((3, 13), abiflags="t"))
    pylock_ft = (
        'lock-version = "1.0"\n'
        "[[packages]]\n"
        'name = "ft-pkg"\n'
        'version = "1.0.0"\n'
        'wheels = [{ name = "ft_pkg-1.0.0-cp313-cp313-manylinux_2_28_x86_64.whl" }]\n'
    )
    assert len(_coverage.gaps(pylock_ft, linux_gnu, (3, 13), abiflags="t")) == 1
    assert len(_coverage.gaps(pylock_ft, linux_gnu, (3, 13), abiflags="")) == 0

    dual_libc_tags = [["cp312-cp312-manylinux_2_28_x86_64", "cp312-cp312-musllinux_1_2_x86_64"]]
    assert _platforms.runtime_needs(dual_libc_tags, platform=linux_musl).libc == ("musl", (1, 2))
    assert _platforms.runtime_needs(dual_libc_tags, platform=linux_gnu).libc == ("glibc", (2, 28))

    dual_mac_tags = [["cp312-cp312-macosx_10_9_x86_64.macosx_11_0_arm64"]]
    assert _platforms.runtime_needs(dual_mac_tags, arch="aarch64").macos == (11, 0)
    assert _platforms.runtime_needs(dual_mac_tags, arch="x86_64").macos == (10, 9)

    # Track 3: _find_env drops broken VIRTUAL_ENV symlinks; _make_writable ignores symlinks
    import contextlib

    broken_venv = tmp_path / "broken_venv"
    (broken_venv / "bin").mkdir(parents=True)
    with contextlib.suppress(OSError):
        (broken_venv / "bin" / "python").symlink_to(tmp_path / "missing_python_bin")
        with monkeypatch.context() as mp:
            mp.setenv("VIRTUAL_ENV", str(broken_venv))
            env = _python._find_env(tmp_path, is_script=True)
            assert env is not None and "VIRTUAL_ENV" not in env

    ext_ro = tmp_path / "external_readonly.txt"
    ext_ro.write_text("secret")
    ext_ro.chmod(0o400)
    before_mode = ext_ro.stat().st_mode & 0o777
    smoke_dir = tmp_path / "smoke_root"
    smoke_dir.mkdir()
    with contextlib.suppress(OSError):
        (smoke_dir / "link.txt").symlink_to(ext_ro)
    _smoke._make_writable(smoke_dir)
    assert (ext_ro.stat().st_mode & 0o777) == before_mode
    ext_ro.chmod(0o600)

    # Track 4: site_packages_index strips editable .pth entries between stdlib and site-packages,
    # and activate() evicts modules under parent BUNDLEUP_RUNTIME_PATHS
    with monkeypatch.context() as mp:
        for var in (
            "PYTHONPATH",
            _runtime.ENV_SITE,
            _runtime.ENV_PATHS,
            _runtime.ENV_PYTHON,
            _runtime.ENV_SCRIPTS,
            _runtime.ENV_INHERIT,
            "BUNDLEUP_INHERIT_PATH",
        ):
            mp.delenv(var, raising=False)
        mp.setattr(_runtime, "_HOST_TAIL", None)
        mp.delitem(sys.__dict__, "_bundleup_host_tail", raising=False)
        fake_stdlib = (os.__file__ and os.path.dirname(os.__file__)) or "/stdlib"
        leaked_pth = str(tmp_path / "editable_src")
        fake_sp = str(tmp_path / "venv" / "lib" / "python3.12" / "site-packages")
        mp.setattr(sys, "path", [fake_stdlib, leaked_pth, fake_sp])
        assert _runtime.site_packages_index() == 1

        p_site = tmp_path / "p_site2"
        p_pth = tmp_path / "p_pth2"
        c_site = tmp_path / "c_site2"
        for d in (p_site, p_pth, c_site):
            d.mkdir()
        pth_mod = type(sys)("pth_shared_mod")
        pth_mod.__file__ = str(p_pth / "pth_shared_mod.py")
        mp.setitem(sys.modules, "pth_shared_mod", pth_mod)
        mp.setenv("BUNDLEUP_RUNTIME_SITE", str(p_site))
        mp.setenv("BUNDLEUP_RUNTIME_PATHS", os.pathsep.join([str(p_site), str(p_pth)]))
        _runtime.activate(str(c_site), [])
        assert "pth_shared_mod" not in sys.modules


def test_phase4_deep_reasoning_audit_regressions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressions for all bugs found and fixed during the Phase 4 deep-reasoning audit across
    Tracks 1, 2, 3, and 4."""
    import ast
    import importlib.metadata
    import importlib.util
    import os
    import sys

    from bundleup import (
        BuildOptions,
        _build,
        _bytecode,
        _cache,
        _errors,
        _imports,
        _loader,
        _payload,
        _python,
        _runtime,
        _source,
        _uv,
        build,
    )

    # Track 1: offline fallback in _uv._run_with_offline_fallback
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> str:
        calls.append(cmd)
        if "--offline" not in cmd:
            raise _errors.UvError("uv pip compile failed", detail="Failed to fetch: dns error")
        return "ok"

    with monkeypatch.context() as mp:
        mp.setattr(_uv, "run", fake_run)
        res = _uv._run_with_offline_fallback(
            ["uv", "pip", "compile", "requirements.in"],
            cwd=tmp_path,
            what="uv pip compile",
            progress=lambda _msg: None,
        )
        assert res == "ok"
        assert len(calls) == 2
        assert calls[1][:4] == ["uv", "pip", "compile", "--offline"]

    # Track 1: export() when source.name is not in exported packages keeps lock_for_install separate
    proj_self = tmp_path / "self_missing_proj"
    proj_self.mkdir()
    (proj_self / "pyproject.toml").write_text('[project]\nname = "self-missing"\nversion = "0.1"\n')
    (proj_self / "uv.lock").write_text('version = 1\nrequires-python = ">=3.9"\n')
    stage_self = tmp_path / "stage_self"
    stage_self.mkdir()

    def fake_export_run(cmd: list[str], **_kwargs: object) -> str:
        out_idx = cmd.index("-o") + 1
        Path(cmd[out_idx]).write_text(
            'lock-version = "1.0"\n'
            'created-by = "uv"\n'
            "[[packages]]\n"
            'name = "other-pkg"\n'
            'version = "1.0.0"\n'
            "wheels = []\n",
            encoding="utf-8",
        )
        return ""

    with monkeypatch.context() as mp:
        mp.setattr(_uv, "run", fake_export_run)
        src_self = _source.load_source(proj_self)
        exported_self = _uv.export(
            "uv",
            src_self,
            lock_mode="locked",
            python=(3, 12),
            stage=stage_self,
            progress=lambda _msg: None,
        )
        install_lock = Path(exported_self.installs[0][1])
        assert install_lock.name == "pylock.install.toml"
        assert 'path = "."' not in install_lock.read_text(encoding="utf-8")
        assert 'path = "."' in exported_self.pylock.read_text(encoding="utf-8")

        proj_virtual = tmp_path / "virtual_proj"
        proj_virtual.mkdir()
        (proj_virtual / "pyproject.toml").write_text(
            '[project]\nname = "virtual-proj"\nversion = "0.2.0"\n[tool.uv]\npackage = false\n',
            encoding="utf-8",
        )
        (proj_virtual / "uv.lock").write_text('version = 1\nrequires-python = ">=3.9"\n')
        src_virtual = _source.load_source(proj_virtual)
        assert not src_virtual.packaged
        assert src_virtual.version == "0.2.0"
        assert _source.project_version(tmp_path, src_virtual) == "0.2.0"
        stage_virtual = tmp_path / "stage_virtual"
        stage_virtual.mkdir()
        exported_virtual = _uv.export(
            "uv",
            src_virtual,
            lock_mode="locked",
            python=(3, 12),
            stage=stage_virtual,
            progress=lambda _msg: None,
        )
        assert len(exported_virtual.installs) == 1
        assert 'path = "."' not in exported_virtual.pylock.read_text(encoding="utf-8")

    # Track 1: unpinned requirements.txt with --locked raises NoLockfileError without resolve()
    req_unpinned = tmp_path / "unpinned_app"
    req_unpinned.mkdir()
    (req_unpinned / "main.py").write_text("print('hi')\n")
    (req_unpinned / "requirements.txt").write_text("rich>=13.0\n")
    with monkeypatch.context() as mp:
        mp.setattr(
            _uv,
            "resolve",
            lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("resolve must not run")),
        )
        with pytest.raises(_errors.NoLockfileError):
            _uv.export(
                "uv",
                _source.load_source(req_unpinned),
                lock_mode="locked",
                python=(3, 12),
                stage=tmp_path / "stage_unpinned",
                progress=lambda _msg: None,
            )

    # Track 1: _strip_pyproject_external works when [tool.uv] has non-resolution keys,
    # and _strip_requirements_external strips --hash from kept lines
    pyproj_ext = tmp_path / "pyproj_ext"
    pyproj_ext.mkdir()
    decl_pyproj = pyproj_ext / "pyproject.toml"
    decl_pyproj.write_text(
        '[project]\nname = "app"\nversion = "0.1"\ndependencies = ["rich>=13", "click>=8"]\n'
        "[tool.uv]\npackage = true\n"
    )
    staged_in = _uv._strip_pyproject_external(decl_pyproj, {"rich"}, pyproj_ext)
    assert staged_in is not None and staged_in.read_text(encoding="utf-8").strip() == "click>=8"

    hashed_req = pyproj_ext / "requirements.txt"
    hashed_req.write_text(
        "rich==13.0.0 --hash=sha256:aaaa\nclick==8.1.7 \\\n    --hash=sha256:bbbb\n"
    )
    staged_req = _uv._strip_requirements_external(hashed_req, {"rich"}, pyproj_ext)
    assert (
        staged_req is not None and staged_req.read_text(encoding="utf-8").strip() == "click==8.1.7"
    )

    # Track 1: LOCAL_PATH relocates compact `path="."` without spaces, and _strip_script_external
    # preserves backslashes in dependency strings
    compact_lock = pyproj_ext / "compact_pylock.toml"
    compact_lock.write_text(
        'lock-version = "1.0"\n[[packages]]\nname = "a"\ndirectory = {path="."}\n'
    )
    _uv.relocate_paths(compact_lock, tmp_path)
    assert 'path="' in compact_lock.read_text(encoding="utf-8")

    pep_script = tmp_path / "pep_bs.py"
    pep_script.write_text(
        '# /// script\n# dependencies = ["rich", "foo; extra == \\"bar\\""]\n# ///\nprint(1)\n'
    )
    staged_script = _uv._strip_script_external(pep_script, {"rich"}, pyproj_ext)
    assert staged_script != pep_script
    assert _source.script_metadata(staged_script.read_text(encoding="utf-8"))["dependencies"] == [
        'foo; extra == "bar"'
    ]

    # Track 1: empty PEP 723 block, CRLF script_metadata, non-list [project] dependencies,
    # and symlinked workspace member resolution
    assert _source.script_metadata("# /// script\r\n# ///\r\nprint(1)\r\n") == {}
    empty_pep = tmp_path / "empty_pep.py"
    empty_pep.write_text("# /// script\n# ///\nprint('ok')\n")
    assert _source.load_source(empty_pep).pep723

    bad_deps_proj = tmp_path / "bad_deps_proj"
    bad_deps_proj.mkdir()
    (bad_deps_proj / "pyproject.toml").write_text(
        '[project]\nname = "bad"\nversion = "0.1"\ndependencies = "not-a-list"\n'
    )
    with pytest.raises(_errors.ProjectError, match="dependencies"):
        _source.load_source(bad_deps_proj)

    if os.name != "nt":
        real_ws = tmp_path / "real_ws"
        (real_ws / "packages" / "member_a").mkdir(parents=True)
        (real_ws / "pyproject.toml").write_text(
            '[tool.uv.workspace]\nmembers = ["packages/*"]\nexclude = [123, "/abs/path"]\n'
        )
        (real_ws / "uv.lock").write_text("version = 1\n")
        link_ws = tmp_path / "link_ws"
        link_ws.symlink_to(real_ws)
        assert _source.find_uv_lock(link_ws / "packages" / "member_a") is not None

    # Track 2: portability() does not false-negative when target.full_version has patch > 0
    # and lock marker uses `python_full_version >= '3.12.1'`
    patch_pylock = tmp_path / "patch_pylock.toml"
    patch_pylock.write_text(
        'lock-version = "1.0"\n'
        "[[packages]]\n"
        'name = "pure-pkg"\n'
        'version = "1.0.0"\n'
        "marker = \"python_full_version >= '3.12.1'\"\n"
        'wheels = [{ name = "pure_pkg-1.0.0-py3-none-any.whl" }]\n'
    )
    patch_target = _python.Target(
        executable=sys.executable,
        version=(3, 12),
        full_version="3.12.3",
        implementation="cpython",
        platform="linux",
        machine="x86_64",
        abiflags="",
        cache_tag="cpython-312",
        markers=_python._platforms.parse("x86_64-unknown-linux-gnu").markers(
            python_full_version="3.12.3"
        ),
    )
    reach = _payload.portability(
        patch_pylock,
        target=patch_target,
        pythons=_python.PythonRange((3, 12), (3, 14)),
        native=False,
    )
    assert reach == _python.Portability(any_os=True, any_cpu=True)

    # Track 2: _lowest and _served handle 3-part versions and same-OS same-CPU pure payloads
    c1 = BuildOptions(path=tmp_path, python="3.11.4")
    c2 = BuildOptions(path=tmp_path, python="3.12.1")
    assert _build._lowest([c1, c2]) == (3, 11)
    cpu_locked_prep = _payload.Prepared(
        source=_source.load_source(empty_pep),
        version=None,
        target=patch_target,
        pylock=patch_pylock,
        site=tmp_path,
        packages=0,
        native=False,
        entry=None,
        script=None,
        diagnostics=[],
        sizes=[],
        pythons=_python.PythonRange((3, 9), None),
        reach=_python.Portability(any_os=False, any_cpu=False),
    )
    assert _build._served(
        [cpu_locked_prep],
        BuildOptions(
            path=tmp_path,
            python="3.12.3",
            python_platform="x86_64-unknown-linux-gnu",
        ),
    )

    # Track 2: --smoke with --entry python and no args fails early in _settle before building
    with pytest.raises(_errors.UsageError, match="--smoke needs a script"):
        build(BuildOptions(path=empty_pep, entry="python", smoke=()))

    # Track 2: _has_attr recognizes `from .sub import x` and `from pkg.sub import x` in __init__.py
    pkg_init = tmp_path / "mypkg" / "__init__.py"
    pkg_init.parent.mkdir(parents=True)
    pkg_init.write_text("from .sub import helper\nfrom mypkg.other import tool\n")
    ok_sub, _, defs_sub = _payload._has_attr(pkg_init, "sub", module="mypkg")
    ok_other, _, defs_other = _payload._has_attr(pkg_init, "other", module="mypkg")
    assert ok_sub and "sub" in defs_sub
    assert ok_other and "other" in defs_other

    # Track 2: PEP 420 namespace package split between site and --external
    ns_site = tmp_path / "ns_site"
    (ns_site / "google" / "protobuf").mkdir(parents=True)
    (ns_site / "google" / "protobuf" / "__init__.py").write_text("")
    m_ns = _payload._locate_module(
        [ns_site], "google.cloud.storage", (3, 12), external=("google-cloud-storage",)
    )
    assert m_ns.found

    # Track 3: external_modules RECORD fallback ignores LICENSE.txt / .pth / bin / Scripts / share
    # / non-Python dirs, handles whitespace-only top_level.txt, and unwraps top-level __pycache__
    class DummyDist:
        def read_text(self, filename: str) -> str | None:
            if filename == "top_level.txt":
                return "   \n"
            if filename == "RECORD":
                return (
                    "LICENSE.txt,sha256=abc,10\n"
                    "README.md,sha256=abc,10\n"
                    "custom.pth,sha256=abc,10\n"
                    "bin/my_tool,sha256=abc,10\n"
                    "Scripts/my_tool.exe,sha256=abc,10\n"
                    "share/doc/pkg/README.md,sha256=abc,10\n"
                    "include/pkg/hdr.h,sha256=abc,10\n"
                    "etc/pkg.conf,sha256=abc,10\n"
                    "data_dir/config.json,sha256=abc,10\n"
                    "__pycache__/pyc_only_mod.cpython-312.pyc,sha256=abc,10\n"
                    "sub_dir/pth_mod.py,sha256=abc,10\n"
                    "sub_dir/pth_pkg/__init__.py,sha256=abc,10\n"
                    "top_ext.cpython-312-darwin.so,sha256=abc,10\n"
                )
            if filename == "custom.pth":
                return "sub_dir\n"
            return None

    with monkeypatch.context() as mp:
        mp.setattr(importlib.metadata, "distribution", lambda _name: DummyDist())
        mods = _imports.external_modules(["custom-dist"])
        assert {"pth_mod", "pth_pkg", "top_ext", "pyc_only_mod"} <= mods
        for non_mod in (
            "LICENSE",
            "README",
            "custom",
            "bin",
            "Scripts",
            "share",
            "include",
            "etc",
            "data_dir",
            "__pycache__",
        ):
            assert non_mod not in mods

    # Track 1: comment ending with backslash in requirements.txt must not swallow next requirement,
    # and --require-hashes / tab-separated --hash are handled when stripping external requirements
    req_backslash = tmp_path / "req_backslash.txt"
    req_backslash.write_text(
        "# Generated from C:\\Users\\dev\\\n"
        "--require-hashes\n"
        "ext-pkg==1.0.0\t--hash=sha256:1111\n"
        "kept-pkg==2.0.0 \\\n"
        "    --hash=sha256:2222\n"
        "# Another comment ending with \\\n"
        "unpinned-pkg>=1.0\n",
        encoding="utf-8",
    )
    assert _uv.pinned_requirements(req_backslash, external=("ext-pkg",)) == (None, False)
    staged_in = _uv._strip_requirements_external(req_backslash, {"ext-pkg"}, tmp_path)
    assert staged_in is not None
    staged_lines = staged_in.read_text(encoding="utf-8").splitlines()
    assert "--require-hashes" not in staged_lines
    assert "kept-pkg==2.0.0" in staged_lines
    assert "unpinned-pkg>=1.0" in staged_lines

    # Track 1: _is_network_error recognizes OS DNS and reqwest error messages;
    # _export_cache_key returns None when setup.py or setup.cfg exists alongside pyproject.toml
    for net_msg in (
        "nodename nor servname provided, or not known",
        "failed to lookup address information: Name or service not known",
        "error sending request for url",
        "No route to host (os error 65)",
        "Network down",
    ):
        assert _uv._is_network_error(net_msg)
    (proj_self / "setup.cfg").write_text("[metadata]\nname = self-missing\n")
    assert (
        _uv._export_cache_key("uv", _source.load_source(proj_self), ["--locked"], "locked") is None
    )
    (proj_self / "setup.cfg").unlink()

    # Track 1 & 2: [tool.bundleup] rejects comma-only external = [","], skips external when CLI
    # overrides --format exe, and _prepare rejects --external with version specifier on self
    from bundleup import _config

    cfg_proj = tmp_path / "cfg_proj"
    cfg_proj.mkdir()
    (cfg_proj / "pyproject.toml").write_text(
        '[project]\nname = "cfg-proj"\nversion = "0.1.0"\n[tool.bundleup]\nexternal = [" , "]\n'
    )
    with pytest.raises(_errors.UsageError, match="`external` must be a string or a list"):
        _config.apply(BuildOptions(path=cfg_proj))
    (cfg_proj / "pyproject.toml").write_text(
        '[project]\nname = "cfg-proj"\nversion = "0.1.0"\n[tool.bundleup]\nexternal = ["boto3"]\n'
    )
    settled_exe, fmt_exe = _build._settle(BuildOptions(path=cfg_proj, format="exe"))
    assert fmt_exe == "exe" and settled_exe.external == ()
    with pytest.raises(_errors.UsageError, match="can't exclude cfg-proj itself"):
        _build._prepare(
            BuildOptions(path=cfg_proj, external=("cfg-proj>=0.1",)),
            fmt="pyz",
            stage=tmp_path,
            steps=_build.Steps(lambda _e: None),
            progress=lambda _e: None,
        )

    # Track 2: CPUS maps 32-bit x86/i386, portability() avoids vacuous any_cpu on unknown OS,
    # and _has_attr handles `import pkg.sub as alias` and `import_module` in __init__.py
    assert _build.CPUS["x86"] == "i686" and _build.CPUS["i386"] == "i686"
    freebsd_target = _python.Target(
        executable=sys.executable,
        version=(3, 12),
        full_version="3.12.0",
        implementation="cpython",
        platform="freebsd14",
        machine="x86_64",
        abiflags="",
        cache_tag="cpython-312",
        markers={"sys_platform": "freebsd14"},
    )
    os_gated_pylock = tmp_path / "os_gated_pylock.toml"
    os_gated_pylock.write_text(
        'lock-version = "1.0"\n'
        "[[packages]]\n"
        'name = "win-only"\n'
        'version = "1.0"\n'
        "marker = \"sys_platform == 'win32'\"\n"
        'wheels = [{ name = "win_only-1.0-py3-none-any.whl" }]\n'
    )
    fb_reach = _payload.portability(
        os_gated_pylock,
        target=freebsd_target,
        pythons=_python.PythonRange((3, 12), (3, 12)),
        native=False,
    )
    assert fb_reach == _python.Portability(any_os=False, any_cpu=False)
    pkg_init.write_text("import mypkg.aliased_sub as _sub\n")
    ok_alias, _, defs_alias = _payload._has_attr(pkg_init, "aliased_sub", module="mypkg")
    assert ok_alias and "aliased_sub" in defs_alias
    pkg_init.write_text("import importlib\nimportlib.import_module('.dyn_sub', __name__)\n")
    ok_dyn, _, _ = _payload._has_attr(pkg_init, "dyn_sub", module="mypkg")
    assert ok_dyn

    # Track 3: imports_in_with_lines handles terminating `try: ... except ImportError: return`
    # and `match sys.platform:` blocks
    guard_tree = ast.parse(
        "def run():\n"
        "    try:\n"
        "        import rich\n"
        "    except ImportError:\n"
        "        return\n"
        "    from rich.console import Console\n"
        "    import mandatory_mod\n"
        "match sys.platform:\n"
        "    case 'win32':\n"
        "        import win_match_mod\n"
        "    case _:\n"
        "        import posix_match_mod\n"
    )
    assert _imports.imports_in(guard_tree) == {"mandatory_mod"}

    # Track 3: search_roots and add_pth normalize backslashes in .pth files
    pth_site = tmp_path / "pth_site"
    (pth_site / "win32" / "lib").mkdir(parents=True)
    (pth_site / "pywin32.pth").write_text("win32\\lib\n")
    assert (pth_site / "win32" / "lib") in _imports.search_roots(pth_site)
    orig_sys_path = list(sys.path)
    _runtime.add_pth(str(pth_site), "pywin32.pth", set())
    assert os.path.normcase(str(pth_site / "win32" / "lib")) in sys.path
    monkeypatch.setattr(sys, "path", orig_sys_path)

    # Track 4: _cache_imported compiles modules when __spec__ is None (like __main__)
    cache_site = tmp_path / "cache_site"
    cache_site.mkdir()
    main_py = cache_site / "script_main.py"
    main_py.write_text("X = 42\n")
    dummy_main = type(sys)("__bundleup_test_main__")
    dummy_main.__file__ = str(main_py)
    dummy_main.__spec__ = None
    with monkeypatch.context() as mp:
        mp.setitem(sys.modules, "__bundleup_test_main__", dummy_main)
        _loader._cache_imported(str(cache_site))
    expected_pyc = Path(importlib.util.cache_from_source(str(main_py)))
    assert expected_pyc.is_file()

    # Track 4: _restore rejects symlinked cache entries & symlinked files inside cache entries,
    # clean_cache skips locked .tmp-*-pruned directories, and _bytecode_copies deduplicates prefixes
    sym_cache = tmp_path / "sym_bcache"
    sym_cache.mkdir()
    real_dir = tmp_path / "real_bcache_dir"
    real_dir.mkdir()
    if os.name != "nt":
        import fcntl
        import time

        (sym_cache / "key123").symlink_to(real_dir)
        dist_obj = _bytecode.Distribution("pkg", "key123", [])
        assert not _bytecode._restore(dist_obj, sym_cache, cache_site)
        inner_sym_dir = sym_cache / "key_inner"
        inner_sym_dir.mkdir()
        (inner_sym_dir / "mod.pyc").symlink_to(expected_pyc)
        assert not _bytecode._restore(
            _bytecode.Distribution("pkg", "key_inner", ["mod.py"]), sym_cache, cache_site
        )
        prune_root = tmp_path / "prune_race_root"
        prune_root.mkdir()
        pruning_tmp = prune_root / ".tmp-app-0123456789abcdef-999-deadbeef-pruned"
        pruning_tmp.mkdir()
        pruning_lock = prune_root / ".lock-app-0123456789abcdef"
        pruning_lock.write_bytes(b"")
        ancient = time.time() - 40 * 86400
        os.utime(pruning_tmp, (ancient, ancient))
        os.utime(pruning_lock, (ancient, ancient))
        with monkeypatch.context() as mp:
            mp.setenv("BUNDLEUP_CACHE", str(prune_root))
            with open(pruning_lock, "r+b") as held_prune:
                fcntl.flock(held_prune.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                _cache.clean_cache(older_than_days=30)
                assert pruning_tmp.is_dir() and pruning_lock.is_file()
            _cache.clean_cache(older_than_days=30)
            assert not pruning_tmp.exists() and not pruning_lock.exists()
    with monkeypatch.context() as mp:
        import shutil

        mp.setattr(_cache, "PYCACHE_PREFIXES", [tmp_path / "dup_prefix"])
        mp.setattr(sys, "pycache_prefix", str(tmp_path / "dup_prefix"))
        rel = os.path.splitdrive(str(cache_site))[1].lstrip("\\/")
        (tmp_path / "dup_prefix" / rel).mkdir(parents=True)
        copies = _cache._bytecode_copies(cache_site)
        assert len(copies) == 1

        mp.setattr(shutil, "_use_fd_functions", False, raising=False)
        _loader._rmtree(str(tmp_path / "nonexistent_dir_on_windows"))
        unsafe_ro = tmp_path / "unsafe_ro_tree"
        (unsafe_ro / "sub").mkdir(parents=True)
        (unsafe_ro / "sub" / "f.txt").write_text("x")
        (unsafe_ro / "sub" / "f.txt").chmod(0o444)
        (unsafe_ro / "sub").chmod(0o444)
        _loader._rmtree(str(unsafe_ro))
        assert not unsafe_ro.exists()

    if sys.version_info >= (3, 11):
        spec = importlib.util.spec_from_file_location(
            "corpus_issues",
            Path(__file__).resolve().parent.parent / "gauntlet" / "corpus_issues.py",
        )
        assert spec is not None and spec.loader is not None
        ci_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ci_mod)
        systemic_rows = [
            {
                "name": f"pkg-{i}",
                "kind": "app",
                "pin": f"pkg-{i}==1.0",
                "phase": "build",
                "code": "uv-failed",
                "outcome": "fail",
                "os": "linux",
                "python": "3.12",
                "network_blocked": True,
                "detail": "err",
            }
            for i in range(12)
        ]
        grouped = ci_mod.group_failures(systemic_rows)
        assert list(grouped) == ["systemic build uv-failed"]
        assert "12 programs fail at build (uv-failed)" in ci_mod.title(
            grouped["systemic build uv-failed"], "corpus"
        )
        assert "**12 programs**" in ci_mod.body(
            "systemic build uv-failed",
            grouped["systemic build uv-failed"],
            "https://example.com",
            "corpus",
        )
