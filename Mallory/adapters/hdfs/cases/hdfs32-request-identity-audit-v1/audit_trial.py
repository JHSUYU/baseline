#!/usr/bin/env python3
"""Audit HDFS-32's concrete DFSAdmin request to DataNode target identity.

The trace does not contain the deleteBlockPool `force` argument.  A force
label is inferred only when both source-ordered DFSAdmin requests, target
checks, and responses are present in a complete passing JUnit run.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
TEST = ROOT / ("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/"
               "hadoop/hdfs/server/datanode/TestDeleteBlockPool.java")
TEST_SHA = "31467bca1249b93cae7ed984bac01d405cde8ec1409a9ef78fa0a0c469a3bb3a"
CHECK = ("org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool"
         "(Ljava/lang/String;Z)V@3819:branch:1")
THROW = ("org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool"
         "(Ljava/lang/String;Z)V@3822:throw:1")
DOOR = ("org.apache.hadoop.hdfs.tools.DFSAdmin#deleteBlockPool"
        "([Ljava/lang/String;I)I@2702:door:1")
DN = "hdfs-cluster-1/dn0"


def read_events(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def source_order_pinned() -> bool:
    if not TEST.is_file() or hashlib.sha256(TEST.read_bytes()).hexdigest() != TEST_SHA:
        return False
    source = TEST.read_text()
    start = source.index("public void testDfsAdminDeleteBlockPool()")
    method = source[start:]
    return (method.index('String[] args = { "-deleteBlockPool", dn1Address, bpid2 };')
            < method.index('String[] forceArgs = { "-deleteBlockPool", dn1Address, bpid2, "force" };'))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--healthy", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    trial = args.trial
    events = read_events(trial / "events.jsonl.gz")
    result = json.loads((trial / "result.json").read_text())
    indexed = {e.get("seq"): e for e in events if isinstance(e.get("seq"), int)}
    if len(indexed) != sum(isinstance(e.get("seq"), int) for e in events):
        raise SystemExit("duplicate event sequence number")
    if not source_order_pinned():
        raise SystemExit("Hadoop JUnit source changed; request order cannot be inferred")

    doors = sorted((e for e in events if e.get("type") == "DOOR_OBSERVED"
                    and e.get("site") == DOOR and e.get("node") == "hdfs-client"),
                   key=lambda e: e["seq"])
    sends = sorted((e for e in events if e.get("type") == "SEND"
                    and e.get("site") == "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest"
                    and e.get("node") == "hdfs-client" and e.get("port") == "request"),
                   key=lambda e: e["seq"])
    checks = sorted((e for e in events if e.get("type") == "TARGET_CHECK"
                     and e.get("site") == CHECK and e.get("node") == DN),
                    key=lambda e: e["seq"])
    throws = sorted((e for e in events if e.get("type") == "TARGET_THROW"
                     and e.get("site") == THROW and e.get("node") == DN),
                    key=lambda e: e["seq"])
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED"]
    pairs = []
    for door in doors:
        following = [s for s in sends if s["seq"] > door["seq"]]
        next_door = min((d["seq"] for d in doors if d["seq"] > door["seq"]), default=10**18)
        if not following or following[0]["seq"] >= next_door:
            pairs.append({"client_door_seq": door["seq"], "request_correlation": None,
                          "target_check_seq": None, "response": None})
            continue
        send = following[0]
        correlation = send.get("correlation")
        server_receives = [e for e in events if e.get("type") == "RECV"
                           and e.get("port") == "request" and e.get("node") == DN
                           and e.get("correlation") == correlation and e["seq"] > send["seq"]]
        recv = min(server_receives, key=lambda e: e["seq"]) if server_receives else None
        client_responses = [e for e in events if e.get("type") == "RECV"
                            and e.get("port") == "response" and e.get("node") == "hdfs-client"
                            and e.get("correlation") == correlation]
        response = min(client_responses, key=lambda e: e["seq"]) if client_responses else None
        target = next((e for e in checks if e.get("context") == correlation
                       and recv and e["seq"] > recv["seq"]
                       and (not response or e["seq"] < response["seq"])), None)
        related_throws = [e for e in throws if target and e.get("occurrence") == target.get("occurrence")
                          and e.get("epoch") == target.get("epoch") and e["seq"] > target["seq"]]
        pairs.append({"client_door_seq": door["seq"], "client_send_seq": send["seq"],
                      "request_correlation": correlation,
                      "server_recv_seq": recv["seq"] if recv else None,
                      "target_check_seq": target["seq"] if target else None,
                      "target_node": target.get("node") if target else None,
                      "target_epoch": target.get("epoch") if target else None,
                      "target_outcome": target.get("outcome") if target else None,
                      "target_throw_seq": related_throws[0]["seq"] if related_throws else None,
                      "response": response.get("site") if response else None})

    junit = result.get("junit_validation", result.get("junit", {}))
    # The unit-test source assigns the first request `force=false` and the
    # second `force=true`.  Do not use this binding after a missing request.
    paired = (len(pairs) == 2 and all(p["request_correlation"] and
                p["server_recv_seq"] and p["target_check_seq"] and p["response"]
                for p in pairs) and len({p["request_correlation"] for p in pairs}) == 2)
    source_binding = paired and junit.get("status") == "passed"
    if source_binding:
        pairs[0]["force_from_pinned_source_order"] = False
        pairs[1]["force_from_pinned_source_order"] = True
    receipt = {"case_id": "HDFS-32", "trial": str(trial),
               "source_sha256": TEST_SHA, "request_target_pairing_complete": paired,
               "force_binding_basis": "pinned source order plus complete paired passing requests" if source_binding else None,
               "request_pairs": pairs, "named_target_checks": len(checks),
               "named_target_throws": len(throws), "fault_applied_seqs": [e["seq"] for e in applied],
               "junit_status": junit.get("status", result.get("junit_status")),
               "junit_validation": junit,
               "interpretation": "A TARGET_THROW after an effective fault is a candidate; review the concrete request and source before claiming a new bug."}
    if args.healthy:
        if (not source_binding or len(checks) != 2 or throws or applied or
                pairs[0]["response"] != "org.apache.hadoop.ipc.Client#getRpcResponse.error" or
                pairs[1]["response"] != "org.apache.hadoop.ipc.Client#getRpcResponse" or
                receipt["junit_status"] != "passed"):
            raise SystemExit("healthy request/target identity gate failed")
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
