#!/usr/bin/env python3
"""Pure-Python path/actor checks; no cluster or JVM is started."""

import unittest

from audit_healthy import NATIVE, bind_parent_resource


def sample():
    common = {"site": NATIVE, "node": "control", "epoch": 0,
              "occurrence": "control:split:one", "thread": "Overseer-1",
              "context": "task:7", "resource": "/live_nodes/127.0.0.1:8983_"}
    first = dict(common, seq=10, id="first", door_ordinal=3)
    second = dict(common, seq=20, id="second", door_ordinal=8)
    return first, second


class BindingTest(unittest.TestCase):
    def test_accepts_same_parent_resource(self):
        first, second = sample()
        got = bind_parent_resource(first, second, {"127.0.0.1:8983_"})
        self.assertEqual("second", got["second_native_event_id"])
        self.assertEqual(8, got["second_native_door_ordinal"])

    def test_rejects_changed_or_nonlive_path(self):
        first, second = sample()
        second["resource"] = "/live_nodes/other"
        with self.assertRaisesRegex(ValueError, "resource_changed"):
            bind_parent_resource(first, second, {"127.0.0.1:8983_"})
        first, second = sample()
        first["resource"] = second["resource"] = "/collections/c1/state.json"
        with self.assertRaisesRegex(ValueError, "not_exact_live_node"):
            bind_parent_resource(first, second, {"127.0.0.1:8983_"})

    def test_rejects_unregistered_parent_and_missing_resource(self):
        first, second = sample()
        with self.assertRaisesRegex(ValueError, "not_registered"):
            bind_parent_resource(first, second, {"127.0.0.1:9999_"})
        first, second = sample()
        second.pop("resource")
        with self.assertRaisesRegex(ValueError, "resource_missing"):
            bind_parent_resource(first, second, {"127.0.0.1:8983_"})

    def test_rejects_cross_actor_occurrence_and_wrong_order(self):
        for key, value in (("node", "shard-1"), ("epoch", 1),
                           ("occurrence", "other"), ("thread", "other"),
                           ("context", "other")):
            first, second = sample()
            second[key] = value
            with self.assertRaisesRegex(ValueError, "cross_actor"):
                bind_parent_resource(first, second, {"127.0.0.1:8983_"})
        first, second = sample()
        second["seq"] = 9
        with self.assertRaisesRegex(ValueError, "order_invalid"):
            bind_parent_resource(first, second, {"127.0.0.1:8983_"})


if __name__ == "__main__":
    unittest.main()
