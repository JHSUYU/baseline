#!/usr/bin/env python3
"""Recompute HDFS-07 verdicts from every original-JUnit event stream."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "evidence/campaign-state.json"
OUT = HERE / "evidence/audit-result.json"
SELECTOR = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal", "faultType")


def selected(event: dict) -> bool:
    return (event.get("siteId") == "Journal.acceptRecovery#L924-933"
            and event.get("journalId") == "test-journal"
            and event.get("journalNode") == "journalnode-2"
            and event.get("epoch", -1) >= 3)


def main() -> None:
    state = json.loads(STATE.read_text())
    reports = []
    for identity, trial in state["completed"].items():
        manifest = json.loads(Path(trial["manifest"]).read_text())
        events = [json.loads(line) for line in Path(trial["trace"]).read_text().splitlines() if line]
        matched = [event for event in events if event["event"] == "FAULT_MATCHED"]
        applied = [event for event in events if event["event"] == "FAULT_APPLIED"]
        sequence = trial["sequence"]
        exact = len(matched) == len(applied) == len(sequence) and all(
            all(applied[index].get(key) == fault[key] for key in SELECTOR)
            for index, fault in enumerate(sequence))
        assert exact == trial["exact_order_applied"], identity
        last = applied[-1]["seq"] if exact else None
        checks = [event for event in events if event["event"] == "TARGET_CHECK"
                  and selected(event) and event.get("newStart") == 1
                  and event.get("newEnd") == 4 and last is not None and event["seq"] > last]
        throws = [event for event in events if event["event"] == "TARGET_THROW"
                  and selected(event) and event.get("exception") == "java.lang.AssertionError"
                  and last is not None and event["seq"] > last]
        valid = exact and bool(checks)
        assert valid == trial["valid_for_feedback"], identity
        assert bool(checks) == trial["target_after_fault"], identity
        assert len(throws) == trial["target_exception_after_fault"], identity
        assert manifest["elapsed_seconds"] == trial["elapsed_seconds"], identity
        assert manifest["returncode"] == trial["junit_exit"], identity
        reports.append({"id": identity, "exact": exact, "target_after_fault": valid,
                        "target_throws": len(throws), "junit_exit": manifest["returncode"],
                        "elapsed_seconds": manifest["elapsed_seconds"],
                        "requested_faults": len(sequence), "applied_faults": len(applied)})
    summary = {"case_id": "HDFS-07", "completed": len(reports),
               "strict": sum(report["exact"] for report in reports),
               "target_retaining": sum(report["target_after_fault"] for report in reports),
               "target_throw_events": sum(report["target_throws"] for report in reports),
               "max_faults": max((report["requested_faults"] for report in reports), default=0),
               "elapsed_seconds": round(state["healthy"]["elapsed_seconds"]
                                        + sum(report["elapsed_seconds"] for report in reports), 3),
               "trials": reports}
    temporary = OUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    temporary.replace(OUT)
    print({key: value for key, value in summary.items() if key != "trials"})


if __name__ == "__main__":
    main()
