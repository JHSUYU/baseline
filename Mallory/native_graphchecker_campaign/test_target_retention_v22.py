"""The opt-in retention slot uses only exact observed queue and trial data."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign
from Mallory.native_graphchecker_campaign.test_anchor_fairness_v21 import plan, state


class TargetRetentionV22Test(unittest.TestCase):
    def test_target_lost_shallow_trials_reduce_priority_without_pruning(self):
        current = state(version=22)
        current["completed_fault_trials"] = 3
        current["queue"] = [plan("lost-anchor", "anchor-0", 2),
                            plan("untried-anchor", "anchor-1", 2)]
        current["trials"] = [{"anchor_address": "anchor-0",
                              "strict_injection": True,
                              "post_fault_target_check_observed": False,
                              "faults": plan("past", "anchor-0")["faults"]}]
        self.assertEqual("untried-anchor", campaign._pick(current)["key"])
        self.assertEqual("lost-anchor", current["queue"][0]["key"])

    def test_requires_strict_target_retaining_prefix_and_pretarget_closure(self):
        current = state(version=22)
        current["completed_fault_trials"] = 3
        good = plan("good", "anchor-0", 2)
        lost = {**plan("lost-prefix", "anchor-0", 2),
                "depth_feedback": {"strict_post_fault_target": False}}
        late = {**plan("late", "anchor-0", 2),
                "target_phase": "after_selected_target"}
        outside = {**plan("outside", "anchor-0", 2),
                   "tier": "outside_closure"}
        current["queue"] = [good, lost, late, outside]
        self.assertEqual("good", campaign._pick(current)["key"])

    def test_retention_slot_does_not_cap_deep_or_outside_slots(self):
        deep = state(version=22)
        deep["completed_fault_trials"] = 6
        self.assertEqual("deep-anchor-1", campaign._pick(deep)["key"])

        outside = state(version=22)
        outside["completed_fault_trials"] = 7
        inside_plan = {**plan("inside", "anchor-7"),
                       "enqueued_at": 0, "attempt": 0,
                       "target_order_distance": 10}
        outside_plan = {**plan("outside", "anchor-7"),
                        "tier": "outside_closure", "enqueued_at": 0,
                        "attempt": 0, "target_order_distance": 10}
        outside["queue"] = [inside_plan, outside_plan]
        outside["fault_id_successes"] = {}
        outside["peer_postfault_attempts"] = {}
        outside["peer_postfault_retained"] = {}
        self.assertEqual("outside", campaign._pick(outside)["key"])

    def test_old_version_has_no_retention_slot_and_policy_is_opt_in(self):
        current = state(version=21)
        current["completed_fault_trials"] = 3
        current["queue"] = [plan("a", "anchor-0", 2),
                            plan("b", "anchor-1", 2)]
        self.assertIsNone(campaign._target_retention_slot({**current,
            "queue": [{**plan("late", "anchor-0", 2),
                       "target_phase": "after_selected_target"}]}))
        base = {"case_id": "test", "budget": {"fault_trials": 256,
                "max_faults_per_trial": 256},
                "recording": {"multi_target_max_anchors": 8}}
        admitted = {"weave_config": {"output_classes": "/unused"},
                    "origin": {}, "zero_vm_sha256": "zero",
                    "runner_classpath_artifacts": []}
        with patch.object(campaign, "_sha", return_value="receipt"):
            old = campaign._new_state({**base, "scheduler_policy": {
                "anchor_fairness": "all_selected_anchors_eighth_v1"}},
                "old", admitted)
            new = campaign._new_state({**base, "scheduler_policy": {
                "anchor_fairness": "all_selected_anchors_eighth_v1",
                "target_retention": "strict_prefix_shallow_eighth_v1"}},
                "new", admitted)
        self.assertEqual(21, old["scheduler_version"])
        self.assertEqual(22, new["scheduler_version"])


if __name__ == "__main__":
    unittest.main()
