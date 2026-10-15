"""Opt-in exact-anchor campaign tests without running a cluster JUnit."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign as core


def fault(ordinal: int = 1) -> dict:
    return {"siteId": "<Io: void send()>#u1", "node": "n0",
            "actorEpochOrdinal": 0, "ordinal": ordinal,
            "exceptionClass": "java.io.IOException",
            "sourceOccurrenceId": f"door-{ordinal}"}


def anchor(address: str) -> dict:
    summary = {"status": "target_reached", "targetReached": True,
               "closureMembershipAuthority":
               "original_runtime_selected_region_finalizer",
               "targetEvidence": {"selectedOccurrenceAddress": address,
                                  "targetCheckOccurrenceIds": ["target-a"]},
               "closureOccurrenceIds": ["door-1"]}
    return {"occurrenceAddress": address, "targetReached": True,
            "summary": summary}


class MultiAnchorCampaignTest(unittest.TestCase):
    def test_old_plan_key_is_bytewise_unchanged_and_anchor_namespaces_it(self):
        one = fault()
        stable = [{key: one[key] for key in core.SELECTOR_FIELDS}]
        old = hashlib.sha256(json.dumps(stable, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(old, core._plan_key([one]))
        self.assertNotEqual(old, core._plan_key([one], "target-a"))
        self.assertNotEqual(core._plan_key([one], "target-a"),
                            core._plan_key([one], "target-b"))

    def test_healthy_queues_doors_per_exact_original_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = {"status": "multi_target_recorded",
                      "retryExactOccurrences": [],
                      "anchors": [anchor("target-a"), anchor("target-b")]}
            result = {"raw_exact_target_throw_count": 0,
                      "eligible_doors": [], "native_target_retained": False}
            doors = [{"fault": fault(), "seq": 1,
                      "tier": "observed_closure"}]
            with patch.object(core, "_region_doors", return_value=doors):
                actual = core._complete_multi_healthy(
                    {"target_site": "Target#u1", "recording": {
                        "multi_target_max_anchors": 2}},
                    Path(directory), result, [], bundle)
            self.assertEqual("healthy_seed", actual["status"])
            self.assertEqual(["target-a", "target-b"],
                             actual["multi_anchor_addresses"])
            self.assertEqual(["target-a", "target-b"],
                             [row["anchor_address"] for row in actual[
                                 "eligible_doors"]])
            self.assertTrue((Path(directory) / "native-summary.json").is_file())

    def test_healthy_region_trial_records_bounded_graphs_once(self):
        bundle = {"schemaVersion": 1, "status": "multi_target_recorded",
                  "retryExactOccurrences": [],
                  "anchors": [anchor("target-a"), anchor("target-b")]}
        config = {"recording": {"test_id": "Example#test", "static_scope_map":
                    "/unused/scope", "candidate_graph": "/unused/graph",
                    "region_skeletons": "/unused/skeleton",
                    "multi_target_max_anchors": 2},
                  "target_site": "Target#u1", "target_throw": {"siteId":
                    "Target#u2", "exceptionClass": "java.io.IOException"}}
        doors = [{"fault": fault(), "seq": 1, "tier": "observed_closure"}]
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(core, "_region_schedule"), \
             patch.object(core, "_analysis_engine_jar", return_value=Path("/unused/jar")), \
             patch.object(core, "record_multiple_region_states",
                          return_value=bundle) as original_graph, \
             patch.object(core, "_region_doors", return_value=doors):
            trial = Path(directory)
            (trial / "iteration-native").mkdir()
            result = core._run_region_trial(config,
                {"weave_config": {"java": "/unused/java"}}, trial, [], None,
                {"junit_passed": True, "raw_exact_target_throw_count": 0},
                [], False, 10)
        self.assertEqual(1, original_graph.call_count)
        self.assertEqual(2, original_graph.call_args.kwargs["max_anchors"])
        self.assertEqual("healthy_seed", result["status"])
        self.assertEqual(["target-a", "target-b"],
                         [row["anchor_address"] for row in result[
                             "eligible_doors"]])

    def test_quota_rotates_anchors_without_rewriting_fault_keys(self):
        addresses = ["target-a", "target-b"]
        state = {"budget": {"max_faults_per_trial": 6}, "queue": [],
                 "seen_plan_keys": [], "completed_fault_trials": 0,
                 "scheduler_version": 10, "multi_anchor_addresses": addresses,
                 "fault_id_attempts": {}, "fault_id_successes": {}}
        for address in addresses:
            for ordinal in (1, 2):
                core._enqueue(state, [{"fault": fault(ordinal), "seq": ordinal,
                                       "tier": "observed_closure",
                                       "anchor_address": address}], [], 0)
        self.assertEqual(4, len(state["queue"]))
        selected = []
        for _ in range(4):
            selected.append(core._pick(state)["anchor_address"])
            state["completed_fault_trials"] += 1
        self.assertEqual(["target-a", "target-b", "target-a", "target-b"],
                         selected)

    def test_faulted_replay_requests_only_pinned_anchor_and_retries_missing(self):
        config = {"recording": {"test_id": "Example#test", "static_scope_map":
                    "/unused/scope", "candidate_graph": "/unused/graph",
                    "region_skeletons": "/unused/skeleton",
                    "multi_target_max_anchors": 2},
                  "target_site": "Target#u1", "target_throw": {"siteId":
                    "Target#u2", "exceptionClass": "java.io.IOException"}}
        admitted = {"weave_config": {"java": "/unused/java"}}
        healthy = {"schemaVersion": 1,
                   "anchors": [anchor("target-a"), anchor("target-b")]}
        def missing(_trace, _output, *, healthy_bundle, **_options):
            self.assertEqual(["target-b"], [row["occurrenceAddress"]
                                            for row in healthy_bundle["anchors"]])
            return {"schemaVersion": 1, "status": "retry_exact_missing",
                    "anchors": [], "retryExactOccurrences": ["target-b"]}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(core, "_region_schedule"), \
             patch.object(core, "_analysis_engine_jar", return_value=Path("/unused/jar")), \
             patch.object(core, "record_pinned_region_states",
                          side_effect=missing) as replay:
            trial = Path(directory)
            (trial / "iteration-native").mkdir()
            for candidate in (False, True):
                result = {"junit_passed": True,
                          "raw_target_throw_differential_candidate": candidate,
                          "eligible_doors": []}
                actual = core._run_region_trial(
                    config, admitted, trial, [fault()], healthy,
                    result, [], True, 10, "target-b")
                self.assertEqual("needs_causal_review" if candidate else
                                 "unmatched", actual["status"])
                self.assertEqual("retry_exact_missing",
                                 actual["anchor_replay_status"])
                self.assertFalse(actual["native_target_retained"])
                self.assertEqual([], actual["eligible_doors"])
            self.assertEqual(2, replay.call_count)

    def test_faulted_replay_uses_one_graph_and_only_its_closure(self):
        config = {"recording": {"test_id": "Example#test", "static_scope_map":
                    "/unused/scope", "candidate_graph": "/unused/graph",
                    "region_skeletons": "/unused/skeleton",
                    "multi_target_max_anchors": 2},
                  "target_site": "Target#u1", "target_throw": {"siteId":
                    "Target#u2", "exceptionClass": "java.io.IOException"}}
        admitted = {"weave_config": {"java": "/unused/java"}}
        healthy = {"schemaVersion": 1,
                   "anchors": [anchor("target-a"), anchor("target-b")]}
        replay = {"schemaVersion": 1, "status": "pinned_recorded",
                  "anchors": [{"occurrenceAddress": "target-b",
                               "summary": anchor("target-b")["summary"]}]}
        doors = [{"fault": fault(1), "seq": 1,
                  "tier": "observed_closure"},
                 {"fault": fault(2), "seq": 2,
                  "tier": "outside_closure"}]
        applied = {"kind": "FAULT_APPLIED", "seq": 3,
                   "occurrenceId": "door-1", "node": "n0",
                   "actorEpochOrdinal": 0}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(core, "_region_schedule"), \
             patch.object(core, "_analysis_engine_jar", return_value=Path("/unused/jar")), \
             patch.object(core, "record_pinned_region_states",
                          return_value=replay) as recording, \
             patch.object(core, "delta_region_state", return_value={
                 "targetRetained": True, "newNodeFamilies": [],
                 "newClosureEdgeFamilies": [], "newBranchOutcomeIds": []
             }) as delta, \
             patch.object(core, "_region_doors", return_value=doors), \
             patch.object(core, "_post_fault_target_checks", return_value={
                 "observed": True}), \
             patch.object(core, "_region_throw_evidence",
                          return_value=([], False, "no_exact_target_throw", None)):
            trial = Path(directory)
            (trial / "iteration-native").mkdir()
            actual = core._run_region_trial(
                config, admitted, trial, [fault()], healthy,
                {"junit_passed": True, "eligible_doors": [],
                 "raw_target_throw_differential_candidate": False},
                [applied], True, 7, "target-b")
        self.assertEqual(1, recording.call_count)
        self.assertEqual("target-b", recording.call_args.kwargs[
            "healthy_bundle"]["anchors"][0]["occurrenceAddress"])
        self.assertEqual(1, delta.call_count)
        self.assertEqual("checked", actual["status"])
        self.assertTrue(actual["fault_in_target_closure"])
        self.assertEqual(["observed_closure"],
                         [door["tier"] for door in actual["eligible_doors"]])
        self.assertEqual(["target-b"],
                         [door["anchor_address"] for door in actual[
                             "eligible_doors"]])

    def test_exact_missing_retry_keeps_anchor_and_plan_key(self):
        chosen = fault()
        key = core._plan_key([chosen], "target-a")
        active = {"name": "r0001", "index": 1, "faults": [chosen],
                  "key": key, "tier": "observed_closure", "novelty": 0,
                  "anchor_address": "target-a", "attempt": 0}
        state = {"active": active, "healthy": {"name": "r0000"},
                 "status": "running", "terminal": False,
                 "elapsed_seconds": 0.0, "trials": [], "queue": [],
                 "budget": {"fault_trials": 4, "seconds": 100,
                            "max_faults_per_trial": 6},
                 "completed_fault_trials": 0, "scheduler_version": 10,
                 "fault_id_attempts": {}, "fault_id_successes": {}}
        result = {"faults": [chosen], "anchor_address": "target-a",
                  "elapsed_seconds": 1.0, "status": "unmatched",
                  "strict_injection": True, "native_target_retained": False,
                  "target_exception_triggered": False,
                  "raw_target_throw_differential_candidate": False,
                  "raw_exact_target_throw_count": 0,
                  "post_fault_target_check_observed": False,
                  "anchor_replay_status": "retry_exact_missing",
                  "runner_mode": "region_state"}
        core._accept(state, result, "r0001")
        self.assertEqual(1, len(state["queue"]))
        self.assertEqual("target-a", state["queue"][0]["anchor_address"])
        self.assertEqual(key, state["queue"][0]["key"])

    def test_resume_rejects_changed_healthy_anchor_graph_before_junit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            healthy = root / "trials" / "r0000"
            graph = healthy / "original-graph" / "anchor-00" / "summary.json"
            graph.parent.mkdir(parents=True)
            summary = anchor("target-a")["summary"]
            graph.write_text(json.dumps(summary) + "\n")
            bundle = {"schemaVersion": 1,
                      "anchors": [{**anchor("target-a"),
                          "summarySha256": core._sha(graph)}]}
            bundle_file = healthy / "native-summary.json"
            bundle_file.write_text(json.dumps(bundle) + "\n")
            (healthy / "result.json").write_text(json.dumps({
                "native_session_sha256": core._sha(bundle_file),
                "raw_exact_target_throw_count": 0}) + "\n")
            state = {"active": {"name": "r0001", "index": 1,
                                "faults": [fault()],
                                "anchor_address": "target-a"},
                     "multi_anchor_addresses": ["target-a"]}
            graph.write_text(json.dumps({**summary,
                "closureOccurrenceIds": ["silently-changed"]}) + "\n")
            with patch.object(core, "_run_trial") as junit:
                with self.assertRaisesRegex(ValueError, "healthy exact target graph changed"):
                    core._resume_active({}, {}, root, state)
                junit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
