"""Tamper checks for the exact SOLR-18 recovery witness."""

from __future__ import annotations

import unittest

from verify_solr18_badversion_recovery import (
    BAD_VERSION, DOOR, SET_IF_NEWER, TARGET, UPDATE, proof,
)


def fixture():
    apply_occ, update_occ, set_occ = "node1:0:apply:1", "node1:0:update:1", "node1:0:set:1"
    plan = {"fault_id": "f1", "fault_type": "EXCEPTION", "exception_class": BAD_VERSION,
            "point": {"site": DOOR, "node": "node1", "epoch": 0, "door_ordinal": 1}}
    events = []

    def add(kind, seq, occurrence, region, site, **extra):
        row = {"type": kind, "id": f"e{seq}", "seq": seq, "node": "node1",
               "epoch": 0, "thread_id": 42, "occurrence": occurrence,
               "region": region, "site": site, **extra}
        events.append(row)

    add("REGION_ENTER", 1, apply_occ, DOOR.split("@", 1)[0], DOOR.split("@", 1)[0],
        parent_id="root")
    for kind, seq in (("DOOR_OBSERVED", 2), ("FAULT_MATCHED", 3), ("FAULT_APPLIED", 4)):
        fields = {"door_ordinal": 1, "exception_class": BAD_VERSION}
        if kind != "DOOR_OBSERVED":
            fields["fault_id"] = "f1"
        add(kind, seq, apply_occ, DOOR.split("@", 1)[0], DOOR, **fields)
    add("REGION_ENTER", 5, update_occ, UPDATE, UPDATE, parent_id=apply_occ)
    add("REGION_ENTER", 6, set_occ, SET_IF_NEWER, SET_IF_NEWER, parent_id=update_occ)
    add("TARGET_CHECK", 7, set_occ, SET_IF_NEWER, TARGET + "4")
    add("REGION_EXIT", 8, set_occ, SET_IF_NEWER, SET_IF_NEWER)
    add("REGION_EXIT", 9, update_occ, UPDATE, UPDATE)
    add("REGION_EXIT", 10, apply_occ, DOOR.split("@", 1)[0], DOOR.split("@", 1)[0])
    return events, plan


class RecoveryProofTests(unittest.TestCase):
    def test_exact_chain(self):
        events, plan = fixture()
        result = proof(events, plan)
        self.assertTrue(result["valid"], result)
        self.assertEqual([edge["kind"] for edge in result["graph_edges"]],
                         ["program_order", "region_parent"])

    def test_wrong_ordinal(self):
        events, plan = fixture()
        events[3]["door_ordinal"] = 2
        self.assertFalse(proof(events, plan)["valid"])

    def test_wrong_thread(self):
        events, plan = fixture()
        events[2]["thread_id"] = 43
        self.assertFalse(proof(events, plan)["valid"])

    def test_wrong_parent(self):
        events, plan = fixture()
        events[4]["parent_id"] = "different"
        self.assertFalse(proof(events, plan)["valid"])

    def test_target_before_fault(self):
        events, plan = fixture()
        events[6]["seq"] = 0
        self.assertFalse(proof(events, plan)["valid"])

    def test_target_after_apply_exit(self):
        events, plan = fixture()
        events[6]["seq"] = 11
        self.assertFalse(proof(events, plan)["valid"])

    def test_target_other_actor(self):
        events, plan = fixture()
        events[6]["node"] = "node2"
        self.assertFalse(proof(events, plan)["valid"])

    def test_wrong_exception(self):
        events, plan = fixture()
        events[2]["exception_class"] = "org.apache.zookeeper.KeeperException$ConnectionLossException"
        self.assertFalse(proof(events, plan)["valid"])

    def test_unbalanced_exit_breaks_observed_graph_path(self):
        events, plan = fixture()
        events[8]["region"] = "different"
        result = proof(events, plan)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "missing_exact_observed_graph_path")

    def test_duplicate_event_id(self):
        events, plan = fixture()
        events[8]["id"] = events[7]["id"]
        self.assertFalse(proof(events, plan)["valid"])

    def test_missing_fault(self):
        events, plan = fixture()
        events = [row for row in events if row["type"] != "FAULT_APPLIED"]
        self.assertFalse(proof(events, plan)["valid"])


if __name__ == "__main__":
    unittest.main()
