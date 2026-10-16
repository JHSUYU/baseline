"""A scheduler slot for every queued, exact target anchor."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign


def plan(key: str, anchor: str, depth: int = 1) -> dict:
    return {"key": key, "anchor_address": anchor,
            "faults": [{"siteId": "<Test: void rpc()>#u1", "node": "dn0",
                        "actorEpochOrdinal": 0,
                        "occurrenceId": f"{key}-{ordinal}",
                        "ordinal": ordinal,
                        "exceptionClass": "java.io.IOException"}
                       for ordinal in range(1, depth + 1)],
            "tier": "observed_closure", "novelty": 0,
            "target_phase": "before_selected_target",
            "peer_relation": "same_peer_before_target",
            "depth_feedback": {"strict_post_fault_target": True,
                               "score": depth}}


def state(version: int = 21) -> dict:
    addresses = [f"anchor-{index}" for index in range(8)]
    return {"scheduler_version": version, "completed_fault_trials": 2,
            "budget": {"fault_trials": 256,
                       "max_faults_per_trial": 256},
            "queue": [plan(f"single-{index}", address)
                      for index, address in enumerate(addresses)] +
                     [plan("deep-anchor-1", addresses[1], 4)],
            "trials": [], "fault_id_attempts": {},
            "multi_anchor_addresses": addresses}


class AnchorFairnessV21Test(unittest.TestCase):
    def test_eighth_slot_reaches_all_eight_anchors_despite_depth_override(self):
        current = state()
        selected = []
        for completed in range(2, 66, 8):
            current["completed_fault_trials"] = completed
            chosen = campaign._pick(current)
            selected.append(chosen["anchor_address"])
            # Target loss and a strict miss must still count as attempts;
            # otherwise a large deep queue can repeatedly starve an anchor.
            current["trials"].append({
                "anchor_address": chosen["anchor_address"],
                "strict_injection": completed % 16 == 2,
                "post_fault_target_check_observed": False,
                "faults": chosen["faults"]})
        self.assertEqual(current["multi_anchor_addresses"], selected)
        self.assertIn("deep-anchor-1",
                      [item["key"] for item in current["queue"]])

    def test_legacy_quota_still_takes_deep_candidate(self):
        current = state(version=16)
        self.assertEqual("deep-anchor-1", campaign._pick(current)["key"])

    def test_policy_is_explicit_and_preserves_default_version(self):
        base = {"case_id": "test", "budget": {"fault_trials": 256,
                "max_faults_per_trial": 256},
                "recording": {"multi_target_max_anchors": 8}}
        admitted = {"weave_config": {"output_classes": "/unused"},
                    "origin": {}, "zero_vm_sha256": "zero",
                    "runner_classpath_artifacts": []}
        with patch.object(campaign, "_sha", return_value="receipt"):
            old = campaign._new_state(base, "old", admitted)
            new = campaign._new_state({**base, "scheduler_policy": {
                "anchor_fairness": "all_selected_anchors_eighth_v1"}},
                "new", admitted)
        self.assertEqual(16, old["scheduler_version"])
        self.assertEqual(21, new["scheduler_version"])


if __name__ == "__main__":
    unittest.main()
