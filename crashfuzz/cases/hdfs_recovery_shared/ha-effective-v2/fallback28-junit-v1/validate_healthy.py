#!/usr/bin/env python3
"""Independently inspect both original-JUnit healthy target/I/O traces."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
        "#testLeaseRecoveryAfterFailover")
SITE = ("<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: "
        "org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12")
RPC_MARKERS = {"FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY", "FAULT:HADOOP_IPC:REQUEST"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / "runtime_trace.jsonl").read_text().splitlines()]


def root(event: dict) -> str:
    return event.get("occurrenceAddress", "").split("/rpc:", 1)[0]


def inspect(directory: Path, receipt: dict) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("test") != TEST or manifest.get("returncode") != 0
            or manifest.get("instrumented") is not True
            or manifest.get("graphchecker_runtime_used") is not False):
        raise RuntimeError("original JUnit healthy manifest mismatch: " + str(directory))
    if (receipt["manifest_sha256"] != sha(directory / "manifest.json")
            or receipt["trace_sha256"] != sha(directory / "runtime_trace.jsonl")
            or receipt["jacoco_sha256"] != sha(directory / "jacoco.exec")
            or receipt["junit_log_sha256"] != sha(directory / "junit.log")):
        raise RuntimeError("healthy raw SHA mismatch: " + str(directory))
    data = events(directory)
    if [e.get("seq") for e in data] != list(range(1, len(data) + 1)):
        raise RuntimeError("trace sequence gap: " + str(directory))
    if not any(e.get("event") == "CLUSTER_REGISTER" and e.get("dataNodes") == 3
               for e in data):
        raise RuntimeError("three-DataNode MiniDFSCluster not observed")
    if any(e.get("event") == "TARGET_THROW" and e.get("caseId") == "HDFS-28"
           for e in data):
        raise RuntimeError("healthy HDFS-28 target exception")
    begins = {e.get("occurrenceAddress"): e for e in data
              if e.get("event") == "RECOVERY_BEGIN" and e.get("sourceKey")
              and e.get("blockId") is not None and e.get("recoveryId") is not None}
    checks = [e for e in data if e.get("event") == "TARGET_CHECK"
              and e.get("caseId") == "HDFS-28" and e.get("siteId") == SITE
              and e.get("outcome") is False and e.get("occurrenceAddress") in begins
              and e.get("sourceKey") == begins[e["occurrenceAddress"]].get("sourceKey")
              and e.get("blockId") == begins[e["occurrenceAddress"]].get("blockId")
              and e.get("recoveryId") == begins[e["occurrenceAddress"]].get("recoveryId")]
    points = []
    for event in data:
        if event.get("event") != "FAULT_POINT_OBSERVED" or event.get("marker") not in RPC_MARKERS:
            continue
        address = root(event)
        begin = begins.get(address)
        if not begin or event.get("sourceKey") != begin.get("sourceKey"):
            continue
        if event.get("blockId") != begin.get("blockId"):
            continue
        later = [check for check in checks if check["seq"] > event["seq"]
                 and check["occurrenceAddress"] == address]
        if later:
            points.append({"io_seq": event["seq"], "marker": event["marker"],
                           "site_id": event.get("siteId"), "owner": event["sourceKey"],
                           "recovery_root": address, "block_id": event["blockId"],
                           "recovery_id": begin["recoveryId"],
                           "hit_ordinal": event.get("hitOrdinal"),
                           "first_later_guard_seq": min(x["seq"] for x in later)})
    if not checks or not points:
        raise RuntimeError("same actor/root pre-guard RPC not observed: " + str(directory))
    return {"guard_count": len(checks), "eligible_pre_guard_rpc_count": len(points),
            "actor_slots": sorted({p["owner"] for p in points}),
            "stable_rpc_families": sorted({p["marker"] + "|" + str(p["site_id"])
                                            for p in points}),
            "points": points,
            "production_coverage": {
                name: manifest.get("covered_" + name + "_count")
                for name in ("probes", "methods", "branch_counts")}}


def main() -> int:
    receipt_path = HERE / "healthy-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("test") != TEST or receipt.get("independent_from_ha_campaign") is not True:
        raise RuntimeError("fallback receipt mismatch")
    results = {name: inspect(HERE / name, receipt["runs"][name])
               for name in ("healthy-a", "healthy-b")}
    manifests = [json.loads((HERE / name / "manifest.json").read_text())
                 for name in ("healthy-a", "healthy-b")]
    for key in ("original_test_class_sha256", "original_tests_jar_sha256",
                "original_test_resource_sha256", "instrumentation_source_sha256"):
        if manifests[0].get(key) != manifests[1].get(key):
            raise RuntimeError("healthy source/build provenance differs: " + key)
    families = set(results["healthy-a"]["stable_rpc_families"]) & set(
        results["healthy-b"]["stable_rpc_families"])
    if not families:
        raise RuntimeError("two healthy traces have no shared actor-bound RPC family")
    output = {"schema": 1, "test": TEST, "receipt_sha256": sha(receipt_path),
              "stable_rpc_families": sorted(families), "runs": results,
              "independent_denominator_started": False,
              "conclusion": "healthy_calibrated_only_no_fault_trials"}
    pending = HERE / "healthy-validation.json.tmp"
    pending.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    pending.replace(HERE / "healthy-validation.json")
    print(json.dumps({"healthy": 2, "guard_counts": [results[x]["guard_count"]
                      for x in ("healthy-a", "healthy-b")],
                      "eligible_rpc": [results[x]["eligible_pre_guard_rpc_count"]
                      for x in ("healthy-a", "healthy-b")],
                      "shared_families": len(families)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
