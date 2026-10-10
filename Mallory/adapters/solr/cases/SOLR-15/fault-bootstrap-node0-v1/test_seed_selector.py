"""Offline checks for the SOLR-15 exact-door bootstrap selector."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import seed_selector as seed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
HEALTHY = ROOT / "data/mallory/solr15_path_healthy_node0_v3/healthy/trials/r0000"


class SelectorTest(unittest.TestCase):
    def test_observed_healthy_second_lookup(self):
        door = seed.second_lookup(HEALTHY)
        self.assertEqual("SOLR-15-r0000:1899", door["id"])
        self.assertEqual("/live_nodes/127.0.0.1:40293_", door["resource"])
        self.assertEqual(42, seed.point_of(door)["door_ordinal"])

    def test_observed_queue_contains_exact_native_door(self):
        import sys
        sys.path.insert(0, str(ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"))
        from Mallory.core.scheduler import mutate

        config = json.loads((HERE / "config-full-node0.json").read_text())
        feedback = json.loads((HEALTHY / "result.json").read_text())["feedback"]
        queue = mutate([], feedback, config, bootstrap=True)
        picked = seed.pick_exact(queue, seed.point_of(seed.second_lookup(HEALTHY)), faults=1)
        fault = picked["faults"][0]
        self.assertEqual("second", fault["expected_door"])
        self.assertEqual("parent_leader_znode", fault["expected_resource_role"])

    def test_resource_audit_requires_second_then_same_path_retry(self):
        base = {"site": seed.NATIVE, "node": "control", "epoch": 0,
                "occurrence": "split:1", "thread": "overseer", "context": "ctx",
                "resource": "/live_nodes/parent"}
        second = {**base, "type": "DOOR_OBSERVED", "seq": 10, "door_ordinal": 4}
        first = {**base, "fault_id": "f1", "seq": 11, "door_ordinal": 4}
        retry = {**base, "fault_id": "f2", "seq": 21, "door_ordinal": 5}
        rows = [second, {**first, "type": "FAULT_MATCHED"},
                {**first, "type": "FAULT_APPLIED"},
                {**retry, "type": "FAULT_MATCHED"},
                {**retry, "type": "FAULT_APPLIED"}]
        plan = [{"fault_id": "f1", "point": seed.point_of(second),
                 "expected_resource_role": "parent_leader_znode", "expected_door": "second"},
                {"fault_id": "f2", "point": seed.point_of({**second, "door_ordinal": 5}),
                 "expected_resource_role": "parent_leader_znode", "expected_door": "retry"}]
        with patch.object(seed, "events", return_value=rows), \
                patch.object(seed, "second_lookup", return_value=second):
            seed.attest_fault_resources(Path("unused"), plan)
            bad = [{**row, "resource": "/live_nodes/other"}
                   if row.get("fault_id") == "f2" else row for row in rows]
            with patch.object(seed, "events", return_value=bad):
                with self.assertRaisesRegex(ValueError, "different live-node path"):
                    seed.attest_fault_resources(Path("unused"), plan)


if __name__ == "__main__":
    unittest.main()
