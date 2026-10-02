"""Replay regression for nondeterministic RPC invocation counts."""

import json
from pathlib import Path
import tempfile
import unittest

from adhoc_crashfuzz.controller import FaultController
from adhoc_crashfuzz.model import FaultAction, FaultSequence, PointKey
from adhoc_crashfuzz.mutation import NodeGroup, mutate_one_fault


class FakeBackend:
    def __init__(self):
        self.killed = []

    def kill_node(self, node):
        self.killed.append(node)

    def start_node(self, node):
        pass


def point_event(context, seq):
    return {"schema": 1, "kind": "FAULT_POINT", "node": "hm1",
            "process": "p1", "seq": seq, "site": "rpc#ENTRY",
            "context": context, "ordinal": 1, "phase": "BEFORE"}


class ControllerTests(unittest.TestCase):
    def test_prepare_points_are_not_injected_or_counted(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", "root/request#1", 1), "hm1", 1)
            controller = FaultController(FaultSequence((action,)), backend,
                                         Path(temp) / "points.jsonl",
                                         armed=False)
            self.assertEqual("CONTINUE", controller.on_event(
                point_event("root/request#1", 1)))
            self.assertEqual([], controller.points)
            self.assertEqual([], backend.killed)
            controller.arm()
            self.assertEqual("CONTINUE", controller.on_event(
                point_event("root/request#1", 2)))
            self.assertTrue(controller.complete)
            self.assertEqual(1, len(controller.points))
            self.assertEqual(["hm1"], backend.killed)

    def test_freeze_prevents_late_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", "root/request#1", 1), "hm1")
            controller = FaultController(FaultSequence((action,)), backend,
                                         Path(temp) / "late.jsonl")
            self.assertFalse(controller.freeze())
            self.assertEqual("CONTINUE", controller.on_event(
                point_event("root/request#1", 1)))
            self.assertFalse(controller.complete)
            self.assertEqual([], backend.killed)
            self.assertEqual([], controller.points)

    def test_site_occurrence_replays_when_rpc_context_shifts(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            seed = FaultController(FaultSequence(), backend,
                                   Path(temp) / "seed.jsonl")
            for index in range(1, 8):
                self.assertEqual("CONTINUE", seed.on_event(
                    point_event("root/request#" + str(index * 10), index)))
            sequences = mutate_one_fault(
                FaultSequence(), seed.points, {"hm1", "hm2"},
                (NodeGroup(frozenset({"hm1", "hm2"}), 1),), 1)
            action = sequences[-1].actions[0]
            self.assertEqual(7, action.site_occurrence)
            self.assertEqual(action, FaultAction.from_dict(action.to_dict()))

            replay = FaultController(FaultSequence((action,)), backend,
                                     Path(temp) / "replay.jsonl",
                                     allow_site_occurrence_fallback=True)
            for index in range(1, 8):
                self.assertEqual("CONTINUE", replay.on_event(
                    point_event("root/request#" + str(index * 10 + 1),
                                index)))
            self.assertTrue(replay.complete)
            self.assertEqual(["hm1"], backend.killed)
            self.assertEqual("shape_occurrence", replay.match_modes[6])
            journal = [json.loads(line) for line in
                       (Path(temp) / "replay.jsonl").read_text().splitlines()]
            self.assertEqual("shape_occurrence", journal[-1]["match_mode"])

    def test_relaxed_identity_still_requires_same_context_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", "root/delete#10", 1), "hm1", 1)
            replay = FaultController(FaultSequence((action,)), backend,
                                     Path(temp) / "shape.jsonl",
                                     allow_site_occurrence_fallback=True)
            self.assertEqual("CONTINUE", replay.on_event(
                point_event("root/truncate#11", 1)))
            self.assertFalse(replay.complete)
            self.assertEqual([], backend.killed)

    def test_shape_occurrence_matches_same_async_path_after_root_shift(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            planned = ("root/org/apache/hbase/Rpc#process()V#112"
                       "/async:Procedure#1/org/apache/hbase/Check#run()V#1")
            actual = ("root/org/apache/hbase/Rpc#process()V#137"
                      "/async:Procedure#2/org/apache/hbase/Check#run()V#1")
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", planned, 1), "hm1", 1)
            replay = FaultController(FaultSequence((action,)), backend,
                                     Path(temp) / "async-shape.jsonl",
                                     allow_site_occurrence_fallback=True)
            self.assertEqual("CONTINUE", replay.on_event(point_event(actual, 1)))
            self.assertTrue(replay.complete)
            self.assertEqual("shape_occurrence", replay.match_modes[0])

    def test_strict_identity_does_not_match_shifted_context(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", "root/request#10", 1), "hm1", 1)
            replay = FaultController(FaultSequence((action,)), backend,
                                     Path(temp) / "strict.jsonl")
            self.assertEqual("CONTINUE", replay.on_event(
                point_event("root/request#11", 1)))
            self.assertFalse(replay.complete)
            self.assertEqual([], backend.killed)

    def test_strict_identity_requires_same_epoch(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", "root/request#10", 1), "hm1",
                trigger_epoch=1)
            replay = FaultController(FaultSequence((action,)), backend,
                                     Path(temp) / "epoch.jsonl")
            self.assertEqual("CONTINUE", replay.on_event(
                point_event("root/request#10", 1)))
            self.assertFalse(replay.complete)
            self.assertEqual([], backend.killed)

    def test_exact_context_remains_preferred(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = FakeBackend()
            action = FaultAction("CRASH", PointKey(
                "hm1", "rpc#ENTRY", "root/request#69", 1), "hm1", 7)
            replay = FaultController(FaultSequence((action,)), backend,
                                     Path(temp) / "replay.jsonl")
            self.assertEqual("CONTINUE", replay.on_event(
                point_event("root/request#69", 1)))
            self.assertEqual("exact", replay.match_modes[0])
            self.assertEqual(["hm1"], backend.killed)


if __name__ == "__main__":
    unittest.main()
