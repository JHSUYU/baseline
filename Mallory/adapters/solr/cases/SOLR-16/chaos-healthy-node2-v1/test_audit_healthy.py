#!/usr/bin/env python3
"""Small, offline checks for same-split and resource-qualified evidence."""

import unittest

from audit_healthy import FIRST, SECOND, NATIVE, REGION, lookup_witness


def door(seq, site, *, occurrence="split-1", resource=None):
    return {"type": "DOOR_OBSERVED", "id": f"e{seq}", "seq": seq,
            "site": site, "node": "control", "epoch": 0,
            "occurrence": occurrence, "thread_id": 7,
            "context": "task-1", "region": REGION, "resource": resource}


class SameSplitEvidenceTest(unittest.TestCase):
    def test_same_split_same_parent_path(self):
        events = [door(1, FIRST), door(2, NATIVE, resource="/live_nodes/leader-1"),
                  door(3, SECOND), door(4, NATIVE, resource="/live_nodes/leader-1")]
        witness, status = lookup_witness(events)
        self.assertEqual(status, "bound")
        self.assertEqual(witness["parent_live_node_resource"], "/live_nodes/leader-1")

    def test_different_split_is_rejected(self):
        events = [door(1, FIRST), door(2, NATIVE, resource="/live_nodes/leader-1"),
                  door(3, SECOND, occurrence="split-2"),
                  door(4, NATIVE, occurrence="split-2", resource="/live_nodes/leader-1")]
        self.assertEqual(lookup_witness(events)[0], None)

    def test_other_znode_is_rejected(self):
        events = [door(1, FIRST), door(2, NATIVE, resource="/collections/x"),
                  door(3, SECOND), door(4, NATIVE, resource="/collections/x")]
        self.assertEqual(lookup_witness(events)[0], None)

    def test_missing_resource_is_reported(self):
        events = [door(1, FIRST), door(2, NATIVE), door(3, SECOND), door(4, NATIVE)]
        self.assertEqual(lookup_witness(events), (None, "resource_missing"))

    def test_intervening_same_thread_event_is_rejected(self):
        events = [door(1, FIRST), door(2, NATIVE, resource="/live_nodes/leader-1"),
                  door(3, SECOND),
                  {**door(4, NATIVE, resource="/live_nodes/leader-1"), "type": "TASK_SUBMIT"},
                  door(5, NATIVE, resource="/live_nodes/leader-1")]
        self.assertEqual(lookup_witness(events)[0], None)


if __name__ == "__main__":
    unittest.main()
