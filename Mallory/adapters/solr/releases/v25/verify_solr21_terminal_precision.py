#!/usr/bin/env python3
"""Summarize SHA-bound same-occurrence postfault checks for SOLR-21."""

import hashlib
import json
from pathlib import Path
import sys


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    campaign = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if (result.get("case_id") != "SOLR-21" or result.get("status") != "budget_exhausted"
            or result.get("fault_trials_completed") != 80
            or audit.get("report_gate_passed") is not True
            or audit.get("campaign_result_sha256") != digest(result_path)
            or audit.get("allow_local_timeline_doors") is not True
            or audit.get("local_timeline_only") is not True
            or audit.get("unknown_applied_faults") != 0):
        raise ValueError("SOLR-21 terminal result or causal audit is not valid")
    checks = set(result["target"]["check_sites"]) if "target" in result else None
    witnesses = []
    retained = 0
    for trial in audit["trials"]:
        if trial.get("target_retained"):
            retained += 1
        if not trial.get("same_actor_target_after_fault"):
            continue
        rows = trial.get("same_actor_target_followups") or []
        if not trial.get("target_retained") or not rows:
            raise ValueError("same-actor claim has no retained target evidence")
        valid = []
        for row in rows:
            if (not isinstance(row.get("fault_seq"), int)
                    or not isinstance(row.get("target_check_seq"), int)
                    or row["fault_seq"] >= row["target_check_seq"]
                    or row.get("node") in (None, "unknown")
                    or row.get("epoch") is None
                    or not row.get("occurrence")
                    or (checks is not None and row.get("target_check_site") not in checks)):
                raise ValueError("postfault target witness is incomplete")
            valid.append(row)
        witnesses.append({"trial_id": trial["trial_id"], "witnesses": valid})
    if (retained != audit.get("target_retained_fault_trials")
            or len(witnesses) != audit.get("same_actor_target_trials")
            or not witnesses):
        raise ValueError("terminal precision totals differ from frozen audit")
    report = {"schema_version": 1, "case_id": "SOLR-21",
              "evidence_kind": "observed_local_timeline_same_actor_same_occurrence",
              "campaign_result_sha256": digest(result_path),
              "offline_causal_audit_sha256": digest(audit_path),
              "fault_trials_completed": result["fault_trials_completed"],
              "duration_seconds": result["duration_seconds"],
              "named_applied_faults": audit["named_applied_faults"],
              "target_retained_fault_trials": retained,
              "same_actor_same_occurrence_target_trials": len(witnesses),
              "target_exception_candidates": sum(bool(row.get("target_exception_candidate"))
                                                 for row in result["trials"]),
              "witnesses": witnesses}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"path": str(destination), "sha256": digest(destination),
                      "same_actor_trials": len(witnesses), "retained": retained},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
