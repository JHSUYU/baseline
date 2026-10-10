"""Offline regression checks for the SOLR-15 runtime-qualified bootstrap."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"))
import seed_selector as seed

PRIOR = ROOT / "data/mallory/solr15_fault_bootstrap_node0_v1/trials/r0001"


class SelectorTest(unittest.TestCase):
    def test_v1_trace_proves_ordinal_shift_and_wrong_path(self):
        rows = seed.events(PRIOR)
        second = seed.second_lookup(PRIOR)
        fault_id = json.loads((PRIOR / "plan.json").read_text())["faults"][0]["fault_id"]
        applied = next(row for row in rows if row.get("type") == "FAULT_APPLIED"
                       and row.get("fault_id") == fault_id)
        self.assertEqual((42, "/overseer/queue"),
                         (applied["door_ordinal"], applied["resource"]))
        self.assertEqual(("SOLR-15-r0001:1898", 47,
                          "/live_nodes/127.0.0.1:42553_"),
                         (second["id"], second["door_ordinal"], second["resource"]))

    def test_plan_replaces_ordinal_with_runtime_phase(self):
        point = {"site": seed.NATIVE, "node": "control", "epoch": 0,
                 "door_ordinal": 42}
        fault = {"fault_id": "f1", "point": point, "fault_type": "EXCEPTION",
                 "exception_class": "java.io.IOException"}
        queue = [{"faults": [fault], "signature": "old"}]
        selected = seed.pick_exact(queue, point, faults=1)
        self.assertEqual({"site": seed.NATIVE, "node": "control", "epoch": 0,
                          "solr15_parent_lookup": "second"},
                         selected["faults"][0]["point"])
        self.assertFalse(queue)

    def test_audit_requires_preinjection_candidate_and_target_after_fault(self):
        common = {"site": seed.NATIVE, "node": "control", "epoch": 0,
                  "occurrence": "split-1", "thread": "overseer", "context": "task-1",
                  "resource": "/live_nodes/parent"}
        second = {**common, "type": "DOOR_OBSERVED", "seq": 10,
                  "door_ordinal": 47}
        fault = {"fault_id": "f1", "point": {"site": seed.NATIVE,
                 "node": "control", "epoch": 0, "solr15_parent_lookup": "second"},
                 "expected_resource_role": "parent_leader_znode",
                 "expected_door": "second"}
        receipt = {**common, "fault_id": "f1", "door_ordinal": 47,
                   "selector_phase": "second", "bound_resource": common["resource"]}
        rows = [second,
                {**receipt, "type": "SOLR15_PARENT_CANDIDATE", "seq": 11},
                {**receipt, "type": "FAULT_MATCHED", "seq": 12},
                {**receipt, "type": "FAULT_APPLIED", "seq": 13},
                {**common, "type": "TARGET_CHECK", "seq": 14,
                 "site": seed.SPLIT + "@536:branch:40"}]
        with patch.object(seed, "events", return_value=rows), \
                patch.object(seed, "second_lookup", return_value=second):
            seed.attest_fault_resources(Path("unused"), [fault])
            self.assertTrue(seed.attest_target_after_fault(Path("unused"), [fault]))
            with patch.object(seed, "events", return_value=rows[:1] + rows[2:]):
                with self.assertRaisesRegex(ValueError, "candidate receipt missing"):
                    seed.attest_fault_resources(Path("unused"), [fault])
            wrong = [{**row, "resource": "/overseer/queue"}
                     if row.get("fault_id") else row for row in rows]
            with patch.object(seed, "events", return_value=wrong):
                with self.assertRaisesRegex(ValueError, "different live-node path"):
                    seed.attest_fault_resources(Path("unused"), [fault])
            with patch.object(seed, "events", return_value=rows[:-1]):
                self.assertFalse(seed.attest_target_after_fault(Path("unused"), [fault]))


if __name__ == "__main__":
    unittest.main()
