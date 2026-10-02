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
                                     Path(temp) / "replay.jsonl")
            for index in range(1, 8):
                self.assertEqual("CONTINUE", replay.on_event(
                    point_event("root/request#" + str(index * 10 + 1),
                                index)))
            self.assertTrue(replay.complete)
            self.assertEqual(["hm1"], backend.killed)
            self.assertEqual("site_occurrence", replay.match_modes[6])
            journal = [json.loads(line) for line in
                       (Path(temp) / "replay.jsonl").read_text().splitlines()]
            self.assertEqual("site_occurrence", journal[-1]["match_mode"])

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
