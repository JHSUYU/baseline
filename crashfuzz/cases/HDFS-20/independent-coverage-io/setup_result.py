#!/usr/bin/env python3
"""Publish the unchanged original MiniDFSCluster JUnit health check."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path


CASE = Path(__file__).resolve().parent
RESULT = CASE.parent / "result.json"


def main() -> None:
    original = json.loads((CASE / "healthy/original/manifest.json").read_text())
    if original["exit"] != 0 or original["compile_exit"] != 0:
        raise RuntimeError("original released JUnit is not healthy")
    result = json.loads(RESULT.read_text())
    result.update({
        "case_id": "HDFS-20",
        "system": "HDFS 3.4.3",
        "source_file": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java",
        "function": "BPOfferService.updateActorStatesFromHeartbeat(BPServiceActor, NNHAStatusHeartbeat)",
        "selection_line": 606,
        "check_code": "assert txid >= lastActiveClaimTxId;",
        "target_exception_type": "java.lang.AssertionError",
        "cluster_test": original["test"],
        "cluster_type": "MiniDFSCluster",
        "cluster_nodes": "1 NameNode, 1 DataNode",
        "status": "healthy_test_passed_probe_pending",
        "healthy_test_exit": original["exit"],
        "healthy_test_elapsed_seconds": original["elapsed_seconds"],
        "elapsed_seconds": original["elapsed_seconds"],
        "target_reached": None,
        "fault_trials": 0,
        "strict_injections": 0,
        "target_after_fault": 0,
        "coverage_gain": {"METHOD": 0, "BRANCH_UNIT": 0, "PROBE": 0},
        "bug_mark": "none",
        "methodology": "coverage_io_source_probes_no_graph",
        "evidence": {
            "independent_original_junit":
            "independent-coverage-io/healthy/original/manifest.json",
            "independent_source_provenance":
            "independent-coverage-io/source-provenance.json",
        },
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    temp = RESULT.with_name(RESULT.name + f".tmp.{os.getpid()}")
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.replace(temp, RESULT)
    print(json.dumps({key: result[key] for key in
                      ("case_id", "status", "healthy_test_elapsed_seconds",
                       "cluster_test", "target_reached")}))


if __name__ == "__main__":
    main()
