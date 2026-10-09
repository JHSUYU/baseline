#!/usr/bin/env python3
"""Independently classify the single SOLR-09 pilot's unmatched replay."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from audit_healthy import CHECK, DOOR, one, require
from Mallory.core.graph import OccurrenceGraph


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence/node2-lane3-timeout-r0001"
EXPECTED = {
    "events.jsonl.gz": "297c17ca6b754f374e7fe2e9f3e15ceadc5627a0da03f38e68591eb0f3a2333e",
    "junit-receipt.json": "1613474620dc0eaaa523e84de369dde4b6e1e0e3076f08a367217b5e5b923ee9",
    "junit.log": "1496f94b273272beeb85518499c78be0f91612a416854ee90df6bcb2caf5ed7d",
    "pilot-result.json": "a137109977a90509e255776e714b5e508c3a77ddd19d6a8d3dc368db478b3151",
    "pilot-terminal.json": "562622b39748b23dbaa8f8a483538786766562f7b732a9d054f52e57d29aaaac",
    "plan.json": "f9dd09137887a4c59e46047a9be9bae447595193509fdf728fc7c1c7eaef0d80",
    "result.json": "db654d9a3883607b9ba97ac4fbcd23775e4ce2ea3bf2e18d353b39120313bf41",
    "sites.jsonl": "4097d59a663abd18b1ed014bc8ce090dd9adc5759178ebd47cda22610f866d26",
    "stderr.log": "873250ea768fde1c17fa87b172d233dfc5361a7c6830227a0ec656eeddc3bc14",
    "stdout.log": "757820fbdabf6c000f346a5bde57ee818e647a54c3ac0bec4d65eec8a847be6c",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for name, expected in EXPECTED.items():
        require(sha(EVIDENCE / name) == expected, f"raw evidence SHA mismatch: {name}")
    manifest = json.loads((HERE / "manifest-pilot-node2-lane3.json").read_text())
    for name, entry in manifest["files"].items():
        require(sha(Path(entry["path"])) == entry["sha256"],
                f"pilot input SHA mismatch: {name}")
    healthy = json.loads((HERE / "healthy-audit-node2-lane3.json").read_text())
    plan = json.loads((EVIDENCE / "plan.json").read_text())
    staged = json.loads((HERE / "pilot-plan-node2-lane3.json").read_text())
    require(plan == staged and len(plan["faults"]) == 1, "executed fault plan changed")
    point = plan["faults"][0]["point"]
    require(point == {"site": DOOR, "node": "node4", "epoch": 0,
                      "door_ordinal": 1}, "expected replay point changed")

    with gzip.open(EVIDENCE / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = tuple(json.loads(line) for line in stream)
    ids = [event["id"] for event in events if event.get("id")]
    require(len(ids) == len(set(ids)), "duplicate raw event IDs")
    door = one([e for e in events if e.get("type") == "DOOR_OBSERVED"
                and e.get("site") == DOOR], "exact typed wait door")
    check = one([e for e in events if e.get("type") == "TARGET_CHECK"
                 and e.get("site") == CHECK], "exact target check")
    require(not any(e.get("type") in ("FAULT_MATCHED", "FAULT_APPLIED", "TARGET_THROW")
                    for e in events), "unexpected applied fault or target throw")
    require(door["door_ordinal"] == 1 and door["exception_class"] ==
            "java.util.concurrent.TimeoutException", "door identity changed")
    require(door["seq"] < check["seq"] and check["outcome"] == "TAKEN",
            "target order or branch changed")
    for field in ("node", "epoch", "thread_id", "occurrence", "context"):
        require(door[field] == check[field], f"raw door/check {field} mismatch")
    require(door["node"] == "node2" and door["epoch"] == 0 and
            door["thread_id"] == 215, "postrun actor identity changed")
    require(healthy["target"]["node"] == point["node"] == "node4" and
            door["node"] != point["node"], "actor drift not established")

    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    require(graph.event_path(door, check, require_edge=False) == (),
            "same-occurrence temporal path changed")
    require(graph.event_path(door, check, require_edge=True) is None,
            "unexpected nonempty graph edge path")
    catalog = [json.loads(row) for row in (EVIDENCE / "sites.jsonl").read_text().splitlines()]
    target_site = one([row for row in catalog if row.get("type") == "TARGET_CHECK"
                       and row.get("site") == CHECK], "target catalog entry")
    door_site = one([row for row in catalog if row.get("type") == "DOOR_OBSERVED"
                     and row.get("site") == DOOR], "door catalog entry")
    source_manifest = json.loads((HERE / "manifest-node2-lane3.json").read_text())
    require(target_site["bytecode_sha256"] == source_manifest["compiled_classes"]
            ["core_jar"]["org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"],
            "target class SHA changed")
    require(door_site["bytecode_sha256"] == source_manifest["compiled_classes"]
            ["core_jar"]["org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler.class"],
            "door owner class SHA changed")
    require(target_site["class_loader_id"] == door_site["class_loader_id"],
            "class loader mismatch")

    junit = json.loads((EVIDENCE / "junit-receipt.json").read_text())
    result = json.loads((EVIDENCE / "result.json").read_text())
    terminal = json.loads((EVIDENCE / "pilot-terminal.json").read_text())
    require(junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == 0, "JUnit terminal changed")
    require(result["feedback"]["status"] == "fault_unmatched" and
            result["feedback"]["target_reached"] is False and
            result["feedback"]["all_faults_applied"] is False,
            "runner's bound-target classification changed")
    require(terminal["trial_result_sha256"] == EXPECTED["result.json"] and
            terminal["plan_sha256"] == manifest["files"]["plan"]["sha256"] and
            terminal["config_sha256"] == manifest["files"]["config"]["sha256"],
            "terminal input/output pins changed")
    require("MALLORY_SOLR_NODE logical=node2" in (EVIDENCE / "junit.log").read_text(),
            "observed node2 registration marker missing")

    receipt = {
        "schema_version": 1,
        "case_id": "SOLR-09",
        "status": "negative_unmatched_actor_drift_exact_target_present",
        "evidence_sha256": EXPECTED,
        "source_commit": manifest["source_commit"],
        "junit": "passed_1_of_1",
        "planned_fault": plan["faults"][0],
        "fault_matched": False,
        "fault_applied": False,
        "observed_door": {"event_id": door["id"], "seq": door["seq"],
                          "node": door["node"], "epoch": door["epoch"],
                          "thread_id": door["thread_id"],
                          "occurrence": door["occurrence"],
                          "door_ordinal": door["door_ordinal"]},
        "observed_target": {"event_id": check["id"], "seq": check["seq"],
                            "node": check["node"], "epoch": check["epoch"],
                            "thread_id": check["thread_id"],
                            "occurrence": check["occurrence"],
                            "outcome": check["outcome"]},
        "door_to_target": {"same_actor_epoch_thread_occurrence": True,
                           "local_ordered_timeline": True,
                           "nonempty_event_time_graph_path": False},
        "classification": "The planned node4 replay did not match the node2 actor. The exact target did execute in the raw trace; the runner's bound-node target_reached=false is a replay-filter result, not target disappearance. No exception was injected, so this is not a recovery experiment.",
    }
    (HERE / "unmatched-pilot-audit-node2-lane3.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": receipt["status"],
                      "door": door["id"], "target": check["id"]}, sort_keys=True))


if __name__ == "__main__":
    main()
