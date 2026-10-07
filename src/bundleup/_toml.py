"""TOML reading on every supported Python: tomllib from 3.11, the tomli backport before."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from tomllib import TOMLDecodeError, loads
else:
    from tomli import TOMLDecodeError, loads

__all__ = ["TOMLDecodeError", "loads"]
