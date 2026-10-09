"""Focused edge tests for the versioned ZooKeeper FOLLOWING retry hook."""

import unittest

from Mallory.adapters.zookeeper.audit_following_retry import (
    SITE, verified_retry_edges, verified_retry_target_paths,
)
from Mallory.core.graph import OccurrenceGraph


OLD = "zk1:1:zookeeper.peer.following:root:1"
NEW = "zk1:1:zookeeper.peer.following:root:2"
TARGET = "zk1:1:org.apache.zookeeper.server.quorum.Learner#registerWithLeader(I)J:root:2"
TOKEN = "zk-following-retry:1:1:47:83921:1"
THREAD = "QuorumPeer[myid=1](plain=127.0.0.1:30073)(secure=disabled)"


def event(seq, kind, occurrence, **fields):
    return {"id": f"run:{seq}", "seq": seq, "type": kind,
            "node": "zk1", "epoch": 1, "thread": THREAD,
            "occurrence": occurrence, **fields}


def valid_trace():
    return (
        event(1, "REGION_ENTER", OLD, site="zookeeper.peer.following", parent_id="root"),
        event(2, "FAULT_APPLIED", OLD, site="zookeeper.quorum.archive.readRecord"),
        event(3, "TASK_SUBMIT", OLD, site=SITE, correlation=TOKEN),
        event(4, "REGION_EXIT", OLD, site="zookeeper.peer.following"),
        event(5, "REGION_ENTER", NEW, site="zookeeper.peer.following", parent_id="root"),
        event(6, "TASK_CLAIM", NEW, site=SITE, correlation=TOKEN),
        event(7, "REGION_ENTER", TARGET,
              site="org.apache.zookeeper.server.quorum.Learner#registerWithLeader(I)J",
              parent_id=NEW),
        event(8, "TARGET_CHECK", TARGET,
              site="org.apache.zookeeper.server.quorum.Learner#registerWithLeader(I)J@518:branch:3"),
        event(9, "REGION_EXIT", TARGET,
              site="org.apache.zookeeper.server.quorum.Learner#registerWithLeader(I)J"),
        event(10, "REGION_EXIT", NEW, site="zookeeper.peer.following"),
    )


class FollowingRetryTest(unittest.TestCase):
    def test_unique_scoped_retry_and_nested_target_edges(self):
        trace = valid_trace()
        verified = verified_retry_edges(trace)
        self.assertEqual(len(verified), 1)
        self.assertEqual((verified[0]["producer_event"], verified[0]["consumer_event"]),
                         ("run:3", "run:6"))
        graph = OccurrenceGraph(trace)
        self.assertTrue(any(edge.kind == "task" and edge.producer_event == "run:3"
                            and edge.consumer_event == "run:6" for edge in graph.edges))
        self.assertTrue(any(edge.kind == "region_parent" and edge.producer_event == "run:5"
                            and edge.consumer_event == "run:7" for edge in graph.edges))
        paths = verified_retry_target_paths(trace, {
            "org.apache.zookeeper.server.quorum.Learner#registerWithLeader(I)J@518:branch:3"})
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["fault_event"], "run:2")
        self.assertEqual(paths[0]["target_check_event"], "run:8")

    def test_cross_epoch_claim_is_rejected_even_if_generic_graph_pairs_token(self):
        trace = list(valid_trace())
        trace[5] = {**trace[5], "epoch": 2}
        with self.assertRaisesRegex(ValueError, "lifecycle epoch"):
            verified_retry_edges(tuple(trace))

    def test_unscoped_claim_is_rejected(self):
        trace = list(valid_trace())
        trace[5] = {**trace[5], "occurrence": "unscoped:zk1:1:root"}
        with self.assertRaisesRegex(ValueError, "actor or lifecycle"):
            verified_retry_edges(tuple(trace))

    def test_duplicate_claim_is_rejected(self):
        trace = valid_trace() + (event(11, "TASK_CLAIM", NEW, site=SITE,
                                       correlation=TOKEN),)
        with self.assertRaisesRegex(ValueError, "unique"):
            verified_retry_edges(trace)

    def test_other_actor_target_cannot_be_joined_to_retry(self):
        trace = list(valid_trace())
        trace[7] = {**trace[7], "node": "zk2"}
        self.assertEqual(verified_retry_target_paths(tuple(trace), {trace[7]["site"]}), [])

    def test_target_before_claim_cannot_be_joined_to_retry(self):
        trace = list(valid_trace())
        trace[6] = {**trace[6], "seq": 5}
        self.assertEqual(verified_retry_target_paths(tuple(trace), {trace[7]["site"]}), [])

    def test_fault_outside_old_following_cannot_be_joined(self):
        trace = list(valid_trace())
        trace[1] = {**trace[1], "occurrence": "unscoped:zk1:1:root"}
        self.assertEqual(verified_retry_target_paths(tuple(trace), {trace[7]["site"]}), [])


if __name__ == "__main__":
    unittest.main()
