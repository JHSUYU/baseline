#!/usr/bin/env python3
"""Report strict valid-only terminal outcomes; no new-bug classification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from strict_policy import trial_path, qualifies


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(out: Path) -> dict:
    config = json.loads((out / "config.json").read_text())
    summary = json.loads((out / "result.json").read_text())
    checkpoint = json.loads((out / "checkpoint.json").read_text())
    provenance = json.loads((out / "seed-provenance.json").read_text())
    errors = []
    if (summary.get("status") not in {"queue_exhausted", "budget_exhausted"} or
            checkpoint.get("status") != summary.get("status") or
            config.get("budget", {}).get("trials") != 80 or
            provenance.get("v6_reused_trials") != [0, 1] or
            provenance.get("v5_archive_sha256") !=
                "78e935277aa479bb0f85879b4f35c3764b7318b8bf9584f523860321e839abab"):
        errors.append("terminal_or_seed_provenance_invalid")
    rows = []
    for number in checkpoint.get("completed_trials", []):
        trial = out / "trials" / f"r{number:04d}"
        result = json.loads((trial / "result.json").read_text())
        try:
            path = trial_path(out, result, config["target"])
        except (OSError, ValueError) as exc:
            path = {"classification": "trace_unverifiable", "detail": str(exc)}
        valid = qualifies(result, path) if number else (
            result.get("junit_validation", {}).get("status") == "passed" and
            result.get("feedback", {}).get("target_reached") is True)
        novelty = result.get("novelty", {})
        if number and (result.get("v6_strict_policy", {}).get("qualified") != valid or
                       not valid and any(novelty.get(k, 0) for k in
                                         ("coverage", "closure_coverage", "closure_edges"))):
            errors.append(f"r{number:04d}_invalid_novelty_or_policy")
        rows.append({"trial_id": number, "result_sha256": sha(trial / "result.json"),
                     "strict_valid": valid, "classification": path["classification"],
                     "rpc_token": path.get("rpc_token"), "target_throw_ids": path.get("target_throw_ids", []),
                     "novelty_credited": novelty,
                     "return_code": result.get("return_code"), "timed_out": result.get("timed_out")})
    if len(rows) < 2 or ([row["trial_id"] for row in rows[:2]] != [0, 1] or
                         not all(row["strict_valid"] for row in rows[:2])):
        errors.append("reused_v5_trials_not_strict_valid")
    return {"schema_version": 1, "case_id": "HDFS-48", "new_bug": False,
            "scope": "strict_valid_only_novelty_no_invalid_promotion",
            "terminal_status": summary.get("status"), "campaign_result_sha256": sha(out / "result.json"),
            "seed_provenance_sha256": sha(out / "seed-provenance.json"),
            "valid_fault_trials": sum(r["strict_valid"] for r in rows[1:]),
            "invalid_fault_trials": sum(not r["strict_valid"] for r in rows[1:]),
            "exact_target_throw_trials": sum(bool(r["target_throw_ids"]) for r in rows[1:]),
            "rows": rows, "strict_gate_passed": not errors, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.out)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"strict_gate_passed": report["strict_gate_passed"],
                      "valid_fault_trials": report["valid_fault_trials"]}, sort_keys=True))
    raise SystemExit(0 if report["strict_gate_passed"] else 2)
