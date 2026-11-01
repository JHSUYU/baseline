#!/usr/bin/env python3
"""Write a finished case's B6 step 5 fields into <system>/inventory.tsv (B6 step 5).

Usage: record.py <system> <case> [<bugs>]
Fields: specula_verdict, run, wall, runtime, usage_waits, tokens, cost, phases, model, cli, bugs.
"""
import csv, json, subprocess, sys
from pathlib import Path

ROOT = Path("/bulk/specula-adhoc")
system, case = sys.argv[1], sys.argv[2]
bugs = sys.argv[3] if len(sys.argv) > 3 else None  # None keeps the recorded value
rows = json.loads(subprocess.run([sys.executable, str(ROOT / "summarize.py"), system], capture_output=True,
                                 text=True, check=True).stdout)
r = next(x for x in rows if x["case"] == case)
fields = {"specula_verdict": f"{r['specula']} ({r['mechanism']}, {r['finding'] or '-'})", "run": r["run"],
          "wall": r["wall"], "runtime": r["runtime"], "usage_waits": f"{r['waits']} ({r['wait_time']})", "tokens": r["tokens"],
          "cost": r["cost"], "phases": r["phases"], "model": r["model"], "cli": r["cli"], "bugs": bugs}
path = ROOT / system / "inventory.tsv"
with open(path, newline="") as f:
    data = list(csv.DictReader(f, delimiter="\t"))
cols = list(data[0].keys())
cols += [c for c in fields if c not in cols]
for row in data:
    if row["case"] == case:
        if bugs is None:
            fields["bugs"] = row.get("bugs", "")
        row.update(fields)
with open(path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", lineterminator="\n", restval="")
    w.writeheader()
    w.writerows(data)
print("\n".join(f"{k}: {v}" for k, v in fields.items()))
