#!/usr/bin/env python3
"""Audit exact ZK06 ACKEPOCH fault, retry, and selected guard retention."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


DOOR = "zookeeper.quorum.ackepoch.write"
RETRY = "zookeeper.peer.following.retry"
TARGET = "org.apache.zookeeper.server.quorum.Leader#waitForEpochAck(JLorg/apache/zookeeper/server/quorum/StateSummary;)V"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def only(rows, description):
    if len(rows) != 1:
        raise ValueError(f"expected one {description}, found {len(rows)}")
    return rows[0]


def same_actor(left, right, *, same_occurrence=True):
    fields = ["node", "epoch", "thread_id"]
    if same_occurrence:
        fields.append("occurrence")
    return all(left.get(field) == right.get(field) for field in fields)


def audit(pilot: Path, healthy_receipt: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    summary_path = pilot / "focused-pilot-result.json"
    trial_path = pilot / "trials/r0001/result.json"
    plan_path = pilot / "pilot-plan.json"
    trace_path = pilot / "trials/r0001/events.jsonl.gz"
    config_path = pilot / "config.json"
    summary, trial, plan, config, healthy = map(
        load, (summary_path, trial_path, plan_path, config_path, healthy_receipt))
    if (summary["status"] != "focused_fault_trial_complete" or
            not (summary["case_id"] == trial["case_id"] == config["case_id"] == "ZOOKEEPER-06") or
            summary["trial_result_sha256"] != sha(trial_path) or
            summary["plan_sha256"] != sha(plan_path) or
            summary["healthy_receipt_sha256"] != sha(healthy_receipt) or
            plan["source_healthy_receipt_sha256"] != sha(healthy_receipt) or
            summary["config_sha256"] != sha(config_path) or
            trial["plan"] != plan["plan"] or
            len(trial["plan"]) != 1 or
            trial["junit_validation"]["status"] != "passed" or
            trial["feedback"]["all_faults_effective"] is not True or
            trial["site_catalog_validation"]["observed_target_class_sha256"] !=
                config["expected_target_class_sha256"]):
        raise ValueError("pilot trial, JUnit, fault identity, or class SHA invalid")
    evidence = trial["events_evidence"]
    if sha(trace_path) != evidence["gzip_sha256"]:
        raise ValueError("pilot compressed trace SHA invalid")
    raw = gzip.decompress(trace_path.read_bytes())
    if (hashlib.sha256(raw).hexdigest() != evidence["raw_sha256"] or
            summary["trace_raw_sha256"] != evidence["raw_sha256"]):
        raise ValueError("pilot raw trace SHA invalid")
    events = [json.loads(line) for line in raw.splitlines()]
    fault = trial["plan"][0]
    point = fault["point"]
    if (fault["fault_type"] != "EXCEPTION" or
            fault["exception_class"] != "java.io.IOException" or
            point["site"] != DOOR):
        raise ValueError("pilot did not select the exact IOException door")
    pair = lambda kind: [e for e in events if e.get("type") == kind and
                          e.get("fault_id") == fault["fault_id"]]
    matched = only(pair("FAULT_MATCHED"), "matched fault")
    applied = only(pair("FAULT_APPLIED"), "applied fault")
    if (not same_actor(matched, applied) or
            any(applied.get(key) != point[key] for key in
                ("site", "node", "epoch", "door_ordinal")) or
            not matched["seq"] < applied["seq"]):
        raise ValueError("fault matched/applied identity differs")
    submitted = only([e for e in events if e.get("type") == "TASK_SUBMIT" and
                      e.get("site") == RETRY and same_actor(applied, e) and
                      e["seq"] > applied["seq"]], "same-peer retry submit")
    claimed = only([e for e in events if e.get("type") == "TASK_CLAIM" and
                    e.get("site") == RETRY and
                    e.get("correlation") == submitted.get("correlation") and
                    same_actor(submitted, e, same_occurrence=False) and
                    e.get("occurrence") != submitted.get("occurrence") and
                    e["seq"] > submitted["seq"]], "exact retry claim")
    door = only([e for e in events if e.get("type") == "DOOR_OBSERVED" and
                 e.get("site") == DOOR and same_actor(claimed, e) and
                 e["seq"] > claimed["seq"]], "post-retry ACKEPOCH door")
    sent = only([e for e in events if e.get("type") == "SEND" and
                 e.get("site") == "zookeeper.quorum.archive.writeRecord" and
                 same_actor(door, e) and str(e.get("port", "")).startswith("18:") and
                 e["seq"] > door["seq"]], "post-retry ACKEPOCH send")
    received = only([e for e in events if e.get("type") == "RECV" and
                     (e.get("transport"), e.get("correlation"), e.get("port")) ==
                     (sent.get("transport"), sent.get("correlation"), sent.get("port")) and
                     e.get("node") != sent.get("node") and
                     e["seq"] > sent["seq"]], "post-retry ACKEPOCH receive")
    ack_region = only([e for e in events if e.get("type") == "REGION_ENTER" and
                       e.get("site") == "zookeeper.leader.ackepoch" and
                       e.get("parent_id") == received.get("correlation") and
                       same_actor(received, e, same_occurrence=False) and
                       e["seq"] > received["seq"]], "ACKEPOCH handler region")
    target_region = only([e for e in events if e.get("type") == "REGION_ENTER" and
                          e.get("site") == TARGET and
                          e.get("parent_id") == ack_region.get("occurrence") and
                          same_actor(ack_region, e, same_occurrence=False) and
                          e["seq"] > ack_region["seq"]], "target method region")
    target_exit = only([e for e in events if e.get("type") == "REGION_EXIT" and
                        e.get("site") == TARGET and
                        same_actor(target_region, e) and
                        e["seq"] > target_region["seq"]], "target method exit")
    selected = [e for e in events if e.get("type") == "TARGET_CHECK" and
                e.get("site") in config["target"]["check_sites"] and
                same_actor(target_region, e) and
                target_region["seq"] < e["seq"] < target_exit["seq"]]
    throws = [e for e in events if e.get("type") == "TARGET_THROW" and
              e.get("site") == config["target"]["throw_site"]]
    if selected or throws:
        status = "post_retry_target_guard_observed"
    else:
        status = "post_retry_target_method_without_selected_guard"
    # The source explains a possible -1 sentinel path; the trace proves only
    # the missing guard. Do not infer the packet payload from transport IDs.
    root = Path(config["cwd"])
    learner = root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java"
    leader = root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java"
    source = load(Path(config["source_overlay_receipt"]))
    for path in (learner, leader):
        relative = str(path.relative_to(root))
        if sha(path) != source["modified_files"][relative]:
            raise ValueError(f"source changed: {relative}")
    record = {
        "schema_version": 1, "case_id": "ZOOKEEPER-06", "status": status,
        "full_campaign_admission": bool(selected),
        "pilot_summary_sha256": sha(summary_path), "pilot_trial_sha256": sha(trial_path),
        "pilot_config_sha256": sha(config_path), "pilot_plan_sha256": sha(plan_path),
        "trace_gzip_sha256": evidence["gzip_sha256"],
        "trace_raw_sha256": evidence["raw_sha256"],
        "healthy_receipt_sha256": sha(healthy_receipt),
        "learner_source_sha256": sha(learner), "leader_source_sha256": sha(leader),
        "matched_event_id": matched["id"], "applied_event_id": applied["id"],
        "retry_submit_event_id": submitted["id"], "retry_claim_event_id": claimed["id"],
        "retry_token": submitted["correlation"],
        "retry_ackepoch_door_event_id": door["id"],
        "retry_packet_send_event_id": sent["id"],
        "retry_packet_receive_event_id": received["id"],
        "retry_packet_correlation": sent["correlation"],
        "target_method_enter_event_id": target_region["id"],
        "target_method_exit_event_id": target_exit["id"],
        "same_packet_target_check_ids": [e["id"] for e in selected],
        "generic_target_checks_outside_packet": sum(
            e.get("type") == "TARGET_CHECK" and not same_actor(target_region, e)
            for e in events),
        "selected_throw_event_ids": [e["id"] for e in throws],
        "source_rationale": {
            "learner_register_with_leader": "On newEpoch > acceptedEpoch, setAcceptedEpoch precedes ACKEPOCH; a later equal-epoch retry encodes -1.",
            "leader_wait_for_epoch_ack": "The selected isMoreRecentThan comparison is inside ss.getCurrentEpoch() != -1.",
            "limit": "Packet payload and leader electionFinished state were not recorded; source rationale is not a value-flow observation.",
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot", type=Path)
    parser.add_argument("healthy_receipt", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(audit(args.pilot.resolve(), args.healthy_receipt.resolve(),
                args.output.resolve())["status"])
