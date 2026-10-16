"""Focused tests for the opt-in priority quota on a frozen queue shape."""

import copy
import unittest

from .campaign import _fault_id, _pick, _plan_key
from .priority_quota import POLICY, choose


ANCHOR = "node0#epoch0/region/exact-target"


def fault(ordinal, site="<P: void rpc()>#u1", exception="java.io.IOException"):
    return {"siteId": site, "node": "node0", "actorEpochOrdinal": 0,
            "sourceOccurrenceId": f"occ-{ordinal}", "ordinal": ordinal,
            "exceptionClass": exception}


def item(faults, *, anchor=ANCHOR, phase="before_selected_target",
         retained=True, score=3, tier="observed_closure"):
    return {"faults": faults, "anchor_address": anchor,
            "key": _plan_key(faults, anchor), "tier": tier,
            "target_phase": phase, "peer_relation": "same_peer_before_target",
            "depth_feedback": {"strict_post_fault_target": retained,
                               "observed_pre_target_phase": True,
                               "score": score},
            "novelty": 0, "enqueued_at": 0, "attempt": 0}


def state(queue, completed=9, policy=POLICY):
    return {"retained_parent_pretarget_priority": policy,
            "completed_fault_trials": completed,
            "budget": {"fault_trials": 256, "max_faults_per_trial": 256,
                       "seconds": 28800},
            "scheduler_version": 16, "queue": queue,
            "multi_anchor_addresses": [ANCHOR], "trials": [],
            "fault_id_attempts": {}, "fault_id_successes": {},
            "peer_postfault_attempts": {}, "peer_postfault_retained": {}}


class PriorityQuotaTest(unittest.TestCase):
    def pick(self, s):
        return choose(s, plan_key=_plan_key, fault_id=_fault_id,
                      depth_limit=s["budget"]["max_faults_per_trial"])

    def test_only_two_of_sixteen_slots_are_eligible(self):
        x = item([fault(1), fault(2)])
        for index in range(16):
            chosen = self.pick(state([x], completed=index))
            self.assertEqual(chosen is x, index in (9, 14))

    def test_exact_parent_retention_phase_and_closure_gate(self):
        good = item([fault(1), fault(2)])
        bad = [item([fault(1), fault(3)], retained=False),
               item([fault(1), fault(4)], phase="after_selected_target"),
               item([fault(1), fault(5)], tier="outside_closure")]
        self.assertIs(self.pick(state([*bad, good])), good)

    def test_malformed_or_changed_plan_key_fails_closed(self):
        x = item([fault(1), fault(2)])
        x["key"] = "changed"
        self.assertIsNone(self.pick(state([x])))

    def test_productive_parent_preferred_without_depth_ceiling(self):
        old = item([fault(1), fault(2)], score=1)
        deep = item([fault(n) for n in range(1, 18)], score=4)
        self.assertIs(self.pick(state([old, deep])), deep)

    def test_legacy_checkpoint_has_identical_selection(self):
        q = [item([fault(1)]), item([fault(2)]),
             item([fault(1), fault(3)])]
        s = state(copy.deepcopy(q), completed=9, policy=None)
        self.assertIsNone(self.pick(s))
        control = copy.deepcopy(s)
        control.pop("retained_parent_pretarget_priority")
        self.assertEqual(_pick(s)["key"], _pick(control)["key"])

    def test_real_pick_removes_only_selected_existing_plan(self):
        good = item([fault(1), fault(2)])
        later = item([fault(1), fault(3)], phase="after_selected_target")
        s = state([later, good], completed=14)
        selected = _pick(s)
        self.assertEqual(selected["key"], good["key"])
        self.assertEqual([x["key"] for x in s["queue"]], [later["key"]])


if __name__ == "__main__":
    unittest.main()
