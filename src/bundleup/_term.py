"""Terminal output: colour, ASCII fallback and a status line (docs/cli-style-guide.md 12-15, 51-56).

Colour has meaning only: red `error`, yellow `warning`, cyan `hint`, bold for what matters, dim
for metadata. Everything degrades to plain text when the stream isn't a terminal.
"""

from __future__ import annotations

import os
from typing import Literal, TextIO

ColorChoice = Literal["auto", "always", "never"]

_CODES = {"red": "31", "yellow": "33", "cyan": "36", "bold": "1", "dim": "2"}


def color_enabled(stream: TextIO, choice: ColorChoice) -> bool:
    """Whether to colour `stream`, following --color, FORCE_COLOR, NO_COLOR and TERM=dumb."""
    if choice != "auto":
        return choice == "always"
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return _is_tty(stream)


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def unicode_ok(stream: TextIO) -> bool:
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    return encoding == "utf8"


class Style:
    """Formats text for one stream."""

    def __init__(self, stream: TextIO, choice: ColorChoice) -> None:
        self.stream = stream
        self.color = color_enabled(stream, choice)
        self.arrow = "→" if unicode_ok(stream) else "->"
        self.dot = "·" if unicode_ok(stream) else "-"

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{_CODES[code]}m{text}\x1b[0m" if self.color else text

    def error(self, text: str) -> str:
        return self._wrap("red", self._wrap("bold", text))

    def warning(self, text: str) -> str:
        return self._wrap("yellow", self._wrap("bold", text))

    def hint(self, text: str) -> str:
        return self._wrap("cyan", self._wrap("bold", text))

    def bold(self, text: str) -> str:
        return self._wrap("bold", text)

    def dim(self, text: str) -> str:
        return self._wrap("dim", text)

    def link(self, text: str, target: str) -> str:
        """An OSC 8 hyperlink where the terminal can show one, plain text otherwise."""
        if not self.color:
            return text
        return f"\x1b]8;;{target}\x1b\\{text}\x1b]8;;\x1b\\"


class StatusLine:
    """One rewriting progress line, shown only on an interactive terminal and never in CI."""

    def __init__(self, stream: TextIO, style: Style, *, enabled: bool) -> None:
        self.stream = stream
        self.style = style
        self.enabled = enabled and _is_tty(stream) and os.environ.get("TERM") != "dumb"
        self.enabled = self.enabled and not os.environ.get("CI")
        self.visible = False

    def show(self, text: str) -> None:
        if self.enabled:
            self.stream.write("\r\x1b[2K" + self.style.dim(text))
            self.stream.flush()
            self.visible = True

    def clear(self) -> None:
        if self.visible:
            self.stream.write("\r\x1b[2K")
            self.stream.flush()
            self.visible = False
