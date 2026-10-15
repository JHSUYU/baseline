"""Generic repeated RPC occurrence scheduling; no cluster or named fault site."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from Mallory.native_graphchecker_campaign import campaign as core


def door(site: str, ordinal: int, seq: int, *, actor: str = "client",
         phase: str = "before_selected_target", anchor: str = "a") -> dict:
    return {"fault": {"siteId": site, "node": actor,
                      "actorEpochOrdinal": 0, "ordinal": ordinal,
                      "exceptionClass": "java.io.IOException",
                      "sourceOccurrenceId": f"{site}-{ordinal}"},
            "seq": seq, "tier": "observed_closure",
            "target_phase": phase, "target_order_distance": 100 - seq,
            "anchor_address": anchor}


def state(completed: int = 2, max_faults: int = 2) -> dict:
    return {"budget": {"max_faults_per_trial": max_faults}, "queue": [],
            "seen_plan_keys": [], "completed_fault_trials": completed,
            "scheduler_version": 14, "multi_anchor_addresses": ["a", "b"],
            "fault_id_attempts": {}, "fault_id_successes": {}}


class RepeatedRpcOccurrenceTest(unittest.TestCase):
    def test_policy_is_opt_in_and_allows_twelve_faults(self):
        config = {"case_id": "sample", "budget": {"fault_trials": 64,
                  "max_faults_per_trial": 12}, "recording": {
                  "multi_target_max_anchors": 4,
                  "repeated_rpc_occurrence_policy": "repeated_rpc_pretarget_v1"}}
        admitted = {"weave_config": {"output_classes": "/unused"},
                    "origin": {}, "zero_vm_sha256": "zero",
                    "runner_classpath_artifacts": []}
        with patch.object(core, "_sha", return_value="receipt"):
            got = core._new_state(config, "config", admitted)
        self.assertEqual(14, got["scheduler_version"])
        self.assertEqual(12, got["budget"]["max_faults_per_trial"])
        self.assertEqual(16, core.MAX_FAULTS)

    def test_marks_only_observed_same_actor_pretarget_static_rpc(self) -> None:
        early = door("RPC", 2, 2)
        late = door("RPC", 3, 3)
        other_actor = door("RPC", 4, 4, actor="other")
        after = door("RPC", 5, 5, phase="after_selected_target")
        ordinary = door("file", 1, 1)
        rows = [early, late, other_actor, after, ordinary]
        core._mark_repeated_rpc_predecessors(rows, frozenset({"RPC"}))
        self.assertEqual(1, early["later_same_site_pretarget_count"])
        self.assertEqual(97, early["last_same_site_target_distance"])
        self.assertTrue(all("later_same_site_pretarget_count" not in row
                            for row in (late, other_actor, after, ordinary)))

    def test_bounded_predecessor_and_exact_same_site_descendant_slots(self) -> None:
        s = state()
        early = door("RPC", 2, 2)
        late = door("RPC", 3, 3)
        core._mark_repeated_rpc_predecessors([early, late], frozenset({"RPC"}))
        core._enqueue(s, [early, late, door("other", 1, 4)], [], 0)
        selected = core._pick(s)
        self.assertEqual(2, selected["faults"][-1]["ordinal"])
        self.assertEqual("RPC", selected["faults"][-1]["siteId"])

        # A fresh trial may reveal a later occurrence after the applied
        # prefix. Only that observed successor is admitted.
        s["completed_fault_trials"] = 6
        core._enqueue(s, [late, door("other", 2, 5)], selected["faults"], 0)
        descendant = core._pick(s)
        self.assertEqual([2, 3], [f["ordinal"] for f in
                                  descendant["faults"]])
        self.assertTrue(descendant["same_site_descendant"])

    def test_different_actor_and_nonincreasing_occurrence_are_not_descendants(self):
        s = state()
        prior = door("RPC", 3, 3)["fault"]
        core._enqueue(s, [door("RPC", 2, 4),
                          door("RPC", 4, 5, actor="other")], [prior], 0)
        self.assertEqual(2, len(s["queue"]))
        self.assertFalse(any(row["same_site_descendant"] for row in s["queue"]))

    def test_only_exact_observed_static_rpc_continuation_crosses_frontier(self):
        previous = door("RPC", 2, 2)["fault"]
        closure = door("ordinary", 1, 3)
        ordinary_frontier = {**door("ordinary", 2, 4),
                             "tier": "static_producer_frontier"}
        different_actor = {**door("RPC", 3, 5, actor="other"),
                           "tier": "static_producer_frontier"}
        later = {**door("RPC", 3, 6),
                 "tier": "static_producer_frontier"}
        after = {**door("RPC", 4, 7, phase="after_selected_target"),
                 "tier": "static_producer_frontier"}
        rows = [closure, ordinary_frontier, different_actor, later, after]
        self.assertEqual([closure], core._anchored_repeated_rpc_doors(
            rows, frozenset({"RPC"}), None))
        self.assertEqual([closure, later], core._anchored_repeated_rpc_doors(
            rows, frozenset({"RPC"}), previous))

    def test_long_repeated_window_near_target_beats_more_distant_poll(self):
        s = state(max_faults=12)
        close = [door("close", ordinal, 70 + ordinal) for ordinal in range(1, 10)]
        distant = [door("distant", ordinal, 10 + ordinal)
                   for ordinal in range(1, 16)]
        rows = close + distant
        core._mark_repeated_rpc_predecessors(
            rows, frozenset({"close", "distant"}))
        core._enqueue(s, rows, [], 0)
        selected = core._pick(s)
        self.assertEqual("close", selected["faults"][-1]["siteId"])
        self.assertGreaterEqual(selected["later_same_site_pretarget_count"], 7)


if __name__ == "__main__":
    unittest.main()
