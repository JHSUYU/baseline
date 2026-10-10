#!/usr/bin/env python3
"""Offline proof-gate tests; no Hadoop JVM is started."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from validate_healthy import evaluate, HEARTBEAT_DOOR


HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "HDFS-20-response-scope-healthy-v1.json").read_text())
TARGET_SITE = CONFIG["target"]["check_sites"][0]
TARGET_REGION = TARGET_SITE.split("@", 1)[0]
TOKEN = "0123456789abcdef:7:0"
DN = "hdfs-cluster-1/dn1"
NN = "hdfs-cluster-1/nn0"


def row(seq: int, kind: str, node: str, thread: int, occurrence: str,
        site: str, **extra) -> dict:
    result = {"id": f"healthy:{seq}", "seq": seq, "type": kind,
              "node": node, "epoch": 0, "thread_id": thread,
              "occurrence": occurrence, "context": extra.pop("context", "root"),
              "site": site}
    result.update(extra)
    return result


def root(node: str, thread: int, context: str, segment: int = 1) -> str:
    return f"unscoped:{node}:0:{context}:thread:{thread}:segment:{segment}"


def healthy_events() -> list[dict]:
    region_occurrence = f"{DN}:0:{TARGET_REGION}:{TOKEN}:1"
    return [
        row(1, "DOOR_OBSERVED", DN, 20, root(DN, 20, "root"),
            HEARTBEAT_DOOR + "1"),
        row(2, "SEND", DN, 20, root(DN, 20, "root"),
            "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest",
            transport="hadoop-ipc", correlation=TOKEN, port="request"),
        row(3, "RECV", NN, 10, root(NN, 10, TOKEN),
            "org.apache.hadoop.ipc.Server.RpcCall#run", context=TOKEN,
            transport="hadoop-ipc", correlation=TOKEN, port="request"),
        row(4, "SEND", NN, 10, root(NN, 10, TOKEN),
            "org.apache.hadoop.ipc.Server.Connection#sendResponse", context=TOKEN,
            transport="hadoop-ipc", correlation=TOKEN, port="response"),
        row(5, "RECV", DN, 20, root(DN, 20, TOKEN),
            "org.apache.hadoop.ipc.Client#getRpcResponse", context=TOKEN,
            transport="hadoop-ipc", correlation=TOKEN, port="response"),
        row(6, "REGION_ENTER", DN, 20, region_occurrence, TARGET_REGION,
            context=TOKEN, region=TARGET_REGION, parent_id=TOKEN),
        row(7, "TARGET_CHECK", DN, 20, region_occurrence, TARGET_SITE,
            context=TOKEN, region=TARGET_REGION),
        row(8, "REGION_EXIT", DN, 20, region_occurrence, TARGET_REGION,
            context=TOKEN, region=TARGET_REGION),
    ]


class HealthyGateTest(unittest.TestCase):
    def test_exact_request_response_and_named_target_pass(self) -> None:
        proof = evaluate(tuple(healthy_events()), CONFIG)
        self.assertEqual(proof["status"], "pass", proof)
        self.assertEqual(proof["token"], TOKEN)
        self.assertEqual(proof["events"]["response_recv"]["seq"], 5)
        self.assertEqual(len(proof["event_time_path"]), 1)
        self.assertEqual(proof["event_time_path"][0]["kind"], "region_parent")

    def test_unknown_actor_and_post_target_response_fail(self) -> None:
        unknown = healthy_events()
        unknown[4]["node"] = "unknown"
        unknown[4]["occurrence"] = root("unknown", 20, TOKEN)
        self.assertEqual(evaluate(tuple(unknown), CONFIG)["status"], "fail")
        late = healthy_events()
        late[4]["seq"] = 9
        late[4]["id"] = "healthy:9"
        self.assertEqual(evaluate(tuple(late), CONFIG)["status"], "fail")

    def test_unmatched_or_ambiguous_rpc_response_fails(self) -> None:
        unmatched = healthy_events()
        unmatched[3]["correlation"] = "different-token"
        self.assertEqual(evaluate(tuple(unmatched), CONFIG)["status"], "fail")
        duplicate = healthy_events()
        extra = copy.deepcopy(duplicate[3])
        extra["id"] = "healthy:4b"
        duplicate.append(extra)
        self.assertEqual(evaluate(tuple(duplicate), CONFIG)["status"], "fail")

    def test_response_context_without_heartbeat_request_fails(self) -> None:
        events = healthy_events()
        events[0]["site"] = "unrelated I/O point"
        self.assertEqual(evaluate(tuple(events), CONFIG)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
