#!/usr/bin/env python3
"""Independently audit the exact SOLR-40 guard across the ten node3 replays.

The current Mallory TARGET_THROW site is the caller's ATHROW instruction.
RoutedAlias.newAliasMustExistException throws before that instruction executes,
so raw JUnit stack evidence and the guard branch must be checked separately.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
OUT = ROOT / "data/mallory/solr40_node3_first_watch_replay_v1_node0/SOLR-40"
OLD = ROOT / "crashfuzz/cases/SOLR-10/actor-v2/evidence/candidate-solr40-v4"
TARGET = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps"
          "(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;"
          "@132:branch:1")
ALIAS_KEY = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#aliases"
FAULT_REGION = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
                "(Lorg/apache/zookeeper/WatchedEvent;)V")
TARGET_MESSAGE = "Routed alias myalias appears to have been removed during request processing."
TARGET_STACK = "at org.apache.solr.update.processor.RoutedAliasUpdateProcessor.getAliasProps(RoutedAliasUpdateProcessor.java:133)"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_trial(path: Path) -> dict:
    with gzip.open(path / "events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    faults = [event for event in events if event["type"] == "FAULT_APPLIED"]
    assert len(faults) == 1
    fault = faults[0]
    assert fault["node"] == "node3" and fault["door_ordinal"] == 1
    checks = [event for event in events if event["type"] == "TARGET_CHECK"
              and event.get("site") == TARGET and event["seq"] > fault["seq"]
              and event["node"] == fault["node"]]
    manager_reads = [event for event in events if event["type"] == "STATE_READ"
                     and event.get("region") == FAULT_REGION
                     and event.get("key", "").endswith("#log")
                     and event["node"] == fault["node"]
                     and event.get("occurrence") == fault.get("occurrence")]
    assert manager_reads
    manager = manager_reads[0]["object"]
    first = checks[0] if checks else None
    if first:
        reads = [event for event in events if event["type"] == "STATE_READ"
                 and event.get("key") == ALIAS_KEY and event["node"] == fault["node"]
                 and event["seq"] < first["seq"]
                 and event.get("region", "").endswith(
                     "AliasesManager#getAliases()Lorg/apache/solr/common/cloud/Aliases;")]
        assert reads
        read = reads[-1]
        assert read["object"] == manager
        writes = [event for event in events if event["type"] == "STATE_WRITE"
                  and event.get("key") == ALIAS_KEY and event["node"] == fault["node"]
                  and event.get("object") == manager and event["seq"] < first["seq"]]
        write = writes[-1] if writes else None
        assert write and write["value_object"] == read["value_object"]
    else:
        read = write = None
    log = (path / "junit.log").read_text(errors="replace")
    stack_confirmed = TARGET_MESSAGE in log and TARGET_STACK in log
    branch_confirms_missing = bool(first and first["outcome"] == "FALLTHROUGH")
    # In bytecode, ifeq at bci 28 jumps on nonempty properties. FALLTHROUGH
    # enters the source-line-133 throw arm.
    assert stack_confirmed == branch_confirms_missing
    result = json.loads((path / "result.json").read_text())
    assert result["feedback"]["all_faults_applied"] is True
    return {
        "trial": path.name,
        "fault_event_id": fault["id"],
        "same_node_target_count": len(checks),
        "first_target_event_id": first["id"] if first else None,
        "fault_to_first_target_ms": round((first["ts"] - fault["ts"]) / 1e6, 1)
        if first else None,
        "fault_manager_object": manager,
        "target_manager_object": read["object"] if read else None,
        "target_aliases_object": read["value_object"] if read else None,
        "target_branch": first["outcome"] if first else None,
        "last_aliases_write_event_id": write["id"] if write else None,
        "last_aliases_write_before_fault": write["seq"] < fault["seq"] if write else None,
        "last_aliases_write_to_fault_ms": round((write["ts"] - fault["ts"]) / 1e6, 1)
        if write else None,
        "source_confirmed_target_exception": stack_confirmed,
        "mallory_feedback_target_exception": result["feedback"]["target_exception_candidate"],
        "junit_log_sha256": sha(path / "junit.log"),
        "trace_sha256": sha(path / "events.jsonl.gz"),
    }


def old_replay(number: int) -> dict:
    path = OLD / f"replay-{number:03d}" / "events.tsv"
    rows = [line.split("\t") for line in path.read_text().splitlines()]
    faults = [row for row in rows if len(row) > 4 and row[2] == "IO_APPLIED_CONNECTION_LOSS"
              and row[4] == "/aliases.json"]
    assert len(faults) == 1
    fault = faults[0]
    target = next(row for row in rows if len(row) > 3 and row[2] == "TARGET_CHECK"
                  and row[3] == "missing" and int(row[0]) > int(fault[0]))
    assert "actor=jetty:node3" in "\t".join(fault)
    assert "actor=jetty:node3" in "\t".join(target)
    assert any(row[2] == "TARGET_EXCEPTION" for row in rows if len(row) > 2)
    return {
        "replay": number,
        "fault_to_target_ms": round((int(target[1]) - int(fault[1])) / 1e6, 1),
        "target_property_result": "missing",
        "events_sha256": sha(path),
    }


def main() -> None:
    rows = [audit_trial(path) for path in sorted((OUT / "trials").glob("r[0-9][0-9][0-9][0-9]"))]
    assert len(rows) == 10
    report = {
        "classification": "prior-witness-seeded exact-plan replay; not Mallory auto-discovery",
        "raw_feedback_unchanged": True,
        "fault_trials": len(rows),
        "same_node_and_manager_target_trials": sum(row["same_node_target_count"] > 0
                                                   for row in rows),
        "source_confirmed_target_exception_trials": sum(
            row["source_confirmed_target_exception"] for row in rows),
        "mallory_feedback_target_exception_trials": sum(
            row["mallory_feedback_target_exception"] for row in rows),
        "rows": rows,
        "old_crashfuzz_hit_replays": [old_replay(number) for number in (5, 7, 8)],
        "probe_gap": "@133:throw:1 is the caller ATHROW after a factory method that throws internally; the caller ATHROW is unreachable on this path",
    }
    (OUT / "source-target-exception-audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in (
        "fault_trials", "same_node_and_manager_target_trials",
        "source_confirmed_target_exception_trials",
        "mallory_feedback_target_exception_trials")}, sort_keys=True))


if __name__ == "__main__":
    main()
