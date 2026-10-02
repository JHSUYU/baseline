import unittest

from adhoc_crashfuzz.feedback import Coverage
from adhoc_crashfuzz.graph import build_graph, target_closure
from adhoc_crashfuzz.model import Event, TargetSpec


def event(kind, node, process, seq, span, **extra):
    return Event(kind, node, process, seq, span=span, **extra)


class GraphTests(unittest.TestCase):
    def test_block_and_branch_coverage_keep_causal_scope(self):
        records = [
            event("METHOD_ENTER", "n", "p", 1, "1", site="path"),
            event("BLOCK", "n", "p", 2, "1", site="path#BB1"),
            event("BRANCH", "n", "p", 3, "1", site="path#B1",
                  outcome="false"),
            event("TARGET", "n", "p", 4, "1", site="check"),
            event("METHOD_ENTER", "n", "p", 5, "2", site="other"),
            event("BLOCK", "n", "p", 6, "2", site="other#BB1"),
            event("GLOBAL_BLOCK", "n", "p", 7, "", site="library#BB1"),
            event("GLOBAL_BRANCH", "n", "p", 8, "", site="library#B1",
                  outcome="true"),
        ]
        graph = build_graph(records)
        closure = target_closure(graph, TargetSpec("check"))
        self.assertTrue(any("path#BB1" in b for b in closure.block_features))
        self.assertFalse(any("other#BB1" in b for b in closure.block_features))
        self.assertFalse(any("library#BB1" in b for b in closure.block_features))
        self.assertEqual({"library#BB1"}, graph.global_blocks)
        coverage = Coverage()
        delta = coverage.observe(closure, graph)
        self.assertIn("library#BB1", delta.global_blocks)
        self.assertIn("library#B1|true", delta.global_branches)
        self.assertFalse(coverage.observe(closure, graph).gained)

    def test_target_closure_follows_message_and_state_candidate(self):
        records = [
            event("METHOD_ENTER", "a", "pa", 1, "1", site="sender"),
            event("MESSAGE_SEND", "a", "pa", 2, "1",
                  correlation="request-1"),
            event("METHOD_ENTER", "b", "pb", 1, "2", site="writer"),
            event("FIELD_WRITE", "b", "pb", 2, "2",
                  location="Cache#version@42"),
            event("METHOD_ENTER", "b", "pb", 3, "3", site="handler"),
            event("MESSAGE_RECV", "b", "pb", 4, "3",
                  correlation="request-1"),
            event("FIELD_READ", "b", "pb", 5, "3",
                  location="Cache#version@42"),
            event("TARGET", "b", "pb", 6, "3", site="check", fatal=True),
            event("METHOD_ENTER", "c", "pc", 1, "4", site="unrelated"),
        ]
        graph = build_graph(records)
        closure = target_closure(graph, TargetSpec("check"))
        self.assertTrue(closure.reached)
        self.assertTrue(closure.fatal)
        self.assertEqual(3, len(closure.nodes))
        self.assertEqual({"MESSAGE", "STATE_CANDIDATE"},
                         {edge.kind for edge in closure.edges})
        self.assertFalse(any("unrelated" in feature
                             for feature in closure.node_features))
        coverage = Coverage()
        self.assertTrue(coverage.observe(closure).gained)
        self.assertFalse(coverage.observe(closure).gained)

    def test_versioned_state_edge_and_unpaired_message_gap(self):
        records = [
            event("METHOD_ENTER", "n", "p", 1, "1", site="writer"),
            event("FIELD_WRITE", "n", "p", 2, "1", location="x@1",
                  state_version="v7"),
            event("METHOD_ENTER", "n", "p", 3, "2", site="reader"),
            event("FIELD_READ", "n", "p", 4, "2", location="x@1",
                  observed_version="v7"),
            event("MESSAGE_RECV", "n", "p", 5, "2", correlation="lost"),
            event("TARGET", "n", "p", 6, "2", site="check"),
        ]
        graph = build_graph(records)
        self.assertEqual({"STATE"}, {edge.kind for edge in graph.edges})
        self.assertTrue(any("producer count 0" in gap for gap in graph.gaps))

    def test_epoch_changes_with_process_instance(self):
        records = [
            event("METHOD_ENTER", "n", "older", 1, "1",
                  site="old", wall_ms=100),
            event("METHOD_ENTER", "n", "newer", 1, "1",
                  site="new", wall_ms=200),
        ]
        graph = build_graph(records)
        self.assertEqual({0, 1}, {node.epoch for node in graph.nodes.values()})

    def test_crash_before_guard_keeps_partial_method_frontier(self):
        records = [
            event("METHOD_ENTER", "m", "p", 1, "1",
                  site="Master#check()V", context="root/request#1"),
            event("FAULT_POINT", "m", "p", 2, "1", site="read-state",
                  context="root/request#1", ordinal=1),
        ]
        graph = build_graph(records)
        closure = target_closure(
            graph, TargetSpec("Master#check()V#B2", node="m",
                              context_prefix="root/request"))
        self.assertFalse(closure.reached)
        self.assertFalse(closure.fatal)
        self.assertEqual(1, len(closure.nodes))
        self.assertEqual(1, len(closure.points))

    def test_target_failover_to_same_role_is_novel(self):
        coverage = Coverage()
        target = TargetSpec("Master#check()V#B2")
        for node in ("m1", "m2"):
            graph = build_graph([
                event("METHOD_ENTER", node, "p", 1, "1",
                      site="Master#check()V"),
                event("TARGET", node, "p", 2, "1",
                      site="Master#check()V#B2"),
            ])
            delta = coverage.observe(target_closure(
                graph, target, {"m1": "master", "m2": "master"}))
            self.assertTrue(delta.gained)
            self.assertTrue(any("TARGET_HOST" in feature
                                for feature in delta.nodes))


if __name__ == "__main__":
    unittest.main()
