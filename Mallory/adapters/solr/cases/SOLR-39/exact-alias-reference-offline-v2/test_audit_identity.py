#!/usr/bin/env python3
"""Small synthetic controls for the case-local identity join and path rule."""

import copy
import unittest

from audit_identity import FIELD, TARGET, audit_rows

TASK = "run:task:1"
REQUEST = "run:request:2"


def fixture():
    markers = [
        dict(kind="write", node="node2", epoch=0, thread_id=11, ts_ns=20,
             context="node2:0:setIfNewer:" + TASK + ":1", owner_ref=7,
             aliases_ref=9, zk_version=3),
        dict(kind="read", node="node2", epoch=0, thread_id=22, ts_ns=40,
             context="node2:0:getAliases:" + REQUEST + ":1", owner_ref=7,
             aliases_ref=9, zk_version=3),
        dict(kind="read", node="node2", epoch=0, thread_id=22, ts_ns=60,
             context="node2:0:getAliases:" + REQUEST + ":2", owner_ref=7,
             aliases_ref=9, zk_version=3),
    ]
    events = [
        dict(type="DOOR_OBSERVED", id="e1", seq=1, node="node2", epoch=0,
             thread_id=11, context=TASK, ts=10,
             site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
                  "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1"),
        dict(type="STATE_WRITE", id="e2", seq=2, node="node2", epoch=0,
             thread_id=11, context=TASK, occurrence=markers[0]["context"], ts=21,
             site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
                  "#setIfNewer(Lorg/apache/solr/common/cloud/Aliases;)Z@2342:field:4",
             key=FIELD, object="o7"),
        dict(type="STATE_READ", id="e3", seq=3, node="node2", epoch=0,
             thread_id=22, context=REQUEST, occurrence=markers[1]["context"], ts=41,
             site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
                  "#getAliases()Lorg/apache/solr/common/cloud/Aliases;@2223:field:1",
             key=FIELD, object="o7"),
        dict(type="STATE_READ", id="e4", seq=4, node="node2", epoch=0,
             thread_id=22, context=REQUEST, occurrence=markers[2]["context"], ts=61,
             site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
                  "#getAliases()Lorg/apache/solr/common/cloud/Aliases;@2223:field:1",
             key=FIELD, object="o7"),
        dict(type="TARGET_CHECK", id="e5", seq=5, node="node2", epoch=0,
             thread_id=22, context=REQUEST, ts=70, branch=TARGET),
    ]
    return events, markers


class ExactAliasReferenceTest(unittest.TestCase):
    def test_exact_path(self):
        events, markers = fixture()
        result = audit_rows(events, markers)
        self.assertEqual(result["paired_field_events"], 3)
        self.assertEqual(len(result["candidate_paths"]), 1)
        self.assertEqual(result["candidate_paths"][0]["watcher_door_seq"], 1)

    def test_wrong_occurrence_does_not_pair(self):
        events, markers = fixture()
        markers[1]["context"] += ":wrong"
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_different_alias_reference_does_not_link(self):
        events, markers = fixture()
        markers[2]["aliases_ref"] = 100
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_different_zk_version_does_not_link(self):
        events, markers = fixture()
        markers[2]["zk_version"] = 4
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_field_event_before_marker_does_not_pair(self):
        events, markers = fixture()
        events[2]["ts"] = 39
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_different_actor_does_not_link(self):
        events, markers = fixture()
        events[-1]["node"] = "node3"
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_different_request_context_does_not_link(self):
        events, markers = fixture()
        events[-1]["context"] = "different:request"
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_different_watcher_task_does_not_parent_write(self):
        events, markers = fixture()
        events[0]["context"] = "unrelated:task"
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_intervening_publication_breaks_path(self):
        events, markers = fixture()
        marker = copy.deepcopy(markers[0])
        marker.update(ts_ns=50, context="node2:0:setIfNewer:run:task:3:1",
                      aliases_ref=10, zk_version=4)
        event = copy.deepcopy(events[1])
        event.update(id="e6", seq=6, ts=51, context="run:task:3",
                     occurrence=marker["context"])
        events.append(event)
        markers.append(marker)
        self.assertEqual(audit_rows(events, markers)["candidate_paths"], [])

    def test_core_owner_identity_collision_is_rejected(self):
        events, markers = fixture()
        events[2]["object"] = "different-owner"
        with self.assertRaisesRegex(ValueError, "identity collision"):
            audit_rows(events, markers)


if __name__ == "__main__":
    unittest.main()
