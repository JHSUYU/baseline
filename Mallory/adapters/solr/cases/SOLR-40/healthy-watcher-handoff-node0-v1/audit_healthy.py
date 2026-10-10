#!/usr/bin/env python3
"""Classify the exact watcher read, alias-cache handoff, and target from one healthy trace."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
sys.path.insert(0, str(PINNED))
from Mallory.core.events import Trace, event_seq  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1"
CHECK = "org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;@132:branch:1"
ALIAS_KEY = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#aliases"
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"
NODE = re.compile(r"MALLORY_SOLR_NODE logical=(\S+) physical=(\S+) epoch=(\d+)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def events(path: Path) -> Trace:
    if not path.is_file():
        return Trace(())
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if len(rows) > 1_000_000:
        raise ValueError("healthy trace exceeds event audit bound")
    return Trace(tuple(rows))


def named_actor(event: dict, actors: dict[tuple[str, int], str]) -> str | None:
    node, epoch = event.get("node"), event.get("epoch")
    if not isinstance(node, str) or not isinstance(epoch, int):
        return None
    return actors.get((node, epoch))


def summarize(out: Path) -> dict:
    trial = out / "trials/r0000"
    result_path, trial_path = out / "result.json", trial / "result.json"
    result = read(result_path) if result_path.is_file() else {}
    trial_result = read(trial_path) if trial_path.is_file() else {}
    log = trial / "junit.log"
    actors = {(node, int(epoch)): physical for node, physical, epoch in NODE.findall(log.read_text())} if log.is_file() else {}
    trace_file = trial / "events.jsonl.gz"
    trace = events(trace_file)
    graph = OccurrenceGraph(trace.events, reject_coarse_roots=True) if trace.events else None
    exact_doors = [event for event in trace.events if event.get("type") == "DOOR_OBSERVED"
                   and event.get("site") == DOOR and event.get("fault_type") == "EXCEPTION"
                   and event.get("exception_class") == EXCEPTION and named_actor(event, actors)]
    checks = [event for event in trace.events if event.get("type") == "TARGET_CHECK"
              and event.get("site") == CHECK and named_actor(event, actors)]
    writes = [event for event in trace.events if event.get("type") == "STATE_WRITE"
              and event.get("key") == ALIAS_KEY and "#setIfNewer" in str(event.get("site", ""))]
    reads = [event for event in trace.events if event.get("type") == "STATE_READ"
             and event.get("key") == ALIAS_KEY and "#getAliases" in str(event.get("site", ""))]
    exact_local, observed_paths, candidate_paths, sampled_handoffs = [], [], [], []
    for door in exact_doors:
        for check in checks:
            if not (door.get("node") == check.get("node") and
                    door.get("epoch") == check.get("epoch") and
                    0 <= event_seq(door) < event_seq(check)):
                continue
            if (door.get("occurrence") == check.get("occurrence") and
                    door.get("thread_id") == check.get("thread_id")):
                exact_local.append((door["id"], check["id"]))
            if graph is not None:
                observed = graph.event_path(door, check, include_candidates=False, require_edge=True)
                candidate = graph.event_path(door, check, include_candidates=True, require_edge=True)
                if observed is not None:
                    observed_paths.append({"door": door["id"], "check": check["id"],
                                           "edge_kinds": [edge.kind for edge in observed]})
                elif candidate is not None:
                    candidate_paths.append({"door": door["id"], "check": check["id"],
                                            "edge_kinds": [edge.kind for edge in candidate]})
            for write in writes:
                if not (door.get("node") == write.get("node") == check.get("node") and
                        door.get("epoch") == write.get("epoch") == check.get("epoch") and
                        event_seq(door) < event_seq(write) < event_seq(check)):
                    continue
                for read_event in reads:
                    if not (write.get("object") == read_event.get("object") and
                            write.get("version") == read_event.get("version") and
                            read_event.get("node") == check.get("node") and
                            read_event.get("epoch") == check.get("epoch") and
                            event_seq(write) < event_seq(read_event) < event_seq(check)):
                        continue
                    sampled_handoffs.append({"door": door["id"], "write": write["id"],
                                             "read": read_event["id"], "check": check["id"],
                                             "object": write["object"], "version": write["version"]})
                    break
                if sampled_handoffs:
                    break
    junit = result.get("healthy_junit_validation") or trial_result.get("junit_validation") or {}
    passed = junit.get("status") == "passed" and junit.get("tests") == 1
    target_ok = bool(checks) and not trial_result.get("feedback", {}).get("target_threw")
    committed_gate_pairs = trial_result.get("feedback", {}).get("watcher_doors_on_target_occurrences", 0)
    strict = bool(observed_paths) or (bool(exact_local) and committed_gate_pairs > 0)
    status = ("observed_handoff_ready_for_dispatch_review" if passed and target_ok and strict else
              "sampled_state_handoff_candidate_only" if passed and target_ok and sampled_handoffs else
              "exact_door_and_target_no_causal_handoff" if passed and target_ok and exact_doors else
              "healthy_target_or_junit_unproven")
    return {"schema_version": 1, "case_id": "SOLR-40", "status": status,
            "junit_passed": passed, "target_nonthrowing": target_ok,
            "named_actor_bindings": [{"logical": node, "epoch": epoch, "physical": physical}
                                     for (node, epoch), physical in sorted(actors.items())],
            "named_exact_door_events": len(exact_doors), "named_exact_target_checks": len(checks),
            "same_occurrence_pretarget_pairs": exact_local[:20],
            "committed_gate_same_occurrence_doors": committed_gate_pairs,
            "observed_graph_paths": observed_paths[:20], "candidate_graph_paths": candidate_paths[:20],
            "sampled_state_handoffs": sampled_handoffs[:20],
            "sampled_state_is_admission_proof": False,
            "trace_sha256": sha(trace_file) if trace_file.is_file() else None,
            "junit_log_sha256": sha(log) if log.is_file() else None,
            "trial_result_sha256": sha(trial_path) if trial_path.is_file() else None,
            "result_sha256": sha(result_path) if result_path.is_file() else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = summarize(args.output)
    path = args.output / "handoff-audit.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_id": "SOLR-40", "status": receipt["status"],
                      "receipt": str(path)}, sort_keys=True))


if __name__ == "__main__":
    main()
