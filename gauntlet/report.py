"""Turn a run_bundlers.py results file into a markdown summary.

Usage:
    uv run gauntlet/report.py gauntlet/results/baseline-2026-10-03.json > gauntlet/results/baseline-2026-10-03.md
"""

# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict

SYMBOL = {"pass": "✅", "run-fail": "❌", "build-fail": "🔨", "refused": "🛑", "late-fail": "💥", "skipped": "·",
          "harness-error": "⚠️"}


def mb(n):
    return f"{n / 1_000_000:.1f}" if n else "–"


def main(path: str) -> None:
    rows = json.load(open(path))
    base = [r for r in rows if r["condition"] == "base"]
    tools = sorted({r["tool"] for r in rows}, key=["pex", "shiv", "zipapps", "zipapp-naive"].index)
    pythons = sorted({r["python"] for r in rows}, key=lambda v: tuple(map(int, v.split("."))))
    projects = sorted({r["project"] for r in rows})

    print(f"# Gauntlet results: `{path.rsplit('/', 1)[-1]}`\n")
    print("Legend: ✅ pass · ❌ built but failed at run time · 🔨 build failed · "
          "🛑 refused at build time (expected) · 💥 built, then failed on the user's machine where it should "
          "have been refused · `·` not applicable\n")

    print("## Base run (network blocked, fresh HOME, empty working directory)\n")
    head = ["Project"] + [f"{t} {p}" for t in tools for p in pythons]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    idx = {(r["project"], r["tool"], r["python"]): r for r in base}
    for proj in projects:
        cells = []
        for t in tools:
            for p in pythons:
                r = idx.get((proj, t, p))
                cells.append(SYMBOL.get(r["outcome"], "?") + (f" {r['error_kind']}" if r and r["error_kind"] and r["outcome"] != "pass" else "") if r else "")
        print(f"| `{proj}` | " + " | ".join(cells) + " |")

    print("\n## Totals (base run, applicable cases)\n")
    print("| Tool | Pass | Run-time failure | Build failure | Correct refusal | Late failure |")
    print("|---|---|---|---|---|---|")
    for t in tools:
        c = defaultdict(int)
        for r in base:
            if r["tool"] == t:
                c[r["outcome"]] += 1
        print(f"| {t} | {c['pass']} | {c['run-fail']} | {c['build-fail']} | {c['refused']} | {c['late-fail']} |")

    print("\n## Speed and size (median over passing base runs)\n")
    print("| Tool | Python | Build (s) | Size (MB) | First run (s) | Warm run (s) |")
    print("|---|---|---|---|---|---|")
    for t in tools:
        for p in pythons:
            ok = [r for r in base if r["tool"] == t and r["python"] == p and r["outcome"] == "pass"]
            if not ok:
                continue
            med = lambda k: statistics.median(r[k] for r in ok if r[k] is not None)
            print(f"| {t} | {p} | {med('build_s'):.1f} | {statistics.median(r['size_bytes'] for r in ok) / 1e6:.1f} "
                  f"| {med('cold_s'):.2f} | {med('warm_s'):.2f} |")

    hostile = [r for r in rows if r["condition"] != "base"]
    if hostile:
        print("\n## Hostile conditions (re-run of bundles that passed the base run)\n")
        conds = sorted({r["condition"] for r in hostile})
        print("| Tool | Python | " + " | ".join(conds) + " |")
        print("|---|---|" + "---|" * len(conds))
        for t in tools:
            for p in pythons:
                cells = []
                for cond in conds:
                    rs = [r for r in hostile if r["tool"] == t and r["python"] == p and r["condition"] == cond]
                    if not rs:
                        cells.append("–")
                        continue
                    passed = sum(r["outcome"] == "pass" for r in rs)
                    cells.append(f"{passed}/{len(rs)}")
                print(f"| {t} | {p} | " + " | ".join(cells) + " |")

    print("\n## Failure details\n")
    for r in sorted(rows, key=lambda r: (r["project"], r["tool"], r["python"], r["condition"])):
        if r["outcome"] in ("pass", "skipped"):
            continue
        detail = "\n".join(r["detail"].strip().splitlines()[-6:])
        print(f"<details><summary><code>{r['project']}</code> · {r['tool']} · py{r['python']} · {r['condition']} · "
              f"{r['outcome']} ({r['error_kind']})</summary>\n\n```\n{detail}\n```\n</details>\n")

    extras = [r for r in base if r["extra"]]
    if extras:
        print("## Reported by the projects\n")
        for r in extras:
            print(f"- `{r['project']}` · {r['tool']} · py{r['python']}: {', '.join(r['extra'])}")


if __name__ == "__main__":
    main(sys.argv[1])
