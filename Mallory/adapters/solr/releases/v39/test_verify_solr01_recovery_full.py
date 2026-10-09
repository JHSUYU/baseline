#!/usr/bin/env python3
"""Fault-chain corruption must not become an accepted recovery witness."""

from __future__ import annotations

from copy import deepcopy
import unittest

from verify_solr01_recovery_full import SITE, witness


class RecoveryChainTest(unittest.TestCase):
    def setUp(self) -> None:
        common = {"site": SITE, "node": "client", "epoch": 0,
                  "thread_id": 22, "occurrence": "client:0:getAliases:root:33",
                  "door_ordinal": 14}
        self.plan = {"fault_id": "f1", "fault_type": "EXCEPTION",
                     "exception_class": "java.io.IOException",
                     "point": {"site": SITE, "node": "client", "epoch": 0,
                               "door_ordinal": 14}}
        self.events = [
            {**common, "type": "DOOR_OBSERVED", "seq": 1, "id": "d1",
             "fault_type": "EXCEPTION", "exception_class": "java.io.IOException"},
            {**common, "type": "FAULT_MATCHED", "seq": 2, "id": "m2",
             "fault_id": "f1", "fault_type": "EXCEPTION",
             "exception_class": "java.io.IOException"},
            {**common, "type": "FAULT_APPLIED", "seq": 3, "id": "a3",
             "fault_id": "f1", "fault_type": "EXCEPTION",
             "exception_class": "java.io.IOException"},
            {"type": "TARGET_CHECK", "seq": 4, "id": "t4", "site": "check",
             "node": "client", "epoch": 0, "thread_id": 22,
             "occurrence": "client:0:getAliases:root:33"},
            {"type": "REGION_EXIT", "seq": 5, "id": "e5",
             "node": "client", "epoch": 0, "thread_id": 22,
             "occurrence": "client:0:getAliases:root:33"},
        ]

    def check(self, events=None, plan=None):
        events = self.events if events is None else events
        plan = self.plan if plan is None else plan
        return witness(events, events[2], plan, {"check"})

    def test_valid_chain(self) -> None:
        rows = self.check()
        self.assertEqual(len(rows), 1)
        self.assertEqual([rows[0][key] for key in
                          ("door_id", "matched_id", "fault_id", "target_check_id")],
                         ["d1", "m2", "a3", "t4"])

    def test_reordered_or_duplicated_match_rejected(self) -> None:
        rows = deepcopy(self.events)
        rows[1]["seq"] = 4
        self.assertEqual(self.check(rows), [])
        rows = deepcopy(self.events)
        rows.insert(2, deepcopy(rows[1]))
        self.assertEqual(witness(rows, rows[3], self.plan, {"check"}), [])
        rows = deepcopy(self.events)
        rows.insert(3, deepcopy(rows[2]))
        self.assertEqual(witness(rows, rows[2], self.plan, {"check"}), [])

    def test_mismatched_plan_and_event_identity_rejected(self) -> None:
        plan = deepcopy(self.plan)
        plan["point"]["epoch"] = 1
        self.assertEqual(self.check(plan=plan), [])
        rows = deepcopy(self.events)
        rows[1]["thread_id"] = 99
        self.assertEqual(self.check(rows), [])
        rows = deepcopy(self.events)
        rows[1]["fault_id"] = "other"
        self.assertEqual(self.check(rows), [])

    def test_check_after_region_exit_rejected(self) -> None:
        rows = deepcopy(self.events)
        rows[3]["seq"] = 5
        rows[4]["seq"] = 4
        self.assertEqual(self.check(rows), [])
        self.assertEqual(self.check(rows[:-1]), [])


if __name__ == "__main__":
    unittest.main()
