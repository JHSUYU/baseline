#!/usr/bin/env python3
"""Pure-Python negative and positive checks for the offline resource gate."""

import copy
import unittest

from verify_resource_binding import FIRST, NATIVE, REGION, SECOND, verify


def sample():
    base = {"type": "DOOR_OBSERVED", "node": "node2", "epoch": 0,
            "occurrence": "node2:split:one", "thread_id": 27, "region": REGION}
    rows = []
    for seq, site, resource, ordinal in (
            (10, FIRST, None, 1),
            (11, NATIVE, "/live_nodes/127.0.0.1:8983_solr", 3),
            (20, SECOND, None, 2),
            (21, NATIVE, "/live_nodes/127.0.0.1:8983_solr", 4),
            (22, NATIVE, "/live_nodes/127.0.0.1:8983_solr", 5)):
        row = dict(base, seq=seq, site=site, door_ordinal=ordinal)
        if resource is not None:
            row["resource"] = resource
        rows.append(row)
    plan = {"faults": [{"point": {"site": NATIVE, "node": "node2",
                                   "epoch": 0, "occurrence": "node2:split:one",
                                   "door_ordinal": 5},
                       "exception_class":
                       "org.apache.zookeeper.KeeperException$ConnectionLossException"}]}
    rows.append(dict(base, type="FAULT_APPLIED", seq=23, site=NATIVE,
                     door_ordinal=5, resource="/live_nodes/127.0.0.1:8983_solr",
                     exception_class="org.apache.zookeeper.KeeperException$ConnectionLossException"))
    return rows, plan


class ResourceBindingTest(unittest.TestCase):
    def test_accepts_retry_attempt_on_same_parent_path(self):
        rows, plan = sample()
        result = verify(rows, plan)
        self.assertEqual("/live_nodes/127.0.0.1:8983_solr", result["resource"])
        self.assertEqual("node2", result["actor"])
        self.assertEqual(2, result["second_native_attempts"])

    def test_rejects_other_znode(self):
        rows, plan = sample()
        rows[-2]["resource"] = "/live_nodes/other_parent"
        rows[-1]["resource"] = "/live_nodes/other_parent"
        with self.assertRaisesRegex(ValueError, "disagree"):
            verify(rows, plan)

    def test_rejects_non_live_nodes_path(self):
        rows, plan = sample()
        for row in rows:
            if row["site"] == NATIVE:
                row["resource"] = "/collections/collection1/state.json"
        with self.assertRaisesRegex(ValueError, "not_exact_live_node"):
            verify(rows, plan)

    def test_rejects_missing_resource(self):
        rows, plan = sample()
        for row in rows:
            row.pop("resource", None)
        with self.assertRaisesRegex(ValueError, "not_exact_live_node"):
            verify(rows, plan)

    def test_rejects_wrong_actor_occurrence_and_ordinal(self):
        for field, value in (("node", "node3"), ("occurrence", "other"),
                             ("door_ordinal", 99)):
            rows, plan = sample()
            plan["faults"][0]["point"][field] = value
            with self.assertRaises(ValueError):
                verify(rows, plan)

    def test_rejects_cross_occurrence_native_attempt(self):
        rows, plan = sample()
        rows[-2]["occurrence"] = "node2:split:other"
        rows[-1]["occurrence"] = "node2:split:other"
        with self.assertRaisesRegex(ValueError, "wrong_occurrence"):
            verify(rows, plan)

    def test_rejects_missing_caller_handoff(self):
        rows, plan = sample()
        rows = [row for row in rows if row["site"] != SECOND]
        with self.assertRaisesRegex(ValueError, "lookup_missing"):
            verify(rows, plan)

    def test_rejects_wrong_plan_resource(self):
        rows, plan = sample()
        plan["faults"][0]["point"]["resource"] = "/live_nodes/other_parent"
        with self.assertRaisesRegex(ValueError, "differs"):
            verify(rows, plan)

    def test_rejects_extra_fault_or_caller_only_plan(self):
        rows, plan = sample()
        plan["faults"].append(copy.deepcopy(plan["faults"][0]))
        with self.assertRaisesRegex(ValueError, "one_native_fault"):
            verify(rows, plan)
        rows, plan = sample()
        plan["faults"][0]["point"]["site"] = SECOND
        with self.assertRaisesRegex(ValueError, "wrong_native"):
            verify(rows, plan)

    def test_rejects_missing_or_wrong_applied_fault(self):
        rows, plan = sample()
        with self.assertRaisesRegex(ValueError, "applied_fault_not_bound"):
            verify(rows[:-1], plan)
        rows, plan = sample()
        rows[-1]["resource"] = "/live_nodes/other_parent"
        with self.assertRaisesRegex(ValueError, "applied_fault_not_bound"):
            verify(rows, plan)
        rows, plan = sample()
        rows[-1]["exception_class"] = "java.io.IOException"
        with self.assertRaisesRegex(ValueError, "applied_fault_not_bound"):
            verify(rows, plan)

    def test_rejects_missing_occurrence_or_truncated_trace(self):
        rows, plan = sample()
        del plan["faults"][0]["point"]["occurrence"]
        with self.assertRaisesRegex(ValueError, "missing_epoch_occurrence"):
            verify(rows, plan)
        rows, plan = sample()
        rows.append({"type": "TRACE_TRUNCATED"})
        with self.assertRaisesRegex(ValueError, "incomplete_event_trace"):
            verify(rows, plan)


if __name__ == "__main__":
    unittest.main()
