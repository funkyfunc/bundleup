"""Group nightly failures by signature into GitHub issues: `corpus-failure` for the corpus,
`smoke-failure` for the smoke test (`--kind smoke`; the 2026-10-07 review found a red smoke run
that nobody would have noticed).

One issue per signature (program + failing phase + code), so forty runs failing for one reason are
one issue. An existing open issue with the same signature is updated with the latest
reproductions; nothing is closed automatically. Run by corpus.yml and nightly.yml (ADR-0017).

Usage:
    uv run gauntlet/corpus_issues.py results/*/corpus.json --repo owner/name [--dry-run]
    uv run gauntlet/corpus_issues.py results/smoke-*/smoke.json --kind smoke --repo owner/name
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

LABELS = {"corpus": "corpus-failure", "smoke": "smoke-failure"}
DESCRIPTIONS = {
    "corpus": "A real program that fails when bundled (nightly corpus run)",
    "smoke": "A popular PyPI package that fails when bundled (nightly smoke test)",
}
MARKER = "<!-- corpus-signature: {} -->"
Row = dict[str, Any]  # one CorpusResult from corpus.py, as JSON; Any: mixed value types


def from_smoke(row: Row, os_name: str) -> Row:
    """A smoke.py result in the corpus's shape. Its file doesn't name the OS; the artifact's
    folder does (smoke-<os>/smoke.json)."""
    outcome = row["outcome"]
    return {
        "name": row["package"],
        "kind": "PyPI package",
        "pin": f"{row['package']}=={row.get('version')}",
        "phase": outcome.removesuffix("-fail"),
        "code": outcome,
        "outcome": outcome if outcome in ("pass", "skipped") else "fail",
        "os": os_name,
        "python": row["python"],
        "network_blocked": row.get("network_blocked"),
        "detail": row.get("detail", ""),
    }


def signature(row: Row) -> str:
    return f"{row['name']} {row['phase']} {row['code']}"


def group_failures(rows: list[Row]) -> dict[str, list[Row]]:
    groups: dict[str, list[Row]] = {}
    for row in rows:
        if row["outcome"] in ("fail", "harness-error"):
            groups.setdefault(signature(row), []).append(row)
    return groups


def title(rows: list[Row], kind: str = "corpus") -> str:
    first = rows[0]
    return f"{kind}: {first['name']} fails at {first['phase'] or 'harness'} ({first['code']})"


def body(sig: str, rows: list[Row], run_url: str, kind: str = "corpus") -> str:
    first = rows[0]
    lines = [
        MARKER.format(sig),
        f"**{first['name']}** ({first['kind']}, `{first['pin']}`) fails at the "
        f"**{first['phase'] or 'harness'}** step with `{first['code']}`.",
        f"Last seen {date.today().isoformat()} in [the nightly {kind} run]({run_url}).",
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
        f"`uv run gauntlet/{kind}.py {first['name']} --python {first['python']}`",
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


def open_issues(repo: str, label: str) -> dict[str, int]:
    """Signature -> issue number for open issues with this label."""
    listed = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--label", label, "--state", "open",
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
    parser.add_argument("results", nargs="+", type=Path, help="corpus.py or smoke.py JSON files")
    parser.add_argument("--kind", choices=sorted(LABELS), default="corpus")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--run-url", default="", help="link to the workflow run")
    parser.add_argument("--dry-run", action="store_true", help="print, don't touch GitHub")
    opts = parser.parse_args()

    rows = []
    for path in opts.results:
        found: list[Row] = json.loads(path.read_text())
        if opts.kind == "smoke":
            found = [from_smoke(row, path.parent.name.removeprefix("smoke-")) for row in found]
        rows += found
    label = LABELS[opts.kind]
    groups = group_failures(rows)
    print(f"{len(rows)} results, {len(groups)} failure signature(s)")
    if not groups:
        return 0
    create_label = ["label", "create", label, "--repo", opts.repo, "--force", "--color",
                    "B60205", "--description", DESCRIPTIONS[opts.kind]]  # fmt: skip
    gh(create_label, dry_run=opts.dry_run)
    existing = {} if opts.dry_run else open_issues(opts.repo, label)
    for sig, failed in sorted(groups.items()):
        text = body(sig, failed, opts.run_url, opts.kind)
        if sig in existing:
            gh(["issue", "edit", str(existing[sig]), "--repo", opts.repo, "--body", text],
               dry_run=opts.dry_run)  # fmt: skip
            print(f"updated #{existing[sig]}: {sig}")
        else:
            name = title(failed, opts.kind)
            create = ["issue", "create", "--repo", opts.repo, "--title", name,
                      "--label", label, "--body", text]  # fmt: skip
            print(gh(create, dry_run=opts.dry_run).strip() or f"would create: {name}")
            if opts.dry_run:
                print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
