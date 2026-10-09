#!/usr/bin/env python3
"""Independently verify the HDFS-24 one-fault retry RPC witnesses.

This checks raw events and plan identities, without importing Mallory's graph
or using its target-retained summary as a causal proof.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


DOOR = ("org.apache.hadoop.hdfs.server.datanode.BPServiceActor"
        "#retrieveNamespaceInfo()Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
        "@260:door:1")
CHECK = ("org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage"
         "#doTransition(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
         "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
         "Lorg/apache/hadoop/hdfs/server/common/HdfsServerConstants$StartupOption;"
         "Ljava/util/List;Lorg/apache/hadoop/conf/Configuration;)Z@414:branch:14")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def one(rows: list[dict], reason: str) -> dict:
    require(len(rows) == 1, f"{reason}: expected one, found {len(rows)}")
    return rows[0]


def numeric_thread(event: dict) -> bool:
    value = event.get("thread_id")
    return isinstance(value, int) and not isinstance(value, bool)


def scoped(event: dict) -> bool:
    return numeric_thread(event) and ":thread:" + str(event["thread_id"]) + ":segment:" in event.get("occurrence", "")


def point_equal(event: dict, point: dict) -> bool:
    return all(event.get(key) == point.get(key) for key in
               ("site", "node", "epoch", "door_ordinal"))


def verify_trial(trial: Path, expected_check: str) -> dict:
    plan = read(trial / "plan.json")
    faults = plan.get("faults", [])
    fault = one(faults, f"{trial.name} plan")
    point = fault["point"]
    require(point.get("site") == DOOR and
            point.get("node", "").startswith("hdfs-cluster-2/dn") and
            point.get("epoch") == 0 and point.get("door_ordinal") == 1,
            f"{trial.name}: wrong exact named door")
    require(fault.get("exception_class") == "java.io.IOException", "wrong fault class")
    outcome = read(trial / "result.json")
    junit = read(trial / "junit-receipt.json")
    feedback = outcome.get("feedback", {})
    require(feedback.get("all_faults_effective") is True and
            feedback.get("target_reached") is True, f"{trial.name}: ineffective or lost target")
    require(junit.get("tests", 0) > 0 and junit.get("errors") == 0 and
            junit.get("failures") == 0 and junit.get("status") == "passed",
            f"{trial.name}: JUnit not passing")
    trace_path = trial / "events.jsonl.gz"
    raw = gzip.open(trace_path, "rb").read()
    events = [json.loads(line) for line in raw.splitlines()]
    require(events and len({e.get("id") for e in events}) == len(events) and
            len({e.get("seq") for e in events}) == len(events),
            f"{trial.name}: missing or duplicate event IDs/sequences")
    obs = one([e for e in events if e.get("type") == "DOOR_OBSERVED" and
               point_equal(e, point)], "exact observed door")
    matched = one([e for e in events if e.get("type") == "FAULT_MATCHED" and
                   e.get("fault_id") == fault["fault_id"]], "matched fault")
    applied = one([e for e in events if e.get("type") == "FAULT_APPLIED" and
                   e.get("fault_id") == fault["fault_id"]], "applied fault")
    require(all(point_equal(e, point) for e in (matched, applied)) and
            all(e.get("exception_class") == "java.io.IOException" for e in
                (obs, matched, applied)), "fault identity or class mismatch")
    actor = (applied["node"], applied["epoch"], applied.get("thread_id"))
    require(all((e.get("node"), e.get("epoch"), e.get("thread_id")) == actor
                for e in (obs, matched)) and
            obs["occurrence"] == matched["occurrence"] == applied["occurrence"] and
            all(scoped(e) for e in (obs, matched, applied)) and
            obs["context"] == "root" and
            obs["seq"] < matched["seq"] < applied["seq"],
            "fault not on one bounded physical DN thread")
    require(not any(e.get("type") == "TARGET_THROW" for e in events),
            "target throw occurred")

    retry = one([e for e in events if e.get("type") == "DOOR_OBSERVED" and
                 e.get("site") == DOOR and e.get("node") == actor[0] and
                 e.get("epoch") == actor[1] and e.get("thread_id") == actor[2] and
                 e.get("occurrence") == applied["occurrence"] and
                 e.get("door_ordinal") == 2 and e["seq"] > applied["seq"]],
                "same-thread second namespace attempt")
    request_send = one([e for e in events if e.get("type") == "SEND" and
                        e.get("site") == "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest" and
                        e.get("node") == actor[0] and e.get("epoch") == actor[1] and
                        e.get("thread_id") == actor[2] and
                        e.get("occurrence") == applied["occurrence"] and
                        e.get("port") == "request" and
                        retry["seq"] < e["seq"] and
                        not any(x.get("type") == "DOOR_OBSERVED" and
                                x.get("site") == DOOR and x.get("node") == actor[0] and
                                retry["seq"] < x["seq"] < e["seq"] for x in events)],
                       "retry request send")
    token = request_send.get("correlation")
    transport = request_send.get("transport")
    require(isinstance(token, str) and token and transport == "hadoop-ipc", "invalid RPC identity")
    pairs = {}
    for event_type, port, label in (("SEND", "request", "request_send"),
                                    ("RECV", "request", "request_recv"),
                                    ("SEND", "response", "response_send"),
                                    ("RECV", "response", "response_recv")):
        pairs[label] = one([e for e in events if e.get("type") == event_type and
                            e.get("transport") == transport and
                            e.get("correlation") == token and e.get("port") == port],
                           f"unique {label}")
    require(pairs["request_send"] is request_send, "request pairing mismatch")
    rr, rs, cr = (pairs["request_recv"], pairs["response_send"],
                  pairs["response_recv"])
    require(all(scoped(e) for e in (request_send, rr, rs, cr)) and
            rr["node"].startswith("hdfs-cluster-2/nn") and
            rs["node"] == rr["node"] and rs["epoch"] == rr["epoch"] and
            rs["thread_id"] == rr["thread_id"] and
            rs["occurrence"] == rr["occurrence"] and
            cr["node"] == actor[0] and cr["epoch"] == actor[1] and
            cr["thread_id"] == actor[2] and
            request_send["seq"] < rr["seq"] < rs["seq"] < cr["seq"],
            "nonphysical or unordered request/response")
    regions = [e for e in events if e.get("type") == "REGION_ENTER" and
               e.get("parent_id") == token and e.get("node") == actor[0] and
               e.get("epoch") == actor[1] and e.get("thread_id") == actor[2] and
               e["seq"] > cr["seq"] and
               e.get("site", "").startswith(
                   "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage#doTransition")]
    require(regions, "no target region after RPC")
    region = min(regions, key=lambda e: e["seq"])
    check = one([e for e in events if e.get("type") == "TARGET_CHECK" and
                 e.get("site") == expected_check and e.get("node") == actor[0] and
                 e.get("epoch") == actor[1] and e.get("thread_id") == actor[2] and
                 e.get("occurrence") == region["occurrence"] and
                 e["seq"] > region["seq"]], "same-DN exact target check")
    return {
        "trial": trial.name, "point": point, "fault_id": fault["fault_id"],
        "actor": {"node": actor[0], "epoch": actor[1], "thread_id": actor[2]},
        "rpc_token": token, "transport": transport,
        "event_ids": {"door": obs["id"], "fault_matched": matched["id"],
                      "fault_applied": applied["id"], "retry_door": retry["id"],
                      "request_send": request_send["id"], "request_recv": rr["id"],
                      "response_send": rs["id"], "response_recv": cr["id"],
                      "region_enter": region["id"], "target_check": check["id"]},
        "event_seqs": {"fault_applied": applied["seq"], "retry_door": retry["seq"],
                       "request_send": request_send["seq"], "request_recv": rr["seq"],
                       "response_send": rs["seq"], "response_recv": cr["seq"],
                       "region_enter": region["seq"], "target_check": check["seq"]},
        "junit": {"tests": junit["tests"], "failures": junit["failures"],
                  "errors": junit["errors"], "status": junit["status"]},
        "target_throw_count": sum(e.get("type") == "TARGET_THROW" for e in events),
        "trace_gzip_sha256": sha256(trace_path),
        "trace_uncompressed_sha256": hashlib.sha256(raw).hexdigest(),
        "plan_sha256": sha256(trial / "plan.json"),
        "result_sha256": sha256(trial / "result.json"),
        "junit_receipt_sha256": sha256(trial / "junit-receipt.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    config, summary, audit = (read(campaign / name) for name in
                              ("config.json", "result.json", "offline-causal-audit.json"))
    require(summary.get("status") == "budget_exhausted" and
            summary.get("case_id") == config.get("case_id") == "HDFS-24" and
            summary.get("fault_trials_completed") == 2 and
            config["budget"]["max_faults_per_trial"] == 1,
            "wrong terminal one-fault pilot")
    require(summary.get("healthy_seed_valid") is True and
            audit.get("report_gate_passed") is True and
            audit.get("applied_fault_identity_valid") is True,
            "healthy or offline gate invalid")
    target = config["target"]
    require(target.get("check_sites") == [CHECK] and
            target.get("exception_class") == "java.io.IOException", "wrong exact target")
    require(config.get("reject_coarse_roots") is True and
            config.get("require_event_time_paths") is True, "coarse graph admitted")
    healthy = campaign / "trials" / "r0000"
    healthy_junit = read(healthy / "junit-receipt.json")
    require(healthy_junit.get("tests", 0) > 0 and
            healthy_junit.get("failures") == healthy_junit.get("errors") == 0 and
            healthy_junit.get("status") == "passed", "healthy JUnit invalid")
    with gzip.open(healthy / "events.jsonl.gz", "rt") as source:
        healthy_events = [json.loads(line) for line in source]
    require(any(e.get("type") == "TARGET_CHECK" and e.get("site") == CHECK and
                e.get("node", "").startswith("hdfs-cluster-2/dn")
                for e in healthy_events) and
            not any(e.get("type") == "TARGET_THROW" for e in healthy_events),
            "healthy exact target missing or throwing")
    rows = [verify_trial(campaign / "trials" / trial, CHECK)
            for trial in ("r0001", "r0002")]
    report = {
        "schema_version": 1, "case_id": "HDFS-24",
        "status": "two_exact_faults_have_unique_event_time_retry_rpc_target_witnesses",
        "scope": "pilot_only_no_bug_claim", "campaign": str(campaign),
        "config_sha256": sha256(campaign / "config.json"),
        "result_sha256": sha256(campaign / "result.json"),
        "offline_audit_sha256": sha256(campaign / "offline-causal-audit.json"),
        "healthy_trace_gzip_sha256": sha256(healthy / "events.jsonl.gz"),
        "healthy_junit_receipt_sha256": sha256(healthy / "junit-receipt.json"),
        "target_check_site": CHECK, "fault_door_site": DOOR,
        "trials": rows,
        "audit_same_actor_target_trials": audit.get("same_actor_target_trials"),
        "audit_same_actor_field_scope": "same_occurrence_local_timeline_only",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"],
                      "trial_count": len(rows), "out": str(args.out)}))


if __name__ == "__main__":
    main()
