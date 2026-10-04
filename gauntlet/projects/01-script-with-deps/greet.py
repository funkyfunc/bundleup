# /// script
# requires-python = ">=3.9"
# dependencies = ["click>=8"]
# ///
"""Gauntlet 01: a PEP 723 script with a pure-Python dependency."""
import sys

import click


@click.command()
@click.option("--name", default="world")
def main(name: str) -> None:
    assert name == "gauntlet", f"argument parsing failed: {name!r}"
    click.echo("GAUNTLET OK 01-script-with-deps")


if __name__ == "__main__":
    sys.exit(main())
