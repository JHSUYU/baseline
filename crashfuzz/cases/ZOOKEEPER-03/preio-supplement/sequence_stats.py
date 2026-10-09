#!/usr/bin/env python3
"""Count exact applied plans separately from postfault target retention."""

from __future__ import annotations

import json
import os
from pathlib import Path

from receipt_validator import ReceiptError, fault_selector, parse_events


ASSETS = Path(os.environ.get("ZK03_SUPPLEMENT_ASSETS",
                             "/users/ZhenyuLi/zk03-supplement-assets"))
ROOT = Path(os.environ.get("ZK03_SUPPLEMENT_RUN_ROOT",
                           "/users/ZhenyuLi/zk03-supplement-runs"))


def main():
    manifest = json.loads((ASSETS / "plan-manifest.json").read_text())
    jobs = {x["supplement_id"]: x for x in manifest["jobs"]}
    state = json.loads((ROOT / "supplement-checkpoint.json").read_text())
    result = []
    for row in state["results"]:
        job = jobs[row["supplement_id"]]
        run = ROOT / row["run_id"]
        receipt = json.loads((run / "run.json").read_text())
        events = parse_events(run / "events.tsv")
        matched = [(seq, fields) for seq, kind, fields in events
                   if kind == "FAULT_MATCHED"]
        applied = [(seq, fields) for seq, kind, fields in events
                   if kind == "FAULT_APPLIED"]
        try:
            exact = ([fault_selector(fields) for _, fields in matched] ==
                     job["plan"] ==
                     [fault_selector(fields) for _, fields in applied] and
                     all(m[0] < a[0] for m, a in zip(matched, applied)))
        except ReceiptError:
            exact = False
        last = applied[-1][0] if applied else 0
        later_target_guards = sum(1 for seq, kind, fields in events
                                  if seq > last and kind == "TARGET_GUARD"
                                  and fields and fields[0] == manifest["target"])
        if row["effective"] and not exact:
            raise RuntimeError("effective row lacks fully applied plan")
        if row["plan"] != job["plan"] or receipt["plan"] != job["plan"]:
            raise RuntimeError("reported plan differs from fixed queue")
        result.append({"run_id": row["run_id"],
                       "supplement_id": row["supplement_id"],
                       "fault_count": len(job["plan"]),
                       "matched_events": len(matched),
                       "applied_events": len(applied),
                       "fully_applied": exact,
                       "same_actor_target_after_fault": row["effective"],
                       "any_target_guards_after_final_fault": later_target_guards,
                       "selected_target_throws": row["selected_target_throws"],
                       "junit_exit": receipt["exit_code"],
                       "elapsed_seconds": receipt["elapsed_seconds"],
                       "new_coverage_lines": row["new_coverage_lines"],
                       "new_io_families": row["new_io_families"]})
    summary = {"case_id": "ZOOKEEPER-03", "status": state["status"],
               "selected": len(result), "pending": len(state["pending_ids"]),
               "fully_applied": sum(x["fully_applied"] for x in result),
               "effective": sum(x["same_actor_target_after_fault"]
                                for x in result),
               "selected_target_throws": sum(x["selected_target_throws"]
                                             for x in result),
               "sum_elapsed_seconds": round(sum(x["elapsed_seconds"]
                                                for x in result), 3),
               "new_coverage_lines": sum(x["new_coverage_lines"]
                                         for x in result),
               "new_io_families": sum(x["new_io_families"]
                                      for x in result),
               "trials": result}
    target = ROOT / "sequence-stats.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, target)
    print(json.dumps({k: summary[k] for k in
                      ("status", "selected", "pending", "fully_applied",
                       "effective", "selected_target_throws",
                       "sum_elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
