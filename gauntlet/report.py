"""Turn a run_bundlers.py results file into a markdown summary.

Usage:
    uv run gauntlet/report.py gauntlet/results/<name>.json > gauntlet/results/<name>.md
"""

# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

Row = dict[str, Any]  # one Result from run_bundlers.py, as JSON; Any: mixed value types

SYMBOL = {
    "pass": "✅",
    "run-fail": "❌",
    "build-fail": "🔨",
    "refused": "🛑",
    "late-fail": "💥",
    "skipped": "·",
    "harness-error": "⚠️",
}
TOOL_ORDER = ["bundleup", "bundleup-py", "pex", "shiv", "zipapps", "zipapp-naive"]
LEGEND = (
    "Legend: ✅ pass · ❌ built but failed at run time · 🔨 build failed · "
    "🛑 refused at build time (expected) · 💥 built, then failed on the user's machine where it "
    "should have been refused · `·` not applicable\n"
)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def outcome_cell(row: Row | None) -> str:
    if row is None:
        return ""
    cell = SYMBOL.get(row["outcome"], "?")
    if row["error_kind"] and row["outcome"] != "pass":
        cell += f" {row['error_kind']}"
    return cell


def base_table(base: list[Row], *, tools: list[str], pythons: list[str]) -> None:
    print("## Base run (network blocked, fresh HOME, empty working directory)\n")
    head = ["Project"] + [f"{t} {p}" for t in tools for p in pythons]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    by_key = {(r["project"], r["tool"], r["python"]): r for r in base}
    for project in sorted({r["project"] for r in base}):
        cells = [outcome_cell(by_key.get((project, t, p))) for t in tools for p in pythons]
        print(f"| `{project}` | " + " | ".join(cells) + " |")


def totals(base: list[Row], *, tools: list[str]) -> None:
    print("\n## Totals (base run, applicable cases)\n")
    print("| Tool | Pass | Run-time failure | Build failure | Correct refusal | Late failure |")
    print("|---|---|---|---|---|---|")
    for tool in tools:
        c = Counter(r["outcome"] for r in base if r["tool"] == tool)
        counts = [c["pass"], c["run-fail"], c["build-fail"], c["refused"], c["late-fail"]]
        print(f"| {tool} | " + " | ".join(str(n) for n in counts) + " |")


def median_of(rows: list[Row], key: str) -> float:
    return statistics.median(r[key] for r in rows if r[key] is not None)


def speed(base: list[Row], *, tools: list[str], pythons: list[str]) -> None:
    print("\n## Speed and size (median over passing base runs)\n")
    print("| Tool | Python | Build (s) | Size (MB) | First run (s) | Warm run (s) |")
    print("|---|---|---|---|---|---|")
    for tool in tools:
        for python in pythons:
            ok = [
                r
                for r in base
                if r["tool"] == tool and r["python"] == python and r["outcome"] == "pass"
            ]
            if not ok:
                continue
            size_mb = statistics.median(r["size_bytes"] for r in ok) / 1e6
            build, cold, warm = (median_of(ok, k) for k in ("build_s", "cold_s", "warm_s"))
            print(f"| {tool} | {python} | {build:.1f} | {size_mb:.1f} | {cold:.2f} | {warm:.2f} |")


def hostile_table(hostile: list[Row], *, tools: list[str], pythons: list[str]) -> None:
    print("\n## Hostile conditions (re-run of bundles that passed the base run)\n")
    conditions = sorted({r["condition"] for r in hostile})
    print("| Tool | Python | " + " | ".join(conditions) + " |")
    print("|---|---|" + "---|" * len(conditions))
    for tool in tools:
        for python in pythons:
            cells = []
            for condition in conditions:
                rs = [
                    r
                    for r in hostile
                    if r["tool"] == tool and r["python"] == python and r["condition"] == condition
                ]
                passed = sum(r["outcome"] == "pass" for r in rs)
                cells.append(f"{passed}/{len(rs)}" if rs else "–")
            print(f"| {tool} | {python} | " + " | ".join(cells) + " |")


def failure_details(rows: list[Row]) -> None:
    print("\n## Failure details\n")
    for r in sorted(rows, key=lambda r: (r["project"], r["tool"], r["python"], r["condition"])):
        if r["outcome"] in ("pass", "skipped"):
            continue
        detail = "\n".join(r["detail"].strip().splitlines()[-6:])
        where = f"<code>{r['project']}</code> · {r['tool']} · py{r['python']} · {r['condition']}"
        summary = f"{where} · {r['outcome']} ({r['error_kind']})"
        print(f"<details><summary>{summary}</summary>\n\n```\n{detail}\n```\n</details>\n")


def main(path: str) -> None:
    rows: list[Row] = json.loads(Path(path).read_text())
    base = [r for r in rows if r["condition"] == "base"]
    tools = sorted({r["tool"] for r in rows}, key=TOOL_ORDER.index)
    pythons = sorted({r["python"] for r in rows}, key=version_key)

    print(f"# Gauntlet results: `{path.rsplit('/', 1)[-1]}`\n")
    print(LEGEND)
    base_table(base, tools=tools, pythons=pythons)
    totals(base, tools=tools)
    speed(base, tools=tools, pythons=pythons)
    hostile = [r for r in rows if r["condition"] != "base"]
    if hostile:
        hostile_table(hostile, tools=tools, pythons=pythons)
    failure_details(rows)

    extras = [r for r in base if r["extra"]]
    if extras:
        print("## Reported by the projects\n")
        for r in extras:
            print(f"- `{r['project']}` · {r['tool']} · py{r['python']}: {', '.join(r['extra'])}")


if __name__ == "__main__":
    main(sys.argv[1])
