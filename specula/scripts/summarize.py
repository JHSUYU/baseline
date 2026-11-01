#!/usr/bin/env python3
"""Summarize a system's Specula ad hoc runs: verdict, time, tokens and cost per case.

Usage: summarize.py <system> [--markdown | --tsv]

For each row of <system>/inventory.tsv, reads the case's latest Specula run (the last
"Run:" line of <system>/logs/<case>.log), its .specula-output/adhoc-result.json and
run.json, and the "Resource usage" table of its summary.md.  Cost, runtime and tokens are
the table's Total row: Specula's own accounting, every agent session and retry included.
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc")
RUNS = Path("/users/ZhenyuLi/Specula/runs")
STAMP = "%Y-%m-%d %H:%M:%S"


def inventory(system: str) -> list[dict[str, str]]:
    with open(ROOT / system / "inventory.tsv", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def run_dir(log: str) -> Path | None:
    runs = re.findall(r"^Run:\s+(\S+)", log, re.M)
    return RUNS / runs[-1] if runs else None


def hms(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"


def resource_rows(summary: Path) -> dict[str, list[str]]:
    """Phase -> [runtime, tokens, cost] from summary.md's Resource usage table."""
    rows: dict[str, list[str]] = {}
    try:
        text = summary.read_text(errors="replace")
    except OSError:
        return rows
    section = text[text.find("## Resource usage") :] if "## Resource usage" in text else ""
    for line in section.splitlines()[1:]:
        if line.startswith("## "):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0] not in ("Phase", "---") and not cells[0].startswith("-"):
            rows[cells[0].replace("**", "")] = cells[1:]
    return rows


def row(system: str, inv: dict[str, str]) -> dict[str, str]:
    case = inv["case"]
    out = {"case": case, "status": inv.get("status", "")}
    log_path = ROOT / system / "logs" / f"{case}.log"
    if not log_path.is_file():
        return {**out, "specula": "not started"}
    log = log_path.read_text(errors="replace")
    rd = run_dir(log)
    if rd is None or not rd.is_dir():
        return {**out, "specula": "not started"}
    work = rd / case / ".specula-output"
    last_invocation = log[log.rfind("=== Pipeline invocation") :]
    finished = re.search(r"finished \(exit (\d+)\)", last_invocation)
    phase = re.findall(r"\] PHASE ([^\n]+)", log)
    result = work / "adhoc-result.json"
    verdict, mechanism, finding = "", "", ""
    if result.is_file():
        try:
            data = json.loads(result.read_text())
            verdict = str(data.get("verdict"))
            mechanism = str(data.get("mechanism") or "none")
            finding = str(data.get("finding") or "")
        except json.JSONDecodeError:
            verdict = "adhoc-result.json unreadable"
    else:
        verdict = "no result yet" if not finished else "no adhoc-result.json"
    starts = re.findall(r"started at (\S+ \S+) UTC", log)
    ends = re.findall(r"finished \(exit \d+\) at (\S+ \S+) UTC", log)
    wall = ""
    if starts and ends:
        wall = hms((datetime.strptime(ends[-1], STAMP) - datetime.strptime(starts[0], STAMP)).total_seconds())
    resources = resource_rows(work / "summary.md")
    total_key = next((k for k in resources if k.startswith("Total")), None)
    total = resources.get(total_key, ["", "", ""]) if total_key else ["", "", ""]
    try:
        run_json = json.loads((rd / "run.json").read_text())
    except (OSError, json.JSONDecodeError):
        run_json = {}
    cli = re.findall(r"^Claude Code CLI: ([^;\n]+)", log, re.M)
    phases = "; ".join(f"{k} {v[0]} {v[2]}" for k, v in resources.items() if k != total_key)
    return {
        **out,
        "specula": verdict,
        "mechanism": mechanism,
        "finding": finding,
        "state": f"exit {finished.group(1)}" if finished else f"running ({phase[-1] if phase else 'start'})",
        "run": rd.name,
        "wall": wall,
        "runtime": total[0] + (" (incomplete)" if total_key and "incomplete" in total_key else ""),
        # Every usage-limit wait (reactive or the proactive quota gate) logs one "Quota: ... sleeping Ns" line.
        "waits": str(len(re.findall(r"Quota: .*sleeping \d+s", log))),
        "wait_time": hms(sum(int(x) for x in re.findall(r"Quota: .*sleeping (\d+)s", log))),
        "tokens": total[1],
        "cost": total[2],
        "phases": phases,
        "model": str(run_json.get("model")),
        "effort": str(run_json.get("effort")),
        "cli": cli[-1].strip() if cli else "",
    }


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    system = args[0]
    rows = [row(system, inv) for inv in inventory(system)]
    cols = ["case", "specula", "mechanism", "finding", "state", "wall", "runtime",
            "waits", "wait_time", "tokens", "cost", "model", "cli", "run"]
    if "--markdown" in sys.argv:
        print("| " + " | ".join(cols) + " |")
        print("|" + "---|" * len(cols))
        for r in rows:
            print("| " + " | ".join(r.get(c, "") for c in cols) + " |")
    elif "--tsv" in sys.argv:
        cols.append("phases")
        print("\t".join(cols))
        for r in rows:
            print("\t".join(r.get(c, "") for c in cols))
    else:
        print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
