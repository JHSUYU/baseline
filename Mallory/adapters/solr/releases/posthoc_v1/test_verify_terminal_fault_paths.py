"""Tamper tests for the posthoc Solr fault identity gate."""

from __future__ import annotations

import unittest

from verify_terminal_fault_paths import exact_fault


def fixture():
    plan = {"fault_id": "f1", "fault_type": "EXCEPTION",
            "exception_class": "java.io.IOException",
            "point": {"site": "A#io@1:door:1", "node": "node1", "epoch": 0,
                      "door_ordinal": 2}}
    common = {**plan["point"], "occurrence": "node1:0:a:1",
              "fault_type": "EXCEPTION", "exception_class": "java.io.IOException"}
    events = [{**common, "type": "DOOR_OBSERVED", "seq": 1, "id": "e1"},
              {**common, "type": "FAULT_MATCHED", "seq": 2, "id": "e2",
               "fault_id": "f1"},
              {**common, "type": "FAULT_APPLIED", "seq": 3, "id": "e3",
               "fault_id": "f1"}]
    return events, plan


class FaultIdentityTests(unittest.TestCase):
    def test_valid_exact_chain(self):
        events, plan = fixture()
        self.assertEqual([e["id"] for e in exact_fault(events, plan)], ["e3"])

    def test_wrong_ordinal(self):
        events, plan = fixture()
        events[2]["door_ordinal"] = 3
        self.assertEqual(exact_fault(events, plan), [])

    def test_wrong_exception_type(self):
        events, plan = fixture()
        events[1]["exception_class"] = "java.lang.RuntimeException"
        self.assertEqual(exact_fault(events, plan), [])

    def test_duplicate_applied_id(self):
        events, plan = fixture()
        events.append({**events[2], "id": "e4", "seq": 4})
        self.assertEqual(exact_fault(events, plan), [])

    def test_reordered_fault(self):
        events, plan = fixture()
        events[1]["seq"] = 4
        self.assertEqual(exact_fault(events, plan), [])


if __name__ == "__main__":
    unittest.main()
