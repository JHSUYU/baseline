#!/usr/bin/env python3
"""Reconcile phase-1/phase-2 production coverage without rerunning JUnits."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import run_campaign as campaign

CASE = Path(__file__).resolve().parents[1]
REPORT = CASE / "campaign/feedback-recompute.json"


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    rows = state["completed"]
    healthy_paths = [campaign.FIRST_HEALTHY, campaign.HEALTHY]
    union_coverage = set().union(*(
        campaign.coverage_ids(path / "coverage.tsv") for path in healthy_paths))
    healthy_events = [event for path in healthy_paths
                      for event in campaign.events(
                          path / "trace/runtime_trace.jsonl")
                      if campaign.relevant(event)]
    union_io = {campaign.point_id(event) for event in healthy_events}
    union_families = {campaign.family_id(event) for event in healthy_events}
    changes = []
    for row in rows:
        before = {key: row[key] for key in (
            "new_coverage_count", "new_io_point_ids", "new_io_family_ids")}
        admitted = row["strict_injection"] and row["target_guard_after_last_fault"]
        ids = campaign.coverage_ids(Path(row["coverage"]))
        events = [event for event in campaign.events(Path(row["trace"]))
                  if campaign.relevant(event)]
        io_ids = {campaign.point_id(event) for event in events}
        family_ids = {campaign.family_id(event) for event in events}
        new_cov = ids - union_coverage if admitted else set()
        new_io = io_ids - union_io if admitted else set()
        new_families = family_ids - union_families if admitted else set()
        row["new_coverage_ids"] = sorted(new_cov)
        row["new_coverage_count"] = len(new_cov)
        row["new_io_point_ids"] = sorted(new_io)
        row["new_io_family_ids"] = sorted(new_families)
        row["observed_io_points"] = len(events)
        campaign.atomic_json(CASE / "campaign" / row["trial"] /
                             "trial-result.json", row)
        if admitted:
            union_coverage.update(new_cov)
            union_io.update(new_io)
            union_families.update(new_families)
        after = {key: row[key] for key in before}
        if before != after:
            changes.append({"trial": row["trial"], "before": before,
                            "after": after})
    campaign.persist(state)
    report = {"case_id": "HDFS-39", "completed_trials": len(rows),
              "reason": "use union of both healthy HDFS production coverage and observed I/O baselines after adding a pre-send IPC probe",
              "raw_junit_trials_rerun": 0, "changed_rows": changes,
              "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    campaign.atomic_json(REPORT, report)
    print(json.dumps({"completed": len(rows), "changed": len(changes),
                      "report": str(REPORT)}))


if __name__ == "__main__":
    main()
