#!/usr/bin/env python3
"""Run one source-selected ACKEPOCH fault after an attested healthy seed."""

import argparse
import hashlib
import json
from pathlib import Path

from Mallory.core.campaign import _run_trial, atomic_json, read_json, validate_config
from Mallory.core.scheduler import mutate


SITE = "zookeeper.quorum.ackepoch.write"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(config_path: Path, healthy: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(out)
    config = read_json(config_path)
    validate_config(config)
    receipt_path = Path(config["healthy_receipt"])
    receipt = read_json(receipt_path)
    if (config["case_id"] != "ZOOKEEPER-06" or config["calibration_only"] or
            sha(receipt_path) != config["healthy_receipt_sha256"] or
            receipt["status"] != "healthy_exact_ackepoch_write_to_target_path" or
            sha(healthy / "result.json") != receipt["campaign_result_sha256"] or
            sha(healthy / "offline-causal-audit.json") != receipt["offline_audit_sha256"] or
            sha(healthy / "trials/r0000/result.json") != receipt["trial_result_sha256"] or
            sha(healthy / "trials/r0000/events.jsonl.gz") != receipt["trace_gzip_sha256"] or
            sha(Path(config["source_overlay_receipt"])) != config["source_overlay_receipt_sha256"]):
        raise ValueError("healthy exact-packet evidence or source is unpinned")
    overlay = read_json(Path(config["source_overlay_receipt"]))
    for relative, expected in overlay["modified_files"].items():
        if sha(Path(overlay["patched_root"]) / relative) != expected:
            raise ValueError(f"source changed: {relative}")
    for artifact in overlay["compiled_artifacts"]:
        if sha(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError(f"class changed: {artifact['path']}")
    for item in config["runtime_artifacts"]:
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"runtime artifact changed: {item['path']}")
    healthy_result = read_json(healthy / "result.json")
    healthy_trial = read_json(healthy / "trials/r0000/result.json")
    if (healthy_result["runtime_attestation"]["valid"] is not True or
            healthy_result["runtime_attestation"]["observed_target_class_sha256"] !=
            config["expected_target_class_sha256"]):
        raise ValueError("loaded target class or healthy binding invalid")
    witnesses = receipt["witnesses"]
    if len(witnesses) != 1:
        raise ValueError("focused pilot requires one unique physical ACKEPOCH witness")
    door_id = witnesses[0]["door_event_id"]
    doors = [row for row in healthy_trial["feedback"]["doors"] if
             row["event_id"] == door_id and row["site"] == SITE and row["in_closure"]]
    if len(doors) != 1:
        raise ValueError("unique in-closure ACKEPOCH door is absent")
    point = doors[0]["point"]
    choices = [candidate for candidate in mutate([], healthy_trial["feedback"], config)
               if candidate["faults"][-1]["point"] == point and
               candidate["faults"][-1]["fault_type"] == "EXCEPTION"]
    if len(choices) != 1 or choices[0]["selection_reason"] != "dynamic_closure":
        raise ValueError("core did not uniquely select the attested ACKEPOCH door")
    plan = choices[0]["faults"]
    if len(plan) != 1 or plan[0].get("exception_class") != "java.io.IOException":
        raise ValueError("unexpected focused fault plan")

    out.mkdir(parents=True)
    atomic_json(out / "config.json", config)
    atomic_json(out / "pilot-plan.json", {
        "schema_version": 1, "case_id": "ZOOKEEPER-06", "plan": plan,
        "source_healthy_receipt_sha256": sha(receipt_path),
        "source_healthy_trial_sha256": receipt["trial_result_sha256"],
        "selection_reason": choices[0]["selection_reason"],
    })

    def save_running(pid):
        atomic_json(out / "running.json", {"pid": pid, "trial_id": 1})

    result = _run_trial(config, out, 1, plan, save_running,
                        healthy_result["target_binding"])
    feedback = result["feedback"]
    summary = {
        "schema_version": 1, "case_id": "ZOOKEEPER-06", "status": "focused_fault_trial_complete",
        "config_sha256": sha(config_path), "healthy_receipt_sha256": sha(receipt_path),
        "plan_sha256": sha(out / "pilot-plan.json"),
        "trial_result_sha256": sha(out / "trials/r0001/result.json"),
        "trace_gzip_sha256": result["events_evidence"]["gzip_sha256"],
        "trace_raw_sha256": result["events_evidence"]["raw_sha256"],
        "elapsed_seconds": result["elapsed_seconds"],
        "junit_status": result["junit_validation"]["status"],
        "fault_identity_valid": feedback.get("fault_identity_valid"),
        "all_faults_effective": feedback.get("all_faults_effective"),
        "generic_target_reached": feedback.get("target_reached"),
        "target_exception_candidate": feedback.get("target_exception_candidate"),
        "scope_limit": "Affected-peer retry, packet ancestry, and postfault exact target require separate raw-trace audit.",
    }
    atomic_json(out / "focused-pilot-result.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--healthy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.config.resolve(), args.healthy.resolve(), args.out.resolve()),
                     sort_keys=True))
