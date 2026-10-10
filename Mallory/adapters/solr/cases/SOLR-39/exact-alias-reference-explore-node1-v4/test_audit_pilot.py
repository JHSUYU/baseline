#!/usr/bin/env python3
"""Controls for strict postfault actor, owner and target matching."""

import unittest

from audit_pilot import TARGET, TARGET_REGION, TARGET_THROW_SITE, TARGET_EXCEPTION, audit_rows
from audit_identity import FIELD

DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
SITE = DOOR + "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1"
PROCESS_OCC = "node2:0:process:task:1:1"
REQUEST = "request:2"
TARGET_OCC = "node2:0:" + TARGET_REGION + ":request:2:1"


def fixture():
    plan = {"fault_id": "f1", "point": {"site": SITE, "node": "node2", "epoch": 0,
                                         "door_ordinal": 1}, "fault_type": "EXCEPTION",
            "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException"}
    common = dict(node="node2", epoch=0)
    events = [
        dict(type="STATE_READ", id="e1", seq=1, ts=5, thread_id=11, context="task:1",
             occurrence=PROCESS_OCC, site=DOOR +
             "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:field:3",
             key="org.apache.solr.common.cloud.ZkStateReader$AliasesManager#this$0",
             object="o7", **common),
        dict(type="DOOR_OBSERVED", id="e2", seq=2, ts=10, thread_id=11,
             context="task:1", occurrence=PROCESS_OCC, site=SITE, door_ordinal=1, **common),
        dict(type="FAULT_MATCHED", id="e3", seq=3, ts=11, thread_id=11,
             context="task:1", occurrence=PROCESS_OCC, site=SITE,
             door_ordinal=1, fault_id="f1", fault_type="EXCEPTION",
             exception_class="org.apache.zookeeper.KeeperException$ConnectionLossException", **common),
        dict(type="FAULT_APPLIED", id="e4", seq=4, ts=12, thread_id=11,
             context="task:1", occurrence=PROCESS_OCC, site=SITE,
             door_ordinal=1, fault_id="f1", fault_type="EXCEPTION",
             exception_class="org.apache.zookeeper.KeeperException$ConnectionLossException", **common),
        dict(type="STATE_READ", id="e5", seq=5, ts=21, thread_id=22, context=REQUEST,
             occurrence="node2:0:getAliases:request:2:1", object="o7", key=FIELD,
             site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
                  "#getAliases()Lorg/apache/solr/common/cloud/Aliases;@2223:field:1", **common),
        dict(type="REGION_ENTER", id="e6", seq=6, ts=30, thread_id=22, context=REQUEST,
             occurrence=TARGET_OCC, site=TARGET_REGION, **common),
        dict(type="STATE_READ", id="e7", seq=7, ts=41, thread_id=22, context=REQUEST,
             occurrence="node2:0:getAliases:request:2:2", object="o7", key=FIELD,
             site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
                  "#getAliases()Lorg/apache/solr/common/cloud/Aliases;@2223:field:1", **common),
        dict(type="TARGET_CHECK", id="e8", seq=8, ts=50, thread_id=22, context=REQUEST,
             occurrence=TARGET_OCC, site=TARGET, branch=TARGET, **common),
    ]
    events.append(dict(type="STATE_WRITE", id="e0", seq=0, ts=1, thread_id=33,
                       context="task:publication", occurrence="node2:0:setIfNewer:task:publication:1",
                       object="o7", key=FIELD,
                       site="org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
                            "#setIfNewer(Lorg/apache/solr/common/cloud/Aliases;)Z@2342:field:4", **common))
    markers = [
        dict(kind="read", node="node2", epoch=0, thread_id=22, ts_ns=20,
             context="node2:0:getAliases:request:2:1", owner_ref=7,
             aliases_ref=9, zk_version=3),
        dict(kind="read", node="node2", epoch=0, thread_id=22, ts_ns=40,
             context="node2:0:getAliases:request:2:2", owner_ref=7,
             aliases_ref=9, zk_version=3),
    ]
    markers.append(dict(kind="write", node="node2", epoch=0, thread_id=33, ts_ns=0,
                        context="node2:0:setIfNewer:task:publication:1", owner_ref=7,
                        aliases_ref=9, zk_version=3))
    result = {"site_catalog_validation": {"valid": True},
              "feedback": {"all_faults_effective": True,
                           "fault_identity_valid": True,
                           "target_exception_candidate": False}}
    return events, markers, result, plan


class StrictPilotAuditTest(unittest.TestCase):
    def test_exact_postfault_target_and_manager(self):
        result = audit_rows(*fixture())
        self.assertTrue(result["strict_fault_effective"])
        self.assertTrue(result["target_retained_same_manager"])
        self.assertEqual(result["qualification"],
                         "outside_closure_target_retained_exact_prepublication_reference")
        self.assertFalse(result["new_bug_confirmed"])

    def test_forged_fault_id_without_actual_application_rejected(self):
        events, markers, result, plan = fixture()
        events.pop(3)
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "fault_unmatched_or_identity_invalid")

    def test_wrong_physical_actor_rejected(self):
        events, markers, result, plan = fixture()
        events[3]["node"] = "node3"
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "fault_unmatched_or_identity_invalid")

    def test_different_manager_rejected(self):
        events, markers, result, plan = fixture()
        events[0]["object"] = "o8"
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "same_manager_prepublication_missing")

    def test_pretarget_check_rejected(self):
        events, markers, result, plan = fixture()
        next(row for row in events if row["type"] == "TARGET_CHECK")["ts"] = 9
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "target_lost_or_manager_path_unqualified")

    def test_missing_constructor_read_rejected(self):
        events, markers, result, plan = fixture()
        events.pop(4)
        markers.pop(0)
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "target_lost_or_manager_path_unqualified")

    def test_missing_prepublication_rejected(self):
        events, markers, result, plan = fixture()
        events.pop()
        markers.pop()
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "same_manager_prepublication_missing")

    def test_different_prepublished_reference_rejected(self):
        events, markers, result, plan = fixture()
        markers[-1]["aliases_ref"] = 10
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "target_lost_or_manager_path_unqualified")

    def test_exact_target_exception_remains_candidate(self):
        events, markers, result, plan = fixture()
        result["feedback"]["target_exception_candidate"] = True
        events.append(dict(type="TARGET_THROW", seq=9, ts=51, node="node2", epoch=0,
                           thread_id=22, context=REQUEST, occurrence=TARGET_OCC,
                           site=TARGET_THROW_SITE, exception_class=TARGET_EXCEPTION))
        observed = audit_rows(events, markers, result, plan)
        self.assertEqual(observed["qualification"],
                         "exact_target_exception_candidate_for_source_review")
        self.assertTrue(observed["target_exception_candidate"])
        self.assertFalse(observed["new_bug_confirmed"])

    def test_other_request_target_exception_is_not_candidate(self):
        events, markers, result, plan = fixture()
        result["feedback"]["target_exception_candidate"] = True
        events.append(dict(type="TARGET_THROW", seq=9, ts=51, node="node2", epoch=0,
                           thread_id=23, context="request:3", occurrence="request:3:target",
                           site=TARGET_THROW_SITE, exception_class=TARGET_EXCEPTION))
        observed = audit_rows(events, markers, result, plan)
        self.assertFalse(observed["target_exception_candidate"])

    def test_wrong_exception_class_is_not_effective(self):
        events, markers, result, plan = fixture()
        events[3]["exception_class"] = "java.io.IOException"
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "fault_unmatched_or_identity_invalid")

    def test_loaded_target_identity_required(self):
        events, markers, result, plan = fixture()
        result["site_catalog_validation"]["valid"] = False
        self.assertEqual(audit_rows(events, markers, result, plan)["qualification"],
                         "target_class_binding_invalid")


if __name__ == "__main__":
    unittest.main()
