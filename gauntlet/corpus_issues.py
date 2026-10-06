"""Group nightly corpus failures by signature into GitHub issues labelled `corpus-failure`.

One issue per signature (program + failing phase + code), so forty runs failing for one reason are
one issue. An existing open issue with the same signature is updated with the latest
reproductions; nothing is closed automatically. Run by .github/workflows/corpus.yml (ADR-0017).

Usage:
    uv run gauntlet/corpus_issues.py results/*/corpus.json --repo owner/name [--dry-run]
"""

# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

LABEL = "corpus-failure"
MARKER = "<!-- corpus-signature: {} -->"
Row = dict[str, Any]  # one CorpusResult from corpus.py, as JSON; Any: mixed value types


def signature(row: Row) -> str:
    return f"{row['name']} {row['phase']} {row['code']}"


def group_failures(rows: list[Row]) -> dict[str, list[Row]]:
    groups: dict[str, list[Row]] = {}
    for row in rows:
        if row["outcome"] in ("fail", "harness-error"):
            groups.setdefault(signature(row), []).append(row)
    return groups


def title(rows: list[Row]) -> str:
    first = rows[0]
    return f"corpus: {first['name']} fails at {first['phase'] or 'harness'} ({first['code']})"


def body(sig: str, rows: list[Row], run_url: str) -> str:
    first = rows[0]
    lines = [
        MARKER.format(sig),
        f"**{first['name']}** ({first['kind']}, `{first['pin']}`) fails at the "
        f"**{first['phase'] or 'harness'}** step with `{first['code']}`.",
        f"Last seen {date.today().isoformat()} in [the nightly corpus run]({run_url}).",
        "",
        "| OS | Python | Network blocked | Detail |",
        "|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: (r["os"], r["python"])):
        detail = row["detail"].replace("\n", " ").replace("|", "\\|")[:500]
        lines.append(f"| {row['os']} | {row['python']} | {row['network_blocked']} | {detail} |")
    lines += [
        "",
        "Reproduce on a CI runner (third-party code: never on a personal machine, ADR-0017):",
        f"`uv run gauntlet/corpus.py {first['name']} --python {first['python']}`",
        "",
        "Triage: a bundleup bug becomes a new gauntlet project plus a fix; a bad refusal "
        "message, a project problem or flakiness gets a comment and is closed by the owner. "
        "Updated by the nightly run; never closed automatically.",
    ]
    return "\n".join(lines) + "\n"


def gh(args: list[str], *, dry_run: bool) -> str:
    if dry_run:
        print("would run: gh " + " ".join(a if " " not in a else repr(a) for a in args[:6]))
        return ""
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def open_issues(repo: str) -> dict[str, int]:
    """Signature -> issue number for open corpus-failure issues."""
    listed = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--label", LABEL, "--state", "open",
         "--limit", "500", "--json", "number,body"],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    prefix, suffix = MARKER.split("{}")
    found = {}
    for issue in json.loads(listed):
        for line in issue["body"].splitlines():
            if line.startswith(prefix) and line.endswith(suffix):
                found[line[len(prefix) : -len(suffix)]] = issue["number"]
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path, help="corpus.py JSON files")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--run-url", default="", help="link to the workflow run")
    parser.add_argument("--dry-run", action="store_true", help="print, don't touch GitHub")
    opts = parser.parse_args()

    rows = [row for path in opts.results for row in json.loads(path.read_text())]
    groups = group_failures(rows)
    print(f"{len(rows)} results, {len(groups)} failure signature(s)")
    if not groups:
        return 0
    description = "A real program that fails when bundled (nightly corpus run)"
    label = ["label", "create", LABEL, "--repo", opts.repo, "--force", "--color", "B60205",
             "--description", description]  # fmt: skip
    gh(label, dry_run=opts.dry_run)
    existing = {} if opts.dry_run else open_issues(opts.repo)
    for sig, failed in sorted(groups.items()):
        text = body(sig, failed, opts.run_url)
        if sig in existing:
            gh(["issue", "edit", str(existing[sig]), "--repo", opts.repo, "--body", text],
               dry_run=opts.dry_run)  # fmt: skip
            print(f"updated #{existing[sig]}: {sig}")
        else:
            create = ["issue", "create", "--repo", opts.repo, "--title", title(failed),
                      "--label", LABEL, "--body", text]  # fmt: skip
            print(gh(create, dry_run=opts.dry_run).strip() or f"would create: {title(failed)}")
            if opts.dry_run:
                print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
