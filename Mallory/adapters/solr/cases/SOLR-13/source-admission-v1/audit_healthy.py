#!/usr/bin/env python3
"""Recompute SOLR-13 exact healthy target and typed-door graph admission."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[5]
sys.path.insert(0, str(BASE))

from Mallory.core.graph import OccurrenceGraph  # noqa: E402


EVIDENCE = HERE / "evidence/node2-lane3-r0000"
EXPECTED = {
    "campaign-result.json": "733e37b68f41db242c1c789cfd85d944ca3f94e069dbbbd3a23ec858faa0e05d",
    "events.jsonl.gz": "c48498d3d826faf445d3a5fa10b64b47e695678e26fb5f8062d6a0c8bade0f0e",
    "junit-receipt.json": "d96555fed73346fb4344e1f528678aad8bbb9bf0af804054f2cb376544d7355c",
    "junit.log": "0344b41475ed0b15e56c12ee1daf5dc1b34dd3e3e69f7d964b132f44dac22ddf",
    "pilot-result.json": "18463e2fd73f7c5cdf30c9ff50776db9bfdf61326e5ec341936803a82af11d46",
    "plan.json": "befe80c16068de989642fa02430d10590dff17d611607841432aa31763aa3b22",
    "result.json": "32e73359aa23526d0d3fe4a4b02dbd46afc637f70256b225445c71f5dbe48798",
    "sites.jsonl": "70f5a35f54b5233296ce0aaf48fcc9bec70531a2f9ef3a23f9e2bb253b562374",
}
CHECK = "org.apache.solr.cloud.api.collections.RoutedAlias#doSynchronous(Lorg/apache/solr/update/AddUpdateCommand;Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;Lorg/apache/solr/core/CoreContainer;)Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;@348:branch:1"
DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1"


def require(value: bool, message: str) -> None:
    if not value:
        raise SystemExit(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one(rows: list[dict], name: str) -> dict:
    require(len(rows) == 1, f"expected exactly one {name}; got {len(rows)}")
    return rows[0]


def main() -> None:
    for name, expected in EXPECTED.items():
        require(sha(EVIDENCE / name) == expected, f"raw evidence SHA mismatch: {name}")
    manifest = json.loads((HERE / "manifest.json").read_text())
    for name, record in manifest["files"].items():
        require(sha(Path(record["path"])) == record["sha256"],
                f"pinned source or runtime input SHA mismatch: {name}")
    config = json.loads((HERE / "healthy-node2-lane3.json").read_text())
    require(config["target"]["check_sites"] == [CHECK], "target selector changed")
    require(config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True,
            "strict graph flags changed")
    require(json.loads((EVIDENCE / "plan.json").read_text())["faults"] == [],
            "healthy trial had a fault plan")

    with gzip.open(EVIDENCE / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = tuple(json.loads(line) for line in stream)
    ids = [event["id"] for event in events if event.get("id")]
    require(len(ids) == len(set(ids)), "duplicate event IDs")
    checks = [e for e in events if e.get("type") == "TARGET_CHECK" and
              e.get("site") == CHECK]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             e.get("site") == DOOR]
    require(len(checks) == 5 and len(doors) == 20,
            "exact target or typed door count changed")
    require(not any(e.get("type") in ("TARGET_THROW", "FAULT_MATCHED", "FAULT_APPLIED")
                    for e in events), "healthy run contains a throw or fault")
    require([e["seq"] for e in checks] == [664, 755, 1141, 1232, 5153],
            "target sequence changed")
    require([(e["node"], e["epoch"], e["thread_id"]) for e in checks] ==
            [("node1", 0, 222)] * 4 + [("node4", 0, 211)],
            "target actor sequence changed")
    require(all(e["node"] == "node1" and e["epoch"] == 0 and
                e["exception_class"] ==
                "org.apache.zookeeper.KeeperException$BadVersionException"
                for e in doors), "typed Overseer door actor or class changed")
    require([e["door_ordinal"] for e in doors] == list(range(1, 21)),
            "typed door ordinals changed")
    require(all(e["outcome"] == "TAKEN" for e in checks),
            "healthy target branch changed")

    catalog = [json.loads(row) for row in (EVIDENCE / "sites.jsonl").read_text().splitlines()]
    target_site = one([row for row in catalog if row.get("type") == "TARGET_CHECK"
                       and row.get("site") == CHECK], "target catalog row")
    door_site = one([row for row in catalog if row.get("type") == "DOOR_OBSERVED"
                     and row.get("site") == DOOR], "typed door catalog row")
    require(target_site["bytecode_sha256"] == manifest["compiled_classes"]
            ["solr-core-8.11.4.jar"]["org/apache/solr/cloud/api/collections/RoutedAlias.class"],
            "loaded target class SHA mismatch")
    require(door_site["bytecode_sha256"] == manifest["compiled_classes"]
            ["solr-solrj-8.11.4.jar"][
                "org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class"],
            "loaded door owner class SHA mismatch")
    require(target_site["class_loader_id"] == door_site["class_loader_id"],
            "target/door class loader differs")

    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    nearby = []
    for check in checks:
        enter = one([e for e in events if e.get("type") == "REGION_ENTER"
                     and e.get("occurrence") == check["occurrence"]],
                    "selected doSynchronous region entry")
        candidates = [door for door in doors if enter["seq"] < door["seq"] < check["seq"]]
        require(len(candidates) == 1, "target region lacks unique temporal candidate")
        door = candidates[0]
        require(graph.event_path(door, check, require_edge=True) is None,
                "candidate unexpectedly has observed event-time graph path")
        nearby.append({"target_event": check["id"], "target_seq": check["seq"],
                       "target_node": check["node"], "target_thread": check["thread_id"],
                       "target_occurrence": check["occurrence"],
                       "region_enter_event": enter["id"],
                       "door_event": door["id"], "door_seq": door["seq"],
                       "door_node": door["node"], "door_thread": door["thread_id"],
                       "door_context": door["context"],
                       "door_ordinal": door["door_ordinal"],
                       "nonempty_event_time_graph_path": False})
    require([row["door_seq"] for row in nearby] == [647, 738, 1124, 1215, 5136],
            "temporal pairing changed")
    require(not any(graph.event_path(door, check, require_edge=True) is not None
                    for door in doors for check in checks if door["seq"] < check["seq"]),
            "some typed door unexpectedly reaches an exact target")

    campaign = json.loads((EVIDENCE / "campaign-result.json").read_text())
    result = json.loads((EVIDENCE / "result.json").read_text())
    pilot = json.loads((EVIDENCE / "pilot-result.json").read_text())
    junit = json.loads((EVIDENCE / "junit-receipt.json").read_text())
    require(campaign["status"] == "calibration_complete" and
            campaign["calibration_only"] is True and
            campaign["fault_trials_completed"] == 0 and
            campaign["runtime_attestation"]["valid"] is True,
            "campaign healthy terminal changed")
    require(junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == 0,
            "original JUnit did not pass")
    require(pilot["target_check_count"] == 5 and
            pilot["target_throw_count"] == 0 and
            pilot["source_revision"] == manifest["source_commit"],
            "pilot target/source summary changed")
    require(result["feedback"]["status"] == "observed" and
            result["feedback"]["target_reached"] is True and
            result["feedback"]["target_threw"] is False,
            "feedback target status changed")
    selected_doors = [row for row in result["feedback"]["doors"] if
                      row.get("site") == DOOR]
    require(len(selected_doors) == 16 and
            not any(row.get("in_closure") for row in selected_doors),
            "typed door feedback closure changed")
    require(campaign["healthy_local_timeline_doors"] == 0,
            "unexpected same-occurrence typed door path")
    require("MALLORY_SOLR_NODE logical=node1" in (EVIDENCE / "junit.log").read_text()
            and "MALLORY_SOLR_NODE logical=node4" in (EVIDENCE / "junit.log").read_text(),
            "registered target actor marker missing")

    receipt = {
        "schema_version": 1,
        "case_id": "SOLR-13",
        "status": "healthy_junit_and_exact_target_with_cross_actor_graph_gap",
        "source_commit": manifest["source_commit"],
        "evidence_sha256": EXPECTED,
        "junit": "passed_1_of_1",
        "faults_applied": 0,
        "target_check_count": len(checks),
        "target_throw_count": 0,
        "typed_door_count": len(doors),
        "target_class_sha256": target_site["bytecode_sha256"],
        "door_class_sha256": door_site["bytecode_sha256"],
        "class_loader": target_site["class_loader_id"],
        "temporal_candidates": nearby,
        "observed_graph": graph.summary(),
        "limit": "Each exact target region contains one earlier typed alias-write door, but its Overseer task context is distinct from the target request context. No typed door has a nonempty event-time graph path to any selected target. Temporal pairing and alias-name similarity do not establish a unique request/reply or task-token link. No fault/full admission follows.",
    }
    (HERE / "healthy-audit-node2-lane3.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": receipt["status"],
                      "target_checks": len(checks), "typed_doors": len(doors),
                      "admitted_door_paths": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
