#!/usr/bin/env python3
"""Verify the frozen HBASE-31 full stage against its named typed healthy seed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from preflight import HERE, REPO, check, require, sha
from preflight_v2 import main as preflight_healthy


def main(allow_detached_source: bool = False) -> None:
    preflight_healthy(allow_detached_source)
    stage = json.loads((HERE / "full-v2-stage-receipt.json").read_text())
    healthy = json.loads((HERE / "HBASE-31.dispatch-binding-v2.healthy.json").read_text())
    full_path = HERE / "HBASE-31.dispatch-binding-v2.full.json"
    check(full_path, stage["config_sha256"])
    check(HERE / "run_full_v2_node1.sh", stage["runner_sha256"])
    check(Path(__file__), stage["preflight_sha256"])
    check(HERE / "verify_full_v2.py", stage["terminal_verifier_sha256"])
    check(HERE / "predicate-source-gap.json", stage["predicate_source_gap_sha256"])
    full = json.loads(full_path.read_text())
    expected = dict(healthy)
    for field in ("budget", "calibration_only", "auto_promote_if_healthy", "mapping",
                  "calibration_attestation"):
        expected.pop(field, None)
    observed = dict(full)
    for field in ("budget", "calibration_only", "auto_promote_if_healthy", "mapping",
                  "calibration_attestation"):
        observed.pop(field, None)
    require(observed == expected, "typed door, target, test, core, artifacts, or path policy changed")
    require(full["budget"] == {"trials": 80, "seconds": 3600,
                               "max_faults_per_trial": 3, "trial_timeout_seconds": 600}
            and full["calibration_only"] is False
            and full["auto_promote_if_healthy"] is True,
            "full campaign budget or promotion policy changed")
    require(full["require_event_time_paths"] is True and
            full["reject_coarse_roots"] is True and
            full["allow_local_timeline_doors"] is False and
            full["agent_properties"]["auto.io.doors"] is False and
            full["mapping"]["healthy_seed_verified_for_this_stage"] is True and
            full["mapping"]["fault_admission_blocked"] is False and
            full["mapping"]["predicate_source_gap_receipt_sha256"] ==
            stage["predicate_source_gap_sha256"], "strict typed full policy changed")
    evidence = REPO / "data/mallory/calibration_v32_dispatch/HBASE-31"
    attestation = full["calibration_attestation"]
    for key, path in (
        ("healthy_receipt_sha256", HERE / "healthy-v2-admission-receipt.json"),
        ("healthy_result_sha256", evidence / "result.json"),
        ("healthy_audit_sha256", evidence / "offline-causal-audit.json"),
        ("healthy_trace_sha256", evidence / "trials/r0000/events.jsonl.gz"),
    ):
        check(path, attestation[key])
    receipt = json.loads((HERE / "healthy-v2-admission-receipt.json").read_text())
    require(receipt["junit"] == {"tests": 1, "succeeded": 1,
                                 "failures": 0, "errors": 0} and
            receipt["audit_healthy_observed_path_doors"] == 8 and
            receipt["target_checks"] == 16 and receipt["target_throws"] == 0 and
            receipt["audit_report_gate_passed"] is True and
            attestation["strict_named_paths"] == 8 and
            attestation["junit_passed"] is True,
            "named typed healthy evidence changed")
    require(stage["healthy_receipt_sha256"] == sha(HERE / "healthy-v2-admission-receipt.json")
            and stage["healthy_trace_sha256"] == attestation["healthy_trace_sha256"]
            and stage["core_release_id"] == full["core_release"]["release_id"]
            and stage["overlay_jar_sha256"] == receipt["overlay_jar_sha256"],
            "full stage pins changed")
    print("PASS HBASE-31 full v2 preflight: exact named typed seed, strict policy, "
          "80/3600/max3, source-gap receipt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-detached-source", action="store_true")
    main(parser.parse_args().allow_detached_source)
