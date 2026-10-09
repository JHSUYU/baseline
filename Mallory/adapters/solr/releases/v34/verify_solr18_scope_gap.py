#!/usr/bin/env python3
"""Bind the SOLR-18 v34 instrumentation gap to raw healthy evidence."""

from __future__ import annotations

from collections import Counter
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph

BASE = Path("/users/ZhenyuLi/baseline")
CAMPAIGN = BASE / "data/mallory/calibration_v34_lane1/SOLR-18"
OUT = BASE / "data/mallory/quality_reviews/solr18_v34_gap/SOLR-18.json"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return digest(path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true",
                        help="Recompute the receipt without changing evidence")
    args = parser.parse_args()
    result = json.loads((CAMPAIGN / "result.json").read_text())
    audit = json.loads((CAMPAIGN / "offline-causal-audit.json").read_text())
    config = json.loads((CAMPAIGN / "config.json").read_text())
    assert result["case_id"] == audit["case_id"] == config["case_id"] == "SOLR-18"
    assert result["status"] == "calibration_complete"
    assert result["healthy_junit_validation"]["status"] == "passed"
    trace_path = CAMPAIGN / "trials/r0000/events.jsonl.gz"
    packed = trace_path.read_bytes()
    raw = gzip.decompress(packed)
    events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
    exact = set(config["target"]["check_sites"])
    checks = [event for event in events if event.get("type") == "TARGET_CHECK"
              and event.get("site") in exact]
    named_node2 = [event for event in checks if event.get("node") == "node2"]
    unknown = [event for event in checks if event.get("node") == "unknown"]
    doors = [event for event in events if event.get("type") == "DOOR_OBSERVED"
             and event.get("node") not in ("unknown", "", None)
             and isinstance(event.get("thread_id"), int)]
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    positive = sum(bool(graph.event_path(door, check, require_edge=True))
                   for door in doors for check in named_node2)
    assert len(unknown) == 3 and positive == 0
    assert {event.get("context") for event in unknown} == {
        next(event["context"] for event in unknown)}
    source_files = {
        "solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java": "ProcessWatchWithExecutor.process submits watcher callback at line 876",
        "solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java": "AliasesManager.process then setIfNewer at lines 2302-2347",
        "core/src/test/org/apache/solr/cloud/AliasIntegrationTest.java": "existing test reads alias state through cluster client at line 462",
        "solrj/src/java/org/apache/solr/client/solrj/impl/BaseCloudSolrClient.java": "getZkStateReader returns provider field at line 288",
    }
    receipt = {
        "schema_version": 1,
        "case_id": "SOLR-18",
        "classification": "instrumentation_identity_and_causal_path_gap",
        "full_campaign_promoted": False,
        "new_bug": None,
        "healthy_result_sha256": sha_file(CAMPAIGN / "result.json"),
        "healthy_audit_sha256": sha_file(CAMPAIGN / "offline-causal-audit.json"),
        "sync_receipt_sha256": sha_file(CAMPAIGN / "sync-receipt.json"),
        "config_sha256": sha_file(CAMPAIGN / "config.json"),
        "trial_result_sha256": sha_file(CAMPAIGN / "trials/r0000/result.json"),
        "raw_trace_gzip_sha256": digest(packed),
        "raw_trace_sha256": digest(raw),
        "raw_trace_bytes": len(raw),
        "junit_status": result["healthy_junit_validation"]["status"],
        "exact_check_counts_by_actor": dict(sorted(Counter(event.get("node") for event in checks).items())),
        "unknown_target_ids": [event["id"] for event in unknown],
        "unknown_target_context": unknown[0]["context"],
        "unknown_target_thread_ids": sorted({event["thread_id"] for event in unknown}),
        "identity_gap_reason": "unregistered_receiver",
        "named_numeric_thread_door_count": len(doors),
        "named_node2_exact_check_count": len(named_node2),
        "root_free_time_respecting_door_to_node2_target_paths": positive,
        "graph_gaps": dict(sorted(graph.gaps.items())),
        "source_review": {name: {"sha256": sha_file(SOURCE / name), "finding": finding}
                          for name, finding in source_files.items()},
    }
    if args.verify_only:
        if not OUT.is_file() or json.loads(OUT.read_text()) != receipt:
            raise SystemExit("SOLR-18 scope-gap receipt differs from raw evidence")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt_sha256": sha_file(OUT),
                      "unknown_checks": len(unknown),
                      "root_free_paths": positive}, sort_keys=True))


if __name__ == "__main__":
    main()
