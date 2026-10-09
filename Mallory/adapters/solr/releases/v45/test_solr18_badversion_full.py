"""Checks for recovery paths inside multi-fault traces."""

from __future__ import annotations

import unittest

from test_solr18_badversion_recovery import fixture
from verify_solr18_badversion_full import full_trace_proof


class FullTraceProofTests(unittest.TestCase):
    def test_single_fault_chain(self):
        events, plan = fixture()
        self.assertTrue(full_trace_proof(events, plan)["valid"])

    def test_unrelated_later_fault_does_not_erase_chain(self):
        events, plan = fixture()
        events.append({**events[3], "id": "other-match", "seq": 11,
                       "type": "FAULT_MATCHED", "fault_id": "other"})
        events.append({**events[3], "id": "other-applied", "seq": 12,
                       "type": "FAULT_APPLIED", "fault_id": "other"})
        self.assertTrue(full_trace_proof(events, plan)["valid"])

    def test_other_fault_cannot_replace_selected_parent_path(self):
        events, plan = fixture()
        events[4]["parent_id"] = "other-fault-branch"
        self.assertFalse(full_trace_proof(events, plan)["valid"])


if __name__ == "__main__":
    unittest.main()
