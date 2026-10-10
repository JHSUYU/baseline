"""Check that actor drift is resolved only for the exact observed command door."""

import unittest

from run_campaign import ROLE, SITE, mutate, role_receipt


class CampaignRoleTest(unittest.TestCase):
    def test_exact_door_promotes_and_preserves_physical_receipt(self):
        point = {"site": SITE, "node": "node4", "epoch": 0, "door_ordinal": 1}
        feedback = {"all_faults_effective": True, "target_reached": True,
                    "last_fault_seq": -1, "doors": [{"point": point, "site": SITE,
                    "event_id": "healthy:266", "event_seq": 266,
                    "fault_type": "EXCEPTION",
                    "exception_class": "java.util.concurrent.TimeoutException",
                    "in_closure": True,
                    "local_timeline_evidence": {"target_check_event_id": "healthy:280"},
                    "role": ROLE, "role_resolution": "unique", "role_ordinal": 1,
                    "role_node": "node4", "role_epoch": 0,
                    "role_source_occurrence": "node4:0:command"}]}
        config = {"budget": {"max_faults_per_trial": 3},
                  "fault_types": ["EXCEPTION"], "explore_outside_closure": False}
        candidates = mutate([], feedback, config)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["faults"][0]["point"],
                         {"site": SITE, "role": ROLE, "role_ordinal": 1})
        observed = {"site": SITE, "role": ROLE, "role_resolution": "unique",
                    "role_ordinal": 1, "node": "node2", "epoch": 0,
                    "role_node": "node2", "role_epoch": 0,
                    "occurrence": "node2:0:command",
                    "role_source_occurrence": "node2:0:command",
                    "region": __import__("run_campaign").REGION, "thread_id": 215}
        self.assertTrue(role_receipt(observed, candidates[0]["faults"][0]["point"]))
        observed["role_source_occurrence"] = "other-command"
        self.assertFalse(role_receipt(observed, candidates[0]["faults"][0]["point"]))


if __name__ == "__main__":
    unittest.main()
