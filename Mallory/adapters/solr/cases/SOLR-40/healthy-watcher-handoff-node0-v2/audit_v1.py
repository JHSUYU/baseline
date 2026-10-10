#!/usr/bin/env python3
"""Read-only causal gap audit of the sealed SOLR-40 v1 healthy trace."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

from call_return import add_balanced_returns

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
sys.path.insert(0, str(PINNED))
from Mallory.core.events import event_address, event_seq  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

DOOR = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
        "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
CHECK = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps"
         "(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;"
         "@132:branch:1")
ALIAS_KEY = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#aliases"
NODE_BINDING = re.compile(r"MALLORY_SOLR_NODE logical=(\S+) physical=(\S+) epoch=(\d+)")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(out: Path) -> dict:
    trace_path = out / "trials/r0000/events.jsonl.gz"
    result_path = out / "trials/r0000/result.json"
    with gzip.open(trace_path, "rt", encoding="utf-8") as stream:
        events = tuple(json.loads(line) for line in stream if line.strip())
    result = json.loads(result_path.read_text())
    junit_log = out / "trials/r0000/junit.log"
    bound = {(node, int(epoch)) for node, _, epoch in
             NODE_BINDING.findall(junit_log.read_text())}
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    bridge = add_balanced_returns(graph, events, event_address, event_seq)
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
             and row.get("site") == DOOR and
             (row.get("node"), row.get("epoch")) in bound]
    targets = [row for row in events if row.get("type") == "TARGET_CHECK"
               and row.get("site") == CHECK and
               (row.get("node"), row.get("epoch")) in bound]
    observed, candidates = [], []
    for door in doors:
        for target in targets:
            if door.get("node") != target.get("node") or door.get("epoch") != target.get("epoch"):
                continue
            path = graph.event_path(door, target, include_candidates=False, require_edge=True)
            candidate = graph.event_path(door, target, include_candidates=True, require_edge=True)
            if path is None and candidate is None:
                continue
            witness = [{"kind": edge.kind, "certainty": edge.certainty,
                        "producer_event": edge.producer_event,
                        "consumer_event": edge.consumer_event}
                       for edge in (path or candidate)]
            row = {"door_event": door["id"], "target_event": target["id"],
                   "node": door["node"], "path": witness}
            if path is not None:
                observed.append(row)
            else:
                candidates.append(row)
    state_candidate_count = sum(any(edge["kind"] == "state" and
                                        edge["certainty"] == "candidate"
                                        for edge in row["path"]) for row in candidates)
    return {
        "schema_version": 1, "case_id": "SOLR-40", "mode": "read_only_v1_trace_audit",
        "source_trace_sha256": sha(trace_path),
        "source_trial_result_sha256": sha(result_path),
        "source_feedback_status": result.get("feedback", {}).get("status"),
        "source_eligible_doors_before_target": result.get("feedback", {}).get(
            "eligible_doors_before_target"),
        "exact_named_doors": len(doors), "exact_named_targets": len(targets),
        "return_bridge": bridge,
        "observed_event_time_paths": observed,
        "candidate_event_time_paths": candidates,
        "candidate_paths_with_sampled_state": state_candidate_count,
        "full_campaign_go": False,
        "reason": ("sampled_shared_field_identity_cannot_prove_an_observed_handoff"
                   if candidates and not observed else
                   "no_observed_watcher_to_target_handoff" if not observed else
                   "observed_path_requires_fresh_v2_healthy_and_fault_admission"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-output", type=Path,
                        default=ROOT / "data/mallory/calibration_solr40_watcher_handoff_v1_node0/SOLR-40")
    parser.add_argument("--receipt", type=Path, default=HERE / "v1-gap-receipt.json")
    args = parser.parse_args()
    receipt = audit(args.v1_output)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in (
        "case_id", "exact_named_doors", "exact_named_targets",
        "candidate_paths_with_sampled_state", "full_campaign_go", "reason")},
        sort_keys=True))


if __name__ == "__main__":
    main()
