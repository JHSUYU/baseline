#!/usr/bin/env python3
"""Qualify known HDFS-17899 and archive case-local raw campaign evidence."""

import hashlib
import json
from pathlib import Path
import tarfile
import sys

HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE.parent
CASE = CAMPAIGN.parent
sys.path.insert(0, str(CAMPAIGN))
import campaign  # noqa: E402

RUNS = HERE / "runs"
ARCHIVE = CAMPAIGN / "campaign-evidence.tar.gz"
INDEX = CAMPAIGN / "campaign-evidence-index.json"
QUALIFICATION = HERE / "qualification.json"
RESULT = CASE / "result.json"
RAW = ("manifest.json", "junit.log", "jacoco.exec", "covered_probes.txt",
       "covered_methods.txt", "covered_branch_counts.txt", "covered_lines.txt",
       "hdfs-audit.log", "audit.json", "launcher.json", "driver.log")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def read_audit(name):
    return json.loads((RUNS / name / "audit.json").read_text())


def qualify():
    healthy = read_audit("one-node-healthy")
    original = read_audit("one-node-persistent-original")
    replay = read_audit("one-node-persistent-original-replay")
    fixed = read_audit("one-node-persistent-fixed")
    for observed in (original, replay):
        if not (observed["harness_complete"] and observed["logical_faults_applied"] == 1
                and observed["remote_response_complete"]
                and observed["remote_rejection_observations"] >= 1
                and observed["client_received_ike_on_wire"]
                and observed["target_after_logical_fault"]
                and observed["same_cached_dek_guards_after_logical_fault"] >= 1
                and observed["cache_clear_events"] == 0
                and observed["junit_failed"] and not observed["junit_timeout"]
                and observed["observed_balancer_exit_codes"] == [-3]
                and observed["successful_block_moves"] < healthy["successful_block_moves"]
                and observed["actual_server_endpoints"] == ["/" + observed["target_datanode"]]):
            raise SystemExit("original or replay lacks remote, target-retaining NO_MOVE_PROGRESS evidence")
    if not (healthy["harness_complete"] and not healthy["junit_failed"]
            and healthy["successful_block_moves"] == 5
            and healthy["remote_rejection_observations"] == 0):
        raise SystemExit("one-node healthy control failed")
    if not (fixed["harness_complete"] and fixed["logical_faults_applied"] == 1
            and fixed["remote_rejection_observations"] >= 1
            and fixed["remote_response_complete"]
            and fixed["cache_clear_events"] >= 1
            and fixed["new_nonce_guards_after_final_rejection"] >= 1
            and fixed["target_after_logical_fault"]
            and not fixed["junit_failed"] and fixed["returncode"] == 0
            and fixed["successful_block_moves"] == healthy["successful_block_moves"]
            and fixed["actual_server_endpoints"] == ["/" + fixed["target_datanode"]]):
        raise SystemExit("fixed control lacks clear/new-nonce/full-progress evidence")
    manifests = [json.loads((RUNS / row["name"] / "manifest.json").read_text())
                 for row in (healthy, original, replay, fixed)]
    if len({row["test_overlay"] for row in manifests}) != 1 or not all(
            row["source_version"] == "3.4.3" for row in manifests):
        raise SystemExit("fixture or source version differs across paired runs")
    if not all(row["dn_reject_persistent"] for row in manifests[1:]):
        raise SystemExit("persistent remote policy missing from a paired run")
    return {"case_id": "HDFS-55", "known_issue": "HDFS-17899",
            "bug_mark": "known_HDFS-17899_reproduced", "new_bug": False,
            "fault_model": ("one persistent synthetic DataNode-side rejection of the "
                            "runtime-selected cached (keyId, nonce) DEK; repeated INVALID_KEY "
                            "responses are observations of one state divergence"),
            "not_natural_nn_rotation": True,
            "workload": ("Hadoop 3.4.3 TestBalancerWithEncryptedTransfer#testEncryptedBalancer0 "
                         "with original TestBalancer.integrationTest/oneNodeTest helper, "
                         "one mover thread, one DN concurrent move, 180s JUnit bound"),
            "target_check": ("KeyManager.newDataEncryptionKey: "
                             "encryptionKey == null || encryptionKey.expiryDate < timer.now()"),
            "source_audit": {
                "KeyManager.java:123": "cached DEK is reused while its local expiry is in the future",
                "SaslDataTransferServer.java:268-282": "DataNode resolves the offered keyId and nonce",
                "SaslDataTransferServer.java:444-458": "InvalidEncryptionKeyException becomes INVALID_KEY SASL response",
                "DataTransferSaslUtil.java:215": "Balancer client decodes remote INVALID_KEY as IKE",
                "Dispatcher.java:408-409": "original generic IOException catch records a failed move without cache clear",
                "ExitStatus.java:29": "NO_MOVE_PROGRESS has exit code -3",
                "Balancer.java:766": "five no-progress iterations return NO_MOVE_PROGRESS",
                "TestBalancer.java:825": "original helper asserts Balancer SUCCESS exit 0",
                "minimal_fix": "on IKE update block keys, clear cached DEK, retry once on a new socket"
            },
            "healthy": healthy, "original": original, "original_replay": replay,
            "fixed": fixed}


def files_to_archive(exact_state, prefix_state):
    files = {CAMPAIGN / "state.json", CAMPAIGN / "trial-ledger.csv",
             CAMPAIGN / "runtime-prefix/state.json",
             CAMPAIGN / "runtime-prefix/trial-ledger.csv",
             QUALIFICATION, HERE / "build/one-node-fixture.json",
             CASE / "Hdfs17899Probe.java", CASE / "build_overlay.py",
             CASE / "run_control.py", HERE / "build_serial_fixture.py",
             HERE / "audit_run.py", HERE / "launch.py", HERE / "finalize.py",
             CAMPAIGN / "audit_stop.py", CASE / "README.md"}
    for row in exact_state["trials"]:
        run = CAMPAIGN / "runs" / row["id"]
        files.update(run / name for name in RAW)
        files.add(CAMPAIGN / "plans" / ("p" + "_".join(map(str, row["sequence"])) + ".tsv"))
    for row in prefix_state["trials"]:
        files.update(CAMPAIGN / "runtime-prefix/runs" / row["id"] / name for name in RAW)
    if prefix_state.get("fixed_replay"):
        run = CAMPAIGN / "runtime-prefix/fixed-replay" / prefix_state["fixed_replay"]["id"]
        files.update(run / name for name in RAW)
    for run in RUNS.iterdir():
        if run.is_dir() and (run / "manifest.json").is_file():
            files.update(run / name for name in RAW)
    files.update((CAMPAIGN / "harness-timeout/p3" / name) for name in RAW)
    generated = HERE / "build/one-node-fixture-src/org/apache/hadoop/hdfs/server/balancer/TestBalancerWithEncryptedTransfer.java"
    files.add(generated)
    return sorted(file for file in files if file.is_file())


def main():
    exact = json.loads((CAMPAIGN / "state.json").read_text())
    prefix = json.loads((CAMPAIGN / "runtime-prefix/state.json").read_text())
    if exact["status"] != "stopped_after_known_bug_reproduction":
        raise SystemExit("exact campaign is still active")
    qualification = qualify()
    atomic(QUALIFICATION, qualification)
    files = files_to_archive(exact, prefix)
    index = {str(file.relative_to(CASE)): {"sha256": sha(file), "bytes": file.stat().st_size}
             for file in files}
    atomic(INDEX, index)
    files.append(INDEX)
    archive_temp = ARCHIVE.with_suffix(ARCHIVE.suffix + ".tmp")
    with tarfile.open(archive_temp, "w:gz") as archive:
        for file in files:
            archive.add(file, arcname=str(file.relative_to(CASE)))
    archive_temp.replace(ARCHIVE)
    covered = campaign.cumulative_coverage(exact)
    healthy_covered = {kind: campaign.ids(campaign.HEALTHY, kind)
                       for kind in campaign.KINDS}
    dn_healthy = RUNS / "one-node-healthy"
    dn_original = RUNS / "one-node-persistent-original"
    dn_gain = {kind: len(campaign.ids(dn_original, kind) - campaign.ids(dn_healthy, kind))
               for kind in campaign.KINDS}
    complete = [row for row in exact["trials"] if row["harness_complete"]]
    full = [row for row in complete if row["fully_applied"]]
    target = [row for row in full if row["target_after_final_fault"]]
    prefix_full = [row for row in prefix["trials"] if row["fully_applied"]]
    prefix_target = [row for row in prefix_full if row["target_after_final_fault"]]
    dn_seconds = sum(json.loads((run / "manifest.json").read_text())["elapsed_seconds"]
                     for run in RUNS.iterdir() if run.is_dir() and (run / "manifest.json").is_file())
    prefix_seconds = sum(row["elapsed_seconds"] for row in prefix["trials"])
    prefix_seconds += prefix["fixed_replay"]["elapsed_seconds"]
    old = json.loads(RESULT.read_text())
    initial_control = old.get("initial_synthetic_control", old.get("known_bug_reproduction"))
    if initial_control is None:
        raise SystemExit("initial synthetic control timing is missing")
    old["initial_synthetic_control"] = initial_control
    old.pop("known_bug_reproduction", None)
    for original_key, explicit_key in (
            ("injected_fault_events", "stateful_control_injected_events"),
            ("post_fault_target_guard_events", "stateful_control_post_fault_target_guard_events"),
            ("post_fault_cached_key_reuse_events", "stateful_control_post_fault_cached_key_reuse_events")):
        if original_key in old:
            old[explicit_key] = old.pop(original_key)
    old.setdefault("stateful_control_fault_policy", old["fault_policy"])
    old.update({
        "status": "quality_complete", "classification": "known_HDFS-17899_reproduced",
        "known_bug": True, "bug_mark": "known_HDFS-17899_reproduced",
        "new_bug": False,
        "fault_policy": qualification["fault_model"],
        "detection_qualification": "campaign/dn-wire/qualification.json",
        "fault_trials": 1 + len(exact["trials"]) + len(prefix["trials"]) + 2,
        "fully_applied_trials": 1 + len(full) + len(prefix_full) + 2,
        "target_after_fault": 1 + len(target) + len(prefix_target) + 2,
        "trial_count_provenance": ("Counts original-version initial synthetic control, "
            "31 exact-plan trials, 12 runtime-prefix trials, and two persistent "
            "DN-wire original/replay trials. Fixed replays and earlier DN-wire "
            "calibrations are separately recorded."),
        "elapsed_seconds": round(sum(run["elapsed_seconds"] for run in
            initial_control.values()) +
            sum(row["elapsed_seconds"] for row in exact["trials"]) +
            prefix_seconds + dn_seconds, 3),
        "coverage_gain": {
            "probes": len(covered["probes"] - healthy_covered["probes"]),
            "production_methods": len(covered["methods"] - healthy_covered["methods"]),
            "branch_count_slots": len(covered["branch_counts"] - healthy_covered["branch_counts"]),
        },
        "coverage_gain_provenance": ("Cumulative complete ordered exact-plan trials "
            "retaining same manager/key target after the final injected event, "
            "relative to original two-phase healthy seed; all other families separate."),
        "dn_wire_coverage_gain_vs_one_node_healthy": {
            "probes": dn_gain["probes"], "production_methods": dn_gain["methods"],
            "branch_count_slots": dn_gain["branch_counts"]},
        "exact_plan_campaign_status": exact["status"],
        "exact_plan_campaign": {
            "budget": exact["budget"], "fault_trials_attempted": len(exact["trials"]),
            "harness_complete_trials": len(complete),
            "fully_applied_trials": len(full),
            "target_after_final_fault_trials": len(target),
            "oracle_candidates": [row["id"] for row in exact["trials"] if row["oracle_candidate"]],
            "planned_fault_events": sum(row["planned_fault_count"] for row in exact["trials"]),
            "matched_fault_events": sum(row["matched_fault_count"] for row in exact["trials"]),
            "applied_fault_events": sum(row["applied_fault_count"] for row in exact["trials"]),
            "elapsed_seconds": round(sum(row["elapsed_seconds"] for row in exact["trials"]), 3),
            "checkpoint": "cases/HDFS-55/campaign/state.json",
            "queue_remaining_resumable": len(exact["queue"])},
        "runtime_prefix_campaign": {
            "status": prefix["status"], "fault_trials_attempted": len(prefix["trials"]),
            "fully_applied_trials": len(prefix_full),
            "target_after_final_fault_trials": len(prefix_target),
            "candidate": "prefix-12", "candidate_kind": "60-second JUnit timeout only",
            "fixed_replay_applied_events": prefix["fixed_replay"]["applied_fault_count"],
            "checkpoint": "cases/HDFS-55/campaign/runtime-prefix/state.json"},
        "dn_wire_persistent_detection": {
            "logical_faults_per_faulted_run": 1,
            "original": qualification["original"],
            "original_replay": qualification["original_replay"],
            "fixed": qualification["fixed"],
            "synthetic_remote_stale_dek_model": True,
            "natural_namenode_rotation_observed": False},
        "dn_wire_calibrations": ["dn-01", "dn-20-original", "dn-20-fixed",
            "nonce-timeout-20-original", "nonce-timeout-20-fixed"],
        "evidence": "cases/HDFS-55/campaign/campaign-evidence.tar.gz",
        "evidence_sha256": sha(ARCHIVE), "evidence_bytes": ARCHIVE.stat().st_size,
        "evidence_index": "cases/HDFS-55/campaign/campaign-evidence-index.json",
        "initial_synthetic_control_evidence": "cases/HDFS-55/known-bug-evidence.tar.gz",
    })
    atomic(RESULT, old)
    print(json.dumps({k: old[k] for k in ("case_id", "status", "bug_mark",
        "fault_trials", "fully_applied_trials", "target_after_fault",
        "elapsed_seconds", "coverage_gain", "evidence_sha256")}, indent=2))


if __name__ == "__main__":
    main()
