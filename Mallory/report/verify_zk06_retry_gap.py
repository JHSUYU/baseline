"""Recheck ZK06's exact retry packet and selected-guard absence from raw evidence."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(data: Path, baseline: Path) -> None:
    admission = data / "admissions"
    pilot = data / "pilots/ZOOKEEPER-06-ackepoch-retry-door-node1-v1"
    snapshot = data / "source_snapshots/ZOOKEEPER-06-ackepoch-retry-v1"
    index = json.loads((data / "quality_reviews/zk06_ackepoch_retry_gap/index.json").read_text())
    paths = {
        "negative_receipt": admission / "ZOOKEEPER-06-ackepoch-retry-door-node1-negative-v1.json",
        "source_gap_receipt": admission / "ZOOKEEPER-06-ackepoch-retry-door-node1-source-gap-v1.json",
        "healthy_receipt": admission / "ZOOKEEPER-06-ackepoch-retry-door-node1-healthy-v1.json",
        "source_snapshot_manifest": snapshot / "source-snapshot-manifest.json",
        "pilot_summary": pilot / "focused-pilot-result.json",
        "pilot_config": pilot / "config.json",
        "pilot_plan": pilot / "pilot-plan.json",
        "pilot_trial": pilot / "trials/r0001/result.json",
        "pilot_trace_gzip": pilot / "trials/r0001/events.jsonl.gz",
        "overlay_receipt": baseline / "Mallory/adapters/zookeeper/zookeeper-3.8.7-ackepoch-retry-door-node1-overlay.json",
    }
    assert index["schema_version"] == 1 and index["case_id"] == "ZOOKEEPER-06"
    assert index["classification"] == "fault_model_target_guard_skipped_on_retry"
    assert all(index[f"{key}_sha256"] == sha(path) for key, path in paths.items())
    negative = json.loads(paths["negative_receipt"].read_text())
    gap = json.loads(paths["source_gap_receipt"].read_text())
    manifest = json.loads(paths["source_snapshot_manifest"].read_text())
    summary = json.loads(paths["pilot_summary"].read_text())
    trial = json.loads(paths["pilot_trial"].read_text())
    assert negative["case_id"] == gap["case_id"] == summary["case_id"] == "ZOOKEEPER-06"
    assert negative["status"] == "post_retry_target_method_without_selected_guard"
    assert gap["status"] == index["classification"]
    assert negative["full_campaign_admission"] is gap["full_campaign_admission"] is False
    assert negative["same_packet_target_check_ids"] == negative["selected_throw_event_ids"] == []
    assert gap["pilot_same_packet_postfault_target_checks"] == gap["pilot_selected_throws"] == 0
    assert gap["pilot_exact_fault_trials"] == 1 and gap["healthy_exact_packet_path_witness_count"] == 1
    assert summary["all_faults_effective"] is summary["fault_identity_valid"] is True
    assert summary["junit_status"] == "passed"
    assert gap["pilot_lineage_receipt_sha256"] == sha(paths["negative_receipt"])
    assert manifest["schema_version"] == 1 and manifest["kind"] == "patched_source_snapshot"
    assert manifest["source_gap_receipt_sha256"] == sha(paths["source_gap_receipt"])
    assert manifest["overlay_receipt_sha256"] == sha(paths["overlay_receipt"])
    assert len(manifest["files"]) == 5
    for relative, record in manifest["files"].items():
        path = snapshot / relative
        assert path.stat().st_size == record["size_bytes"]
        assert sha(path) == record["sha256"]
        if relative in gap["patched_source_files"]:
            assert record["sha256"] == gap["patched_source_files"][relative]
        else:
            assert record["sha256"] == gap["pristine_source_files"][relative]
    assert negative["leader_source_sha256"] == manifest["files"]["zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java"]["sha256"]
    assert negative["learner_source_sha256"] == manifest["files"]["zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java"]["sha256"]
    assert negative["healthy_receipt_sha256"] == gap["healthy_receipt_sha256"] == sha(paths["healthy_receipt"])
    assert negative["pilot_config_sha256"] == summary["config_sha256"] == sha(paths["pilot_config"])
    assert negative["pilot_plan_sha256"] == summary["plan_sha256"] == sha(paths["pilot_plan"])
    assert negative["pilot_summary_sha256"] == sha(paths["pilot_summary"])
    assert negative["pilot_trial_sha256"] == summary["trial_result_sha256"] == sha(paths["pilot_trial"])
    assert negative["trace_gzip_sha256"] == summary["trace_gzip_sha256"] == sha(paths["pilot_trace_gzip"])
    raw = gzip.decompress(paths["pilot_trace_gzip"].read_bytes())
    assert hashlib.sha256(raw).hexdigest() == negative["trace_raw_sha256"] == summary["trace_raw_sha256"]
    assert trial["events_evidence"]["gzip_sha256"] == negative["trace_gzip_sha256"]
    assert trial["events_evidence"]["raw_sha256"] == negative["trace_raw_sha256"]
    events = [json.loads(line) for line in raw.splitlines()]
    by_id = {event["id"]: event for event in events}
    assert len(by_id) == len(events)
    names = (("matched_event_id", "FAULT_MATCHED"), ("applied_event_id", "FAULT_APPLIED"),
             ("retry_submit_event_id", "TASK_SUBMIT"), ("retry_claim_event_id", "TASK_CLAIM"),
             ("retry_ackepoch_door_event_id", "DOOR_OBSERVED"),
             ("retry_packet_send_event_id", "SEND"), ("retry_packet_receive_event_id", "RECV"),
             ("target_method_enter_event_id", "REGION_ENTER"),
             ("target_method_exit_event_id", "REGION_EXIT"))
    chain = []
    for field, kind in names:
        event = by_id[negative[field]]
        assert event["type"] == kind
        chain.append(event)
    assert [event["seq"] for event in chain] == sorted(event["seq"] for event in chain)
    match, applied, submit, claim, door, send, recv, enter, leave = chain
    assert match["fault_id"] == applied["fault_id"]
    assert (match["node"], match["epoch"], match["thread_id"], match["occurrence"]) == (
        applied["node"], applied["epoch"], applied["thread_id"], applied["occurrence"])
    assert applied["node"] == submit["node"] == claim["node"] == door["node"] == send["node"]
    assert applied["thread_id"] == submit["thread_id"] == claim["thread_id"] == door["thread_id"] == send["thread_id"]
    assert submit["correlation"] == claim["correlation"] == negative["retry_token"]
    assert claim["occurrence"] == door["occurrence"] == send["occurrence"]
    assert send["correlation"] == recv["correlation"] == enter["context"] == leave["context"] == negative["retry_packet_correlation"]
    assert recv["node"] == enter["node"] == leave["node"]
    assert enter["occurrence"] == leave["occurrence"]
    checks = [event for event in events if event["type"] == "TARGET_CHECK"]
    throws = [event for event in events if event["type"] == "TARGET_THROW"]
    assert len(checks) == negative["generic_target_checks_outside_packet"] == 4
    assert not throws
    assert not any(event["occurrence"] == enter["occurrence"] or
                   enter["seq"] <= event["seq"] <= leave["seq"] for event in checks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    verify(args.data_root, args.baseline)
    print("ZOOKEEPER-06 retry packet: selected guard skipped")
