#!/usr/bin/env python3
"""Audit a SOLR-16 healthy split with a path-qualified leader lookup witness."""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

REGION = ("org.apache.solr.cloud.api.collections.SplitShardCmd#split("
          "Lorg/apache/solr/common/cloud/ClusterState;"
          "Lorg/apache/solr/common/cloud/ZkNodeProps;"
          "Lorg/apache/solr/common/util/NamedList;)Z")
FIRST = REGION + "@164:door:2"
SECOND = REGION + "@523:door:3"
NATIVE = ("org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2("
          "Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
          "Lorg/apache/zookeeper/data/Stat;@301:door:1")
CHECK = REGION + "@539:branch:41"
THROW = REGION + "@543:throw:1"
PHYSICAL = re.compile(r"(?:node[1-9][0-9]*|shard-[1-9][0-9]*|control)")
LIVE_NODE = re.compile(r"/live_nodes/[^/]+")


def identity(event: dict) -> tuple:
    return tuple(event.get(key) for key in
                 ("node", "epoch", "occurrence", "thread_id", "context", "region"))


def lookup_witness(events: list[dict]) -> tuple[dict | None, str]:
    """Bind both stat reads to one split and the same parent live-node path."""
    sequenced = [event for event in events if isinstance(event.get("seq"), int)]
    doors = [event for event in sequenced if event.get("type") == "DOOR_OBSERVED"
             and event.get("site") in {FIRST, SECOND, NATIVE}]
    pathless = False
    for second in doors:
        if second["site"] != SECOND or not PHYSICAL.fullmatch(str(second.get("node", ""))):
            continue
        key = identity(second)
        if key[-1] != REGION or not isinstance(key[2], str) or not key[2]:
            continue
        same = sorted((event for event in sequenced if identity(event) == key),
                      key=lambda event: event["seq"])
        firsts = [event for event in same if event.get("site") == FIRST
                  and event.get("type") == "DOOR_OBSERVED"
                  and event["seq"] < second["seq"]]
        if len(firsts) != 1:
            continue
        first = firsts[0]
        first_index = same.index(first)
        second_index = same.index(second)
        if first_index + 1 >= len(same) or second_index + 1 >= len(same):
            continue
        first_native = same[first_index + 1]
        second_native = same[second_index + 1]
        if (first_native.get("type") != "DOOR_OBSERVED"
                or first_native.get("site") != NATIVE
                or first_native["seq"] >= second["seq"]
                or second_native.get("type") != "DOOR_OBSERVED"
                or second_native.get("site") != NATIVE):
            continue
        resources = {first_native.get("resource"), second_native.get("resource")}
        witness = {"actor": second["node"], "epoch": second["epoch"],
                   "split_occurrence": second["occurrence"],
                   "thread_id": second["thread_id"], "context": second["context"],
                   "first_caller_event_id": first.get("id"),
                   "second_caller_event_id": second.get("id"),
                   "first_native_event_id": first_native.get("id"),
                   "second_native_event_id": second_native.get("id")}
        if len(resources) == 1:
            resource = next(iter(resources))
            if isinstance(resource, str) and LIVE_NODE.fullmatch(resource):
                witness["parent_live_node_resource"] = resource
                return witness, "bound"
        pathless = pathless or None in resources
    return None, "resource_missing" if pathless else "same_split_path_handoff_missing"


def attest(output: Path) -> dict:
    result = json.loads((output / "result.json").read_text())
    trial = json.loads((output / "trials/r0000/result.json").read_text())
    catalog = {row.get("site") for line in
               (output / "trials/r0000/sites.jsonl").read_text().splitlines()
               if (row := json.loads(line))}
    with gzip.open(output / "trials/r0000/events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream if line.strip()]
    junit = result.get("healthy_junit_validation") or {}
    validation = trial.get("site_catalog_validation") or {}
    feedback = trial.get("feedback") or {}
    witness, identity_status = lookup_witness(events)
    reasons = []
    if not (junit.get("status") == "passed" and junit.get("tests") == 1
            and junit.get("failures") == 0 and junit.get("errors") == 0):
        reasons.append("original_cluster_junit_not_1_0_0")
    if result.get("status") != "calibration_complete" or result.get("case_id") != "SOLR-16":
        reasons.append("healthy_campaign_not_complete")
    if trial.get("plan") != [] or result.get("fault_trials_completed") != 0:
        reasons.append("healthy_trace_contains_faults")
    if feedback.get("trace_truncated") is not False or any(
            event.get("type") == "TRACE_TRUNCATED" for event in events):
        reasons.append("healthy_trace_incomplete")
    if validation.get("valid") is not True or validation.get("class_hash_match") is not True:
        reasons.append("loaded_target_class_or_catalog_unattested")
    if not {FIRST, SECOND, NATIVE, CHECK, THROW}.issubset(catalog):
        reasons.append("exact_target_or_typed_door_catalog_missing")
    if not any(event.get("type") == "DOOR_OBSERVED" and event.get("site") == NATIVE
               for event in events):
        reasons.append("typed_native_exists_door_not_observed")
    if witness is None:
        reasons.append(identity_status)
    return {"schema_version": 1, "case_id": "SOLR-16",
            "variant": "chaos-healthy-node2-v1",
            "status": "passed" if not reasons else "failed", "reasons": reasons,
            "original_junit": junit, "exact_check_site": CHECK, "exact_throw_site": THROW,
            "typed_fault_door": NATIVE, "identity_status": identity_status,
            "same_split_identity_witness": witness,
            "healthy_exact_check_reached": bool(feedback.get("target_check_reached")),
            "healthy_exact_throw_reached": bool(feedback.get("target_threw")),
            "resource_path_attested": witness is not None,
            "full_campaign_admitted": False,
            "note": "A healthy target throw is an expected protective abort in this JUnit, not a bug finding."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = attest(args.output)
    (args.output / "solr16-chaos-healthy-gate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
