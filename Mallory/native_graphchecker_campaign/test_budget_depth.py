"""Budget-derived native fault sequence depth without a live JUnit."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Mallory.native_graphchecker_campaign import campaign


def fault(number: int) -> dict:
    return {"siteId": "<Test: void rpc()>#u1", "node": "dn0",
            "actorEpochOrdinal": 0, "ordinal": number,
            "exceptionClass": "java.io.IOException"}


def state(prefix: list[dict], *, retained: bool = True) -> tuple[dict, dict]:
    key = campaign._plan_key(prefix, "anchor-A")
    active = {"index": 6, "name": "r0006", "faults": prefix,
              "key": key, "anchor_address": "anchor-A",
              "tier": "observed_closure", "novelty": 0,
              "attempt": 0, "target_phase": "before_selected_target",
              "peer_relation": "unknown"}
    campaign_state = {
        "case_id": "TEST", "scheduler_version": 16,
        "budget": {"fault_trials": 64, "seconds": 3600,
                   "max_faults_per_trial": "until_budget"},
        "completed_fault_trials": 5, "elapsed_seconds": 0.0,
        "status": "running", "terminal": False,
        "healthy": {"status": "healthy_seed"},
        "trials": [], "queue": [], "active": active,
        "multi_anchor_addresses": ["anchor-A", "anchor-B"],
        "seen_plan_keys": [key], "fault_id_attempts": {},
        "fault_id_successes": {}, "peer_postfault_attempts": {},
        "peer_postfault_retained": {}, "seen_node_families": [],
        "seen_edge_families": [], "seen_branch_outcomes": []}
    result = {
        "case_id": "TEST", "faults": prefix, "elapsed_seconds": 1.0,
        "anchor_address": "anchor-A",
        "status": "checked" if retained else "target_lost",
        "runner_mode": "region_state", "strict_injection": True,
        "native_target_retained": retained,
        "post_fault_target_check_observed": retained,
        "fault_in_target_closure": retained,
        "target_temporal_admitted": False,
        "target_exception_triggered": False,
        "eligible_doors": [{"fault": fault(17),
                            "anchor_address": "anchor-A",
                            "tier": "observed_closure",
                            "target_phase": "before_selected_target"}],
        "native_delta": {"newNodeFamilies": [],
                         "newClosureEdgeFamilies": [],
                         "newBranchOutcomeIds": []}}
    return campaign_state, result


class BudgetDepthTest(unittest.TestCase):
    def test_new_budget_derived_campaign_records_scheduler_sixteen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "native-original-weave-receipt.json").write_text("{}")
            admitted = {"weave_config": {"output_classes": str(root)},
                        "origin": {}, "zero_vm_sha256": "a",
                        "runner_classpath_artifacts": []}
            config = {"case_id": "generic", "budget": {
                "fault_trials": 256, "seconds": 3600,
                "max_faults_per_trial": "until_budget"},
                "recording": {}}
            fresh = campaign._new_state(config, "config-sha", admitted)
            self.assertEqual(16, fresh["scheduler_version"])
            self.assertEqual("until_budget", fresh["budget"]["max_faults_per_trial"])

    def test_budget_token_and_explicit_depth_above_sixteen(self) -> None:
        self.assertEqual(256, campaign._effective_fault_depth({
            "fault_trials": 256, "max_faults_per_trial": "until_budget"}))
        self.assertEqual(17, campaign._effective_fault_depth({
            "fault_trials": 64, "max_faults_per_trial": 17}))
        # Existing numeric checkpoints can retain a depth greater than their
        # trial count; new depths beyond sixteen must fit that count.
        self.assertEqual(12, campaign._effective_fault_depth({
            "fault_trials": 8, "max_faults_per_trial": 12}))
        for budget in ({"fault_trials": 16, "max_faults_per_trial": 17},
                       {"fault_trials": 64, "max_faults_per_trial": "forever"},
                       {"fault_trials": True,
                        "max_faults_per_trial": "until_budget"}):
            with self.assertRaises(ValueError):
                campaign._effective_fault_depth(budget)

    def test_strict_retained_prefix_enqueues_and_selects_depth_seventeen(self) -> None:
        prefix = [fault(number) for number in range(1, 17)]
        campaign_state, result = state(prefix)
        campaign._accept(campaign_state, result, "r0006")
        self.assertEqual(6, campaign_state["completed_fault_trials"])
        self.assertEqual(17, len(campaign_state["queue"][0]["faults"]))
        self.assertTrue(campaign_state["queue"][0]["depth_feedback"][
            "strict_post_fault_target"])
        # The recurring strict-prefix progress slot must beat a shallower
        # eligible candidate; merely permitting depth 17 in the queue is not
        # enough to exercise it within a finite trial budget.
        campaign_state["queue"].append({
            "key": "shallower", "faults": [fault(1), fault(2)],
            "anchor_address": "anchor-A", "tier": "observed_closure",
            "novelty": 100, "target_phase": "before_selected_target",
            "depth_feedback": {"strict_post_fault_target": True,
                               "score": 100}})
        chosen = campaign._pick(campaign_state)
        self.assertEqual(17, len(chosen["faults"]))
        self.assertEqual("anchor-A", chosen["anchor_address"])

    def test_target_loss_does_not_extend_and_budget_stop_still_applies(self) -> None:
        prefix = [fault(number) for number in range(1, 17)]
        campaign_state, result = state(prefix, retained=False)
        campaign._accept(campaign_state, result, "r0006")
        self.assertEqual([], campaign_state["queue"])
        at_budget, _ = state(prefix)
        at_budget["completed_fault_trials"] = 64
        at_budget["active"] = None
        at_budget["queue"] = [{"faults": prefix, "key": "pending"}]
        campaign._finish_status(at_budget)
        self.assertEqual("complete_trial_budget", at_budget["status"])

    def test_resumes_exact_seventeen_fault_result_and_rejects_over_budget(self) -> None:
        prefix = [fault(number) for number in range(1, 18)]
        campaign_state, result = state(prefix)
        result["eligible_doors"] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign._atomic(root / "trials/r0006/result.json", result)
            campaign._resume_active({}, {}, root, campaign_state)
            self.assertEqual(6, campaign_state["completed_fault_trials"])
            self.assertIsNone(campaign_state["active"])
        oversized = [fault(number) for number in range(1, 66)]
        bad, _ = state(oversized)
        with self.assertRaisesRegex(ValueError, "active plan exceeds"):
            campaign._resume_active({}, {}, Path("/nonexistent"), bad)
        bad["active"] = None
        bad["queue"] = [{"faults": oversized, "key": "bad"}]
        with self.assertRaisesRegex(ValueError, "queued plan exceeds"):
            campaign._pick(bad)


if __name__ == "__main__":
    unittest.main()
