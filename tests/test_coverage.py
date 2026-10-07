"""Wheel coverage from the lock alone (ADR-0031)."""

from __future__ import annotations

from bundleup import _coverage as c
from bundleup._platforms import parse

WHEEL = "https://files.example/{}"
PYLOCK = """\
lock-version = "1.0"
created-by = "test"

[[packages]]
name = "app"
directory = {{ path = "." }}

[[packages]]
name = "pure"
version = "1.0"
wheels = [{{ url = "{pure}" }}]

[[packages]]
name = "pillow"
version = "12.3.0"
wheels = [
    {{ url = "{pillow_new}" }},
    {{ url = "{pillow_mac}" }},
]

[[packages]]
name = "colorama"
version = "0.4.6"
marker = "sys_platform == 'win32'"
wheels = [{{ url = "{colorama}" }}]

[[packages]]
name = "docopt"
version = "0.6.2"
sdist = {{ url = "https://files.example/docopt-0.6.2.tar.gz" }}
""".format(
    pure=WHEEL.format("pure-1.0-py3-none-any.whl"),
    pillow_new=WHEEL.format(
        "pillow-12.3.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    ),
    pillow_mac=WHEEL.format("pillow-12.3.0-cp311-cp311-macosx_11_0_arm64.whl"),
    colorama=WHEEL.format("colorama-0.4.6-py2.py3-none-any.whl"),
)


def test_gaps_and_a_platform_level_that_works() -> None:
    old = parse("x86_64-manylinux_2_17")
    found = c.gaps(PYLOCK, old, (3, 11))
    assert [(g.package, g.source_only) for g in found] == [("pillow", False), ("docopt", True)]
    assert found[0].available == ("manylinux_2_27_x86_64", "manylinux_2_28_x86_64")  # same OS
    assert c.suggestion(found, old, PYLOCK) == "x86_64-manylinux_2_28"
    codes = [(d.code, d.level) for d in c.diagnostics(found, old, PYLOCK)]
    assert codes == [("no-wheel", "error"), ("source-only", "warning")]


def test_covered_targets_and_markers() -> None:
    assert [g.package for g in c.gaps(PYLOCK, parse("linux"), (3, 11))] == ["docopt"]
    assert [g.package for g in c.gaps(PYLOCK, parse("macos"), (3, 11))] == ["docopt"]
    # Windows: no pillow wheel, but colorama (win32 only) is covered by its pure wheel.
    found = c.gaps(PYLOCK, parse("windows"), (3, 11))
    assert [g.package for g in found] == ["pillow", "docopt"]
    assert c.suggestion(found, parse("windows"), PYLOCK) is None
    # A compiled wheel for another Python version doesn't count.
    assert "pillow" in [g.package for g in c.gaps(PYLOCK, parse("linux"), (3, 12))]


def test_the_matrix_covers_every_platform_and_python() -> None:
    cells = c.matrix(PYLOCK, [(3, 11), (3, 12)])
    assert len(cells) == len(c.MATRIX_PLATFORMS) * 2
    by = {(cell.platform, cell.python): cell for cell in cells}
    assert by[("x86_64-unknown-linux-gnu", (3, 11))].ok  # pillow has a 2_28 wheel for 3.11
    assert by[("x86_64-unknown-linux-gnu", (3, 12))].missing == ("pillow",)  # cp311 only
    assert not by[("x86_64-pc-windows-msvc", (3, 11))].ok
    assert by[("aarch64-apple-darwin", (3, 11))].source_only == ("docopt",)
