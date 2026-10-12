"""Fail-closed replay and event-time tests for a transported HBase RPC token."""

from __future__ import annotations

import unittest

from Mallory.core.audit import _audit_faults
from Mallory.core.events import Trace
from Mallory.core.feedback import analyze
from Mallory.core.scheduler import _replay_point


BASE = ("org.apache.hadoop.hbase.ipc.RpcServer#call"
        "(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
        "Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)"
        "Lorg/apache/hadoop/hbase/util/Pair;@447:door:1"
        ":rpc:hbase.pb.ClientService.Get:request:")
SITE = BASE + "120"
PORT = "hbase.pb.ClientService.Get"
TOKEN = "trial-r0001:task:120"
CHECK = "ConnectionImplementation#relocateRegion@910:branch:2"
TARGET = {"check_sites": [CHECK], "throw_site": "target:throw:1",
          "exception_class": "org.apache.hadoop.hbase.TableNotEnabledException",
          "node": "client"}
PLAN = [{"fault_id": "f1", "point": {"site": SITE},
         "fault_type": "IO_EXCEPTION", "exception_class": "java.io.IOException"}]


def row(seq, kind, node, occurrence, *, site="", context=TOKEN, thread=8, **fields):
    return {"seq": seq, "id": f"trial-r0001:{seq}", "type": kind, "site": site,
            "node": node, "epoch": 0, "occurrence": occurrence,
            "context": context, "thread_id": thread, **fields}


def trace(*, node="rs0", fault=True, duplicate=False, wrong_port=False,
          wrong_context=False, unscoped=False, missing_exit=False,
          target_before_response=False):
    server_root = f"unscoped:{node}:0:{TOKEN}:thread:8:segment:1"
    region = (server_root if unscoped else
              f"{node}:0:{SITE}:region:{TOKEN}:1")
    received_context = "trial-r0001:task:121" if wrong_context else TOKEN
    events = [
        row(1, "SEND", "client", "client:0:root:1", site="client:send", thread=1,
            context="root", transport="hbase-rpc", correlation=TOKEN, port=PORT),
        row(2, "RECV", node, server_root, site="hbase:RpcServer.call",
            context=received_context, transport="hbase-rpc",
            correlation=received_context,
            port="hbase.pb.ClientService.Scan" if wrong_port else PORT),
        row(3, "REGION_ENTER", node, region, site=SITE + ":region",
            parent_id=TOKEN),
        row(4, "DOOR_OBSERVED", node, region, site=SITE, door_ordinal=7,
            hit=1, fault_type="IO_EXCEPTION", exception_class="java.io.IOException"),
    ]
    if duplicate:
        events.append(row(5, "DOOR_OBSERVED", node, region, site=SITE,
                          door_ordinal=8, hit=2, fault_type="IO_EXCEPTION",
                          exception_class="java.io.IOException"))
    if fault:
        events.extend([row(6, "FAULT_MATCHED", node, region, site=SITE,
                           fault_id="f1", door_ordinal=7, hit=1),
                       row(7, "FAULT_APPLIED", node, region, site=SITE,
                           fault_id="f1", door_ordinal=7, hit=1)])
    if target_before_response:
        events.append(row(8, "TARGET_CHECK", "client", "client:0:target:1",
                          site=CHECK, thread=1))
    events.extend([
        row(9, "SEND", node, region, site="hbase:RpcServer.call:completion",
            transport="hbase-rpc-response", correlation=TOKEN, port=PORT),
        row(11, "RECV", "client", "unscoped:client:0:" + TOKEN +
            ":thread:1:segment:2", site="hbase:RpcConnection.readResponse",
            thread=1, transport="hbase-rpc-response", correlation=TOKEN, port=PORT),
        row(12, "REGION_ENTER", "client", "client:0:target:1",
            site="client:target", thread=1, parent_id=TOKEN),
        row(13, "TARGET_CHECK", "client", "client:0:target:1", site=CHECK,
            thread=1),
    ])
    if not missing_exit:
        events.append(row(10, "REGION_EXIT", node, region, site=SITE + ":region"))
    events.sort(key=lambda event: event["seq"])
    return Trace(tuple(events))


def feedback(events, fault=True, mode="qualified_request_site"):
    return analyze(events, TARGET, PLAN if fault else [], return_code=0,
                   timed_out=False, reject_coarse_roots=True,
                   require_event_time_paths=True, replay_identity_mode=mode,
                   replay_identity_site_prefixes=[BASE])


class QualifiedRequestReplayTest(unittest.TestCase):
    def test_named_rs_migration_keeps_site_and_exact_path(self):
        for node in ("rs0", "rs1"):
            healthy = feedback(trace(node=node, fault=False), fault=False)
            doors = [door for door in healthy["doors"] if door["site"] == SITE]
            self.assertEqual(1, len(doors))
            self.assertTrue(doors[0]["in_closure"])
            self.assertEqual({"site": SITE}, _replay_point(doors[0], {
                "replay_identity_mode": "qualified_request_site",
                "replay_identity_site_prefixes": [BASE]}))
            faulted = trace(node=node)
            result = feedback(faulted)
            self.assertTrue(result["all_faults_effective"])
            self.assertTrue(result["target_reached"])
            self.assertEqual(1, len(result["qualified_request_followups"]))
            receipt = _audit_faults(faulted.events, PLAN,
                                    "qualified_request_site", [BASE])[0]
            self.assertTrue(receipt["applied_identity_valid"])
            self.assertEqual(1, receipt["observed_door_matches"])

    def test_collision_or_wrong_request_fails_closed(self):
        for variant in ({"duplicate": True}, {"wrong_port": True},
                        {"wrong_context": True}, {"unscoped": True},
                        {"missing_exit": True}):
            faulted = trace(**variant)
            result = feedback(faulted)
            self.assertFalse(result["all_faults_effective"], variant)
            self.assertFalse(_audit_faults(faulted.events, PLAN,
                              "qualified_request_site", [BASE])[0]
                             ["applied_identity_valid"], variant)

    def test_legacy_ordinal_mode_does_not_use_site_only_replay(self):
        legacy = feedback(trace(fault=False), fault=False, mode="door_ordinal")
        door = next(door for door in legacy["doors"] if door["site"] == SITE)
        self.assertEqual({"site", "node", "epoch", "door_ordinal"},
                         set(_replay_point(door, {"replay_identity_mode":
                                                 "door_ordinal"})))
        self.assertFalse(_audit_faults(trace().events, PLAN, "door_ordinal")[0]
                         ["exact_point"])


if __name__ == "__main__":
    unittest.main()
