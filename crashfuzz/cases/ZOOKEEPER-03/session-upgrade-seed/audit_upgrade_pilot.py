#!/usr/bin/env python3
"""Recompute pilot feedback against both fault-free original-JUnit baselines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import run_upgrade_pilot as pilot
from receipt_validator import parse_events


def baseline_feedback():
    coverage = set()
    families = set()
    evidence = {}
    for label in ("healthy-a", "healthy-b"):
        root = pilot.HEALTH / label
        rows = parse_events(root / "events.tsv")
        coverage |= set((root / "coverage.tsv").read_text().splitlines())
        families |= {"@@".join(fields[:3]) for _, kind, fields in rows
                     if kind == "IO" and len(fields) >= 7
                     and fields[6] == "upgradedSession"}
        evidence[label] = {"events_sha256": pilot.sha(root / "events.tsv"),
                           "coverage_sha256": pilot.sha(root / "coverage.tsv")}
    return coverage, families, evidence


def main():
    _, _, manifest = pilot.verify()
    state = json.loads(pilot.CHECKPOINT.read_text())
    jobs = {job["pilot_id"]: job for job in manifest["jobs"]}
    seen_coverage, seen_io, baselines = baseline_feedback()
    baseline_coverage = len(seen_coverage)
    baseline_io = len(seen_io)
    audited = []
    for old in state["results"]:
        job = jobs[old["run_id"]]
        receipt = json.loads((pilot.PILOT / job["pilot_id"] / "run.json").read_text())
        if receipt["selector"] != job["selector"] or \
                receipt["events_sha256"] != pilot.sha(
                    pilot.PILOT / job["pilot_id"] / "events.tsv") or \
                receipt["coverage_sha256"] != pilot.sha(
                    pilot.PILOT / job["pilot_id"] / "coverage.tsv"):
            raise RuntimeError("raw trial/selector SHA disagreement: " + job["pilot_id"])
        fresh = pilot.audit(job, receipt, seen_coverage, seen_io)
        for field in ("run_id", "selector", "exact_injection",
                      "target_after_final_fault", "target_receipt",
                      "selected_target_throws", "junit_exit", "events_sha256"):
            if fresh[field] != old[field]:
                raise RuntimeError("stored vs raw identity audit differs: " +
                                   job["pilot_id"] + " " + field)
        audited.append({key: fresh[key] for key in
                        ("run_id", "selector", "exact_injection",
                         "target_after_final_fault", "target_receipt",
                         "selected_target_throws", "elapsed_seconds", "junit_exit",
                         "new_target_coverage_lines", "new_target_io_families",
                         "events_sha256", "coverage_sha256")})
        seen_coverage |= set(fresh["coverage"])
        seen_io |= set(fresh["io_families"])
    result = {"case_id": "ZOOKEEPER-03", "phase": "session-upgrade-pilot",
              "status": state["status"], "manifest_sha256": pilot.sha(pilot.MANIFEST),
              "checkpoint_sha256": pilot.sha(pilot.CHECKPOINT),
              "healthy_baselines": baselines,
              "healthy_coverage_lines": baseline_coverage,
              "healthy_io_families": baseline_io,
              "selected": len(audited),
              "strict_injections": sum(x["exact_injection"] for x in audited),
              "target_retaining": sum(x["target_after_final_fault"] for x in audited),
              "selected_target_throws": sum(x["selected_target_throws"] for x in audited),
              "new_target_coverage_lines": len(seen_coverage) - baseline_coverage,
              "new_target_io_families": len(seen_io) - baseline_io,
              "sum_elapsed_seconds": round(sum(x["elapsed_seconds"] for x in audited), 3),
              "trials": audited}
    output = pilot.PILOT / "pilot-feedback-audit.json"
    pilot.up.write_json(output, result)
    print(json.dumps({k: result[k] for k in
        ("status", "selected", "strict_injections", "target_retaining",
         "selected_target_throws", "new_target_coverage_lines",
         "new_target_io_families", "sum_elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
