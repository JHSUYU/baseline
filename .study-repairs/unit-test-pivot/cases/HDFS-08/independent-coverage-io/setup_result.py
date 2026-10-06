#!/usr/bin/env python3
"""Publish independent healthy JUnit evidence for HDFS-08 atomically."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_RESULT = HERE.parent / "result.json"
HEALTHY = HERE / "healthy/instrumented-segment-context"


def main() -> None:
    original = json.loads((HERE / "healthy/original/manifest.json").read_text())
    instrumented = json.loads((HEALTHY / "manifest.json").read_text())
    events = [json.loads(line) for line in
              (HEALTHY / "trace/runtime_trace.jsonl").read_text().splitlines()
              if line.strip()]
    guards = [row for row in events if row["event"] == "TARGET_GUARD" and
              row["site"] == "Journal.checkRequest:486" and
              row["node"] == "jn2" and row["caller"] == "finalizeLogSegment"]
    if (original["exit"] != 0 or instrumented["exit"] != 0 or
            len(guards) != 2 or not all(row["allowed"] for row in guards) or
            {(row["segmentStartTxId"], row["segmentEndTxId"])
             for row in guards} != {(1, 3), (4, 4)}):
        raise RuntimeError("independent original JUnit target evidence invalid")
    coverage = Counter(line.split("\t", 1)[0] for line in
                       (HEALTHY / "coverage.tsv").read_text().splitlines())
    previous = json.loads(ROOT_RESULT.read_text())
    previous.update({
        "system": "HDFS 3.4.3", "status": "healthy_target_and_io_verified",
        "methodology": "coverage_io_source_probes_no_graph",
        "cluster_test": "org.apache.hadoop.hdfs.qjournal.client."
                        "TestQuorumJournalManager#testSingleWriter",
        "cluster_type": "MiniJournalCluster", "cluster_nodes": "3 JournalNodes",
        "source_file": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/"
                       "org/apache/hadoop/hdfs/qjournal/server/Journal.java",
        "function": "Journal.checkRequest(RequestInfo)",
        "selection_line": 486,
        "check_code": "if (reqInfo.getEpoch() < lastPromisedEpoch.get()) "
                      "{ throw new IOException(\"IPC's epoch ...\"); }",
        "target_exception_type": "java.io.IOException",
        "target_runtime_identity": {
            "node": "jn2", "caller": "finalizeLogSegment",
            "journal_id": guards[0]["journalId"],
            "segments": [{"start_txid": row["segmentStartTxId"],
                          "end_txid": row["segmentEndTxId"],
                          "source_guard_ordinal": row["ordinal"],
                          "request_epoch": row["requestEpoch"],
                          "promised_epoch": row["promisedEpoch"],
                          "request_serial": row["serial"]} for row in guards]},
        "target_reached": True,
        "healthy_target_guard_invocations": len(guards),
        "healthy_target_guard_outcomes": [row["allowed"] for row in guards],
        "healthy_io_points": sum(row["event"] == "IO_OBSERVED" for row in events),
        "healthy_unknown_io_node_points": sum(
            row["event"] == "IO_OBSERVED" and row["node"] == "unknown"
            for row in events),
        "healthy_test_exit": 0,
        "healthy_test_elapsed_seconds": original["elapsed_seconds"],
        "healthy_probe_elapsed_seconds": instrumented["elapsed_seconds"],
        "healthy_production_coverage_ids": dict(coverage),
        "fault_trials": 0, "strict_injections": 0,
        "strict_injection_trials": 0, "fully_applied_trials": 0,
        "target_after_fault": 0, "post_fault_target_reach_trials": 0,
        "coverage_gain": {"METHOD": 0, "BRANCH_UNIT": 0, "PROBE": 0},
        "bug_mark": "none",
        "elapsed_seconds": round(original["elapsed_seconds"] +
                                 instrumented["elapsed_seconds"], 3),
        "reason": "Independent source probes reached both selected jn2 journal "
                  "segments in the unchanged original cluster JUnit; fault "
                  "campaign is pending.",
        "evidence": {"independent_source_provenance":
                     "independent-coverage-io/source-provenance.json",
                     "independent_healthy_original":
                     "independent-coverage-io/healthy/original/manifest.json",
                     "independent_healthy_probe":
                     "independent-coverage-io/healthy/instrumented-segment-context/manifest.json",
                     "independent_healthy_trace":
                     "independent-coverage-io/healthy/instrumented-segment-context/trace/runtime_trace.jsonl",
                     "independent_healthy_coverage":
                     "independent-coverage-io/healthy/instrumented-segment-context/coverage.tsv"},
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    temp = ROOT_RESULT.with_name(ROOT_RESULT.name + ".tmp." + str(os.getpid()))
    with temp.open("w") as stream:
        json.dump(previous, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, ROOT_RESULT)
    print(json.dumps({key: previous[key] for key in
                      ("status", "cluster_test", "healthy_io_points",
                       "healthy_production_coverage_ids", "elapsed_seconds")},
                     indent=2))


if __name__ == "__main__":
    main()
