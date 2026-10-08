"""A script that runs another of the skill's scripts with sys.executable (ADR-0040)."""

import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.exit(subprocess.call([sys.executable, os.path.join(here, "make_deck.py"), "from-sibling"]))
