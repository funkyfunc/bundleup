"""What a build writes (ADR-0014, ADR-0025) and how big it may be (ADR-0039)."""

from __future__ import annotations

import re
from typing import Literal

from ._errors import UsageError

Format = Literal["pyz", "py", "dir", "lambda"]
FORMATS: tuple[Format, ...] = ("pyz", "py", "dir", "lambda")
# Formats that run through bundleup's loader, so they check the machine, unpack, and run an entry
# point; `dir` and `lambda` are imported by a host instead.
LOADED: tuple[Format, ...] = ("pyz", "py")

# Decimal units, as upload limits are written ("30 MB"), and binary ones for those who want them.
UNITS = {"": 1, "b": 1, "kb": 10**3, "mb": 10**6, "gb": 10**9}
UNITS |= {"kib": 2**10, "mib": 2**20, "gib": 2**30}
SIZE = re.compile(r"\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>[a-z]*)\s*", re.IGNORECASE)


def parse_size(text: str) -> int:
    """`30MB`, `250 MiB` or `1000` (bytes) -> bytes. Raises UsageError otherwise."""
    match = SIZE.fullmatch(text)
    unit = match["unit"].lower() if match else ""
    if match is None or unit not in UNITS:
        raise UsageError(
            f"can't read the size `{text}`",
            hint="a number with an optional unit: 30MB, 250MiB, 1000 (bytes)",
        )
    return int(float(match["number"]) * UNITS[unit])


def describe_size(n: int) -> str:
    """Bytes as people write limits: `30 MB`, `1.5 MB`."""
    for unit, size in (("GB", 10**9), ("MB", 10**6), ("KB", 10**3)):
        if n >= size:
            return f"{n / size:.1f}".removesuffix(".0") + f" {unit}"
    return f"{n} bytes"
