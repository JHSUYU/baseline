#!/usr/bin/env python3
"""Reproduce the source-backed SOLR-16 target-absent healthy receipt, without a JVM."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
OUT = ROOT / "data/mallory/solr16_chaos_healthy_node0_v1/healthy"
CONFIG = HERE.parent / "chaos-healthy-node0-v1/config-healthy-node0.json"
GATE = OUT / "solr16-chaos-healthy-gate.json"
TRIAL = OUT / "trials/r0000"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    result = json.loads((TRIAL / "result.json").read_text(encoding="utf-8"))
    with gzip.open(TRIAL / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream if line.strip()]
    source = SOURCE / config["target"]["source_path"]
    test = SOURCE / "solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java"
    lines = source.read_text(encoding="utf-8").splitlines()
    test_lines = test.read_text(encoding="utf-8").splitlines()
    if sha(source) != config["mapping"]["target_source_sha256"]:
        raise ValueError("target source revision changed")
    if sha(test) != config["mapping"]["test_source_sha256"]:
        raise ValueError("cluster JUnit source revision changed")
    checks = {164: ".exists(", 523: ".exists(",
              524: "leaderZnodeStat == null || ephemeralOwner !=",
              539: "ephemeralOwner != leaderZnodeStat.getEphemeralOwner()",
              542: "The zk session id for the shard leader node"}
    for line, fragment in checks.items():
        if fragment not in lines[line - 1]:
            raise ValueError(f"source control flow changed at line {line}")
    if ("testSplitWithChaosMonkey" not in test_lines[415]
            or "slice.getReplicas().size() > 1" not in test_lines[451]
            or "Thread.sleep(1000 + random().nextInt(500))" not in test_lines[457]
            or "cjetty.jetty.stop()" not in test_lines[458]
            or "requestStatus(asyncId).waitFor(cloudClient, 120)" not in test_lines[479]
            or "cjetty.jetty.start()" not in test_lines[505]):
        raise ValueError("chaos JUnit timing changed")
    junit = gate["original_junit"]
    if (junit.get("status") != "passed" or junit.get("tests") != 1
            or junit.get("failures") != 0 or junit.get("errors") != 0):
        raise ValueError("healthy JUnit did not pass 1/0/0")
    witness = gate.get("same_split_identity_witness") or {}
    ids = {row.get("id"): row for row in events}
    first = ids.get(witness.get("first_native_event_id"))
    second = ids.get(witness.get("second_native_event_id"))
    if (not first or not second or first.get("resource") != second.get("resource")
            or first.get("resource") != witness.get("parent_live_node_resource")
            or first.get("occurrence") != second.get("occurrence")
            or first.get("node") != second.get("node")
            or first.get("thread_id") != second.get("thread_id")):
        raise ValueError("same-split leader path witness changed")
    check = gate["exact_check_site"]
    if (gate.get("status") != "failed"
            or gate.get("reasons") != ["exact_target_check_missing_after_same_split_lookup"]
            or any(row.get("type") == "TARGET_CHECK" and row.get("site") == check
                   for row in events)):
        raise ValueError("selected check is no longer absent")
    coverage = result["feedback"]["coverage_ids"]
    preguard = [site for site in coverage if "SplitShardCmd#split" in site
                and "@524:branch:" in site]
    if not preguard:
        raise ValueError("outer postlookup branch was not covered")
    return {
        "schema_version": 1, "case_id": "SOLR-16",
        "status": "candidate_skip_target_unreached",
        "healthy_junit": "1/0/0", "healthy_faults": 0,
        "cluster_test": config["cluster_test"],
        "source_revision": config["mapping"]["source_git_revision"],
        "leader_path": first["resource"],
        "first_native_event_id": first["id"],
        "second_native_event_id": second["id"],
        "first_seq": first["seq"], "second_seq": second["seq"],
        "same_actor_epoch_thread_split": True,
        "outer_condition_line": 524,
        "outer_branch_coverage": sorted(preguard),
        "exact_check_line": 539, "exact_check_reached": False,
        "exact_throw_line": 543, "exact_throw_reached": False,
        "control_flow_inference": "The selected line-539 check is nested under the line-524 missing-node-or-owner-change condition and after the line-536 null test. This run continued into later replica creation without executing line 539, so the same-path second lookup did not expose a replacement session. Stat return values are not directly traced.",
        "workload_limit": "The unchanged chaos JUnit stops the parent leader after two sub-shard replicas appear and a 1000-1499 ms delay, but restarts that same node only after waiting for the asynchronous split result. If the second lookup occurs while the node is stopped, line 538 throws for a null stat; if it precedes the stop, the original owner remains. The selected line-539 check needs that same live-node path to reappear with a new ZooKeeper session before the second lookup. Reviewed adjacent split tests do not deliberately create that window.",
        "next_action": "No fault campaign or completed-check promotion. A future cluster workload must replace the same parent's ZooKeeper session between the two reads and reach the exact line-539 check before target-closure injection is admissible.",
        "source_sha256": sha(source), "test_sha256": sha(test),
        "trace_sha256": sha(TRIAL / "events.jsonl.gz"),
        "result_sha256": sha(TRIAL / "result.json"),
        "gate_sha256": sha(GATE),
    }


if __name__ == "__main__":
    print(json.dumps(audit(), sort_keys=True, indent=2))
