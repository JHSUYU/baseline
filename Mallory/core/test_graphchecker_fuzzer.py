"""Checkpoint and selection tests for the native GraphChecker queue."""

from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.core.graphchecker_campaign import _archive_jsonl, _trial_verdict
from Mallory.core.graphchecker_fuzzer import (_accept_result, _admit_capacity,
                                             _enqueue, _finish,
                                             _pause_running_jvm,
                                             _actor_site_key, _plan_key,
                                             _retention_score,
                                             _new_state, _pick, _resume_active,
                                             _trial_record,
                                             run_campaign)
from Mallory.core.resource_guard import CapacityGuardStop


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
                             "raw_target_check_rows": 0,
                             "raw_target_throw_rows": 0,
                             "unattributed_target_check_rows": 0,
                             "unattributed_target_throw_rows": 0,
                             "attributed_target_check_rows": 0,
                             "attributed_target_throw_rows": 0,
                             "last_fault_seq": 4 if plan else None,
                             "eligible_doors": doors or []},
                "graphchecker_feedback": {"newClosureEdges": 1,
                                           "newClosureCoverageSites": 2,
                                           "closureNodeFamilies": ["target"],
                                           "closureEdgeFamilies": [],
                                           "closureCoverageSiteIds": []}}

    def test_checkpoint_keeps_raw_differential_separate_from_graph_candidate(self):
        result = self.result([self.door(1, 1)])
        result["target_exception_triggered"] = True
        result["target_exception_candidate_raw_differential"] = True
        record = _trial_record("r0001", result)
        self.assertTrue(record["target_exception_candidate_raw_differential"])
        self.assertFalse(record["target_exception_candidate"])

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
        state["scheduler_version"] = 4
        first = {key: self.door(2, 1)[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        doors = [self.door(3, 2), self.door(6, 3)]
        self.assertEqual(1, _enqueue(state, self.result([first], doors), [first]))
        self.assertEqual(3, state["queue"][0]["faults"][-1]["ordinal"])
        self.assertEqual(2, len(state["queue"][0]["faults"]))
        self.assertTrue(state["queue"][0]["parent_target_retained"])
        self.assertGreater(state["queue"][0]["parent_graph_delta"], 0)

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
        state["scheduler_version"] = 2
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

    def test_v3_repeated_target_loss_downweights_but_keeps_site(self):
        state = _new_state(self.config(), self.budget())
        doors = [self.door(1, 1, site="lost-site"),
                 self.door(2, 2, site="fresh-site")]
        _enqueue(state, self.result([], doors), [])
        state["site_target_retention"][_actor_site_key(doors[0])] = {
            "preserved": 0, "lost": 5, "productive": 0}
        self.assertEqual("fresh-site", _pick(state["queue"], 0, state)[
            "faults"][-1]["siteId"])
        self.assertEqual("lost-site", _pick(state["queue"], 1, state)[
            "faults"][-1]["siteId"])

    def test_v3_productive_parent_and_external_quota(self):
        state = _new_state(self.config(), self.budget())
        doors = [self.door(1, 1, site="closure-a"),
                 self.door(2, 2, site="closure-b"),
                 self.door(3, 3, "selected_scope_observed", "scope")]
        _enqueue(state, self.result([], doors), [])
        for item in state["queue"]:
            if item["faults"][-1]["siteId"] == "closure-b":
                item["parent_target_retained"] = True
                item["parent_graph_delta"] = 8
        self.assertEqual("closure-b", _pick(state["queue"], 0, state)[
            "faults"][-1]["siteId"])
        self.assertEqual("selected_scope_observed",
                         _pick(state["queue"], 5, state)["tier"])

    def test_v3_outside_closure_gets_sparse_fixed_slot(self):
        state = _new_state(self.config(), self.budget())
        _enqueue(state, self.result([], [
            self.door(1, 1, site="closure"),
            self.door(2, 2, "outside_closure", "outside")]), [])
        self.assertEqual("outside_closure", _pick(state["queue"], 17, state)[
            "tier"])

    def test_static_producer_fault_can_extend_once_without_causal_credit(self):
        state = _new_state(self.config(), self.budget())
        first_door = self.door(2, 1, "static_may_observed", "rpc-reply")
        first = {key: first_door[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        state["active"] = {"index": 1, "name": "r0001", "faults": [first],
                           "selection_tier": "static_may_observed",
                           "static_producer_frontier": True}
        closure = self.door(6, 2, "observed_closure", "target-io")
        unrelated = self.door(7, 3, "outside_closure", "unrelated-io")
        faulted = self.result([first], [closure, unrelated])
        faulted["evidence"]["injection_specific_target_reached"] = False
        _accept_result(state, "r0001", faulted)
        self.assertEqual(0, state["trials"][0]["target_closure_novelty"])
        self.assertEqual("checked", state["trials"][0]["status"])
        self.assertFalse(state["trials"][0]["target_exception_candidate"])
        self.assertEqual(1, state["producer_frontier_continuations_enqueued"])
        self.assertEqual(1, len(state["queue"]))
        continuation = _pick(state["queue"], 7, state)
        self.assertTrue(continuation["producer_frontier_continuation"])
        self.assertEqual(["rpc-reply", "target-io"],
                         [fault["siteId"] for fault in continuation["faults"]])
        self.assertEqual("observed_closure", continuation["tier"])

    def test_static_producer_continuation_requires_retained_target(self):
        state = _new_state(self.config(), self.budget())
        first_door = self.door(2, 1, "static_may_observed", "rpc-reply")
        first = {key: first_door[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        state["active"] = {"index": 1, "name": "r0001", "faults": [first],
                           "static_producer_frontier": True}
        faulted = self.result([first], [self.door(6, 2)])
        faulted["evidence"]["injection_specific_target_reached"] = False
        faulted["evidence"]["post_fault_target_reached"] = False
        _accept_result(state, "r0001", faulted)
        self.assertEqual([], state["queue"])
        self.assertEqual(0, state["producer_frontier_continuations_enqueued"])

    def test_static_producer_continuation_queue_is_bounded(self):
        state = _new_state(self.config(), self.budget())
        first = {key: self.door(2, 1, "static_may_observed", "rpc-reply")[key]
                 for key in ("siteId", "node", "occurrenceId", "ordinal",
                             "exceptionClass")}
        state["active"] = {"index": 1, "name": "r0001", "faults": [first],
                           "static_producer_frontier": True}
        doors = [self.door(5 + index, 2 + index, site=f"io-{index}")
                 for index in range(16)]
        faulted = self.result([first], doors)
        faulted["evidence"]["injection_specific_target_reached"] = False
        _accept_result(state, "r0001", faulted)
        self.assertEqual(8, len(state["queue"]))
        self.assertEqual(8, state["producer_frontier_continuations_enqueued"])

    def test_v3_target_loss_does_not_penalize_another_logical_node(self):
        state = _new_state(self.config(), self.budget())
        nn = self.door(1, 1, site="shared-site")
        dn = {**self.door(2, 2, site="shared-site"), "node": "dn-1#epoch0"}
        self.assertEqual(_actor_site_key(nn), _actor_site_key({
            **nn, "node": "nn-1#epoch3"}))
        _enqueue(state, self.result([], [nn, dn]), [])
        state["site_target_retention"][_actor_site_key(nn)] = {
            "preserved": 0, "lost": 5, "productive": 0}
        self.assertEqual("dn-1#epoch0", _pick(state["queue"], 0, state)[
            "faults"][-1]["node"])

    def test_v3_retention_history_counts_only_strict_faults(self):
        state = _new_state(self.config(), self.budget())
        state["scheduler_version"] = 3
        fault = {key: self.door(1, 1)[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        state["active"] = {"index": 1, "name": "r0001", "faults": [fault]}
        lost = self.result([fault])
        lost["evidence"]["injection_specific_target_reached"] = False
        _accept_result(state, "r0001", lost)
        actor_site = _actor_site_key(fault)
        self.assertEqual({"preserved": 0, "lost": 1, "productive": 0},
                         state["site_target_retention"][actor_site])
        state["active"] = {"index": 2, "name": "r0002", "faults": [fault]}
        _accept_result(state, "r0002", self.result([fault]))
        self.assertEqual({"preserved": 1, "lost": 1, "productive": 1},
                         state["site_target_retention"][actor_site])
        state["active"] = {"index": 3, "name": "r0003", "faults": [fault]}
        unmatched = self.result([fault])
        unmatched["status"] = "unmatched"
        unmatched["evidence"]["strict_injection"] = False
        unmatched["evidence"]["injection_specific_target_reached"] = False
        _accept_result(state, "r0003", unmatched)
        self.assertEqual({"preserved": 1, "lost": 1, "productive": 1},
                         state["site_target_retention"][actor_site])
        item = {"tier": "observed_closure", "novelty": 0,
                "faults": [fault], "enqueued_at": 0}
        bad = {**state, "site_target_retention": {actor_site: {
            "preserved": 0, "lost": 5, "productive": 0}}}
        self.assertGreater(_retention_score(item, 2, state),
                           _retention_score(item, 2, bad))

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

    def test_v4_target_absent_bootstraps_only_observed_typed_static_doors(self):
        state = _new_state(self.config(), self.budget())
        state["scheduler_version"] = 4
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        doors = [self.door(1, 1, "observed_closure", "fake-closure"),
                 self.door(2, 2, "static_may_observed", "may"),
                 self.door(3, 3, "selected_scope_observed", "scope"),
                 self.door(4, 4, "outside_closure", "outside"),
                 {**self.door(5, 5, "static_may_observed", "untyped"),
                  "exceptionClass": None}]
        healthy = self.result([], doors)
        healthy["status"] = "healthy_seed"
        healthy["evidence"]["target_reached"] = False
        healthy["graphchecker_feedback"] = {"newClosureEdges": 99,
                                             "newClosureNodes": 99}
        _accept_result(state, "r0000", healthy)
        self.assertEqual(4, state["scheduler_version"])
        self.assertEqual(1, state["bootstrap_policy_version"])
        self.assertEqual("running", state["status"])
        self.assertFalse(state["healthy_target_reached"])
        self.assertEqual(2, state["bootstrap_seed_doors"])
        self.assertEqual({"may", "scope"}, {
            item["faults"][0]["siteId"] for item in state["queue"]})
        self.assertTrue(all(len(item["faults"]) == 1 and
                            item["novelty"] == 0 and item["bootstrap_seed"]
                            for item in state["queue"]))

    def test_v4_target_absent_requires_observed_typed_static_door(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "outside_closure")])
        healthy["evidence"]["target_reached"] = False
        _accept_result(state, "r0000", healthy)
        self.assertEqual("no_observed_fault_door", state["status"])
        self.assertEqual(0, state["bootstrap_seed_doors"])
        self.assertEqual([], state["queue"])

    def test_v5_unattributed_healthy_target_blocks_without_spending_budget(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "static_may_observed", "may")])
        healthy["evidence"].update(
            target_reached=False, raw_target_check_rows=2,
            unattributed_target_check_rows=2)
        _accept_result(state, "r0000", healthy)
        self.assertEqual("blocked_healthy_target_attribution", state["status"])
        self.assertTrue(state["terminal"])
        self.assertEqual(0, state["completed_fault_trials"])
        self.assertEqual([], state["queue"])
        self.assertEqual(2, state["healthy"]["unattributed_target_check_rows"])

    def test_v5_truly_absent_healthy_target_keeps_bootstrap(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "static_may_observed", "may")])
        healthy["evidence"]["target_reached"] = False
        _accept_result(state, "r0000", healthy)
        self.assertEqual("running", state["status"])
        self.assertEqual(1, state["bootstrap_seed_doors"])
        self.assertEqual(1, len(state["queue"]))

    def test_v5_healthy_gate_requires_all_exact_rows_unattributed(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "static_may_observed", "may")])
        healthy["evidence"].update(
            target_reached=False, raw_target_check_rows=2,
            unattributed_target_check_rows=1,
            attributed_target_check_rows=1)
        _accept_result(state, "r0000", healthy)
        self.assertEqual("running", state["status"])
        self.assertEqual(1, len(state["queue"]))

    def test_v4_unattributed_healthy_target_preserves_old_bootstrap(self):
        state = _new_state(self.config(), self.budget())
        state["scheduler_version"] = 4
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "static_may_observed", "may")])
        healthy["evidence"].update(
            target_reached=False, raw_target_check_rows=1,
            unattributed_target_check_rows=1)
        _accept_result(state, "r0000", healthy)
        self.assertEqual("running", state["status"])
        self.assertEqual(1, len(state["queue"]))

    def test_v4_bootstrap_expands_only_after_strict_causal_target_discovery(self):
        state = _new_state(self.config(), {**self.budget(),
                                           "max_faults_per_trial": 3})
        state["scheduler_version"] = 4
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "static_may_observed", "may")])
        healthy["evidence"]["target_reached"] = False
        _accept_result(state, "r0000", healthy)
        seed = state["queue"].pop()
        fault = seed["faults"][0]
        state["active"] = {"index": 1, "name": "r0001", "faults": [fault],
                           "bootstrap_seed": True}
        absent = self.result([fault], [self.door(6, 2, "static_may_observed", "new")])
        absent["evidence"].update(target_reached=False,
                                  injection_specific_target_reached=False)
        absent["graphchecker_feedback"].update(edges=5, nodes=3,
            globalCoverageSiteIds=["branch:a:true"])
        _accept_result(state, "r0001", absent)
        self.assertEqual(1, len(state["queue"]))
        self.assertIsNone(state["target_discovered_trial"])
        self.assertEqual(1, state["bootstrap_fault_trials"])
        second = state["queue"].pop()
        self.assertEqual(["may", "new"], [
            fault["siteId"] for fault in second["faults"]])
        self.assertEqual("static_may_observed", second["tier"])
        self.assertTrue(second["bootstrap_seed"])
        self.assertFalse(second["parent_target_retained"])
        self.assertEqual(0, second["parent_graph_delta"])
        self.assertGreater(second["novelty"], 0)
        self.assertEqual({"new_io_sites": 1, "new_coverage_sites": 1,
                          "graph_edge_count_gain": 5,
                          "graph_node_count_gain": 3},
                         state["trials"][0]["bootstrap_feedback"])

        state["active"] = {"index": 2, "name": "r0002", "faults": second["faults"],
                           "bootstrap_seed": True}
        discovered = self.result(second["faults"], [self.door(6, 3)])
        _accept_result(state, "r0002", discovered)
        self.assertEqual("r0002", state["target_discovered_trial"])
        self.assertEqual(2, state["bootstrap_fault_trials"])
        self.assertEqual(1, len(state["queue"]))
        self.assertEqual(3, len(state["queue"][0]["faults"]))
        self.assertEqual("observed_closure", state["queue"][0]["tier"])
        self.assertGreater(state["queue"][0]["novelty"], 0)

    def test_v4_bootstrap_does_not_expand_from_unrelated_target_or_unmatched(self):
        for strict, reached in ((True, True), (False, False)):
            with self.subTest(strict=strict, reached=reached):
                state = _new_state(self.config(), self.budget())
                state["active"] = {"index": 0, "name": "r0000", "faults": []}
                healthy = self.result([], [self.door(
                    1, 1, "static_may_observed", "may")])
                healthy["evidence"]["target_reached"] = False
                _accept_result(state, "r0000", healthy)
                seed = state["queue"].pop()
                state["active"] = {"index": 1, "name": "r0001",
                                   "faults": seed["faults"],
                                   "bootstrap_seed": True}
                later = self.result(seed["faults"], [self.door(
                    6, 2, "observed_closure", "fake-closure")])
                later["evidence"].update(
                    strict_injection=strict, target_reached=reached,
                    injection_specific_target_reached=False)
                if not strict:
                    later["status"] = "unmatched"
                _accept_result(state, "r0001", later)
                self.assertIsNone(state["target_discovered_trial"])
                self.assertFalse(any(len(item["faults"]) > 1 for item in state["queue"]))

    def test_v4_bootstrap_depth_and_trial_limits(self):
        state = _new_state(self.config(), {"fault_trials": 2, "seconds": 60,
                                            "max_faults_per_trial": 5})
        self.assertEqual({"fault_trials": 2, "max_faults_per_trial": 3},
                         state["bootstrap_limits"])
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, "static_may_observed", "may")])
        healthy["evidence"]["target_reached"] = False
        _accept_result(state, "r0000", healthy)
        for index in (1, 2):
            item = state["queue"].pop()
            state["active"] = {"index": index, "name": f"r{index:04d}",
                               "faults": item["faults"],
                               "bootstrap_seed": True}
            absent = self.result(item["faults"], [self.door(
                5 + index, index + 1, "static_may_observed", f"next-{index}")])
            absent["evidence"].update(target_reached=False,
                                      injection_specific_target_reached=False)
            _accept_result(state, f"r{index:04d}", absent)
        self.assertEqual("complete_bootstrap_budget", state["status"])
        self.assertEqual([], state["queue"])
        self.assertIsNone(state["target_discovered_trial"])

    def test_v2_v3_checkpoints_keep_target_absent_terminal_behavior(self):
        for version in (2, 3):
            with self.subTest(version=version):
                state = _new_state(self.config(), self.budget())
                state["scheduler_version"] = version
                state.pop("bootstrap_policy_version")
                state["active"] = {"index": 0, "name": "r0000", "faults": []}
                healthy = self.result([], [self.door(
                    1, 1, "static_may_observed", "may")])
                healthy["evidence"]["target_reached"] = False
                _accept_result(state, "r0000", healthy)
                self.assertEqual("no_healthy_target", state["status"])
                self.assertEqual([], state["queue"])

    def test_healthy_expected_throw_uses_prior_count_differential(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1)])
        healthy["evidence"]["target_throw_seen"] = True
        _accept_result(state, "r0000", healthy)
        self.assertTrue(state["healthy_target_reached"])
        self.assertEqual(1, len(state["queue"]))
        evidence = {"target_exception_triggered": True,
                    "injection_specific_target_reached": True,
                    "injection_specific_target_throw": True,
                    "target_throw_rows_after_fault": [{}, {}]}
        self.assertEqual(("candidate", True), _trial_verdict(evidence, [{}], 1))
        evidence["target_throw_rows_after_fault"].pop()
        self.assertEqual(("needs_differential_review", False),
                         _trial_verdict(evidence, [{}], 1))

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

    def test_external_healthy_seed_archive_is_pinned_across_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_file = root / "config.json"
            config_file.write_text("{}")
            seed = root / "independent-healthy.jsonl.gz"
            seed.write_bytes(b"healthy seed archive")
            config = {**self.config(), "target": {
                "throw_site_id": "throw", "exception_class": "java.io.IOException"}}
            state = _new_state(config, self.budget())
            state.update(status="complete_queue", terminal=True,
                         additional_healthy_seed_pins=[{
                             "path": str(seed.resolve()),
                             "archive_sha256": hashlib.sha256(
                                 seed.read_bytes()).hexdigest()}])
            (root / "checkpoint.json").write_text(json.dumps(state))
            with patch("Mallory.core.graphchecker_fuzzer.load_config",
                       return_value=config), patch(
                       "Mallory.core.graphchecker_fuzzer._budget",
                       return_value=self.budget()), patch(
                       "Mallory.core.graphchecker_fuzzer._prior_trace_metadata",
                       return_value=(0, "content-sha", "archive-sha")), patch(
                       "Mallory.core.graphchecker_fuzzer._prior_trace_profiles",
                       return_value={}):
                self.assertEqual("complete_queue", run_campaign(
                    config_file, root, additional_healthy_seeds=[seed])["status"])
                seed.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "healthy seeds changed"):
                    run_campaign(config_file, root, additional_healthy_seeds=[seed])

    def test_capacity_pause_checkpoints_before_preparation_and_can_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_file = root / "config.json"
            config_file.write_text('{"capacity_guard": {}}')
            refused = {"phase": "preparation", "reason": "pg0_start_floor",
                       "sample": {"pg0_available_bytes": 1}}
            accepted = {"phase": "preparation", "reason": None,
                        "sample": {"pg0_available_bytes": 2}}
            with patch("Mallory.core.graphchecker_fuzzer.load_config",
                       return_value=self.config()), patch(
                       "Mallory.core.graphchecker_fuzzer._budget",
                       return_value=self.budget()), patch(
                       "Mallory.core.graphchecker_fuzzer.load_capacity_guard",
                       return_value={}), patch(
                       "Mallory.core.graphchecker_fuzzer.check_capacity",
                       return_value=refused), patch(
                       "Mallory.core.graphchecker_fuzzer.prepare") as prepare:
                paused = run_campaign(config_file, root)
            prepare.assert_not_called()
            self.assertFalse(paused["terminal"])
            self.assertEqual("pg0_start_floor", paused["capacity_pause"]["reason"])
            self.assertIsNone(paused["active"])
            with patch("Mallory.core.graphchecker_fuzzer.check_capacity",
                       return_value=accepted):
                self.assertTrue(_admit_capacity(
                    paused, root / "checkpoint.json", {}, root, "preparation"))
            self.assertNotIn("capacity_pause", paused)
            self.assertNotIn("capacity_pause", json.loads(
                (root / "checkpoint.json").read_text()))

    def test_running_jvm_capacity_stop_preserves_active_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = _new_state(self.config(), self.budget())
            state["active"] = {"index": 1, "name": "r0001",
                               "faults": [{"siteId": "rpc"}]}
            receipt = {"phase": "running", "reason": "shm_floor",
                       "sample": {"scratch_available_bytes": 0}}
            paused = _pause_running_jvm(state, root / "checkpoint.json",
                                        CapacityGuardStop(receipt))
            self.assertFalse(paused["terminal"])
            self.assertEqual("r0001", paused["active"]["name"])
            saved = json.loads((root / "checkpoint.json").read_text())
            self.assertEqual(receipt, saved["capacity_pause"])

    def test_checkpoint_policy_preserves_v2_v3_v4_replay(self):
        for version in (2, 3, 4, 5):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config_file = root / "config.json"
                config_file.write_text("{}")
                state = _new_state(self.config(), self.budget())
                state["scheduler_version"] = version
                state["status"] = "complete_queue"
                state["terminal"] = True
                if version < 4:
                    for field in ("bootstrap_policy_version", "bootstrap_limits"):
                        state.pop(field)
                if version < 5:
                    for field in ("closure_novelty_policy_version",
                                  "seen_target_closure_node_families",
                                  "seen_target_closure_edge_families",
                                  "seen_target_closure_coverage_sites"):
                        state.pop(field)
                (root / "checkpoint.json").write_text(json.dumps(state))
                with patch("Mallory.core.graphchecker_fuzzer.load_config",
                           return_value=self.config()), patch(
                           "Mallory.core.graphchecker_fuzzer._budget",
                           return_value=self.budget()):
                    self.assertEqual("complete_queue", run_campaign(
                        config_file, root)["status"])
                    if version >= 4:
                        state["bootstrap_policy_version"] = 99
                        (root / "checkpoint.json").write_text(json.dumps(state))
                        with self.assertRaisesRegex(ValueError, "bootstrap checkpoint"):
                            run_campaign(config_file, root)

    def test_v5_repeated_target_closure_family_is_rewarded_once(self):
        state = _new_state(self.config(), {**self.budget(),
                                           "max_faults_per_trial": 3})
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([], [self.door(1, 1, site="seed")])
        healthy["graphchecker_feedback"].update(
            closureNodeFamilies=["target"], closureEdgeFamilies=[],
            closureCoverageSiteIds=["target-branch"])
        _accept_result(state, "r0000", healthy)
        self.assertEqual(0, state["healthy"]["target_closure_novelty"])
        self.assertEqual(["target"], state["seen_target_closure_node_families"])
        self.assertEqual(0, state["queue"][0]["novelty"])

        seed = state["queue"].pop()
        first = self.result(seed["faults"], [self.door(6, 2, site="child-1")])
        first["graphchecker_feedback"].update(
            closureNodeFamilies=["target", "recovery"],
            closureEdgeFamilies=["rpc-to-target"],
            closureCoverageSiteIds=["target-branch", "recovery-branch"])
        state["active"] = {"index": 1, "name": "r0001", "faults": seed["faults"]}
        _accept_result(state, "r0001", first)
        self.assertEqual(7, state["trials"][-1]["target_closure_novelty"])
        self.assertEqual({"new_node_families": 1,
                          "new_edge_families": 1,
                          "new_coverage_sites": 1},
                         state["trials"][-1]["target_closure_feedback"])
        self.assertEqual(7, state["queue"][-1]["novelty"])
        self.assertEqual(7, state["queue"][-1]["parent_graph_delta"])

        repeat = self.result(seed["faults"], [self.door(7, 3, site="child-2")])
        repeat["graphchecker_feedback"].update(
            closureNodeFamilies=["target", "recovery"],
            closureEdgeFamilies=["rpc-to-target"],
            closureCoverageSiteIds=["target-branch", "recovery-branch"],
            newClosureNodes=99, newClosureEdges=99,
            newClosureCoverageSites=99)
        state["active"] = {"index": 2, "name": "r0002", "faults": seed["faults"]}
        _accept_result(state, "r0002", repeat)
        self.assertEqual(0, state["trials"][-1]["target_closure_novelty"])
        self.assertEqual(0, state["queue"][-1]["novelty"])
        self.assertEqual(0, state["queue"][-1]["parent_graph_delta"])
        self.assertEqual(1, state["site_target_retention"][
            _actor_site_key(seed["faults"][-1])]["productive"])

    def test_v5_unmatched_or_unrelated_target_does_not_consume_novelty(self):
        state = _new_state(self.config(), self.budget())
        fault = {key: self.door(1, 1)[key] for key in
                 ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
        for index, strict, specific in ((1, False, False), (2, True, False)):
            state["active"] = {"index": index, "name": f"r{index:04d}",
                               "faults": [fault]}
            trial = self.result([fault])
            trial["evidence"]["strict_injection"] = strict
            trial["evidence"]["injection_specific_target_reached"] = specific
            trial["graphchecker_feedback"].update(
                closureNodeFamilies=["target", "new"],
                closureEdgeFamilies=[], closureCoverageSiteIds=[])
            _accept_result(state, f"r{index:04d}", trial)
            self.assertEqual(0, state["trials"][-1]["target_closure_novelty"])
        self.assertEqual([], state["seen_target_closure_node_families"])

    def test_v5_rejects_target_feedback_without_family_identity(self):
        state = _new_state(self.config(), self.budget())
        state["active"] = {"index": 0, "name": "r0000", "faults": []}
        healthy = self.result([])
        healthy["graphchecker_feedback"].pop("closureEdgeFamilies")
        with self.assertRaisesRegex(ValueError, "closure family field missing"):
            _accept_result(state, "r0000", healthy)
        self.assertEqual([], state["seen_target_closure_node_families"])

    def test_v5_resume_preserves_seen_families_and_reconciles_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = _new_state(self.config(), self.budget())
            state["seen_target_closure_node_families"] = ["recovery", "target"]
            state["seen_target_closure_edge_families"] = ["rpc-to-target"]
            state["seen_target_closure_coverage_sites"] = ["branch"]
            fault = {key: self.door(1, 1)[key] for key in
                     ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")}
            state["active"] = {"index": 1, "name": "r0001", "faults": [fault]}
            trial = root / "trials" / "r0001"
            trial.mkdir(parents=True)
            result = self.result([fault], [self.door(6, 2, site="child")])
            result["graphchecker_feedback"].update(
                closureNodeFamilies=["target", "recovery"],
                closureEdgeFamilies=["rpc-to-target"],
                closureCoverageSiteIds=["branch"],
                newClosureEdges=99)
            (trial / "result.json").write_text(json.dumps(result))
            state = json.loads(json.dumps(state))  # checkpoint roundtrip
            with patch("Mallory.core.graphchecker_fuzzer.run_trial") as runner:
                _resume_active(state, root, self.config(), root / "prepared")
            runner.assert_not_called()
            self.assertEqual(1, state["completed_fault_trials"])
            self.assertEqual(0, state["trials"][0]["target_closure_novelty"])
            self.assertEqual(0, state["queue"][0]["novelty"])

            state["status"] = "complete_queue"
            (root / "checkpoint.json").write_text(json.dumps(state))
            config_file = root / "config.json"
            config_file.write_text("{}")
            with patch("Mallory.core.graphchecker_fuzzer.load_config",
                       return_value=self.config()), patch(
                       "Mallory.core.graphchecker_fuzzer._budget",
                       return_value=self.budget()), patch(
                       "Mallory.core.graphchecker_fuzzer._verify_recorded_evidence"):
                self.assertEqual(1, run_campaign(config_file, root)[
                    "completed_fault_trials"])
                state["closure_novelty_policy_version"] = 99
                (root / "checkpoint.json").write_text(json.dumps(state))
                with self.assertRaisesRegex(ValueError, "closure novelty policy"):
                    run_campaign(config_file, root)
                state["closure_novelty_policy_version"] = 1
                state.pop("seen_target_closure_edge_families")
                (root / "checkpoint.json").write_text(json.dumps(state))
                with self.assertRaisesRegex(ValueError, "closure novelty checkpoint"):
                    run_campaign(config_file, root)

    def test_wave_pause_preserves_immutable_successor_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_file = root / "config.json"
            config_file.write_text("{}")
            (root / "prepared").mkdir()
            (root / "prepared" / "weave-receipt.json").write_text("{}")
            state = _new_state(self.config(), self.budget())
            state["healthy"] = {"name": "r0000"}
            state["completed_fault_trials"] = 1
            state["next_trial_index"] = 2
            _enqueue(state, self.result([], [self.door(1, 1)]), [])
            (root / "checkpoint.json").write_text(json.dumps(state))

            def complete_selected(current, *_):
                if current["active"] is not None:
                    current["completed_fault_trials"] += 1
                    current["active"] = None

            with patch("Mallory.core.graphchecker_fuzzer.load_config",
                       return_value=self.config()), patch(
                       "Mallory.core.graphchecker_fuzzer._budget",
                       return_value=self.budget()), patch(
                       "Mallory.core.graphchecker_fuzzer._verify_recorded_evidence"), patch(
                       "Mallory.core.graphchecker_fuzzer._resume_active",
                       side_effect=complete_selected) as runner:
                paused = run_campaign(config_file, root, stop_after_fault_trials=1)
                self.assertEqual("running", paused["status"])
                self.assertFalse(paused["terminal"])
                self.assertEqual(1, paused["completed_fault_trials"])
                self.assertEqual(1, len(paused["queue"]))
                self.assertEqual(self.budget(), paused["budget"])
                self.assertEqual("config-sha", paused["config_sha256"])
                self.assertFalse((root / "summary.json").exists())
                self.assertEqual(1, runner.call_count)  # no fault trial in wave one

                successor = run_campaign(config_file, root,
                                         stop_after_fault_trials=2)
                self.assertEqual(2, successor["completed_fault_trials"])
                self.assertEqual(self.budget(), successor["budget"])
                self.assertEqual("config-sha", successor["config_sha256"])
                self.assertEqual(2, json.loads((root / "checkpoint.json").read_text())[
                    "completed_fault_trials"])


if __name__ == "__main__":
    unittest.main()
