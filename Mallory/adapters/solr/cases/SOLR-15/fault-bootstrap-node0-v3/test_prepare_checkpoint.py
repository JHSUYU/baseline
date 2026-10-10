"""Offline checkpoint replay and fail-closed continuation checks."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_trial
import prepare_checkpoint as seed

_spec = importlib.util.spec_from_file_location("solr15_v3_runner", seed.HERE / "run_campaign.py")
assert _spec is not None and _spec.loader is not None
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)


class ContinuationTest(unittest.TestCase):
    def setUp(self):
        self.config = seed.read(seed.HERE / "config-full-node0.json")

    def test_exact_replay_retains_budget_and_untried_depth_three_queue(self):
        state, receipt = seed.reconstruct(self.config)
        self.assertEqual([0, 1, 2, 3, 4], state["completed_trials"])
        self.assertEqual(5, state["next_trial"])
        self.assertEqual(10, len(state["queue"]))
        self.assertEqual(2, receipt["invalid_trial_edge_fingerprints_removed"])
        self.assertEqual([1, 2, 3, 4],
                         [p["trial_id"] for p in receipt["replayed_picks"]])
        self.assertEqual(receipt, seed.read(seed.HERE / "reconstruction-receipt.json"))
        self.assertFalse(any(item.get("replay_of") in (2, 3) for item in state["queue"]))
        self.assertEqual(1, sum(item["scope_tier"] == "dynamic_closure"
                                for item in state["queue"]))
        self.assertEqual(9, sum(item["scope_tier"] == "outside_closure"
                                for item in state["queue"]))
        native = [item["faults"][-1]["point"] for item in state["queue"]
                  if item["faults"][-1]["point"]["site"] == seed.seed.NATIVE]
        self.assertEqual(3, len(native))
        self.assertEqual(1, sum(point.get("resource_role") == "bound_parent"
                                for point in native))
        self.assertTrue(all(point.get("resource") or point.get("resource_role")
                            for point in native))

    def test_changed_v2_evidence_fails_closed(self):
        original = seed.read

        def changed(path: Path):
            result = original(path)
            if path == seed.HERE / "source-receipt.json":
                result = copy.deepcopy(result)
                result["files"]["trials/r0002/result.json"] = "0" * 64
            return result

        with patch.object(seed, "read", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "v2 evidence changed"):
                seed.reconstruct(self.config)

    def test_replay_rejects_changed_selected_plan(self):
        original = seed.v2_runner._picked

        def wrong(queue, next_trial, fault_trials_completed, config):
            result = original(queue, next_trial, fault_trials_completed, config)
            if next_trial == 2:
                result = copy.deepcopy(result)
                result["faults"][-1]["fault_id"] = "wrong"
            return result

        with patch.object(seed.v2_runner, "_picked", side_effect=wrong):
            with self.assertRaisesRegex(ValueError, "different r0002 plan"):
                seed.reconstruct(self.config)

    def test_native_candidate_without_observed_path_is_rejected(self):
        prior, _ = seed._replay(seed.read(seed.SOURCE / "config.json"),
                                sanitize_last=True)
        native = next(item for item in prior["queue"] if
                      item["faults"][-1]["point"]["site"] == seed.seed.NATIVE)
        door = seed._source_door(native)
        with patch.object(seed, "_source_door", return_value={**door, "resource": None}):
            with self.assertRaisesRegex(ValueError, "lacks an observed path"):
                seed.qualify_candidate(native)

    def test_source_graph_tier_drift_is_rejected(self):
        prior, _ = seed._replay(seed.read(seed.SOURCE / "config.json"),
                                sanitize_last=True)
        native = next(item for item in prior["queue"] if
                      item["selection_reason"] == "dynamic_closure")
        original = seed.read

        def changed(path: Path):
            result = original(path)
            if path == seed.SOURCE / "trials/r0002/result.json":
                result = copy.deepcopy(result)
                point = native["faults"][-1]["point"]
                for door in result["feedback"]["doors"]:
                    if door.get("point") == point:
                        door["in_closure"] = False
            return result

        with patch.object(seed, "read", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "tier differs"):
                seed.qualify_candidate(native)

    def test_prior_invalid_depth_three_cannot_pass_all_faults_gate(self):
        trial = seed.SOURCE / "trials/r0004"
        plan = json.loads((trial / "plan.json").read_text())["faults"]
        with self.assertRaisesRegex(ValueError, "third fault matched/applied"):
            audit_trial.attest(trial, plan)

    def test_invalid_new_trial_is_archived_and_contributes_no_novelty(self):
        state, _ = seed.reconstruct(self.config)
        item = copy.deepcopy(state["queue"][0])
        result = {"trial_id": 5, "plan": item["faults"],
                  "feedback": {"coverage_ids": ["new"],
                               "closure_coverage_ids": ["new"],
                               "closure_edges": [{"kind": "new"}],
                               "target_reached": True,
                               "target_check_reached": True,
                               "target_exception_candidate": True,
                               "all_faults_effective": False}}
        raw_expected = copy.deepcopy(result)
        with tempfile.TemporaryDirectory(prefix="solr15-v3-drop-test-") as temp:
            output = Path(temp)
            trial = output / "trials/r0005"
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps(result))
            captured = []

            def apply(state_arg, config_arg, result_arg, item_arg):
                captured.append(copy.deepcopy(result_arg))

            with patch.object(runner, "OUT", output), \
                    patch.object(runner.audit_trial, "attest",
                                 side_effect=ValueError("third fault missing")), \
                    patch.object(runner, "ORIGINAL_APPLY", side_effect=apply):
                runner._applied(state, self.config, result, item)
            self.assertEqual(raw_expected,
                             json.loads((trial / "raw-result.json").read_text()))
            self.assertEqual([], captured[0]["feedback"]["coverage_ids"])
            self.assertEqual([], captured[0]["feedback"]["closure_edges"])
            self.assertFalse(captured[0]["feedback"]["target_exception_candidate"])
            self.assertEqual("dropped_invalid_depth_three",
                             captured[0]["feedback"]["status"])
            self.assertEqual(5, state["dropped_trials"][-1]["trial_id"])

    def test_all_applied_without_postfault_target_is_dropped(self):
        state, _ = seed.reconstruct(self.config)
        item = copy.deepcopy(state["queue"][0])
        result = {"trial_id": 5, "plan": item["faults"],
                  "feedback": {"coverage_ids": ["new"],
                               "target_check_reached": False,
                               "all_faults_effective": True}}
        with tempfile.TemporaryDirectory(prefix="solr15-v3-target-test-") as temp:
            output = Path(temp)
            trial = output / "trials/r0005"
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps(result))
            captured = []
            with patch.object(runner, "OUT", output), \
                    patch.object(runner.audit_trial, "attest",
                                 return_value={"target_after_all_faults": False}), \
                    patch.object(runner, "ORIGINAL_APPLY",
                                 side_effect=lambda *_args: captured.append(_args[2])):
                runner._applied(state, self.config, result, item)
            self.assertFalse(captured[0]["feedback"]["all_faults_effective"])
            self.assertEqual([], captured[0]["feedback"]["coverage_ids"])
            self.assertIn("target check did not follow",
                          state["dropped_trials"][-1]["reason"])

    def test_prethird_throw_cannot_credit_exception_candidate(self):
        state, _ = seed.reconstruct(self.config)
        item = copy.deepcopy(state["queue"][0])
        result = {"trial_id": 5, "plan": item["faults"],
                  "feedback": {"coverage_ids": ["new"],
                               "target_check_reached": True,
                               "target_exception_candidate": True,
                               "all_faults_effective": True}}
        with tempfile.TemporaryDirectory(prefix="solr15-v3-throw-test-") as temp:
            output = Path(temp)
            trial = output / "trials/r0005"
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps(result))
            captured = []
            attestation = {"target_after_all_faults": True,
                           "target_throw_after_all_faults": False}
            with patch.object(runner, "OUT", output), \
                    patch.object(runner.audit_trial, "attest",
                                 return_value=attestation), \
                    patch.object(runner, "ORIGINAL_APPLY",
                                 side_effect=lambda *_args: captured.append(_args[2])):
                runner._applied(state, self.config, result, item)
            self.assertFalse(captured[0]["feedback"]["target_exception_candidate"])
            self.assertEqual([], captured[0]["feedback"]["coverage_ids"])
            self.assertIn("target throw did not follow",
                          state["dropped_trials"][-1]["reason"])

    def test_seed_copy_is_idempotent_and_rejects_tampered_prior_trial(self):
        with tempfile.TemporaryDirectory(prefix="solr15-v3-seed-test-") as temp:
            output = Path(temp) / "continuation"
            with patch.object(seed, "OUT", output):
                receipt = seed.prepare(self.config)
                self.assertEqual([0, 1, 2, 3, 4],
                                 seed.read(output / "checkpoint.json")["completed_trials"])
                self.assertEqual(receipt, seed.prepare(self.config))
                trial = output / "trials/r0002/result.json"
                trial.write_text(trial.read_text() + " ")
                with self.assertRaisesRegex(ValueError, "prior evidence changed"):
                    seed.prepare(self.config)


if __name__ == "__main__":
    unittest.main()
