#!/usr/bin/env python3
"""Classify a fresh SOLR-09 healthy trace and its physical command role."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import preflight

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
CORE = ROOT / "Mallory/adapters/solr/cases/SOLR-09/runtime-role-v1/work"
sys.path.insert(0, str(CORE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(out: Path) -> dict:
    trial = out / "trials/r0000"
    files = ("events.jsonl.gz", "sites.jsonl", "junit-receipt.json",
             "junit.log", "plan.json")
    digests = {name: sha(trial / name) for name in files}
    junit = json.loads((trial / "junit-receipt.json").read_text())
    plan = json.loads((trial / "plan.json").read_text())
    with gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    catalog = [json.loads(line) for line in (trial / "sites.jsonl").read_text().splitlines()]
    log = (trial / "junit.log").read_text(errors="replace")
    target_sites = [row for row in catalog if row.get("type") == "TARGET_CHECK"
                    and row.get("site") == preflight.CHECK]
    door_sites = [row for row in catalog if row.get("type") == "DOOR_OBSERVED"
                  and row.get("site") == preflight.DOOR]
    manifest = json.loads((HERE / "manifest.json").read_text())
    class_identity = (len(target_sites) == len(door_sites) == 1 and
                      target_sites[0].get("bytecode_sha256") == manifest["classes"]["target"] and
                      door_sites[0].get("bytecode_sha256") == manifest["classes"]["door_owner"])
    passed = (junit.get("status") == "passed" and junit.get("tests") == 1 and
              junit.get("failures") == junit.get("errors") == 0)
    no_fault = (plan.get("faults") == [] and not any(
        row.get("type") in ("FAULT_MATCHED", "FAULT_APPLIED") for row in events))
    no_throw = not any(row.get("type") == "TARGET_THROW" and
                       row.get("site", "").startswith(preflight.CHECK.rsplit("@", 1)[0])
                       for row in events)
    checks = [row for row in events if row.get("type") == "TARGET_CHECK"
              and row.get("site") == preflight.CHECK]
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
             and row.get("site") == preflight.DOOR and
             row.get("exception_class") == "java.util.concurrent.TimeoutException"]
    matches = []
    for check in checks:
        for door in doors:
            fields = ("node", "epoch", "thread_id", "occurrence", "context")
            if not (door.get("seq", -1) < check.get("seq", -1) and
                    all(door.get(key) == check.get(key) for key in fields)):
                continue
            node = door.get("node", "")
            named = (bool(re.fullmatch(r"node[0-9]+", node)) and
                     f"MALLORY_SOLR_NODE logical={node}" in log)
            role = (door.get("role") == preflight.ROLE and
                    door.get("role_resolution") == "unique" and
                    door.get("role_node") == node and
                    door.get("role_epoch") == door.get("epoch") and
                    door.get("role_source_occurrence") == door.get("occurrence") and
                    isinstance(door.get("role_ordinal"), int) and
                    door["role_ordinal"] > 0)
            region = next((row for row in events if row.get("type") == "REGION_ENTER" and
                           row.get("occurrence") == check.get("occurrence") and
                           row.get("seq", -1) < door.get("seq", -1)), None)
            parent = next((row for row in events if row.get("type") == "REGION_ENTER" and
                           region is not None and row.get("occurrence") == region.get("parent_id") and
                           row.get("seq", -1) < region.get("seq", -1)), None)
            handoff = (region is not None and parent is not None and
                       "OverseerCollectionMessageHandler#processMessage" in parent.get("site", "") and
                       parent.get("node") == node and parent.get("thread_id") == door.get("thread_id"))
            graph = OccurrenceGraph(events, reject_coarse_roots=True)
            path = graph.event_path(door, check, require_edge=True)
            matches.append({"check_event_id": check.get("id"), "door_event_id": door.get("id"),
                            "node": node, "epoch": door.get("epoch"),
                            "thread_id": door.get("thread_id"),
                            "occurrence": door.get("occurrence"),
                            "role_ordinal": door.get("role_ordinal"),
                            "target_outcome": check.get("outcome"),
                            "physical_registration": named,
                            "unique_role_binding": role,
                            "overseer_parent_handoff": handoff,
                            "nonempty_door_to_target_graph_path": path is not None})
    admitted = (passed and no_fault and no_throw and class_identity and
                any(row["physical_registration"] and row["unique_role_binding"] and
                    row["overseer_parent_handoff"] and row["target_outcome"] == "TAKEN"
                    for row in matches))
    return {"schema_version": 1, "case_id": "SOLR-09",
            "status": "healthy_role_admitted" if admitted else "healthy_role_gap",
            "junit_passed_1_of_1": passed, "no_fault": no_fault,
            "no_target_throw": no_throw, "class_identity": class_identity,
            "exact_target_count": len(checks), "typed_door_count": len(doors),
            "same_occurrence_candidates": matches, "evidence_sha256": digests,
            "limit": "A healthy role match supports a separately admitted bounded pilot; it does not prove the line-278 throw or a nonempty graph path."}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_healthy.py OUTPUT_DIR")
    print(json.dumps(summarize(Path(sys.argv[1])), indent=2, sort_keys=True))
