"""Gauntlet 09: imports whose module names are only known at runtime."""
import importlib
import sys

from pygments import highlight
from pygments.formatters import NullFormatter
from pygments.lexers import get_lexer_by_name


def load_handler(kind: str):
    return importlib.import_module(f"{__name__}.handlers.{kind}")


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "csv"
    handler = load_handler(kind)
    assert handler.handle("a,b") == ["a", "b"]

    lexer = get_lexer_by_name("rust")  # never imported statically anywhere
    out = highlight("fn main() {}", lexer, NullFormatter())
    assert "fn main" in out
    print("GAUNTLET OK 09-dynamic-imports")
    return 0
