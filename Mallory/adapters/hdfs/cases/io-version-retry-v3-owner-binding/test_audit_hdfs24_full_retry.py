#!/usr/bin/env python3
"""Regression tests for the HDFS-24 terminal event-time witness gate."""

from __future__ import annotations

import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from audit_hdfs24_full_retry import (EvidenceError, audit_campaign,
                                     witness_for_fault)
from verify_hdfs24_retry_v3 import CHECK, DOOR


class RetryWitnessTest(unittest.TestCase):
    def setUp(self):
        self.token = "test-run:17:0"
        self.dn = "hdfs-cluster-2/dn0"
        self.nn = "hdfs-cluster-2/nn0"
        self.dn_root = f"unscoped:{self.dn}:0:root:thread:566:segment:1"
        self.nn_rpc = f"unscoped:{self.nn}:0:{self.token}:thread:528:segment:2"
        self.dn_rpc = f"unscoped:{self.dn}:0:{self.token}:thread:566:segment:2"
        self.region = f"{self.dn}:0:BlockPoolSliceStorage#doTransition:{self.token}:1"
        self.point = {"site": DOOR, "node": self.dn, "epoch": 0,
                      "door_ordinal": 1}
        self.fault = {"fault_id": "fault1", "point": self.point,
                      "exception_class": "java.io.IOException"}
        self.events = [
            self.event(1, "DOOR_OBSERVED", self.dn, 566, self.dn_root,
                       site=DOOR, door_ordinal=1, exception_class="java.io.IOException"),
            self.event(2, "FAULT_MATCHED", self.dn, 566, self.dn_root,
                       site=DOOR, door_ordinal=1, fault_id="fault1",
                       exception_class="java.io.IOException"),
            self.event(3, "FAULT_APPLIED", self.dn, 566, self.dn_root,
                       site=DOOR, door_ordinal=1, fault_id="fault1",
                       exception_class="java.io.IOException"),
            self.event(4, "DOOR_OBSERVED", self.dn, 566, self.dn_root,
                       site=DOOR, door_ordinal=2, exception_class="java.io.IOException"),
            self.event(5, "SEND", self.dn, 566, self.dn_root,
                       site="org.apache.hadoop.ipc.Client.Connection#sendRpcRequest",
                       transport="hadoop-ipc", correlation=self.token, port="request"),
            self.event(6, "RECV", self.nn, 528, self.nn_rpc,
                       transport="hadoop-ipc", correlation=self.token, port="request",
                       context=self.token),
            self.event(7, "SEND", self.nn, 528, self.nn_rpc,
                       transport="hadoop-ipc", correlation=self.token, port="response",
                       context=self.token),
            self.event(8, "RECV", self.dn, 566, self.dn_rpc,
                       transport="hadoop-ipc", correlation=self.token, port="response",
                       context=self.token),
            self.event(9, "REGION_ENTER", self.dn, 566, self.region,
                       site="org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage#doTransition",
                       parent_id=self.token, context=self.token),
            self.event(10, "TARGET_CHECK", self.dn, 566, self.region,
                       site=CHECK, context=self.token),
        ]

    @staticmethod
    def event(seq, typ, node, thread, occurrence, **extra):
        return {"id": f"test:{seq}", "seq": seq, "type": typ,
                "node": node, "epoch": 0, "thread_id": thread,
                "occurrence": occurrence, "context": "root", **extra}

    def verdict(self, events=None):
        return witness_for_fault(events or self.events, self.fault)

    def test_exact_path_is_witnessed(self):
        classification, path = self.verdict()
        self.assertEqual(classification, "strict_event_time_retry_rpc_target")
        self.assertEqual(path["event_seqs"]["target_check"], 10)
        self.assertEqual(path["intervening_applied_fault_ids"], [])

    def test_duplicate_rpc_token_is_rejected(self):
        events = copy.deepcopy(self.events)
        duplicate = copy.deepcopy(events[6])
        duplicate.update(id="test:11", seq=11)
        events.append(duplicate)
        self.assertIsNone(self.verdict(events)[1])

    def test_different_dn_thread_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[7]["thread_id"] = 999
        self.assertIsNone(self.verdict(events)[1])

    def test_wrong_parent_token_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[8]["parent_id"] = "unrelated-token"
        self.assertIsNone(self.verdict(events)[1])

    def test_wrong_event_order_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[6]["seq"] = 4
        self.assertIsNone(self.verdict(events)[1])

    def test_unscoped_numeric_thread_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[4]["occurrence"] = "root"
        self.assertIsNone(self.verdict(events)[1])

    def test_no_retry_is_negative(self):
        events = [e for e in self.events if e["seq"] != 4]
        self.assertEqual(self.verdict(events)[0], "no_same_thread_retry")

    def test_pilot_and_archive_tamper(self):
        pilot = (Path(__file__).resolve().parents[5] /
                 "data/mallory/pilots/HDFS-24-v3-exact-retry")
        if not pilot.exists():
            self.skipTest("raw pilot evidence unavailable")
        self.assertEqual(audit_campaign(pilot)["strict_witness_trials"], 2)
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / "campaign"
            shutil.copytree(pilot, copied)
            with (copied / "trials/r0001/plan.json").open("ab") as out:
                out.write(b" ")
            with self.assertRaisesRegex(EvidenceError, "archive manifest mismatch"):
                audit_campaign(copied)


if __name__ == "__main__":
    unittest.main()
