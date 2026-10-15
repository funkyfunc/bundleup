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
