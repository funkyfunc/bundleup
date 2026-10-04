"""Gauntlet 03: several pure-Python dependencies."""
import attrs
import click
import tomli_w
from packaging.version import Version


@attrs.define
class Release:
    name: str
    version: str


def main() -> int:
    release = Release("gauntlet", "1.2.3")
    assert Version(release.version) > Version("1.2")
    doc = tomli_w.dumps(attrs.asdict(release))
    assert 'version = "1.2.3"' in doc
    click.echo("GAUNTLET OK 03-pure-deps")
    return 0
