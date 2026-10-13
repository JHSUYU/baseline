"""Checkpoint and selection tests for the native GraphChecker queue."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.graphchecker_fuzzer import (_accept_result, _enqueue, _finish,
                                             _new_state, _pick, _resume_active,
                                             run_campaign)


class GraphCheckerFuzzerTest(unittest.TestCase):
    def config(self):
        return {"schema_version": 1, "case_id": "fixture",
                "config_sha256": "config-sha"}

    def budget(self):
        return {"fault_trials": 4, "seconds": 60, "max_faults_per_trial": 2}

    def door(self, seq, ordinal, tier="observed_closure"):
        return {"siteId": "io", "node": "nn-1#epoch0",
                "occurrenceId": f"occ-{ordinal}", "ordinal": ordinal,
                "exceptionClass": "java.io.IOException", "seq": seq,
                "tier": tier}

    def result(self, plan, doors=None):
        return {"schema_version": 1, "case_id": "fixture", "status": "checked",
                "elapsed_seconds": 2.5, "fault_plan": plan,
                "junit_passed": True, "target_exception_triggered": False,
                "target_exception_candidate": False,
                "evidence": {"strict_injection": bool(plan),
                             "post_fault_target_reached": bool(plan),
                             "target_reached": True,
                             "last_fault_seq": 4 if plan else None,
                             "eligible_doors": doors or []},
                "graphchecker_feedback": {"newClosureEdges": 1,
                                           "newClosureCoverageSites": 2}}

    def test_enqueue_samples_late_occurrences_and_excludes_after_target(self):
        state = _new_state(self.config(), self.budget())
        doors = [self.door(i, i) for i in range(1, 101)]
        doors.append(self.door(101, 101, "after_target"))
        self.assertEqual(5, _enqueue(state, self.result([], doors), []))
        ordinals = {item["faults"][0]["ordinal"] for item in state["queue"]}
        self.assertEqual({1, 25, 50, 75, 100}, ordinals)
        self.assertNotIn(101, ordinals)

    def test_mutation_adds_only_later_observed_fault(self):
        state = _new_state(self.config(), self.budget())
        first = {key: self.door(2, 1)[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        doors = [self.door(3, 2), self.door(6, 3)]
        self.assertEqual(1, _enqueue(state, self.result([first], doors), [first]))
        self.assertEqual(3, state["queue"][0]["faults"][-1]["ordinal"])
        self.assertEqual(2, len(state["queue"][0]["faults"]))

    def test_periodic_exploration_selects_static_may(self):
        state = _new_state(self.config(), self.budget())
        _enqueue(state, self.result([], [self.door(1, 1),
                                         self.door(2, 2, "static_may_observed")]), [])
        self.assertEqual("static_may_observed", _pick(state["queue"], 4)["tier"])

    def test_reconcile_completed_active_trial_without_rerunning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = root / "trials" / "r0000"
            trial.mkdir(parents=True)
            result = self.result([], [self.door(1, 1)])
            (trial / "result.json").write_text(json.dumps(result))
            state = _new_state(self.config(), self.budget())
            state["active"] = {"index": 0, "name": "r0000", "faults": []}
            with patch("Mallory.core.graphchecker_fuzzer.run_trial") as runner:
                _resume_active(state, root, self.config(), root / "prepared")
            runner.assert_not_called()
            self.assertIsNone(state["active"])
            self.assertEqual("r0000", state["healthy"]["name"])
            self.assertEqual(1, len(state["queue"]))

    def test_failing_healthy_junit_does_not_seed_fault_queue(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        baseline = self.result([], [self.door(1, 1)])
        baseline["junit_passed"] = False
        _accept_result(state, "r0000", baseline)
        self.assertEqual("blocked_healthy_junit", state["status"])
        self.assertEqual([], state["queue"])

    def test_terminal_checkpoint_returns_without_prepare_or_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_file = root / "config.json"
            config_file.write_text("{}")
            state = _new_state(self.config(), self.budget())
            state["status"] = "complete_queue"
            state["terminal"] = True
            (root / "checkpoint.json").write_text(json.dumps(state))
            with patch("Mallory.core.graphchecker_fuzzer.load_config",
                       return_value=self.config()), patch(
                       "Mallory.core.graphchecker_fuzzer._budget",
                       return_value=self.budget()), patch(
                       "Mallory.core.graphchecker_fuzzer.prepare") as prepare:
                returned = run_campaign(config_file, root)
            prepare.assert_not_called()
            self.assertTrue(returned["terminal"])
            self.assertTrue((root / "summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
