#!/usr/bin/env python3
"""Offline regression checks against the sealed v4 trace; no JVM."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
import unittest

from audit_full import CORE, DOOR, healthy_witness, witness
import sys
sys.path.insert(0, str(CORE))
from Mallory.core.scheduler import mutate

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
TRACE = BASE / "data/mallory/healthy_observations/HDFS-48-rename-presend-v4/trials/r0000/events.jsonl.gz"
CFG = HERE / "HDFS-48-node2-one-fault-full-v5.json"


def synthetic() -> tuple[list[dict], dict, set[str], str]:
    with gzip.open(TRACE, "rt") as stream:
        healthy = [json.loads(line) for line in stream]
    cfg = json.loads(CFG.read_text())
    target = cfg["target"]
    door = next(e for e in healthy if e.get("type") == "DOOR_OBSERVED" and
                e.get("site") == DOOR)
    assert healthy_witness(healthy, set(target["check_sites"]))
    events = copy.deepcopy(healthy)
    for event in events:
        if event["seq"] >= door["seq"]:
            event["seq"] += 3
    retry = next(e for e in events if e["id"] == door["id"])
    retry["door_ordinal"] = 2
    observed = copy.deepcopy(door)
    observed["id"] = "test:fault-door"
    matched = copy.deepcopy(observed)
    matched.update({"type": "FAULT_MATCHED", "id": "test:fault-matched",
                    "seq": door["seq"] + 1, "fault_id": "f-test"})
    applied = copy.deepcopy(observed)
    applied.update({"type": "FAULT_APPLIED", "id": "test:fault-applied",
                    "seq": door["seq"] + 2, "fault_id": "f-test"})
    events.extend((observed, matched, applied))
    events.sort(key=lambda event: event["seq"])
    fault = {"fault_id": "f-test", "point": {"site": DOOR, "node": "hdfs-client",
             "epoch": 0, "door_ordinal": 1}, "fault_type": "EXCEPTION",
             "exception_class": "java.io.IOException"}
    return events, fault, set(target["check_sites"]), target["throw_site"]


class OfflineWitnessTest(unittest.TestCase):
    def test_v4_feedback_generates_only_exact_fault(self) -> None:
        cfg = json.loads(CFG.read_text())
        result = json.loads((BASE / "data/mallory/healthy_observations/"
                             "HDFS-48-rename-presend-v4/trials/r0000/result.json").read_text())
        candidates = mutate([], result["feedback"], cfg)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["faults"][0]["point"],
                         {"site": DOOR, "node": "hdfs-client", "epoch": 0,
                          "door_ordinal": 1})
        self.assertEqual(candidates[0]["faults"][0]["exception_class"],
                         "java.io.IOException")

    def test_exact_retry_rpc_target(self) -> None:
        events, fault, checks, throw = synthetic()
        result = witness(events, fault, checks, throw)
        self.assertEqual(result["classification"], "strict_postfault_retry_rpc_target")
        self.assertTrue(result["rpc_token"])
        self.assertTrue(any(e["kind"] == "rpc" for e in result["graph_edges"]))

    def test_wrong_actor_rejected(self) -> None:
        events, fault, checks, throw = synthetic()
        next(e for e in events if e["id"] == "test:fault-applied")["node"] = "unknown"
        self.assertEqual(witness(events, fault, checks, throw)["classification"],
                         "fault_actor_epoch_or_occurrence_mismatch")

    def test_missing_rpc_handoff_rejected(self) -> None:
        events, fault, checks, throw = synthetic()
        recv = next(e for e in events if e.get("type") == "RECV" and
                    e.get("port") == "request" and e.get("node") == "hdfs-cluster-1/nn0" and
                    e["seq"] > 185)
        recv["correlation"] = "wrong-token"
        self.assertEqual(witness(events, fault, checks, throw)["classification"],
                         "retry_rpc_roundtrip_missing_or_ambiguous")

    def test_additional_fault_rejected(self) -> None:
        events, fault, checks, throw = synthetic()
        extra = copy.deepcopy(next(e for e in events if e["id"] == "test:fault-applied"))
        extra["id"] = "test:extra-fault"
        extra["fault_id"] = "f-extra"
        events.append(extra)
        self.assertEqual(witness(events, fault, checks, throw)["classification"],
                         "additional_applied_fault")

    def test_fictitious_presend_send_rejected(self) -> None:
        events, fault, checks, throw = synthetic()
        request = copy.deepcopy(next(e for e in events if e.get("type") == "SEND" and
                                     e.get("site") == "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest" and
                                     e.get("node") == "hdfs-client" and e["seq"] > 186))
        request.update({"id": "test:fictitious-send", "seq": 184})
        events.append(request)
        self.assertEqual(witness(events, fault, checks, throw)["classification"],
                         "faulted_presend_attempt_emitted_request")

    def test_exact_target_throw_is_source_review(self) -> None:
        events, fault, checks, throw = synthetic()
        target = next(e for e in events if e.get("type") == "TARGET_CHECK" and
                      e.get("node") == "hdfs-cluster-1/nn0" and e.get("site") in checks)
        thrown = copy.deepcopy(target)
        thrown.update({"type": "TARGET_THROW", "site": throw, "id": "test:target-throw",
                       "seq": max(e["seq"] for e in events) + 1})
        events.append(thrown)
        self.assertEqual(witness(events, fault, checks, throw)["classification"],
                         "exact_target_throw_source_review")


if __name__ == "__main__":
    unittest.main()
