#!/usr/bin/env python3
"""Pin the bounded SOLR-22 request-door precision gap to raw traces and source."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/core/src/java/org/apache/solr/handler/ReplicationHandler.java")
TARGET_SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/core/src/java/org/apache/solr/core/IndexDeletionPolicyWrapper.java")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(path: Path) -> tuple[dict, ...]:
    return tuple(json.loads(line) for line in gzip.open(path, "rb") if line.strip())


def inspect(campaign: Path, strict_sidecar: Path) -> dict:
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    sync_path = campaign / "sync-receipt.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    strict = json.loads(strict_sidecar.read_text())
    assert result["case_id"] == strict["case_id"] == "SOLR-22"
    assert result["status"] == "budget_exhausted" and result["fault_trials_completed"] == 8
    assert audit["report_gate_passed"] is True
    assert strict["campaign_result_sha256"] == digest(result_path)
    assert strict["offline_audit_sha256"] == digest(audit_path)
    assert strict["classification"] == "postfault_causal_path_unverified"
    assert strict["qualified_root_free_rpc_trial_ids"] == []
    healthy_path = campaign / "trials/r0000/events.jsonl.gz"
    healthy = events(healthy_path)
    graph = OccurrenceGraph(healthy, reject_coarse_roots=True)
    actor = strict["resolved_physical_target_node"]
    exact = set(json.loads((campaign / "config.json").read_text())["target"]["check_sites"])
    targets = [event for event in healthy if event.get("type") == "TARGET_CHECK"
               and event.get("node") == actor and event.get("site") in exact]
    server_doors = [event for event in healthy if event.get("type") == "DOOR_OBSERVED"
                    and event.get("node") == actor]
    server_paths = [(door["id"], target["id"])
                    for door in server_doors for target in targets
                    if door["seq"] < target["seq"]
                    and graph.event_path(door, target, require_edge=True)]
    assert not server_paths, "a named server door gained a target path"
    retained = []
    for row in strict["trials"]:
        if not (row["fault_effective"] and row["target_reached"]
                and row["target_actor_unique_and_bound"]):
            continue
        trial_id = row["trial_id"]
        trial_dir = campaign / f"trials/r{trial_id:04d}"
        trial_path = trial_dir / "result.json"
        assert digest(trial_path) == row["trial_result_sha256"]
        trace_path = trial_dir / "events.jsonl.gz"
        assert digest(trace_path) == row["events_gzip_sha256"]
        trial_events = events(trace_path)
        fault = [event for event in trial_events if event.get("type") == "FAULT_APPLIED"]
        assert len(fault) == 1
        fault = fault[0]
        later_same_request_sends = [event for event in trial_events
                                    if event.get("type") == "SEND"
                                    and event.get("node") == fault.get("node")
                                    and event.get("epoch") == fault.get("epoch")
                                    and event.get("thread_id") == fault.get("thread_id")
                                    and event.get("occurrence") == fault.get("occurrence")
                                    and event["seq"] > fault["seq"]]
        assert not later_same_request_sends
        later_targets = [event for event in trial_events
                         if event.get("type") == "TARGET_CHECK"
                         and event.get("site") in exact and event.get("node") == actor
                         and event["seq"] > fault["seq"]]
        retained.append({"trial_id": trial_id, "trial_result_sha256": digest(trial_path),
                         "trace_gzip_sha256": digest(trace_path),
                         "fault_id": fault["id"], "fault_seq": fault["seq"],
                         "fault_node": fault["node"], "fault_site": fault["site"],
                         "later_same_thread_occurrence_send_count": 0,
                         "later_bound_actor_target_check_count": len(later_targets)})
    assert [row["trial_id"] for row in retained] == [1, 3, 6]
    source_text = SOURCE.read_text()
    assert "commit = delPol.getAndSaveCommitPoint(gen);" in source_text
    assert "private void getFileList(SolrParams solrParams, SolrQueryResponse rsp)" in source_text
    return {"schema_version": 1, "case_id": "SOLR-22",
            "classification": "bounded_no_current_same_request_injectable_door",
            "full_campaign_promoted": False,
            "result_sha256": digest(result_path), "offline_audit_sha256": digest(audit_path),
            "sync_receipt_sha256": digest(sync_path),
            "strict_sidecar_sha256": digest(strict_sidecar),
            "healthy_trace_gzip_sha256": digest(healthy_path),
            "healthy_bound_actor": actor, "healthy_bound_actor_door_count": len(server_doors),
            "healthy_bound_actor_door_to_target_path_count": 0,
            "healthy_client_request_path_witness_ids": strict["healthy_numeric_root_free_request_witness_ids"],
            "retained_but_unlinked_trials": retained,
            "source_review": {
                str(SOURCE): {"sha256": digest(SOURCE),
                              "finding": "getFileList parses generation and directly calls getAndSaveCommitPoint; no caught I/O operation precedes the selected guard inside this handler"},
                str(TARGET_SOURCE): {"sha256": digest(TARGET_SOURCE),
                                     "finding": "the selected knownCommits/deleted/latestCommit guard runs at method entry before reference-count update"}},
            "scope": "existing TestPullReplica#testAddDocs, v33g2p client request door; no claim about untested server/background fault models"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--strict-sidecar", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.campaign, args.strict_sidecar)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": report["classification"],
                      "retained_but_unlinked_trials": [row["trial_id"] for row in
                                                      report["retained_but_unlinked_trials"]]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
