#!/usr/bin/env python3
"""Recompute the SOLR-09 node2 healthy event path from SHA-pinned raw files."""

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
    "campaign-result.json": "1ab32cdc21a5d9dcd970cd2b5a4281976e7032ea288035cdd074a0af51d64963",
    "events.jsonl.gz": "4206e33d696a968c8e4eb2fbb66f427cd649f859794629a0f6ae07d21d9c12d3",
    "junit-receipt.json": "6271c5387b02cf8a1147963fcd810bdc99c473bf431e5c27e7a210eacb0b5e7b",
    "junit.log": "568a06476ec36e16c0e48155bbcf62ff1e53d1e96a2da2b5cd22520ee3483e85",
    "pilot-result.json": "4814430aaf1c60256c691bce5aab090d162e167e71d25845642f47db550ea837",
    "plan.json": "befe80c16068de989642fa02430d10590dff17d611607841432aa31763aa3b22",
    "result.json": "b57b55becdae8edffaf3682b5cb26f208856568fa5ac248fa794802e8dc3eeb6",
    "sites.jsonl": "4097d59a663abd18b1ed014bc8ce090dd9adc5759178ebd47cda22610f866d26",
}
CHECK = "org.apache.solr.cloud.api.collections.DeleteReplicaCmd#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;Ljava/lang/String;Lorg/apache/solr/common/cloud/ZkNodeProps;Ljava/lang/String;Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V@277:branch:7"
DOOR = "org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1"


def require(value: bool, message: str) -> None:
    if not value:
        raise SystemExit(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def one(rows: list[dict], description: str) -> dict:
    require(len(rows) == 1, f"expected one {description}; got {len(rows)}")
    return rows[0]


def source_line(path: Path, line: int, fragment: str) -> None:
    lines = path.read_text().splitlines()
    require(line <= len(lines) and fragment in lines[line - 1],
            f"pinned source control flow changed at {path.name}:{line}")


def main() -> None:
    for name, expected in EXPECTED.items():
        path = EVIDENCE / name
        require(path.is_file() and sha(path.read_bytes()) == expected,
                f"missing or changed raw evidence: {name}")

    manifest = json.loads((HERE / "manifest-node2-lane3.json").read_text())
    for name in ("target_source", "overseer_source", "test_source",
                 "zk_state_reader_source", "core_jar", "solrj_jar",
                 "config", "sites", "runner_shell"):
        record = manifest["files"][name]
        require(sha(Path(record["path"]).read_bytes()) == record["sha256"],
                f"source SHA mismatch: {name}")
    target_source = Path(manifest["files"]["target_source"]["path"])
    overseer_source = Path(manifest["files"]["overseer_source"]["path"])
    for line, fragment in ((251, "sendShardRequest"), (257, "processResponses(results, shardHandler, false"),
                           (260, "waitForCoreNodeGone"), (264, "deleteCoreNode"),
                           (265, "waitForCoreNodeGone"), (266, "return Boolean.FALSE"),
                           (267, "catch (Exception e)"), (277, "if (!callable.call())"),
                           (278, "throw new SolrException"),
                           (282, "catch (Exception ex)")):
        source_line(target_source, line, fragment)
    for line, fragment in ((434, "zkStateReader.waitForState"),
                           (443, "catch (TimeoutException e)"),
                           (444, "return false"), (452, "OverseerAction.DELETECORE"),
                           (457, "offerStateUpdate")):
        source_line(overseer_source, line, fragment)

    with gzip.open(EVIDENCE / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = tuple(json.loads(line) for line in stream)
    ids = [event.get("id") for event in events if event.get("id")]
    require(len(ids) == len(set(ids)), "duplicate raw event IDs")
    check = one([event for event in events if event.get("type") == "TARGET_CHECK"
                 and event.get("site") == CHECK], "exact target check")
    door = one([event for event in events if event.get("type") == "DOOR_OBSERVED"
                and event.get("site") == DOOR], "typed wait door")
    require(not any(event.get("type") in ("TARGET_THROW", "FAULT_MATCHED", "FAULT_APPLIED")
                    for event in events), "healthy run contains a target throw or fault")
    require(check["seq"] > door["seq"], "door did not precede target")
    for field in ("node", "epoch", "thread_id", "occurrence", "context"):
        require(door.get(field) == check.get(field), f"door/target {field} mismatch")
    require(check["node"] == "node4" and check["epoch"] == 0
            and check["thread_id"] == 217, "observed target actor changed")
    require(door.get("door_ordinal") == 1 and
            door.get("exception_class") == "java.util.concurrent.TimeoutException",
            "typed wait door identity changed")
    require(check.get("outcome") == "TAKEN", "healthy target branch changed")

    parent = one([event for event in events if event.get("type") == "REGION_ENTER"
                  and "OverseerCollectionMessageHandler#processMessage" in event.get("site", "")
                  and event.get("occurrence") == next(
                      (row.get("parent_id") for row in events
                       if row.get("type") == "REGION_ENTER" and
                       row.get("occurrence") == check["occurrence"]), None)],
                 "Overseer command parent")
    child = one([event for event in events if event.get("type") == "REGION_ENTER"
                 and event.get("occurrence") == check["occurrence"]], "deleteCore region")
    require(parent["seq"] < child["seq"] < door["seq"] < check["seq"],
            "parent/child/door/check sequence changed")

    token = check["context"]
    submit = one([event for event in events if event.get("type") == "TASK_SUBMIT"
                  and event.get("correlation") == token], "Overseer task submit")
    claim = one([event for event in events if event.get("type") == "TASK_CLAIM"
                 and event.get("correlation") == token], "Overseer task claim")
    require(submit["seq"] < claim["seq"] < parent["seq"] and
            submit["node"] == claim["node"] == parent["node"] and
            claim["thread_id"] == parent["thread_id"] and
            parent["parent_id"] == token and
            child["parent_id"] == parent["occurrence"],
            "Overseer token/actor handoff changed")

    catalog = [json.loads(line) for line in (EVIDENCE / "sites.jsonl").read_text().splitlines()]
    target_site = one([row for row in catalog if row.get("type") == "TARGET_CHECK"
                       and row.get("site") == CHECK], "target class catalog entry")
    door_site = one([row for row in catalog if row.get("type") == "DOOR_OBSERVED"
                     and row.get("site") == DOOR], "door class catalog entry")
    require(target_site["bytecode_sha256"] ==
            manifest["compiled_classes"]["core_jar"][
                "org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"],
            "target bytecode SHA mismatch")
    require(door_site["bytecode_sha256"] ==
            manifest["compiled_classes"]["core_jar"][
                "org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler.class"],
            "door owner bytecode SHA mismatch")
    require(target_site["class_loader_id"] == door_site["class_loader_id"],
            "target/door loader mismatch")

    campaign = json.loads((EVIDENCE / "campaign-result.json").read_text())
    trial = json.loads((EVIDENCE / "result.json").read_text())
    pilot = json.loads((EVIDENCE / "pilot-result.json").read_text())
    junit = json.loads((EVIDENCE / "junit-receipt.json").read_text())
    require(json.loads((EVIDENCE / "plan.json").read_text())["faults"] == [],
            "trial had a fault plan")
    require(campaign["calibration_only"] is True and
            campaign["status"] == "calibration_complete" and
            campaign["fault_trials_completed"] == 0, "not a healthy-only terminal")
    require(junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == 0,
            "original JUnit did not pass")
    require(pilot["target_check_count"] == 1 and
            pilot["target_throw_count"] == 0 and
            pilot["source_revision"] == manifest["source_commit"],
            "pilot target/source summary changed")
    require(campaign["runtime_attestation"]["valid"] is True and
            campaign["runtime_attestation"]["target_identity_gap_count"] == 0,
            "runtime target identity gap")
    require("MALLORY_SOLR_NODE logical=node4" in (EVIDENCE / "junit.log").read_text(),
            "node4 registration marker missing")

    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    parents = [edge for edge in graph.edges if edge.kind == "region_parent" and
               edge.producer_event == parent["id"] and
               edge.consumer_event == child["id"]]
    require(len(parents) == 1, "named parent edge missing")
    require(graph.event_path(door, check, require_edge=False) == (),
            "same-occurrence temporal witness missing")
    require(graph.event_path(door, check, require_edge=True) is None,
            "door unexpectedly has a nonempty graph path")
    feedback = trial["feedback"]
    selected_doors = [row for row in feedback["doors"] if row["event_id"] == door["id"]]
    require(len(selected_doors) == 1 and selected_doors[0]["in_closure"] and
            selected_doors[0]["local_timeline_evidence"]["target_check_event_id"] == check["id"],
            "feedback did not retain typed local timeline")
    require(feedback["require_event_time_paths"] is True and
            feedback["reject_coarse_roots"] is True,
            "strict feedback flags missing")

    receipt = {
        "schema_version": 1,
        "case_id": "SOLR-09",
        "status": "healthy_exact_target_with_typed_local_timeline_graph_gap",
        "evidence_sha256": EXPECTED,
        "source_commit": manifest["source_commit"],
        "source_control_flow": {
            "unload_then_first_wait": "DeleteReplicaCmd.java:251,257,260",
            "timeout_catch_returns_false": "OverseerCollectionMessageHandler.java:434,443-444",
            "fallback_queue_then_second_wait": "DeleteReplicaCmd.java:264-266; OverseerCollectionMessageHandler.java:450-457",
            "selected_guard": "DeleteReplicaCmd.java:275-283",
            "verified_source_sha256": {name: manifest["files"][name]["sha256"]
                                       for name in ("target_source", "overseer_source")},
        },
        "junit": "passed_1_of_1",
        "faults_applied": 0,
        "target": {"event_id": check["id"], "seq": check["seq"],
                   "node": check["node"], "epoch": check["epoch"],
                   "thread_id": check["thread_id"], "occurrence": check["occurrence"],
                   "class_sha256": target_site["bytecode_sha256"],
                   "loader": target_site["class_loader_id"],
                   "outcome": check["outcome"]},
        "typed_door": {"event_id": door["id"], "seq": door["seq"],
                       "site": door["site"], "ordinal": door["door_ordinal"],
                       "exception_class": door["exception_class"],
                       "class_sha256": door_site["bytecode_sha256"]},
        "overseer_handoff": {"token": token, "submit_event": submit["id"],
                              "claim_event": claim["id"],
                              "parent_region_event": parent["id"],
                              "delete_core_region_event": child["id"],
                              "observed_parent_edge": True},
        "door_to_target": {"same_actor_epoch_thread_occurrence": True,
                           "local_ordered_timeline": True,
                           "nonempty_event_time_graph_path": False},
        "limit": "The direct wait door has an empty-edge same-occurrence witness; the observed parent edge precedes the door and does not supply a door-to-target edge. No fault or full admission follows.",
    }
    (HERE / "healthy-audit-node2-lane3.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": receipt["status"], "target_event": check["id"],
                      "door_event": door["id"], "nonempty_graph_path": False},
                     sort_keys=True))


if __name__ == "__main__":
    main()
