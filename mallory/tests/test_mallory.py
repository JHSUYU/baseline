"""Unit tests: the graph of a GraphChecker trace, fault points, plants and the Q-policy."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mallory import faults, graph, policy

CLIENT = "auto0/client0#epoch0"
MASTER = "auto0/master0#epoch0"
CALL = "<org.apache.hadoop.hbase.ipc.AbstractRpcClient: Call callMethod(Message)>"
FINISH = "<org.apache.hadoop.hbase.ipc.RpcConnection: void finishCall(Call)>"
CAS = "<org.apache.hadoop.hbase.backup.impl.BackupSystemTable: void startBackupExclusiveOperation()>"


def address(node: str, region: str, ctx: str, *frames: str) -> str:
    return f"{node}/region/{region}/ctx:{ctx}/idx:" + "/".join(f"{f}@0" for f in frames)


MAIN = "TEST-worker-1"
HANDLER = "RpcServer.handler=3"
NETTY = "RS-EventLoopGroup-1-2"


def trace_rows(fatal: bool = False, applied: bool = False) -> list[dict]:
    cas = address(CLIENT, "REGION.cas", "Root:CLIENT/test#1", CAS, CALL)
    reply = address(CLIENT, "REGION.finish", "Anchor:00aa@HBASE_RPC/test", FINISH)
    rows = [
        {"event": "METHOD_ENTER", "seq": 1, "method": CAS, "callId": 1, "sourceKey": CLIENT,
         "threadName": MAIN},
        {"event": "PLANT_MARKER", "seq": 2, "nanos": 200, "rootId": "FAULT:HBASE_RPC:REQUEST",
         "siteId": CALL + "#u60", "occurrences": ["c1"], "occurrenceAddress": cas,
         "threadName": MAIN},
        {"event": "EXCHANGE_SEND", "seq": 3, "transport": "HBASE_RPC", "correlationId": "r1",
         "attemptId": "1", "half": "REQUEST", "method": CALL, "sourceKey": CLIENT,
         "threadName": MAIN},
        {"event": "EXCHANGE_RECEIVE", "seq": 4, "transport": "HBASE_RPC", "correlationId": "r1",
         "attemptId": "1", "half": "REQUEST", "sourceKey": MASTER, "threadName": HANDLER},
        {"event": "STORE_WRITE", "seq": 5, "transport": "HBASE_ZK", "location": "/hbase/lock",
         "version": "3", "occurrenceAddress": address(MASTER, "REGION.m", "Root:WAKE/x#2", CAS),
         "threadName": HANDLER},
        {"event": "STORE_READ", "seq": 6, "transport": "HBASE_ZK", "location": "/hbase/lock",
         "version": "3", "op": "getData", "occurrenceAddress": cas, "threadName": MAIN},
        {"event": "PLANT_MARKER", "seq": 7, "nanos": 700, "rootId": "FAULT:HBASE_RPC:RESPONSE",
         "siteId": FINISH + "#u44", "occurrences": ["f1", "c1"], "occurrenceAddress": reply,
         "threadName": NETTY},
        {"event": "PLANT_MARKER", "seq": 8, "nanos": 800, "rootId": "FAULT:HBASE_RPC:RESPONSE",
         "siteId": FINISH + "#u44", "occurrences": ["f1", "c1"], "occurrenceAddress": reply,
         "threadName": NETTY},
        {"event": "BRANCH", "seq": 9, "callId": 1, "siteId": CAS + "#u24", "outcome": not fatal},
    ]
    if applied:
        rows.append({"event": "PLANT_APPLIED", "seq": 10, "row": 0,
                     "planted": "FAULT:HBASE_RPC:RESPONSE", "occurrenceAddress": reply})
    if fatal:
        rows.append({"event": "PLANT_FATAL", "seq": 11, "siteId": CAS + "#u24",
                     "occurrenceAddress": cas, "atAnchor": True})
    return rows


def write_trace(directory: Path, rows: list[dict]) -> Path:
    path = directory / "runtime_trace.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


class GraphTest(unittest.TestCase):
    def test_edges_join_timelines_messages_and_store_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = graph.build(write_trace(Path(tmp), trace_rows()))
        client, master = graph.timeline(CLIENT, MAIN), graph.timeline(MASTER, HANDLER)
        self.assertEqual(master, "auto0/master0#epoch0 | RpcServer.handler=N")
        send = (client, "send HBASE_RPC REQUEST AbstractRpcClient.callMethod")
        receive = (master, "receive HBASE_RPC REQUEST")
        write = (master, "write HBASE_ZK /hbase/lock")
        read = (client, "read getData /hbase/lock")
        enter = (client, "enter BackupSystemTable.startBackupExclusiveOperation")
        self.assertIn((send, receive), run.edges)              # message
        self.assertIn((write, read), run.edges)                # store version
        self.assertIn((enter, send), run.edges)                # program order
        self.assertFalse(run.fatal)
        self.assertEqual(len(run.markers), 3)

    def test_fatal_needs_the_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = graph.build(write_trace(Path(tmp), trace_rows(fatal=True, applied=True)))
        self.assertTrue(run.fatal)
        self.assertEqual(run.applied_rows, {0})
        # the planted fault sits on the timeline of the marker that planted it
        self.assertIn((graph.timeline(CLIENT, NETTY), "fault FAULT:HBASE_RPC:RESPONSE"),
                      [event for _, event in run.events])

    def test_context_keeps_the_exchange_and_the_call_path(self) -> None:
        reply = address(CLIENT, "REGION.finish", "Anchor:00aa@HBASE_RPC/test", FINISH)
        self.assertEqual(graph.context_of(reply), "Anchor:00aa ")
        request = address(CLIENT, "REGION.cas", "Root:CLIENT/test#1", CAS, CALL)
        self.assertEqual(graph.context_of(request),
                         "Root:CLIENT/test BackupSystemTable.startBackupExclusiveOperation")
        self.assertEqual(graph.region_of_address(request), "REGION.cas")
        self.assertEqual(graph.node_of_address(request), CLIENT)


class FaultTest(unittest.TestCase):
    def test_invocations_count_a_site_under_its_innermost_occurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = graph.build(write_trace(Path(tmp), trace_rows()))
        points = faults.points(run)
        self.assertEqual([(p.occurrence, p.invocation) for p in points],
                         [("c1", 1), ("f1", 1), ("f1", 2)])
        self.assertEqual(faults.points(run, after_nanos=700)[0].invocation, 2)
        self.assertEqual(points[1].action, "FAULT:HBASE_RPC:RESPONSE @ RpcConnection.finishCall#u44")

    def test_plant_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = graph.build(write_trace(Path(tmp), trace_rows()))
            point = faults.points(run)[1]
            target = {"kind": "TARGET", "occurrence": "t1", "siteId": CAS + "#u24", "value": False}
            planted, outside = faults.write_plant(Path(tmp) / "t1.plant.jsonl", (point,), [target])
            rows = [json.loads(line) for line in
                    (Path(tmp) / "t1.plant.jsonl").read_text().splitlines()]
            self.assertEqual((Path(tmp) / "t1.plant-outside.jsonl").read_text(), "")
        self.assertEqual((planted, outside), ([0], set()))
        self.assertEqual(rows[0], {"kind": "ROOT", "category": "FAULT", "rootId": point.root,
                                   "occurrence": "f1", "siteId": point.site, "invocation": 1,
                                   "value": "true", "row": 0})
        self.assertEqual(rows[1]["kind"], "TARGET")
        self.assertIs(rows[1]["value"], False)
        self.assertEqual(rows[1]["row"], 1)

    def test_door_evaluations_outside_the_window_are_fault_points_too(self) -> None:
        place = "before|" + CLIENT + "|RS-EventLoopGroup-N-N"
        outside_rows = [
            {"event": "OUTSIDE_MARKER", "nanos": 100, "rootId": "FAULT:HBASE_RPC:RESPONSE",
             "siteId": FINISH + "#u44", "place": place, "invocation": 1},
            {"event": "OUTSIDE_APPLIED", "nanos": 150, "rootId": "FAULT:HBASE_RPC:RESPONSE",
             "siteId": FINISH + "#u44", "place": place, "invocation": 2}]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "t1"
            run_dir.mkdir()
            trace = write_trace(run_dir, trace_rows())
            log = graph.outside_log(trace)
            self.assertEqual(log, Path(tmp) / "t1.outside.jsonl")
            log.write_text("".join(json.dumps(row) + "\n" for row in outside_rows))
            run = graph.build(trace, log)
            points = faults.points(run)
            plant = Path(tmp) / "t2.plant.jsonl"
            planted, outside = faults.write_plant(plant, (points[1], points[3]), [])
            outside_rows_written = [json.loads(line) for line in
                                    faults.outside_plant(plant).read_text().splitlines()]
        # one order across the window: the two outside evaluations came first
        self.assertEqual([p.outside for p in points], [True, True, False, False, False])
        self.assertEqual(points[0].occurrence, "outside:" + place)
        self.assertEqual((points[1].invocation, points[1].node), (2, CLIENT))
        self.assertEqual(run.outside_applied, {(FINISH + "#u44", place, 2)})
        self.assertEqual(faults.evaluated_at(run, (points[1], points[3])), 700)
        self.assertEqual([p.nanos for p in faults.points(run, after_nanos=150)], [200, 700, 800])
        self.assertEqual(planted, [0])
        self.assertEqual(outside, {(FINISH + "#u44", place, 2)})
        self.assertEqual(outside_rows_written,
                         [{"siteId": FINISH + "#u44", "place": place, "invocation": 2}])
        # an outside point and a window point of one site may share a plan
        self.assertTrue(faults.compatible((points[1],), points[3]))

    def test_one_occurrence_per_site_in_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = graph.build(write_trace(Path(tmp), trace_rows()))
        first, second, third = faults.points(run)
        self.assertTrue(faults.compatible((second,), third))     # same occurrence, next invocation
        self.assertFalse(faults.compatible((second,), second))   # the same point twice
        other = faults.FaultPoint(second.site, second.root, "c1", 1, second.node, second.line,
                                  "", "", 0)
        self.assertFalse(faults.compatible((second,), other))    # another occurrence of the site
        self.assertTrue(faults.compatible((first,), second))


class PolicyTest(unittest.TestCase):
    def test_untried_actions_are_optimistic_and_rewards_rank_the_tried(self) -> None:
        q = policy.QPolicy(epsilon=0.0)
        self.assertEqual(q.value("s", "a"), q.optimistic)
        q.update("s", "a", gained=0.0, next_state=None)
        q.update("s", "b", gained=1.0, next_state=None)
        self.assertLess(q.value("s", "a"), q.value("s", "b"))
        pick = q.choose(["a", "b", "c"], state_of=lambda c: "s", action_of=lambda c: c,
                        tried_count=lambda c: q.tries.get("s", {}).get(c, 0))
        self.assertEqual(pick, 2)                                # the untried action
        # among equally ranked candidates the draw, not their order, decides
        fresh = [policy.QPolicy(epsilon=0.0, seed=seed) for seed in range(20)]
        picks = {p.choose(["x", "y", "z"], state_of=lambda c: "s", action_of=lambda c: c,
                          tried_count=lambda c: 0) for p in fresh}
        self.assertEqual(picks, {0, 1, 2})
        self.assertGreater(policy.reward(10), policy.reward(1))
        self.assertLessEqual(policy.reward(1000), 1.0)
        self.assertEqual(policy.reward(0), 0.0)
        self.assertEqual(policy.reward(38, noise=38), 0.0)       # no more than two healthy runs differ
        self.assertAlmostEqual(policy.reward(48, noise=38), policy.reward(10))


if __name__ == "__main__":
    unittest.main()
