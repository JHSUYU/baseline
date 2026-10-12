import copy
import unittest

from role_plan import ROLE, SITE, attest_applied, promote
from prepare_pilot import TARGET, prepare
from audit_pilot import audit


class RolePlanTest(unittest.TestCase):
    def setUp(self):
        self.plan = {"schema_version": 1, "faults": [{"fault_id": "f1",
            "fault_type": "EXCEPTION", "point": {"site": SITE, "node": "node2",
            "epoch": 0, "door_ordinal": 16}}]}
        self.healthy = [{"id": "healthy:99", "type": "DOOR_OBSERVED", "site": SITE,
            "node": "node2", "epoch": 0, "door_ordinal": 16,
            "role": ROLE, "role_resolution": "unique", "role_ordinal": 16,
            "role_node": "node2", "role_epoch": 0,
            "role_leader_id": "election-2"}]

    def test_role_plan_replays_on_a_different_physical_leader(self):
        promoted = promote(self.plan, self.healthy)
        self.assertEqual(promoted["faults"][0]["point"],
                         {"site": SITE, "role": ROLE, "role_ordinal": 16})
        event = {"type": "FAULT_APPLIED", "site": SITE, "fault_id": "f1",
                 "node": "node1", "epoch": 0, "role": ROLE,
                 "role_resolution": "unique", "role_ordinal": 16,
                 "role_node": "node1", "role_epoch": 0,
                 "role_leader_id": "election-1"}
        self.assertEqual(attest_applied(promoted, [event])["physical_node"], "node1")

    def test_old_trace_fails_closed(self):
        old = copy.deepcopy(self.healthy)
        old[0].pop("role_ordinal")
        with self.assertRaisesRegex(ValueError, "role ordinal"):
            promote(self.plan, old)

    def test_ambiguous_or_disagreeing_binding_fails_closed(self):
        ambiguous = copy.deepcopy(self.healthy)
        ambiguous[0]["role_resolution"] = "ambiguous"
        with self.assertRaisesRegex(ValueError, "unique"):
            promote(self.plan, ambiguous)
        conflicting = copy.deepcopy(self.healthy)
        conflicting[0]["role_node"] = "node4"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            promote(self.plan, conflicting)

    def test_inexact_site_rejected(self):
        self.plan["faults"][0]["point"]["site"] = SITE.replace("@246", "@247")
        with self.assertRaisesRegex(ValueError, "exact"):
            promote(self.plan, self.healthy)

    def test_applied_event_must_preserve_physical_identity(self):
        promoted = promote(self.plan, self.healthy)
        event = {"type": "FAULT_APPLIED", "site": SITE, "fault_id": "f1",
                 "node": "node1", "epoch": 0, "role": ROLE,
                 "role_resolution": "unique", "role_ordinal": 16,
                 "role_node": "node2", "role_epoch": 0,
                 "role_leader_id": "election-1"}
        with self.assertRaisesRegex(ValueError, "disagrees"):
            attest_applied(promoted, [event])

    def test_prepares_only_a_role_door_with_later_target(self):
        trace = [dict(self.healthy[0]), {"type": "TARGET_CHECK", "site": TARGET,
                                       "id": "healthy:100"}]
        plan, receipt = prepare(trace, 16)
        self.assertEqual(plan["faults"][0]["point"],
                         {"site": SITE, "role": ROLE, "role_ordinal": 16})
        self.assertEqual(receipt["later_healthy_target_id"], "healthy:100")

    def test_preparation_requires_observed_causal_path(self):
        door = dict(self.healthy[0], occurrence="overseer:1")
        target = {"type": "TARGET_CHECK", "site": TARGET, "id": "healthy:100",
                  "node": "node2", "epoch": 0, "occurrence": "target:1"}
        feedback = {"doors": [{"event_id": "healthy:99", "in_closure": True}],
                    "closure_edges": [{"source": '["node2","0","overseer:1"]',
                                       "target": '["node2","0","target:1"]',
                                       "certainty": "observed", "kind": "task",
                                       "producer_event": "healthy:99",
                                       "consumer_event": "healthy:100"}]}
        _, receipt = prepare([door, target], 16, feedback)
        self.assertEqual(len(receipt["observed_causal_path"]), 1)
        feedback["closure_edges"][0]["certainty"] = "inferred"
        with self.assertRaisesRegex(ValueError, "no observed causal path"):
            prepare([door, target], 16, feedback)

    def test_preparation_fails_without_later_target(self):
        trace = [{"type": "TARGET_CHECK", "site": TARGET}, dict(self.healthy[0])]
        with self.assertRaisesRegex(ValueError, "no later"):
            prepare(trace, 16)

    def test_pilot_audit_requires_postfault_target_continuation(self):
        plan = promote(self.plan, self.healthy)
        applied = {"type": "FAULT_APPLIED", "site": SITE, "fault_id": "f1",
                   "node": "node1", "epoch": 2, "role": ROLE,
                   "role_resolution": "unique", "role_ordinal": 16,
                   "role_node": "node1", "role_epoch": 2,
                   "role_leader_id": "election-1"}
        self.assertEqual(audit(plan, [applied])["status"], "target_lost")
        self.assertEqual(audit(plan, [applied, {"type": "TARGET_CHECK", "site": TARGET,
                                                  "id": "trial:101"}])["status"],
                         "applied_target_continued")


if __name__ == "__main__":
    unittest.main()
