#!/usr/bin/env python3
"""Record a natural full terminal independently of causal-path quality."""

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(campaign: Path) -> None:
    summary_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    status = summary["status"]
    count = summary["fault_trials_completed"]
    if summary["case_id"] != "HBASE-24" or status not in {
        "budget_exhausted", "queue_exhausted"
    } or not 0 < count <= 80 or audit["case_id"] != "HBASE-24" or (
        audit["terminal_status"] != status or audit["trial_count"] != count + 1
    ):
        raise SystemExit("HBASE-24 campaign has no consistent natural full terminal")
    result = {
        "schema_version": 1,
        "case_id": "HBASE-24",
        "kind": "natural_full_terminal",
        "status": status,
        "fault_trials_completed": count,
        "budget": {"trials": 80, "seconds": 3600, "max_faults_per_trial": 3},
        "campaign_result_sha256": sha(summary_path),
        "offline_audit_sha256": sha(audit_path),
        "audit_report_gate_passed": audit["report_gate_passed"],
        "same_actor_target_trials": audit.get("same_actor_target_trials"),
        "observed_graph_path_doors": audit.get("healthy_observed_path_doors"),
        "exact_exception_trials": summary.get("exact_exception_trials"),
        "completion_independent_of_path_quality": True,
    }
    (campaign / "terminal-verdict.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    main(parser.parse_args().campaign)
