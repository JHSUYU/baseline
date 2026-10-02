import unittest

from adhoc_crashfuzz.model import FaultAction, FaultSequence, PointKey
from adhoc_crashfuzz.mutation import (NodeGroup, ObservedPoint,
                                      mutate_one_fault, state_after)


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {"a", "b", "c"}
        self.groups = (NodeGroup(frozenset(self.nodes), 1),)
        self.a = PointKey("a", "send", "root/step#1", 1)
        self.b = PointKey("b", "retry", "root/step#2", 1)

    def test_initial_mutation_crashes_reporting_nodes(self):
        mutations = mutate_one_fault(
            FaultSequence(), [ObservedPoint(self.a, 0),
                              ObservedPoint(self.b, 1)],
            self.nodes, self.groups, 3)
        self.assertEqual([("CRASH", "a"), ("CRASH", "b")],
                         [(m.actions[-1].kind, m.actions[-1].target_node)
                          for m in mutations])

    def test_after_crash_only_reboot_at_later_live_reporter(self):
        prior = FaultSequence((FaultAction("CRASH", self.a, "a"),))
        mutations = mutate_one_fault(
            prior, [ObservedPoint(self.a, 0), ObservedPoint(self.b, 1)],
            self.nodes, self.groups, 3, last_injected_order=0)
        self.assertEqual(1, len(mutations))
        self.assertEqual("REBOOT", mutations[0].actions[-1].kind)
        self.assertEqual("a", mutations[0].actions[-1].target_node)
        self.assertEqual(({"a", "b", "c"}, set()),
                         state_after(mutations[0], self.nodes, self.groups))

    def test_invalid_crash_of_other_node_and_full_down_group(self):
        with self.assertRaises(ValueError):
            state_after(FaultSequence((FaultAction("CRASH", self.a, "b"),)),
                        self.nodes, self.groups)
        with self.assertRaises(ValueError):
            NodeGroup(frozenset({"only"}), 1)


if __name__ == "__main__":
    unittest.main()
