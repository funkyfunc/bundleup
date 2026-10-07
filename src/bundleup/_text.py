"""Small wording helpers shared by the CLI and the library's messages."""

from __future__ import annotations

SHOWN = 20  # lines of a long list shown in a message's detail


def plural(n: int, word: str) -> str:
    """'1 package', '3 packages'."""
    return f"{n} {word}{'' if n == 1 else 's'}"


def listing(items: list[str], shown: int = SHOWN) -> str:
    """The first `shown` items, one per line, then '... and N more'."""
    more = [f"... and {len(items) - shown} more"] if len(items) > shown else []
    return "\n".join(items[:shown] + more)


def findings(errors: int, warnings: int) -> str:
    """'1 error and 2 warnings', '3 warnings', '' when there are none."""
    parts = [plural(n, word) for n, word in ((errors, "error"), (warnings, "warning")) if n]
    return " and ".join(parts)
