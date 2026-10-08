"""A lock made against another index (a company's Artifactory, say) is bundled from that index,
with the locked files: bundleup used to export bare `name==version` pins and install them from
the default index, so a private package wasn't found, and a same-named one on PyPI would have
been bundled instead (dependency confusion)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bundleup import BuildOptions, build


def test_a_package_from_a_private_index_is_bundled_from_it(
    tmp_path: Path, private_index: str
) -> None:
    script = tmp_path / "tool.py"
    script.write_text(private_index + 'import acme_private\nprint("from", acme_private.WHO)\n')
    locked = subprocess.run(
        ["uv", "lock", "--script", str(script)], capture_output=True, text=True, cwd=tmp_path
    )
    assert locked.returncode == 0, locked.stderr
    result = build(BuildOptions(path=script, output=tmp_path / "tool.pyz"))
    done = subprocess.run(
        [sys.executable, str(result.output)], capture_output=True, text=True, cwd=tmp_path
    )
    assert done.stdout.strip() == "from the company index", done.stderr
