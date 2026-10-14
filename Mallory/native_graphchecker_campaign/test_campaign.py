"""Fixture-backed native campaign tests; no live system campaign is started."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Mallory.native_graphchecker_feedback.feedback import (
    HERE as FEEDBACK_DIR, NoNativeTargetError, _classpath, build,
    summarize_target_set,
)
from Mallory.native_graphchecker_campaign import campaign as core


class NativeAdmissionLineageTest(unittest.TestCase):
    def test_trial_elapsed_includes_graph_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            result = {"elapsed_seconds": 2.0}
            with patch.object(core.time, "monotonic", return_value=13.5):
                saved = core._save_trial_result(trial, result, 10.0)
            self.assertEqual(3.5, saved["elapsed_seconds"])
            self.assertEqual(2.0, saved["junit_elapsed_seconds"])
            self.assertEqual(1.5, saved["analysis_elapsed_seconds"])
            self.assertEqual(saved, core._load(trial / "result.json"))

    def test_selected_skeletons_need_not_equal_static_weave_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / "static.jsonl"
            woven = root / "woven.jsonl"
            selected = root / "selected.jsonl"
            static.write_text("all-regions\n")
            woven.write_bytes(static.read_bytes())
            selected.write_text("one-region\n")
            proof = core._skeleton_lineage(static, woven, selected)
            self.assertNotEqual(proof["static_skeletons_sha256"],
                                proof["selected_skeletons_sha256"])
            woven.write_text("different-static-input\n")
            with self.assertRaisesRegex(ValueError, "pinned static skeletons"):
                core._skeleton_lineage(static, woven, selected)

    def test_selected_task_is_exactly_one_row_of_full_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            full = root / "full.jsonl"
            chosen = root / "chosen.jsonl"
            row = '{"taskId":"TASK.B","payload":"original"}\n'
            full.write_text('{"taskId":"TASK.A"}\n' + row)
            chosen.write_text(row)
            proof = core._task_plan_lineage(full, chosen, "TASK.B")
            self.assertNotEqual(proof["recording_plan_sha256"],
                                proof["selected_task_plan_sha256"])
            chosen.write_text('{"taskId":"TASK.B","payload":"changed"}\n')
            with self.assertRaisesRegex(ValueError, "full schedule"):
                core._task_plan_lineage(full, chosen, "TASK.B")

    def test_region_state_pins_fresh_schedule_without_unused_task_equality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fresh = root / "fresh.jsonl"
            woven = root / "woven.jsonl"
            index = root / "index.json"
            fresh.write_text('{"taskId":"TASK.A","rootCallId":"fresh"}\n')
            woven.write_text('{"taskId":"TASK.A","rootCallId":"older"}\n')
            index.write_text('{"tasks":1}\n')
            receipt = core._region_state_plan_lineage(fresh, index, woven)
            self.assertEqual(1, receipt["recording_plan_task_count"])
            self.assertEqual(core._sha(fresh), receipt["recording_plan_sha256"])
            self.assertEqual(core._sha(index), receipt["recording_index_sha256"])
            self.assertNotEqual(receipt["recording_plan_sha256"],
                                receipt["unused_weave_task_plan_sha256"])
            task_free = core._region_state_plan_lineage(fresh, index, None)
            self.assertEqual(core._sha(fresh), task_free["recording_plan_sha256"])
            self.assertNotIn("unused_weave_task_plan_sha256", task_free)
            with self.assertRaisesRegex(ValueError, "full schedule"):
                core._task_plan_lineage(fresh, woven, "TASK.A")

    def test_runner_prefix_uses_fresh_trial_result_path(self) -> None:
        prefix = core._runner_prefix(
            {"args_before_test": ["{trial_result_file}"]}, Path("/tmp/trial"))
        self.assertEqual(["/tmp/trial/junit-result.json"], prefix)

    def test_region_state_trial_omits_symbolic_task_publication(self) -> None:
        args = core._mode_jvm_args(
            {"mode": "region_state"}, {}, Path("/tmp/trial"),
            {"class": "ExampleTest", "method": "testOperation"})
        self.assertEqual(["-Dcausynth.trace.mode=region-state",
                          "-Dcausynth.trace.test=ExampleTest#testOperation"], args)

    def test_unmatched_region_selector_gets_bounded_retry(self) -> None:
        faults = [{"siteId": "I/O#u1", "node": "peer-1",
                   "actorEpochOrdinal": 0, "ordinal": 1,
                   "exceptionClass": "java.io.IOException"}]
        state = {"active": {"index": 1, "name": "r0001", "faults": faults,
                            "key": "plan-1", "tier": "pre_target_actor",
                            "novelty": 0, "attempt": 0},
                 "elapsed_seconds": 0.0, "completed_fault_trials": 0,
                 "trials": [], "queue": [], "status": "running", "terminal": False,
                 "budget": {"fault_trials": 10, "seconds": 60,
                            "max_faults_per_trial": 4},
                 "healthy": {"status": "healthy_seed"}}
        result = {"faults": faults, "elapsed_seconds": 1.0,
                  "status": "unmatched", "runner_mode": "region_state",
                  "strict_injection": False, "native_target_retained": False,
                  "target_exception_triggered": False}
        core._accept(state, result, "r0001")
        self.assertEqual(1, state["queue"][0]["attempt"])
        self.assertEqual(1, state["trials"][0]["retry_enqueued"])
        self.assertEqual("running", state["status"])


class ObservedActorSuccessorTest(unittest.TestCase):
    """An unmatched actor can supply a new exact selector, never a loose one."""

    @staticmethod
    def _fault(site: str, node: str, ordinal: int = 1) -> dict:
        return {"siteId": site, "node": node, "actorEpochOrdinal": 0,
                "ordinal": ordinal, "exceptionClass": "java.io.IOException"}

    @classmethod
    def _row(cls, kind: str, site: str, node: str, seq: int,
             occurrence: str, ordinal: int = 1) -> dict:
        return {**cls._fault(site, node, ordinal), "kind": kind, "seq": seq,
                "occurrenceId": occurrence}

    def test_successor_uses_append_order_and_verified_prefix(self) -> None:
        planned = [self._fault("RPC#first", "dn1"),
                   self._fault("RPC#missing", "dn1")]
        rows = [self._row("FAULT_DOOR", "RPC#first", "dn1", 1, "first"),
                # This actor's higher local seq is still before the applied
                # prefix in the append-only file and must be excluded.
                self._row("FAULT_DOOR", "RPC#missing", "dn2", 90, "early"),
                self._row("FAULT_APPLIED", "RPC#first", "dn1", 2, "first"),
                self._row("FAULT_DOOR", "RPC#missing", "dn3", 1, "later"),
                self._row("FAULT_DOOR", "RPC#missing", "dn3", 1, "duplicate"),
                self._row("FAULT_DOOR", "RPC#missing", "dn1", 3, "planned"),
                self._row("FAULT_DOOR", "RPC#other", "dn4", 1, "wrong")]
        prefix, successors = core._unmatched_actor_successors(planned, rows)
        self.assertEqual(1, prefix)
        self.assertEqual(1, len(successors))
        self.assertEqual("dn3", successors[0]["fault"]["node"])
        self.assertEqual("later", successors[0]["fault"]["sourceOccurrenceId"])
        self.assertEqual("outside_closure", successors[0]["tier"])
        self.assertEqual((False, None), core._strict_faults(planned, rows))
        successor_plan = [planned[0], successors[0]["fault"]]
        successor_rows = [rows[0], rows[2], rows[3],
                          self._row("FAULT_APPLIED", "RPC#missing", "dn3",
                                    2, "later")]
        self.assertTrue(core._strict_faults(successor_plan, successor_rows)[0])

    def test_invalid_applied_prefix_and_absent_door_yield_no_successor(self) -> None:
        planned = [self._fault("RPC#first", "dn1"),
                   self._fault("RPC#missing", "dn1")]
        wrong_prefix = [self._row("FAULT_DOOR", "RPC#first", "dn2", 1, "x"),
                        self._row("FAULT_APPLIED", "RPC#first", "dn2", 2, "x"),
                        self._row("FAULT_DOOR", "RPC#missing", "dn3", 3, "y")]
        self.assertEqual((0, []), core._unmatched_actor_successors(
            planned, wrong_prefix))
        no_matching_site = [self._row("FAULT_DOOR", "RPC#first", "dn1", 1, "x"),
                            self._row("FAULT_APPLIED", "RPC#first", "dn1", 2,
                                      "x"),
                            self._row("FAULT_DOOR", "RPC#other", "dn3", 1,
                                      "y")]
        self.assertEqual((1, []), core._unmatched_actor_successors(
            planned, no_matching_site))

    def test_v3_enqueues_once_and_v2_checkpoint_keeps_old_rule(self) -> None:
        planned = [self._fault("RPC#first", "dn1"),
                   self._fault("RPC#missing", "dn1")]
        replacement = {**self._fault("RPC#missing", "dn3"),
                       "sourceOccurrenceId": "observed"}
        successor = {"fault": replacement, "seq": 1,
                     "tier": "outside_closure"}

        def state(version: int) -> dict:
            item = {"index": 1, "name": "r0001", "faults": planned,
                    "key": core._plan_key(planned), "tier": "outside_closure",
                    "novelty": 0, "attempt": 0}
            return {"scheduler_version": version, "active": item,
                    "elapsed_seconds": 0.0, "completed_fault_trials": 0,
                    "trials": [], "queue": [], "seen_plan_keys": [item["key"]],
                    "fault_id_attempts": {}, "fault_id_successes": {},
                    "status": "running", "terminal": False,
                    "budget": {"fault_trials": 10, "seconds": 60,
                               "max_faults_per_trial": 4},
                    "healthy": {"status": "healthy_seed"}}

        result = {"faults": planned, "elapsed_seconds": 1.0,
                  "status": "unmatched", "runner_mode": "region_state",
                  "strict_injection": False, "native_target_retained": False,
                  "target_exception_triggered": False,
                  "applied_prefix_count": 1,
                  "observed_actor_successors": [successor, successor]}
        current = state(3)
        core._accept(current, result, "r0001")
        generated = [x for x in current["queue"] if x["faults"][-1]["node"] ==
                     "dn3"]
        self.assertEqual(1, len(generated))
        self.assertEqual(planned[0], generated[0]["faults"][0])
        self.assertEqual(1, current["trials"][0][
            "observed_actor_successors_enqueued"])
        self.assertEqual(1, current["trials"][0]["retry_enqueued"])
        self.assertEqual(1, current["fault_id_attempts"][core._fault_id(
            planned[-1])])
        previous = state(2)
        core._accept(previous, result, "r0001")
        self.assertEqual(1, len(previous["queue"]))
        self.assertNotIn("observed_actor_successors_enqueued",
                         previous["trials"][0])


class NativeQueueDiversityTest(unittest.TestCase):
    """The queue should reach distinct doors without losing deep sequences."""

    @staticmethod
    def _item(site: str, key: str, *, novelty: int = 0,
              depth: int = 1, tier: str = "observed_closure",
              enqueued_at: int = 0) -> dict:
        fault = {"siteId": site, "exceptionClass": "java.io.IOException"}
        return {"faults": [dict(fault) for _ in range(depth)], "key": key,
                "tier": tier, "novelty": novelty,
                "enqueued_at": enqueued_at, "attempt": 0}

    @staticmethod
    def _state(items: list[dict], *, completed: int = 0,
               version: int = 2) -> dict:
        state = {"queue": items, "completed_fault_trials": completed,
                 "elapsed_seconds": 0.0, "trials": [], "active": None,
                 "status": "running", "terminal": False,
                 "healthy": {"status": "healthy_seed"},
                 "budget": {"fault_trials": 100, "seconds": 1000,
                            "max_faults_per_trial": 4}}
        if version >= 2:
            state.update(scheduler_version=version, fault_id_attempts={},
                         fault_id_successes={})
        return state

    @staticmethod
    def _complete(state: dict, item: dict, number: int,
                  *, applied: bool = True) -> None:
        name = f"r{number:04d}"
        state["active"] = {"index": number, "name": name,
                           "faults": item["faults"], "key": item["key"],
                           "tier": item["tier"], "novelty": item["novelty"]}
        core._accept(state, {"faults": item["faults"],
                             "elapsed_seconds": 1.0,
                             "status": "invalid_native_session",
                             "strict_injection": applied,
                             "native_target_retained": False,
                             "target_exception_triggered": False}, name)

    def test_fault_id_ignores_actor_but_distinguishes_exception(self) -> None:
        first = {"siteId": "RPC#u1", "exceptionClass": "java.io.IOException",
                 "node": "nn", "ordinal": 1}
        same_io = dict(first, node="dn", ordinal=9)
        different_exception = dict(first, exceptionClass="java.net.SocketException")
        self.assertEqual(core._fault_id(first), core._fault_id(same_io))
        self.assertNotEqual(core._fault_id(first),
                            core._fault_id(different_exception))

    def test_distinct_last_fault_sites_survive_high_novelty_duplicates_and_resume(self) -> None:
        state = self._state([self._item("RPC#A", "a1", novelty=60),
                             self._item("RPC#A", "a2", novelty=60),
                             self._item("RPC#B", "b", novelty=0),
                             self._item("RPC#C", "c", novelty=0)])
        picked = core._pick(state)
        self.assertEqual("RPC#A", picked["faults"][-1]["siteId"])
        self._complete(state, picked, 1)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            core._atomic(checkpoint, state)
            state = core._load(checkpoint)
        sites = [picked["faults"][-1]["siteId"]]
        for number in (2, 3):
            picked = core._pick(state)
            sites.append(picked["faults"][-1]["siteId"])
            self._complete(state, picked, number)
        self.assertEqual({"RPC#A", "RPC#B", "RPC#C"}, set(sites))
        self.assertEqual(1, state["fault_id_attempts"][core._fault_id(
            {"siteId": "RPC#A", "exceptionClass": "java.io.IOException"})])

    def test_wait_depth_and_outside_slots(self) -> None:
        waiting = self._state([self._item("RPC#new", "new", novelty=60,
                                              enqueued_at=5),
                               self._item("RPC#old", "old", enqueued_at=0)],
                              completed=6)
        self.assertEqual("RPC#old", core._pick(waiting)["faults"][-1]["siteId"])
        depth = self._state([self._item("RPC#single", "single", novelty=60),
                             self._item("RPC#deep", "deep", depth=2)],
                            completed=3)
        self.assertEqual(2, len(core._pick(depth)["faults"]))
        outside = self._state([self._item("RPC#inside", "inside"),
                               self._item("RPC#outside", "outside",
                                          tier="outside_closure")], completed=7)
        self.assertEqual("RPC#outside", core._pick(outside)["faults"][-1]["siteId"])

    def test_v4_bounds_deep_trials_despite_inherited_closure_novelty(self) -> None:
        # A single checked seed may yield many high-novelty two-fault plans.
        # Their second actor can run before the first fault on the next JVM.
        # Keep depth exploration, but leave most slots for fresh single faults.
        for completed, expected in enumerate((1, 1, 2, 1, 1, 1, 2, 1)):
            state = self._state([
                self._item("RPC#single", "single", depth=1),
                self._item("RPC#deep", "deep", depth=2, novelty=60),
                self._item("RPC#outside", "outside", tier="outside_closure"),
            ], completed=completed, version=4)
            selected = core._pick(state)
            self.assertEqual(expected, len(selected["faults"]), completed)
            if completed == 7:
                self.assertEqual("outside_closure", selected["tier"])

        # Frozen v3 checkpoints keep their exact former selection rule.
        prior = self._state([
            self._item("RPC#single", "single"),
            self._item("RPC#deep", "deep", depth=2, novelty=60),
        ], completed=1, version=3)
        self.assertEqual(2, len(core._pick(prior)["faults"]))

    def test_v4_depth_slot_falls_back_when_no_deep_plan_exists(self) -> None:
        state = self._state([self._item("RPC#single", "single")],
                            completed=2, version=4)
        self.assertEqual(1, len(core._pick(state)["faults"]))

    def test_closure_feedback_still_breaks_ties_within_diverse_fault_ids(self) -> None:
        state = self._state([self._item("RPC#low", "low", novelty=0),
                             self._item("RPC#high", "high", novelty=7)])
        self.assertEqual("RPC#high", core._pick(state)["faults"][-1]["siteId"])

    def test_unmatched_attempt_rotates_without_claiming_success(self) -> None:
        state = self._state([self._item("RPC#A", "a1", novelty=60),
                             self._item("RPC#A", "a2", novelty=60),
                             self._item("RPC#B", "b")])
        selected = core._pick(state)
        self._complete(state, selected, 1, applied=False)
        self.assertEqual({}, state["fault_id_successes"])
        self.assertEqual("RPC#B", core._pick(state)["faults"][-1]["siteId"])

    def test_legacy_checkpoint_keeps_frozen_picker(self) -> None:
        old = self._state([self._item("RPC#A", "a", novelty=60),
                           self._item("RPC#B", "b")], version=1)
        old["fault_id_attempts"] = {core._fault_id(
            {"siteId": "RPC#A", "exceptionClass": "java.io.IOException"}): 99}
        self.assertEqual("RPC#A", core._pick(old)["faults"][-1]["siteId"])


class WireTemporalProofTest(unittest.TestCase):
    """Two exact actors; VM event IDs and receipt order are separate clocks."""

    def setUp(self) -> None:
        self.target = "Keys#check#u3#1"
        self.summary = {"perTargetOccurrences": [{
            "sessionId": "seed", "targetOccurrenceId": "target-occ",
            "targetNodeName": "dn", "targetRows": [{
                "occurrenceId": "target-occ", "siteId": self.target,
                "reachedAnchor": True}],
            "closureMembers": [
                {"occurrenceId": "source-occ", "node": "nn#epoch0"},
                {"occurrenceId": "target-occ", "node": "dn#epoch0"}],
            "observedEdgesWithinClosure": [{
                "type": "WIRE", "producerOccurrenceId": "source-occ",
                "consumerOccurrenceId": "target-occ", "evidence": {
                    "producerEndpointId": "producer-exact",
                    "consumerEndpointId": "consumer-exact",
                    "exportSeq": 71, "attachSeq": 4}}]}]}
        self.events = [
            {"kind": "FAULT_APPLIED", "seq": 8,
             "occurrenceId": "source-occ", "node": "nn",
             "actorEpochOrdinal": 0},
            {"kind": "ENDPOINT_EXPORT", "seq": 9,
             "sessionId": "seed", "endpointId": "producer-exact",
             "nativeVmEventId": 71, "occurrenceId": "source-occ",
             "node": "nn", "actorEpochOrdinal": 0},
            {"kind": "ENDPOINT_ATTACH", "seq": 2,
             "sessionId": "seed", "endpointId": "consumer-exact",
             "producerEndpointId": "producer-exact", "nativeVmEventId": 4,
             "occurrenceId": "target-occ", "node": "dn",
             "actorEpochOrdinal": 0},
            {"kind": "TARGET_CHECK", "seq": 3,
             "siteId": "Keys#check#u3", "targetAnchorSiteId": self.target,
             "occurrenceId": "target-occ", "node": "dn",
             "actorEpochOrdinal": 0},
        ]

    def test_trial_jvm_args_use_fresh_workdir(self) -> None:
        args = core._trial_jvm_args({"jvm_args": [
            "-Djava.io.tmpdir={trial_workdir}",
            "-Dbuild.test.dir={trial_workdir}", "-Xmx1g"]},
            Path("/tmp/native-r0001/workdir"))
        self.assertEqual([
            "-Djava.io.tmpdir=/tmp/native-r0001/workdir",
            "-Dbuild.test.dir=/tmp/native-r0001/workdir", "-Xmx1g"], args)

    def test_receipt_parser_checks_each_actor_clock_separately(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "events.jsonl"
            path.write_text("".join(json.dumps(row) + "\n"
                                    for row in self.events))
            self.assertEqual(self.events, core._rows(path))
            duplicate = [dict(row) for row in self.events]
            duplicate[1]["seq"] = duplicate[0]["seq"]
            path.write_text("".join(json.dumps(row) + "\n"
                                    for row in duplicate))
            with self.assertRaisesRegex(ValueError, "nonmonotone"):
                core._rows(path)

    def test_region_target_throw_requires_same_actor_check_after_fault(self) -> None:
        target_site = "Keys#check#u3"
        target_throw = {"siteId": "Keys#throw#u4",
                        "exceptionClass": "java.io.IOException"}
        fault = {"kind": "FAULT_APPLIED", "seq": 4, "node": "dn",
                 "actorEpochOrdinal": 1, "occurrenceId": "target-occ"}
        check = {"kind": "TARGET_CHECK", "seq": 5,
                 "siteId": target_site, "node": "dn",
                 "actorEpochOrdinal": 1, "occurrenceId": "target-occ"}
        throw = {"kind": "TARGET_THROW", "seq": 6,
                 "siteId": target_throw["siteId"],
                 "exceptionClass": target_throw["exceptionClass"],
                 "node": "dn", "actorEpochOrdinal": 1,
                 "occurrenceId": "target-occ"}
        rows, admitted, reason, evidence = core._region_throw_evidence(
            [fault, check, throw], target_site, target_throw, fault)
        self.assertEqual([throw], rows)
        self.assertTrue(admitted)
        self.assertEqual("same_occurrence_before_check", reason)
        self.assertEqual(4, evidence["faultSeq"])
        late = dict(fault, seq=7)
        rows, admitted, reason, evidence = core._region_throw_evidence(
            [check, throw, late], target_site, target_throw, late)
        self.assertEqual([throw], rows)
        self.assertFalse(admitted)
        self.assertEqual("cross_occurrence_order_unproved", reason)
        self.assertIsNone(evidence)

    def test_region_door_priority_uses_original_exact_closure_membership(self) -> None:
        summary = {"targetSiteId": "Keys#check#u3",
                   "closureMembershipAuthority":
                       "original_runtime_selected_region_finalizer",
                   "closureOccurrenceIds": ["target-occ", "other-occ"]}
        check = {"kind": "TARGET_CHECK", "seq": 7,
                 "siteId": summary["targetSiteId"], "node": "dn",
                 "actorEpochOrdinal": 1, "occurrenceId": "target-occ"}
        doors = [{"kind": "FAULT_DOOR", "seq": index + 1,
                  "siteId": "RPC#dn", "node": "dn", "actorEpochOrdinal": 1,
                  "occurrenceId": occurrence, "ordinal": 1,
                  "exceptionClass": "java.io.IOException"}
                 for index, occurrence in enumerate(("target-occ", "other-occ",
                                                      "outside-occ"))]
        ranked = core._region_doors([*doors, check], summary)
        self.assertEqual(["observed_closure", "observed_closure",
                          "pre_target_actor"],
                         [item["tier"] for item in ranked])
        after = dict(doors[0], seq=8, ordinal=2)
        self.assertEqual("observed_closure",
                         core._region_doors([check, after], summary)[0]["tier"])
        with self.assertRaisesRegex(ValueError, "original closure authority"):
            core._region_doors([*doors, check], {"targetSiteId": "Keys#check#u3"})

    def test_region_mutation_uses_global_observed_order_after_fault(self) -> None:
        summary = {"targetSiteId": "Keys#check#u3",
                   "closureMembershipAuthority":
                       "original_runtime_selected_region_finalizer",
                   "closureOccurrenceIds": ["a"]}
        earlier = {"kind": "FAULT_DOOR", "seq": 100,
                   "siteId": "RPC#earlier", "node": "peer-a",
                   "actorEpochOrdinal": 0, "occurrenceId": "a",
                   "ordinal": 1, "exceptionClass": "java.io.IOException"}
        applied = {"kind": "FAULT_APPLIED", "seq": 2,
                   "siteId": "RPC#first", "node": "peer-b",
                   "actorEpochOrdinal": 0, "occurrenceId": "b",
                   "ordinal": 1, "exceptionClass": "java.io.IOException"}
        later = dict(earlier, siteId="RPC#later", seq=101)
        doors = core._region_doors([earlier, applied, later], summary, applied)
        self.assertEqual(["RPC#later"],
                         [item["fault"]["siteId"] for item in doors])

    def test_region_schedule_copies_only_one_original_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trial = Path(directory)
            iteration = trial / "iteration-native"
            trace = iteration / "trace"
            trace.mkdir(parents=True)
            (trace / "streaming_trace_manifest.json").write_text(
                '{"status":"CLOSED"}\n')
            source = iteration / "sessions" / "one" / "schedule.jsonl"
            source.parent.mkdir(parents=True)
            source.write_bytes(b'{"mark":"original"}\n')
            core._region_schedule(iteration, trial)
            self.assertEqual(source.read_bytes(),
                             (trace / "schedule.jsonl").read_bytes())
            receipt = json.loads((trial / "schedule-lineage.json").read_text())
            self.assertTrue(receipt["copied"])
            self.assertEqual(receipt["source_sha256"],
                             receipt["destination_sha256"])
            (trace / "schedule.jsonl").unlink()
            other = iteration / "sessions" / "two" / "schedule.jsonl"
            other.parent.mkdir(parents=True)
            other.write_bytes(b'{"mark":"different"}\n')
            with self.assertRaisesRegex(ValueError, "unique original schedule"):
                core._region_schedule(iteration, trial)

    def test_queue_door_filter_does_not_compare_actor_clocks(self) -> None:
        door = {"kind": "FAULT_DOOR", "seq": 1,
                "siteId": "RPC#dn", "node": "dn", "actorEpochOrdinal": 0,
                "occurrenceId": "target-occ", "ordinal": 1,
                "exceptionClass": "java.io.IOException"}
        summary = {"closureMembers": self.summary["perTargetOccurrences"][0][
            "closureMembers"]}
        self.assertEqual(1, len(core._doors([door], summary, self.events[0])))

    def test_directed_wire_path_admits_with_local_actor_order(self) -> None:
        admitted, reason, proof = core._temporal_target(
            self.events, self.summary, self.target)
        self.assertTrue(admitted)
        self.assertEqual("wire_path_before_check", reason)
        self.assertEqual("producer-exact", proof["wirePath"][0][
            "producerEndpointId"])
        self.assertEqual("consumer-exact", proof["wirePath"][0][
            "consumerEndpointId"])
        # The consumer's local seq is lower than the producer's local seq.
        self.assertLess(proof["wirePath"][0]["attachSeq"], proof["faultSeq"])

    def test_reversed_local_order_refuses(self) -> None:
        for index, sequence in ((1, 7), (2, 3), (3, 2)):
            with self.subTest(index=index):
                events = [dict(row) for row in self.events]
                events[index]["seq"] = sequence
                admitted, reason, proof = core._temporal_target(
                    events, self.summary, self.target)
                self.assertFalse(admitted)
                self.assertEqual("cross_occurrence_order_unproved", reason)
                self.assertIsNone(proof)

    def test_mismatched_original_endpoint_or_actor_refuses(self) -> None:
        for index, key, value in ((1, "endpointId", "other-export"),
                                  (2, "nativeVmEventId", 5),
                                  (2, "producerEndpointId", "other-producer"),
                                  (2, "sessionId", "other-session"),
                                  (2, "node", "nn")):
            with self.subTest(index=index, field=key):
                events = [dict(row) for row in self.events]
                events[index][key] = value
                admitted, reason, proof = core._temporal_target(
                    events, self.summary, self.target)
                self.assertFalse(admitted)
                self.assertEqual("cross_occurrence_order_unproved", reason)
                self.assertIsNone(proof)


class NativeCampaignFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not core.JAR.is_file():
            raise unittest.SkipTest("source-built original GraphChecker engine is absent")
        cls.classes = build(engine_jar=core.JAR)
        cls.classpath = f"{cls.classes}:{_classpath(core.JAR)}"
        subprocess.run(["javac", "-cp", cls.classpath, "-d", str(cls.classes),
                        str(FEEDBACK_DIR / "SyntheticNativeSession.java")],
                       check=True, timeout=120, capture_output=True)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.seed = self.root / "seed"
        self._generate(self.seed)
        self.woven = self.root / "woven"
        self.woven.mkdir()
        (self.woven / "native-original-weave-receipt.json").write_text("{}\n")
        self.weave_config = self.root / "weave.json"
        self.weave_config.write_text("{}\n")
        self.config_file = self.root / "case.json"
        self.config = {
            "case_id": "FIXTURE-01", "target_site": "Keys#check#u3",
            "target_throw": {"siteId": "Keys#throw#u4",
                             "exceptionClass": "java.io.IOException"},
            "native_weave_config": str(self.weave_config),
            "recording": {"trace_dir": str(self.seed), "test_id": "fixture",
                          "target_name": "fixture",
                          "max_jobs": 256,
                          "candidate_graph": str(self.seed / "graph.jsonl"),
                          "static_scope_map": str(self.seed / "static_scope_map.jsonl"),
                          "region_skeletons": str(self.seed / "regions.jsonl")},
            "junit": {"class": "UnchangedFixtureTest", "method": "testOperation"},
            "runner": {"zero_vm_java": str(self.root / "vm-java"),
                       "main_class": "UnchangedJUnitRunner", "classpath": []},
            "budget": {"fault_trials": 1, "seconds": 60,
                       "max_faults_per_trial": 2},
            "timeout_seconds": 30,
        }
        self.config_file.write_text(json.dumps(self.config))
        self.admitted = {"weave_config": {"output_classes": str(self.woven)},
                         "weave_receipt": {}, "origin": {
                             "recording_plan_sha256": "fixture"},
                         "zero_vm_sha256": "fixture-zero",
                         "runner_classpath_artifacts": []}

    def test_region_state_rejects_recording_of_another_junit(self) -> None:
        self.config["runner"]["mode"] = "region_state"
        with self.assertRaisesRegex(ValueError, "recording test_id must match"):
            core._validate_config(self.config)
        self.config["recording"]["test_id"] = (
            "UnchangedFixtureTest#testOperation")
        core._validate_config(self.config)

    def _generate(self, iteration: Path, *, mixed_target: bool = False,
                  direct_wire: bool = False) -> None:
        subprocess.run(["java", "-cp", self.classpath,
                        "edu.uva.liftlab.mallory.nativefeedback.SyntheticNativeSession",
                        str(iteration), *(["--second-target-unreached"]
                                         if mixed_target else []),
                        *(["--direct-target-wire"] if direct_wire else [])],
                       check=True, timeout=30, capture_output=True)

    def _executor(self, *, emit_door: bool, applied_identity: str | None = None,
                  throw: bool = False, mixed_target: bool = False,
                  cross_occurrence: bool = False, post_target: bool = False,
                  omit_check: bool = False):
        def execute(config, admitted, trial, faults):
            iteration = trial / "iteration-native"
            self._generate(iteration, mixed_target=mixed_target)
            if emit_door:
                summary = summarize_target_set(
                    iteration, config["target_site"], trial / "peek.json",
                    static_scope_map=self.seed / "static_scope_map.jsonl",
                    engine_jar=core.JAR)
                target = summary["targetOccurrenceIds"][0]
                target_node = summary["perTargetOccurrences"][0]["targetNodeName"]
                source = (next(item for item in summary["closureMembers"]
                               if item["regionId"] == "R.writer")["occurrenceId"]
                          if cross_occurrence else target)
                door = {"kind": "FAULT_DOOR", "seq": 1,
                        "siteId": "RPC#getKeys", "node": target_node,
                        "actorEpochOrdinal": 0,
                        "occurrenceId": source, "ordinal": 1,
                        "exceptionClass": "java.io.IOException"}
                check = {"kind": "TARGET_CHECK", "seq": 3 if faults else 2,
                         "siteId": "Keys#check#u3",
                         "targetAnchorSiteId": config["target_site"],
                         "node": target_node, "actorEpochOrdinal": 0,
                         "occurrenceId": target}
                rows = []
                if faults:
                    if post_target and not omit_check:
                        rows.append({**check, "seq": 1})
                    if post_target:
                        door["seq"] = 2
                    rows.append(door)
                    applied = {**door, "kind": "FAULT_APPLIED",
                               "seq": 3 if post_target else 2,
                               "occurrenceId": (applied_identity or
                                                source)}
                    rows.append(applied)
                    if not post_target and not omit_check:
                        rows.append(check)
                    if throw:
                        rows.append({"kind": "TARGET_THROW",
                                     "seq": 4 if post_target or not omit_check
                                     else 3,
                                     "siteId": "Keys#throw#u4",
                                     "exceptionClass": "java.io.IOException",
                                     "occurrenceId": target, "node": target_node,
                                     "actorEpochOrdinal": 0})
                else:
                    rows.append(door)
                    if not omit_check:
                        rows.append(check)
                (iteration / "fault-events.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in rows))
            return {"return_code": 0, "timed_out": False,
                    "elapsed_seconds": 0.01}
        return execute

    def _wire_executor(self, *, reversed_attach: bool = False):
        def execute(config, admitted, trial, faults):
            iteration = trial / "iteration-native"
            self._generate(iteration, direct_wire=True)
            summary = summarize_target_set(
                iteration, config["target_site"], trial / "peek.json",
                static_scope_map=self.seed / "static_scope_map.jsonl",
                engine_jar=core.JAR)
            one = summary["perTargetOccurrences"][0]
            target = one["targetOccurrenceId"]
            edge = next(item for item in one["observedEdgesWithinClosure"]
                        if item["type"] == "WIRE" and
                        item["consumerOccurrenceId"] == target and
                        item["producerOccurrenceId"] != target)
            source = edge["producerOccurrenceId"]
            evidence = edge["evidence"]
            door = {"kind": "FAULT_DOOR", "seq": 1,
                    "siteId": "RPC#getKeys", "node": "nn",
                    "actorEpochOrdinal": 0, "occurrenceId": source,
                    "ordinal": 1, "exceptionClass": "java.io.IOException"}
            check = {"kind": "TARGET_CHECK", "seq": 5,
                     "siteId": "Keys#check#u3",
                     "targetAnchorSiteId": config["target_site"],
                     "node": "dn", "actorEpochOrdinal": 0,
                     "occurrenceId": target}
            rows = [door]
            if faults:
                rows.extend([
                    {**door, "kind": "FAULT_APPLIED", "seq": 2},
                    {"kind": "ENDPOINT_EXPORT", "seq": 3,
                     "sessionId": one["sessionId"],
                     "endpointId": evidence["producerEndpointId"],
                     "nativeVmEventId": evidence["exportSeq"],
                     "node": "nn", "actorEpochOrdinal": 0,
                     "occurrenceId": source},
                ])
                if reversed_attach:
                    rows.append(check)
                rows.append({"kind": "ENDPOINT_ATTACH",
                             "seq": 6 if reversed_attach else 4,
                             "sessionId": one["sessionId"],
                             "endpointId": evidence["consumerEndpointId"],
                             "producerEndpointId": evidence["producerEndpointId"],
                             "nativeVmEventId": evidence["attachSeq"],
                             "node": "dn", "actorEpochOrdinal": 0,
                             "occurrenceId": target})
                if not reversed_attach:
                    rows.append(check)
                rows.append({"kind": "TARGET_THROW",
                             "seq": 7 if reversed_attach else 6,
                             "siteId": config["target_throw"]["siteId"],
                             "exceptionClass": "java.io.IOException",
                             "node": "dn", "actorEpochOrdinal": 0,
                             "occurrenceId": target})
            else:
                rows.append({**check, "seq": 2})
            (iteration / "fault-events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows))
            return {"return_code": 0, "timed_out": False,
                    "elapsed_seconds": 0.01}
        return execute

    def _run(self, executor) -> dict:
        with patch.object(core, "_admit", return_value=self.admitted), patch.object(
                core, "_verify_pins"), patch.object(
                core, "_execute_junit", side_effect=executor):
            return core.run_campaign(self.config_file, self.root / "campaign")

    def test_zero_fault_collects_original_native_session(self) -> None:
        state = self._run(self._executor(emit_door=False))
        self.assertEqual("no_observed_fault_door", state["status"])
        self.assertEqual(0, state["completed_fault_trials"])
        healthy = core._load(self.root / "campaign/trials/r0000/result.json")
        self.assertEqual("healthy_seed", healthy["status"])
        self.assertTrue(healthy["native_target_retained"])
        self.assertEqual(1, len(healthy["native_target_occurrence_ids"]))
        self.assertTrue((self.root /
                         "campaign/trials/r0000/native-summary.json").is_file())

    def test_one_generic_fault_requires_exact_receipt_and_target_retention(self) -> None:
        state = self._run(self._executor(emit_door=True, throw=True))
        self.assertEqual("complete_trial_budget", state["status"])
        self.assertEqual(1, state["completed_fault_trials"])
        self.assertEqual("candidate", state["trials"][0]["status"])
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertTrue(faulted["strict_injection"])
        self.assertTrue(faulted["fault_in_target_closure"])
        self.assertTrue(faulted["target_temporal_admitted"])
        self.assertEqual("same_occurrence_before_check",
                         faulted["target_temporal_reason"])
        self.assertTrue(faulted["native_target_retained"])
        self.assertTrue(faulted["target_exception_triggered"])
        self.assertEqual(0, faulted["native_delta"]["newObservedClosureEdges"])
        self.assertTrue((self.root / "campaign/summary.json").is_file())

    def test_post_target_fault_in_same_region_is_not_candidate(self) -> None:
        self._run(self._executor(emit_door=True, throw=True,
                                 post_target=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertTrue(faulted["fault_in_target_closure"])
        self.assertFalse(faulted["target_temporal_admitted"])
        self.assertEqual("post_target_fault", faulted["target_temporal_reason"])
        self.assertTrue(faulted["target_exception_triggered"])
        self.assertEqual("needs_causal_review", faulted["status"])

    def test_cross_occurrence_closure_member_requires_order_proof(self) -> None:
        self._run(self._executor(emit_door=True, throw=True,
                                 cross_occurrence=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertTrue(faulted["fault_in_target_closure"])
        self.assertFalse(faulted["target_temporal_admitted"])
        self.assertEqual("cross_occurrence_order_unproved",
                         faulted["target_temporal_reason"])
        self.assertEqual("needs_causal_review", faulted["status"])

    def test_cross_occurrence_without_throw_still_needs_causal_review(self) -> None:
        self._run(self._executor(emit_door=True, cross_occurrence=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertFalse(faulted["target_exception_triggered"])
        self.assertEqual("cross_occurrence_order_unproved",
                         faulted["target_temporal_reason"])
        self.assertEqual("needs_causal_review", faulted["status"])

    def test_original_wire_edge_admits_two_actor_candidate(self) -> None:
        self._run(self._wire_executor())
        result = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertEqual("candidate", result["status"])
        self.assertTrue(result["target_temporal_admitted"])
        self.assertEqual("wire_path_before_check", result["target_temporal_reason"])
        self.assertEqual(1, len(result["target_temporal_evidence"]["wirePath"]))

    def test_original_wire_edge_rejects_post_check_attach(self) -> None:
        self._run(self._wire_executor(reversed_attach=True))
        result = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertFalse(result["target_temporal_admitted"])
        self.assertEqual("cross_occurrence_order_unproved",
                         result["target_temporal_reason"])
        self.assertEqual("needs_causal_review", result["status"])

    def test_missing_target_check_receipt_fails_closed(self) -> None:
        self._run(self._executor(emit_door=True, throw=True,
                                 omit_check=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertFalse(faulted["target_temporal_admitted"])
        self.assertEqual("target_check_not_recorded",
                         faulted["target_temporal_reason"])
        self.assertEqual("needs_causal_review", faulted["status"])

    def test_mixed_reach_keeps_reached_target_without_unreached_union(self) -> None:
        state = self._run(self._executor(emit_door=True, throw=True,
                                         mixed_target=True))
        self.assertEqual("complete_trial_budget", state["status"])
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        summary = core._load(self.root / "campaign/trials/r0001/native-summary.json")
        self.assertEqual("candidate", faulted["status"])
        self.assertTrue(faulted["native_target_retained"])
        self.assertEqual(1, len(summary["perTargetOccurrences"]))
        self.assertEqual(1, len(summary["unreachedTargetRows"]))
        self.assertNotIn(summary["unreachedTargetRows"][0]["occurrenceId"],
                         summary["targetOccurrenceIds"])

    def test_cross_run_selector_binds_fresh_exact_occurrence(self) -> None:
        planned = [{"siteId": "RPC#getKeys", "node": "nn0",
                    "actorEpochOrdinal": 1, "ordinal": 2,
                    "exceptionClass": "java.io.IOException",
                    "sourceOccurrenceId": "healthy-process:old"}]
        door = {"kind": "FAULT_DOOR", "seq": 1,
                "siteId": "RPC#getKeys", "node": "nn0",
                "actorEpochOrdinal": 1, "ordinal": 2,
                "exceptionClass": "java.io.IOException",
                "occurrenceId": "trial-process:fresh"}
        applied = {**door, "kind": "FAULT_APPLIED", "seq": 2}
        self.assertEqual((True, 2), core._strict_faults(planned, [door, applied]))
        wrong_epoch = {**applied, "actorEpochOrdinal": 0}
        self.assertEqual((False, None), core._strict_faults(planned, [door, wrong_epoch]))
        wrong_actor = {**applied, "node": "nn1"}
        self.assertEqual((False, None), core._strict_faults(planned, [door, wrong_actor]))

    def test_wrong_fault_occurrence_is_unmatched_and_never_candidate(self) -> None:
        state = self._run(self._executor(emit_door=True,
                                         applied_identity="wrong-occurrence",
                                         throw=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertEqual("unmatched", faulted["status"])
        self.assertFalse(faulted["strict_injection"])
        self.assertFalse(faulted["target_exception_triggered"])
        self.assertEqual([], state["queue"])

    def test_fault_trial_without_target_is_discarded_even_with_throw_receipt(self) -> None:
        native_summary = core.summarize_target_set
        seen = 0

        def target_set(*args, **kwargs):
            nonlocal seen
            seen += 1
            if seen == 1:
                return native_summary(*args, **kwargs)
            raise NoNativeTargetError("no native target occurrence matches site/actor selection")

        with patch.object(core, "summarize_target_set", side_effect=target_set):
            state = self._run(self._executor(emit_door=True, throw=True))
        faulted = core._load(self.root / "campaign/trials/r0001/result.json")
        self.assertEqual("target_lost", faulted["status"])
        self.assertFalse(faulted["native_target_retained"])
        self.assertFalse(faulted["target_exception_triggered"])
        self.assertEqual([], state["queue"])

    def test_resume_accepts_completed_trial_without_duplicate_junit(self) -> None:
        self._run(self._executor(emit_door=True, throw=True))
        checkpoint = self.root / "campaign/checkpoint.json"
        state = core._load(checkpoint)
        state["status"], state["terminal"] = "running", False
        state["trials"], state["completed_fault_trials"] = [], 0
        state["active"] = {"index": 1, "name": "r0001", "faults": core._load(
            self.root / "campaign/trials/r0001/result.json")["faults"]}
        core._atomic(checkpoint, state)
        with patch.object(core, "_admit", return_value=self.admitted), patch.object(
                core, "_verify_pins"), patch.object(core, "_execute_junit") as execute:
            resumed = core.run_campaign(self.config_file, self.root / "campaign")
        execute.assert_not_called()
        self.assertEqual(1, resumed["completed_fault_trials"])
        changed = {**self.admitted, "zero_vm_sha256": "different-vm"}
        with patch.object(core, "_admit", return_value=changed):
            with self.assertRaisesRegex(ValueError, "checkpoint inputs changed"):
                core.run_campaign(self.config_file, self.root / "campaign")

    def test_fresh_runner_preserves_junit_identity_and_woven_class_priority(self) -> None:
        java = self.root / "fake-zero-java"
        java.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path('invocation.json').write_text(json.dumps({"
            "'argv': sys.argv[1:], 'sessions': os.environ.get("
            "'CAUSYNTH_CONCOLIC_SESSIONS'), 'plan': os.environ.get("
            "'MALLORY_NATIVE_FAULT_PLAN')}))\n")
        java.chmod(0o755)
        plan = self.root / "execution_task_plan.jsonl"
        plan.write_text('{"taskId":"recorded-task"}\n')
        library = self.root / "library"
        library.mkdir()
        config = dict(self.config)
        config["runner"] = {**config["runner"], "zero_vm_java": str(java),
                            "classpath": [str(library)]}
        admitted = {"weave_config": {"output_classes": str(self.woven),
                                     "task_plan": str(plan),
                                     "task_id": "recorded-task"}}
        trial = self.root / "fresh-trial"
        trial.mkdir()
        result = core._execute_junit(config, admitted, trial, [])
        self.assertEqual(0, result["return_code"])
        invocation = json.loads((trial / "iteration-native/workdir/invocation.json")
                                .read_text())
        argv = invocation["argv"]
        self.assertIn("-Dcausynth.concolic.task.id=recorded-task", argv)
        self.assertEqual(["UnchangedFixtureTest", "testOperation"], argv[-2:])
        self.assertEqual(str(self.woven), argv[argv.index("-cp") + 1].split(os.pathsep)[0])
        self.assertEqual(str(trial / "iteration-native/sessions"),
                         invocation["sessions"])
        self.assertTrue((trial / "iteration-native/fault-plan.json").is_file())

    def test_resume_reuses_content_pinned_recording_admission(self) -> None:
        for name in ("streaming_trace_manifest.json", "graph.jsonl",
                     "static_scope_map.jsonl", "regions.jsonl"):
            (self.seed / name).write_text('{"fixture":true}\n')
        vm = self.root / "vm-java"
        vm.write_text("fixture-vm\n")
        scheduler = self.root / "ConcolicScheduler.java"
        scheduler.write_text("// pinned fixture source\n")
        self.weave_config.write_text(json.dumps({"output_classes": str(self.woven)}))
        output = self.root / "admission"
        output.mkdir()
        with patch.object(core, "verify_existing", return_value={"verified": True}), patch.object(
                core, "_scheduler_source", return_value=scheduler), patch.object(
                core, "_verify_recording_plan", return_value={"plan": "derived"}) as derive:
            first = core._admit(self.config, output)
            second = core._admit(self.config, output)
            self.assertEqual(first["origin"], second["origin"])
            derive.assert_called_once()
            (self.seed / "graph.jsonl").write_text("changed graph\n")
            with self.assertRaisesRegex(ValueError, "admission inputs changed"):
                core._admit(self.config, output)


if __name__ == "__main__":
    unittest.main()
