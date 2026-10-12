#!/usr/bin/env python3
"""Build a lossless 102-check selective-revisit ledger from current evidence."""

from __future__ import annotations

import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MALLORY = ROOT / "data/mallory/checklist102.json"
CRASHFUZZ = ROOT / "data/crashfuzz/checklist102.json"
DECISIONS = Path(__file__).with_name("revisit_decisions.json")
OUT = ROOT / "data/mallory/revisit"


def build() -> dict:
    mallory = json.loads(MALLORY.read_text())
    crashfuzz = json.loads(CRASHFUZZ.read_text())
    decisions = json.loads(DECISIONS.read_text())["decisions"]
    prior = {row["case_id"]: row for row in crashfuzz["rows"]
             if row.get("selection_group") != "added_known_issue"}
    rows = []
    for case in mallory["rows"]:
        case_id = case["case_id"]
        historical = prior.get(case_id)
        if historical is None:
            raise ValueError(f"missing original CrashFuzz row: {case_id}")
        reviewed = decisions.get(case_id)
        if reviewed:
            decision = reviewed["decision"]
            reason = reviewed["reason"]
            evidence = reviewed["evidence"]
            if not (ROOT / evidence).exists():
                raise ValueError(f"missing decision evidence for {case_id}: {evidence}")
        elif case["report_status"] in ("source_review_no_suitable_test",
                                       "no_mapped_cluster_test"):
            decision = "workload_gap"
            reason = "Current source/test inventory has no suitable mapped cluster workload."
            evidence = case.get("source_review_receipt") or case.get("source_gap_receipt")
        else:
            decision = "pending_source_review"
            reason = "No case-specific potential decision recorded yet."
            evidence = None
        rows.append({
            "case_id": case_id,
            "system": case["system"],
            "source_path": case["source_path"],
            "source_line": case["source_line"],
            "function": case["function"],
            "check_code": case["check_code"],
            "cluster_test": case["cluster_test"],
            "mallory_report_status": case["report_status"],
            "mallory_quality_status": case["quality_status"],
            "mallory_strict_target_trials": case.get("strict_target_trials"),
            "mallory_exact_exception_trials": case.get("exact_exception_trials"),
            "mallory_duration_seconds": case.get("duration_seconds"),
            "crashfuzz_status": historical.get("status"),
            "crashfuzz_bug_mark": historical.get("bug_mark"),
            "crashfuzz_elapsed_seconds": historical.get("elapsed_seconds"),
            "decision": decision,
            "reason": reason,
            "decision_evidence": evidence,
        })
    if len(rows) != 102 or len({row["case_id"] for row in rows}) != 102:
        raise ValueError("revisit ledger must contain exactly the original 102 checks")
    if set(decisions) - {row["case_id"] for row in rows}:
        raise ValueError("decision references a nonoriginal case")
    return {"schema_version": 1, "scope": "original_102", "count": len(rows),
            "decision_counts": dict(sorted(collections.Counter(row["decision"] for row in rows).items())),
            "rows": rows}


def render(report: dict) -> str:
    lines = ["# Selective revisit of the original 102 ad hoc checks", "",
             "This ledger joins the existing CrashFuzz and Mallory results with a source-specific",
             "rerun decision for every original check. Target exceptions alone are not confirmed new bugs.", "",
             "Decision counts: " + ", ".join(f"{key}={value}" for key, value in report["decision_counts"].items()),
             "", "| Check | System | Source location | Function / check | Prior CrashFuzz s | Prior Mallory s | Mallory target / exact throws | Revisit decision | Reason |",
             "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |"]
    for row in report["rows"]:
        source = f"{row['source_path']}:{row['source_line']}"
        observed = f"{row['mallory_strict_target_trials'] or 0} / {row['mallory_exact_exception_trials'] or 0}"
        reason = row["reason"].replace("|", "\\|")
        check = str(row["check_code"]).replace("|", "\\|").replace("\n", "<br>")
        function = str(row["function"]).replace("|", "\\|")
        crashfuzz_s = row["crashfuzz_elapsed_seconds"]
        mallory_s = row["mallory_duration_seconds"]
        lines.append(f"| {row['case_id']} | {row['system']} | {source} | `{function}`<br>`{check}` | "
                     f"{crashfuzz_s if crashfuzz_s is not None else '—'} | "
                     f"{mallory_s if mallory_s is not None else '—'} | {observed} | "
                     f"{row['decision']} | {reason} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    result = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "triage102.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (OUT / "triage102.md").write_text(render(result))
    print(json.dumps(result["decision_counts"], sort_keys=True))
