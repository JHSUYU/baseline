#!/usr/bin/env python3
"""Sealed replay, strict multifault, and zero-invalid-novelty checks."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from seed_continuation import CONFIG, derive
from strict_policy import campaign, qualifies, strict_path, trial_path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
V5 = BASE / "data/mallory/campaigns/HDFS-48-rename-presend-full-v5"
LANE2 = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")


def synthetic_second_fault() -> tuple[list[dict], list[dict], dict]:
    cfg = json.loads(CONFIG.read_text())
    result = json.loads((V5 / "trials/r0001/result.json").read_text())
    with gzip.open(V5 / "trials/r0001/events.jsonl.gz", "rt") as source:
        events = [json.loads(line) for line in source]
    retry = next(e for e in events if e.get("type") == "DOOR_OBSERVED" and
                 e.get("door_ordinal") == 2 and e.get("site") ==
                 "hdfs:client-send-rpc-request:rename")
    original_seq = retry["seq"]
    for event in events:
        if event["seq"] > original_seq:
            event["seq"] += 3
    matched = copy.deepcopy(retry)
    matched.update({"type": "FAULT_MATCHED", "id": "test:matched-2",
                    "seq": original_seq + 1, "fault_id": "f-test-2"})
    applied = copy.deepcopy(retry)
    applied.update({"type": "FAULT_APPLIED", "id": "test:applied-2",
                    "seq": original_seq + 2, "fault_id": "f-test-2"})
    final_retry = copy.deepcopy(retry)
    final_retry.update({"id": "test:retry-3", "seq": original_seq + 3,
                        "door_ordinal": 3, "hit": 3})
    events.extend((matched, applied, final_retry))
    events.sort(key=lambda e: e["seq"])
    plan = result["plan"] + [{"fault_id": "f-test-2", "fault_type": "EXCEPTION",
                              "exception_class": "java.io.IOException",
                              "point": {"site": "hdfs:client-send-rpc-request:rename",
                                        "node": "hdfs-client", "epoch": 0,
                                        "door_ordinal": 2}}]
    return events, plan, cfg["target"]


class OfflineContinuationTest(unittest.TestCase):
    def test_v5_strict_seed_and_two_fault_candidate(self) -> None:
        cfg = json.loads(CONFIG.read_text())
        result = json.loads((V5 / "trials/r0001/result.json").read_text())
        proof = trial_path(V5, result, cfg["target"])
        self.assertTrue(qualifies(result, proof))
        self.assertEqual(proof["request_recv_id"], "HDFS-48-r0001:188")
        candidates = campaign.mutate(result["plan"], result["feedback"], cfg)
        self.assertEqual(len(candidates), 1)
        self.assertEqual([f["point"]["door_ordinal"] for f in candidates[0]["faults"]],
                         [1, 2])

    def test_exact_two_fault_path_and_broken_token(self) -> None:
        events, plan, target = synthetic_second_fault()
        self.assertEqual(strict_path(events, plan, target)["classification"],
                         "strict_multifault_retry_rpc_target")
        recv = next(e for e in events if e.get("type") == "RECV" and
                    e.get("port") == "request" and e.get("node") ==
                    "hdfs-cluster-1/nn0" and e["seq"] > 185)
        recv["correlation"] = "wrong-token"
        self.assertEqual(strict_path(events, plan, target)["classification"],
                         "retry_rpc_roundtrip_missing")

    def test_sealed_checkpoint_reuse_and_invalid_zero_novelty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hdfs48-v6-offline-") as directory:
            out = Path(directory) / "derived"
            proof = derive(out, source_override=LANE2)
            self.assertEqual(proof["v6_reused_trials"], [0, 1])
            self.assertEqual(proof["next_fault_ordinals"], [1, 2])
            state = json.loads((out / "checkpoint.json").read_text())
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["completed_trials"], [0, 1])
            self.assertEqual(len(state["queue"]), 1)
            coverage_before = (state["coverage_ids"], state["closure_coverage_ids"],
                               state["edge_fingerprints"])
            shutil.copytree(out / "trials/r0001", out / "trials/r0002")
            invalid = json.loads((out / "trials/r0002/result.json").read_text())
            invalid["trial_id"] = 2
            item = state["queue"].pop()
            invalid["plan"] = item["faults"]
            state["next_trial"] = 3
            campaign._apply_result(state, json.loads(CONFIG.read_text()), invalid, item)
            self.assertEqual(invalid["v6_strict_policy"]["qualified"], False)
            self.assertEqual(invalid["novelty"], {"coverage": 0,
                                                 "closure_coverage": 0,
                                                 "closure_edges": 0})
            self.assertEqual((state["coverage_ids"], state["closure_coverage_ids"],
                              state["edge_fingerprints"]), coverage_before)
            self.assertEqual(state["queue"], [])


if __name__ == "__main__":
    unittest.main()
