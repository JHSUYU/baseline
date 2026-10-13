"""Checkpoint and selection tests for the native GraphChecker queue."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.graphchecker_campaign import _archive_jsonl
from Mallory.core.graphchecker_fuzzer import (_accept_result, _enqueue, _finish,
                                             _plan_key,
                                             _new_state, _pick, _resume_active,
                                             run_campaign)


class GraphCheckerFuzzerTest(unittest.TestCase):
    def config(self):
        return {"schema_version": 1, "case_id": "fixture",
                "config_sha256": "config-sha"}

    def budget(self):
        return {"fault_trials": 4, "seconds": 60, "max_faults_per_trial": 2}

    def door(self, seq, ordinal, tier="observed_closure", site="io"):
        return {"siteId": site, "node": "nn-1#epoch0",
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
                             "injection_specific_target_reached": bool(plan),
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

    def test_enqueue_preserves_stable_replay_selector(self):
        state = _new_state(self.config(), self.budget())
        door = {**self.door(1, 1), "replayOccurrenceId": "stable-rpc-lineage"}
        self.assertEqual(1, _enqueue(state, self.result([], [door]), []))
        self.assertEqual("stable-rpc-lineage",
                         state["queue"][0]["faults"][0]["replayOccurrenceId"])
        changed_seed = {**state["queue"][0]["faults"][0],
                        "occurrenceId": "different-exact-rpc-id"}
        self.assertEqual(_plan_key([changed_seed]),
                         _plan_key(state["queue"][0]["faults"]))

    def test_summary_tracks_guard_coverage_across_trials(self):
        state = _new_state({**self.config(), "target": {
            "check_site_id": "guard-a", "check_site_ids": ["guard-a", "guard-b"]}},
            self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1)])
        healthy["evidence"]["observed_check_sites"] = ["guard-a"]
        _accept_result(state, "r0000", healthy)
        state["active"] = {"index": 1, "name": "r0001", "faults": []}
        faulted = self.result([], [])
        faulted["evidence"]["observed_check_sites"] = ["guard-b"]
        _accept_result(state, "r0001", faulted)
        with tempfile.TemporaryDirectory() as temp:
            state["status"] = "complete_queue"
            _finish(state, Path(temp))
            summary = json.loads((Path(temp) / "summary.json").read_text())
        self.assertEqual(["guard-a", "guard-b"], summary["observed_check_sites"])
        self.assertEqual([], summary["missing_check_sites"])

    def test_periodic_exploration_selects_static_may(self):
        state = _new_state(self.config(), self.budget())
        _enqueue(state, self.result([], [self.door(1, 1),
                                         self.door(2, 2, "static_may_observed")]), [])
        self.assertEqual("static_may_observed", _pick(state["queue"], 4)["tier"])

    def test_v2_periodic_selected_scope_quota_and_site_fairness(self):
        state = _new_state(self.config(), self.budget())
        doors = [self.door(1, 1, site="closure-a"),
                 self.door(2, 2, site="closure-b"),
                 self.door(3, 3, "static_may_observed", "may"),
                 self.door(4, 4, "selected_scope_observed", "scope")]
        _enqueue(state, self.result([], doors), [])
        state["last_fault_site_attempts"]["closure-a"] = 3
        first = _pick(state["queue"], 0, state)
        self.assertEqual("closure-b", first["faults"][-1]["siteId"])
        self.assertEqual("static_may_observed",
                         _pick(state["queue"], 2, state)["tier"])
        self.assertEqual("selected_scope_observed",
                         _pick(state["queue"], 5, state)["tier"])

    def test_v1_checkpoint_keeps_old_outside_tier(self):
        state = _new_state(self.config(), self.budget())
        state.pop("scheduler_version")
        _enqueue(state, self.result([], [self.door(
            1, 1, "selected_scope_observed", "scope")]), [])
        self.assertEqual("outside_closure", state["queue"][0]["tier"])

    def test_unrelated_later_target_does_not_expand_fault_sequence(self):
        state = _new_state(self.config(), self.budget())
        fault = {key: self.door(1, 1)[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        state["active"] = {"index": 1, "name": "r0001", "faults": [fault]}
        result = self.result([fault], [self.door(6, 2)])
        result["evidence"]["injection_specific_target_reached"] = False
        result["target_exception_triggered"] = True
        _accept_result(state, "r0001", result)
        self.assertEqual([], state["queue"])
        self.assertEqual(1, state["last_fault_site_strict"]["io"])

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

    def test_resume_validates_compressed_trial_before_accepting_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = root / "trials" / "r0000"
            trial.mkdir(parents=True)
            artifacts = {}
            for name, filename in (("raw_trace", "graphchecker-raw.jsonl"),
                                   ("window_trace", "graphchecker-trace.jsonl"),
                                   ("graph", "graphchecker-graph.jsonl")):
                source = trial / filename
                source.write_text('{"kind":"WINDOW_OPEN","seq":1}\n')
                artifacts[name] = _archive_jsonl(source, trial)
            result = self.result([], [self.door(1, 1)])
            result.update({"backend": "graphchecker_native", "artifacts": artifacts,
                           "raw_trace_sha256": artifacts["raw_trace"]["content_sha256"],
                           "trace_sha256": artifacts["window_trace"]["content_sha256"],
                           "graph_sha256": artifacts["graph"]["content_sha256"]})
            (trial / "result.json").write_text(json.dumps(result))
            state = _new_state(self.config(), self.budget())
            state["active"] = {"index": 0, "name": "r0000", "faults": []}
            with patch("Mallory.core.graphchecker_fuzzer.run_trial") as runner:
                _resume_active(state, root, self.config(), root / "prepared")
            runner.assert_not_called()
            self.assertIsNone(state["active"])
            state["status"] = "complete_queue"
            state["terminal"] = True
            (root / "checkpoint.json").write_text(json.dumps(state))
            with (trial / "graphchecker-trace.jsonl.gz").open("ab") as archive:
                archive.write(b"changed")
            config_file = root / "config.json"
            config_file.write_text("{}")
            with patch("Mallory.core.graphchecker_fuzzer.load_config",
                       return_value=self.config()), patch(
                       "Mallory.core.graphchecker_fuzzer._budget",
                       return_value=self.budget()):
                with self.assertRaisesRegex(ValueError, "changed window_trace"):
                    run_campaign(config_file, root)

    def test_failing_healthy_junit_does_not_seed_fault_queue(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        baseline = self.result([], [self.door(1, 1)])
        baseline["junit_passed"] = False
        _accept_result(state, "r0000", baseline)
        self.assertEqual("blocked_healthy_junit", state["status"])
        self.assertEqual([], state["queue"])

    def test_unmatched_plan_requeues_twice_with_budget_accounting(self):
        state = _new_state(self.config(), self.budget())
        fault = {key: self.door(1, 1)[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        for index in range(1, 4):
            state["active"] = {"index": index, "name": f"r{index:04d}",
                               "faults": [fault], "selection_tier": "observed_closure",
                               "unmatched_retry": index - 1}
            trial = self.result([fault])
            trial["status"] = "unmatched"
            trial["evidence"]["strict_injection"] = False
            trial["evidence"]["post_fault_target_reached"] = False
            _accept_result(state, f"r{index:04d}", trial)
            self.assertEqual(index, state["completed_fault_trials"])
            if index < 3:
                self.assertEqual(index, state["queue"][-1]["unmatched_retry"])
                state["queue"].clear()
            else:
                self.assertEqual([], state["queue"])
        self.assertEqual(7.5, state["trial_elapsed_seconds"])

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
