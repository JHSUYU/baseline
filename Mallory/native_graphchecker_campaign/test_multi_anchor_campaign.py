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
    def test_retention_policy_requires_opt_in_multi_anchor_scope(self):
        config = {"case_id": "example", "target_site": "Target#u1",
                  "native_weave_config": "/unused", "target_throw": {
                      "siteId": "Target#u2", "exceptionClass": "java.io.IOException"},
                  "recording": {"trace_dir": "/unused", "test_id": "X#y",
                      "target_name": "target", "candidate_graph": "/unused",
                      "static_scope_map": "/unused", "region_skeletons": "/unused",
                      "max_jobs": 1, "anchor_retention_policy":
                      "smoothed_postfault_3of4"}}
        with self.assertRaisesRegex(ValueError, "requires multi-target anchors"):
            core._validate_config(config)
        config["recording"]["anchor_retention_policy"] = "unknown"
        with self.assertRaisesRegex(ValueError, "requires multi-target anchors"):
            core._validate_config(config)

    def test_retention_policy_preserves_initial_rotation_then_uses_three_of_four(self):
        addresses = [f"target-{index}" for index in range(4)]
        state = {"budget": {"max_faults_per_trial": 6}, "queue": [],
                 "seen_plan_keys": [], "completed_fault_trials": 0,
                 "scheduler_version": 11, "multi_anchor_addresses": addresses,
                 "fault_id_attempts": {}, "fault_id_successes": {}, "trials": []}
        for address in addresses:
            for ordinal in range(1, 9):
                core._enqueue(state, [{"fault": fault(ordinal), "seq": ordinal,
                                       "tier": "observed_closure",
                                       "anchor_address": address}], [], 0)
        selected = []
        for _ in range(8):
            chosen = core._pick(state)
            address = chosen["anchor_address"]
            selected.append(address)
            state["trials"].append({"anchor_address": address,
                                    "strict_injection": True,
                                    "post_fault_target_check_observed":
                                    address == "target-2"})
            state["completed_fault_trials"] += 1
        self.assertEqual(addresses, selected[:4])
        self.assertEqual(["target-2"] * 3, selected[4:7])
        self.assertEqual("target-3", selected[7])

    def test_retention_policy_ignores_unmatched_unapplied_trial(self):
        state = {"completed_fault_trials": 4, "trials": [
            {"anchor_address": "a", "strict_injection": True,
             "post_fault_target_check_observed": False},
            {"anchor_address": "b", "strict_injection": True,
             "post_fault_target_check_observed": True},
            {"anchor_address": "a", "strict_injection": False,
             "post_fault_target_check_observed": True}]}
        self.assertEqual("b", core._retention_anchor_order(state, ["a", "b"])[0])

    def test_new_campaign_only_opts_into_scheduler_v11_when_requested(self):
        config = {"case_id": "example", "budget": {"fault_trials": 8},
                  "recording": {"multi_target_max_anchors": 4}}
        admitted = {"weave_config": {"output_classes": "/unused"},
                    "origin": {}, "zero_vm_sha256": "zero",
                    "runner_classpath_artifacts": []}
        with patch.object(core, "_sha", return_value="receipt"):
            old = core._new_state(config, "config", admitted)
            config["recording"]["anchor_retention_policy"] = (
                "smoothed_postfault_3of4")
            new = core._new_state(config, "config2", admitted)
        self.assertEqual(10, old["scheduler_version"])
        self.assertEqual(11, new["scheduler_version"])
        self.assertNotIn("anchor_retention_policy", old["multi_anchor_config"])
        self.assertEqual("smoothed_postfault_3of4", new[
            "multi_anchor_config"]["anchor_retention_policy"])
        config["recording"]["control_plane_peer_policy"] = (
            "same_peer_pretarget_quarter")
        with patch.object(core, "_sha", return_value="receipt"):
            peer = core._new_state(config, "config3", admitted)
        self.assertEqual(12, peer["scheduler_version"])
        self.assertEqual({}, peer["peer_postfault_attempts"])

    def test_control_peer_quarter_selects_only_observed_same_peer_door(self):
        addresses = [f"target-{index}" for index in range(4)]
        state = {"budget": {"max_faults_per_trial": 6}, "queue": [],
                 "seen_plan_keys": [], "completed_fault_trials": 0,
                 "scheduler_version": 12, "multi_anchor_addresses": addresses,
                 "fault_id_attempts": {}, "fault_id_successes": {},
                 "peer_postfault_attempts": {}, "peer_postfault_retained": {},
                 "trials": []}
        for index, address in enumerate(addresses):
            door = {"fault": fault(index + 1), "seq": index + 1,
                    "tier": "observed_closure", "anchor_address": address,
                    "target_phase": "before_selected_target",
                    "selected_target_actor": False,
                    "target_order_distance": 1,
                    "peer_relation": ("same_peer_before_target" if
                                      index == 2 else "unknown")}
            core._enqueue(state, [door], [], 0)
        selected = core._pick(state)
        self.assertEqual(addresses[2], selected["anchor_address"])
        self.assertEqual("same_peer_before_target", selected["peer_relation"])
        self.assertEqual(3, len(state["queue"]))

    def test_peer_policy_validation_requires_pinned_may_and_retention(self):
        config = {"case_id": "example", "target_site": "Target#u1",
                  "native_weave_config": "/unused", "target_throw": {
                      "siteId": "Target#u2", "exceptionClass": "java.io.IOException"},
                  "recording": {"trace_dir": "/unused", "test_id": "X#y",
                      "target_name": "target", "candidate_graph": "/unused",
                      "static_scope_map": "/unused", "region_skeletons": "/unused",
                      "max_jobs": 1, "multi_target_max_anchors": 4,
                      "admission_mode": "region_state_no_schedule",
                      "anchor_retention_policy": "smoothed_postfault_3of4",
                      "control_plane_peer_policy":
                          "same_peer_pretarget_quarter"},
                  "runner": {"mode": "region_state"}}
        with self.assertRaisesRegex(ValueError, "control-plane peer policy"):
            core._validate_config(config)

    def test_healthy_peer_hint_is_versioned_and_requires_exact_join(self):
        config = {"target_site": "Target#u1", "recording": {
            "multi_target_max_anchors": 2,
            "static_may_scope_map": "/unused/map",
            "static_may_scope_map_sha256": "a" * 64,
            "control_plane_peer_policy": "same_peer_pretarget_quarter"}}
        rows = [anchor("dn#epoch0/region/a"),
                anchor("dn#epoch1/region/b")]
        bundle = {"status": "multi_target_recorded", "anchors": rows,
                  "retryExactOccurrences": []}
        door = {"fault": fault(), "seq": 1, "tier": "observed_closure",
                "target_phase": "before_selected_target"}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(core, "rpc_producer_sites", return_value=frozenset()), \
             patch.object(core, "observed_rpc_door_sites",
                          return_value=frozenset({fault()["siteId"]})), \
             patch.object(core, "_region_doors", return_value=[door]), \
             patch.object(core, "rank_region_doors_by_peer") as rank:
            rank.side_effect = lambda doors, *args: (
                [{**item, "peer_relation": "same_peer_before_target"}
                 for item in doors],
                {"status": "ranked", "samePeerBeforeTargetCount": 1})
            (Path(directory) / "scope.jsonl").write_text("\n")
            config["recording"]["static_may_scope_map"] = str(
                Path(directory) / "scope.jsonl")
            result = core._complete_multi_healthy(
                config, Path(directory), {"raw_exact_target_throw_count": 0},
                [], bundle)
            self.assertEqual("healthy_seed", result["status"])
            self.assertEqual(2, rank.call_count)
            self.assertEqual(2, len(result["eligible_doors"]))
            self.assertEqual(core._sha(Path(directory) /
                             "peer-ranking-receipt.json"), result[
                                 "peer_ranking_receipt_sha256"])
            self.assertTrue(all(item["peer_relation"] ==
                                "same_peer_before_target" for item in result[
                                    "eligible_doors"]))
            rank.side_effect = lambda doors, *args: (
                [{**item, "peer_relation": "unknown"} for item in doors],
                {"status": "ranked", "samePeerBeforeTargetCount": 0})
            blocked = core._complete_multi_healthy(
                config, Path(directory), {"raw_exact_target_throw_count": 0},
                [], bundle)
            self.assertEqual("blocked_healthy_peer_scope", blocked["status"])
            self.assertEqual([], blocked["eligible_doors"])

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
