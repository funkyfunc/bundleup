"""Gauntlet 05: data files found relative to __file__."""
import os
from datetime import datetime
from pathlib import Path

import pytz

TEMPLATES = Path(__file__).parent / "templates"


def main() -> int:
    text = (TEMPLATES / "report.txt").read_text().format(name="gauntlet")
    assert text.strip() == "Report for gauntlet", text
    assert os.path.isdir(TEMPLATES), "templates directory is not a real directory"

    tz = pytz.timezone("America/New_York")
    stamp = tz.localize(datetime(2026, 1, 15, 12, 0))
    assert stamp.utcoffset().total_seconds() == -5 * 3600
    print("GAUNTLET OK 05-dunder-file-data")
    return 0
