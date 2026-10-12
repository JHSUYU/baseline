#!/usr/bin/env python3
"""Recount exact alias faults and subsequent SOLR-40 target events from raw traces."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
OUT = ROOT / "data/mallory/solr40_targeted_replay_v2_node0/SOLR-40"
DOOR = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
        "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps"
         "(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;"
         "@132:branch:1")
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(out: Path = OUT) -> None:
    rows = []
    for trial in sorted((out / "trials").glob("r[0-9][0-9][0-9][0-9]")):
        if not (trial / "result.json").is_file():
            continue
        result = json.loads((trial / "result.json").read_text())
        trace = trial / "events.jsonl.gz"
        with gzip.open(trace, "rt") as stream:
            events = [json.loads(line) for line in stream]
        plan = result.get("plan") or []
        applied = [e for e in events if e.get("type") == "FAULT_APPLIED"]
        checks = [e for e in events if e.get("type") == "TARGET_CHECK"
                  and e.get("site") == CHECK]
        throws = [e for e in events if e.get("type") in
                  ("TARGET_THROW", "TARGET_EXCEPTION")]
        if plan:
            point = plan[0]["point"]
            assert len(plan) == 1 and plan[0]["exception_class"] == EXCEPTION
            assert point["site"] == DOOR
            assert len(applied) <= 1
            fault = applied[0] if applied else None
            if fault:
                assert (fault["site"], fault["node"], fault["epoch"],
                        fault["door_ordinal"], fault["exception_class"]) == (
                        point["site"], point["node"], point["epoch"],
                        point["door_ordinal"], EXCEPTION)
            later = [e for e in checks if fault and e["seq"] > fault["seq"]]
            same_node = [e for e in later if e["node"] == fault["node"] and
                         e["epoch"] == fault["epoch"]]
        else:
            assert not applied
            fault = None
            later, same_node = checks, []
        rows.append({
            "trial": trial.name,
            "junit_status": result.get("junit_validation", {}).get("status"),
            "feedback_status": result["feedback"].get("status"),
            "planned_fault": bool(plan),
            "fault_applied": fault is not None,
            "fault_node": fault.get("node") if fault else None,
            "fault_seq": fault.get("seq") if fault else None,
            "fault_ordinal": fault.get("door_ordinal") if fault else None,
            "fault_event_id": fault.get("id") if fault else None,
            "target_check_count": len(checks),
            "post_fault_target_nodes": sorted({e["node"] for e in later}),
            "same_node_post_fault_target_count": len(same_node),
            "same_node_post_fault_target_event_ids": [e["id"] for e in same_node],
            "target_exception_event_ids": [e["id"] for e in throws],
            "target_exception_candidate": result["feedback"].get(
                "target_exception_candidate") is True,
            "trace_sha256": sha(trace),
            "junit_log_sha256": sha(trial / "junit.log"),
            "result_sha256": sha(trial / "result.json"),
        })
    summary = {
        "case_id": "SOLR-40",
        "source": "original Solr 8.11.4 TimeRoutedAliasUpdateProcessorTest#test",
        "target": CHECK,
        "fault_door": DOOR,
        "fault_exception": EXCEPTION,
        "fault_trials": sum(row["planned_fault"] for row in rows),
        "exact_applied_fault_trials": sum(row["fault_applied"] for row in rows),
        "same_node_post_fault_target_trials": sum(
            row["same_node_post_fault_target_count"] > 0 for row in rows),
        "target_exception_trials": sum(row["target_exception_candidate"] for row in rows),
        "rows": rows,
    }
    manifest = out / "replay-manifest.json"
    if manifest.is_file():
        replay = json.loads(manifest.read_text())
        summary["classification"] = replay["classification"]
        summary["requested_replays"] = replay["requested_replays"]
        summary["complete"] = len(rows) == replay["requested_replays"]
        summary["replay_manifest_sha256"] = sha(manifest)
    path = out / "targeted-replay-audit.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: summary[key] for key in
                      ("fault_trials", "exact_applied_fault_trials",
                       "same_node_post_fault_target_trials",
                       "target_exception_trials")}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    main(args.out)
