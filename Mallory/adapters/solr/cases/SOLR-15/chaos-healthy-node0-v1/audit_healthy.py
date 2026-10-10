#!/usr/bin/env python3
"""Attest one fault-free chaos JUnit and an observed second leader lookup."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "chaos-target-discovery-v1"
spec = importlib.util.spec_from_file_location("solr15_original_healthy_audit",
                                             ORIGINAL / "audit_healthy.py")
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)

FIRST = "org.apache.solr.cloud.api.collections.SplitShardCmd#split(Lorg/apache/solr/common/cloud/ClusterState;Lorg/apache/solr/common/cloud/ZkNodeProps;Lorg/apache/solr/common/util/NamedList;)Z@164:door:2"
SECOND = "org.apache.solr.cloud.api.collections.SplitShardCmd#split(Lorg/apache/solr/common/cloud/ClusterState;Lorg/apache/solr/common/cloud/ZkNodeProps;Lorg/apache/solr/common/util/NamedList;)Z@523:door:3"
NATIVE = original.NATIVE


def _identity(event: dict) -> tuple:
    return (event.get("node"), event.get("epoch"), event.get("occurrence"),
            event.get("thread"), event.get("context"))


def attest(output: Path) -> dict:
    base = original.attest(output)
    trial = json.loads((output / "trials/r0000/result.json").read_text())
    result = json.loads((output / "result.json").read_text())
    relevant = []
    with gzip.open(output / "trials/r0000/events.jsonl.gz", "rt") as trace:
        for line in trace:
            event = json.loads(line)
            if event.get("type") == "DOOR_OBSERVED" and event.get("site") in {FIRST, SECOND, NATIVE}:
                relevant.append(event)
    first = [event for event in relevant if event["site"] == FIRST]
    second = [event for event in relevant if event["site"] == SECOND]
    native = [event for event in relevant if event["site"] == NATIVE]
    witness = None
    for later in second:
        key = _identity(later)
        if not re.fullmatch(r"node[1-9][0-9]*", str(key[0])):
            continue
        earlier = next((event for event in first
                        if _identity(event) == key and event["seq"] < later["seq"]), None)
        nested = next((event for event in native
                       if event.get("node") == later.get("node")
                       and event.get("epoch") == later.get("epoch")
                       and event.get("thread") == later.get("thread")
                       and event.get("context") == later.get("context")
                       and event["seq"] > later["seq"]), None)
        if earlier and nested:
            witness = {"first_caller_event_id": earlier["id"],
                       "second_caller_event_id": later["id"],
                       "native_exists_event_id": nested["id"],
                       "node": key[0], "epoch": key[1],
                       "split_occurrence": key[2], "thread": key[3],
                       "context": key[4]}
            break
    reasons = list(base["reasons"])
    if result.get("status") != "calibration_complete":
        reasons.append("healthy_campaign_not_terminal_calibration")
    if trial.get("plan") != [] or result.get("fault_trials_completed") != 0:
        reasons.append("healthy_trace_contains_fault_plan_or_fault_trial")
    if trial.get("feedback", {}).get("trace_truncated") is not False:
        reasons.append("healthy_trace_truncated_or_unattested")
    if witness is None:
        reasons.append("same_split_first_second_and_native_exists_handoff_missing")
    return {"schema_version": 1, "case_id": "SOLR-15",
            "variant": "chaos-healthy-node0-v1",
            "status": "passed" if not reasons else "failed", "reasons": reasons,
            "original_gate": base, "observed_first_caller_doors": len(first),
            "observed_second_caller_doors": len(second),
            "observed_native_exists_doors": len(native),
            "same_split_handoff_witness": witness,
            "resource_path_attested": False, "full_campaign_admitted": False,
            "note": "Temporal proximity identifies a second exists call; the event has no ZooKeeper path."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    receipt = attest(args.output)
    (args.output / "chaos-healthy-node0-gate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
