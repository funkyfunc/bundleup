"""A lock made against another index (a company's Artifactory, say) is bundled from that index,
with the locked files: bundleup used to export bare `name==version` pins and install them from
the default index, so a private package wasn't found, and a same-named one on PyPI would have
been bundled instead (dependency confusion)."""

from __future__ import annotations

import base64
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

from bundleup import BuildOptions, build

FILES = {
    "acme_private/__init__.py": 'WHO = "the company index"\n',
    "acme_private-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: acme-private\n"
    "Version: 1.0\n",
    "acme_private-1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\n"
    "Root-Is-Purelib: true\nTag: py3-none-any\n",
}


def wheel(index: Path) -> None:
    """A tiny wheel, written by hand so the test needs no build backend or network."""
    index.mkdir()
    record = []
    with zipfile.ZipFile(index / "acme_private-1.0-py3-none-any.whl", "w") as zf:
        for name, text in FILES.items():
            data = text.encode()
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
            record.append(f"{name},sha256={digest.decode()},{len(data)}")
            zf.writestr(name, data)
        record.append("acme_private-1.0.dist-info/RECORD,,")
        zf.writestr("acme_private-1.0.dist-info/RECORD", "\n".join(record) + "\n")


def test_a_package_from_a_private_index_is_bundled_from_it(tmp_path: Path) -> None:
    wheel(tmp_path / "index")
    script = tmp_path / "tool.py"
    script.write_text(f"""\
# /// script
# requires-python = ">=3.9"
# dependencies = ["acme-private"]
# [[tool.uv.index]]
# name = "corp"
# url = "{(tmp_path / "index").as_posix()}"
# format = "flat"
# explicit = true
# [tool.uv.sources]
# acme-private = {{ index = "corp" }}
# ///
import acme_private
print("from", acme_private.WHO)
""")
    locked = subprocess.run(
        ["uv", "lock", "--script", str(script)], capture_output=True, text=True, cwd=tmp_path
    )
    assert locked.returncode == 0, locked.stderr
    result = build(BuildOptions(path=script, output=tmp_path / "tool.pyz"))
    done = subprocess.run(
        [sys.executable, str(result.output)], capture_output=True, text=True, cwd=tmp_path
    )
    assert done.stdout.strip() == "from the company index", done.stderr
