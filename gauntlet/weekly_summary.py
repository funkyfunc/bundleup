"""Weekly summary of the nightly runs (roadmap item 6, step 7): what passed and failed, by night and
OS, from the results each run attached on GitHub. Writes a findings page, so the nightly runs leave
a record in the repo after GitHub deletes their artifacts (90 days).

Usage:
    uv run gauntlet/weekly_summary.py --repo funkyfunc/bundleup \
        --out docs/findings/<date>-nightly-summary.md
"""

# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

Row = dict[str, Any]  # one result from smoke.py or corpus.py, as JSON; Any: mixed value types
WORKFLOWS = {"smoke": "nightly.yml", "corpus": "corpus.yml"}
PASSING = ("pass", "skipped")


@dataclass
class Night:
    """One run of one workflow: when it started, its link, and results by OS."""

    created: datetime
    url: str
    results: dict[str, list[Row]]  # OS -> rows

    @property
    def date(self) -> str:
        return self.created.strftime("%Y-%m-%d %H:%M")


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def nights(repo: str, workflow: str, since: datetime, kind: str) -> list[Night]:
    fields = "databaseId,createdAt,status,url"
    listed = json.loads(gh("run", "list", "--repo", repo, "--workflow", workflow, "--json", fields))
    found = []
    for run in listed:
        created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
        if created < since or run["status"] != "completed":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = subprocess.run(
                ["gh", "run", "download", str(run["databaseId"]), "--repo", repo, "-D", tmp],
                capture_output=True,
                text=True,
            )
            results: dict[str, list[Row]] = {}
            if downloaded.returncode == 0:
                for path in sorted(Path(tmp).glob(f"{kind}-*/{kind}.json")):
                    results[path.parent.name.removeprefix(f"{kind}-")] = json.loads(
                        path.read_text()
                    )
        found.append(Night(created, run["url"], results))
    return sorted(found, key=lambda n: n.created)


def section(title: str, kind: str, runs: list[Night], name_key: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not runs:
        return [*lines, "No runs this week.", ""]
    lines += ["| Night | OS | Pass | Skipped | Failed |", "|---|---|---|---|---|"]
    failures: dict[tuple[str, str], list[str]] = defaultdict(list)
    last_detail: dict[tuple[str, str], str] = {}
    for night in runs:
        if not night.results:
            lines.append(f"| [{night.date}]({night.url}) | (no results attached) | | | |")
        for os_name, rows in sorted(night.results.items()):
            counts = Counter("pass" if r["outcome"] == "pass" else r["outcome"] for r in rows)
            failed = sum(n for outcome, n in counts.items() if outcome not in PASSING)
            lines.append(
                f"| [{night.date}]({night.url}) | {os_name} | {counts['pass']} | "
                f"{counts['skipped']} | {failed} |"
            )
            for r in rows:
                if r["outcome"] not in PASSING:
                    key = (r[name_key], os_name)
                    failures[key].append(night.date)
                    last_detail[key] = (
                        r.get("detail", "")[:200].replace("\n", " ").replace("|", "\\|")
                    )
    lines.append("")
    if failures:
        last = runs[-1]
        lines += [f"Failures ({kind}):", "", "| Name | OS | Nights failed | Last night | Detail |"]
        lines.append("|---|---|---|---|---|")
        for (name, os_name), dates in sorted(failures.items()):
            detail = last_detail[(name, os_name)]
            rows = last.results.get(os_name, [])
            now = next((r["outcome"] for r in rows if r[name_key] == name), "not run")
            lines.append(
                f"| {name} | {os_name} | {len(dates)} ({', '.join(dates)}) | {now} | {detail} |"
            )
    else:
        lines.append(f"No {kind} failures this week.")
    return [*lines, ""]


def open_issues(repo: str) -> list[str]:
    query = ["--label", "corpus-failure", "--state", "open", "--json", "number,title,url"]
    listed = json.loads(gh("issue", "list", "--repo", repo, *query))
    return [f"- [#{i['number']}]({i['url']}) {i['title']}" for i in listed]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    opts = parser.parse_args()
    end = datetime.now(timezone.utc)  # noqa: UP017 (pyright checks as 3.9, which has no UTC)
    since = end - timedelta(days=opts.days)
    smoke = nights(opts.repo, WORKFLOWS["smoke"], since, "smoke")
    corpus = nights(opts.repo, WORKFLOWS["corpus"], since, "corpus")
    issues = open_issues(opts.repo)
    lines = [
        f"# Nightly runs: {since.date().isoformat()} to {end.date().isoformat()}",
        "",
        "Written by the weekly job ([`weekly.yml`](../../.github/workflows/weekly.yml) running "
        "[`weekly_summary.py`](../../gauntlet/weekly_summary.py)) from the results each nightly "
        "run attached on GitHub. Add a line of analysis when merging if anything changed.",
        "",
        *section("Smoke test (most-downloaded PyPI packages)", "smoke", smoke, "package"),
        *section("Corpus (real programs, installed vs bundled)", "corpus", corpus, "name"),
        "## Open `corpus-failure` issues",
        "",
        *(issues or ["None."]),
        "",
    ]
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text("\n".join(lines))
    print(f"wrote {opts.out}: {len(smoke)} smoke and {len(corpus)} corpus runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
