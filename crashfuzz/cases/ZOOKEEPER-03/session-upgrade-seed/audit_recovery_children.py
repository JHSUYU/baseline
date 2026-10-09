#!/usr/bin/env python3
"""Independently recompute all two-fault receipts and feedback from raw TSV."""

from __future__ import annotations

import json

import run_recovery_children as child


def main():
    _, _, manifest, parent_audit = child.verify()
    state = json.loads(child.CHECKPOINT.read_text())
    jobs = {j["child_id"]: j for j in manifest["jobs"]}
    covered, known_io = child.base_feedback(parent_audit)
    checked = []
    for previous in state["results"]:
        job = jobs[previous["run_id"]]
        root = child.ROOT / job["child_id"]
        receipt = json.loads((root / "run.json").read_text())
        if receipt["selector"] != "|||".join(job["plan"]) or \
                receipt["events_sha256"] != child.pilot.sha(root / "events.tsv") or \
                receipt["coverage_sha256"] != child.pilot.sha(root / "coverage.tsv"):
            raise RuntimeError("raw child receipt/plan/hash disagreement: " + job["child_id"])
        current = child.audit(job, receipt, covered, known_io)
        for key in ("run_id", "plan", "faults_matched", "faults_applied",
                    "exact_injection", "target_after_final_fault", "target_receipt",
                    "selected_target_throws", "junit_exit",
                    "new_target_coverage_lines", "new_target_io_families",
                    "events_sha256", "coverage_sha256"):
            if current[key] != previous[key]:
                raise RuntimeError("stored vs raw child audit differs: " +
                                   job["child_id"] + " " + key)
        if current["target_after_final_fault"]:
            covered |= set(current["coverage"])
            known_io |= set(current["io_families"])
        checked.append({key: current[key] for key in
                        ("run_id", "parent", "plan", "faults_matched",
                         "faults_applied", "exact_injection",
                         "target_after_final_fault", "target_receipt",
                         "selected_target_throws", "junit_exit",
                         "new_target_coverage_lines", "new_target_io_families",
                         "elapsed_seconds", "events_sha256", "coverage_sha256")})
    if len(checked) + len(jobs.keys() - {x["run_id"] for x in checked}) != 13:
        raise RuntimeError("child queue denominator changed")
    result = {"case_id": "ZOOKEEPER-03", "phase": manifest["phase"],
              "status": state["status"], "manifest_sha256": child.pilot.sha(child.MANIFEST),
              "checkpoint_sha256": child.pilot.sha(child.CHECKPOINT),
              "parent_pilot_archive_sha256": child.pilot.sha(child.PARENT_ARCHIVE),
              "selected": len(checked),
              "strict_two_fault_injections": sum(x["exact_injection"] for x in checked),
              "target_retaining": sum(x["target_after_final_fault"] for x in checked),
              "selected_target_throws": sum(x["selected_target_throws"] for x in checked),
              "new_target_coverage_lines": sum(x["new_target_coverage_lines"] for x in checked),
              "new_target_io_families": sum(x["new_target_io_families"] for x in checked),
              "sum_elapsed_seconds": round(sum(x["elapsed_seconds"] for x in checked), 3),
              "trials": checked}
    child.pilot.up.write_json(child.ROOT / "child-independent-audit.json", result)
    print(json.dumps({k: result[k] for k in
        ("status", "selected", "strict_two_fault_injections", "target_retaining",
         "selected_target_throws", "new_target_coverage_lines",
         "new_target_io_families", "sum_elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
