#!/usr/bin/env python3
"""Read-only preflight for a replayable HBASE-07 RPC fault identity.

This script deliberately does not create a fault plan or launch a JVM. It joins
the client request to the server call using the transported correlation token
already present in the trace, then checks that a semantic selector is unique.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

TARGET_REGION = "org.apache.hadoop.hbase.client.HBaseAdmin#restoreSnapshot(Ljava/lang/String;ZZ)V"
TARGET_CHECK = TARGET_REGION + "@2787:branch:2"
RPC_METHOD = "hbase.pb.MasterService.GetCompletedSnapshots"
SERVER_DOOR = (
    "org.apache.hadoop.hbase.ipc.RpcServer#call"
    "(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
    "Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)"
    "Lorg/apache/hadoop/hbase/util/Pair;@447:door:1"
)


def _read_events(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def inspect_events(events: list[dict]) -> dict:
    """Find the first GetCompletedSnapshots request inside each target invocation."""
    entries = [e for e in events if e.get("type") == "REGION_ENTER"
               and e.get("site") == TARGET_REGION and e.get("node") == "client"]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK"
              and e.get("site") == TARGET_CHECK and e.get("node") == "client"]
    cases = []
    for entry in entries:
        occurrence = entry["occurrence"]
        following = [e for e in checks if e.get("occurrence") == occurrence
                     and e["seq"] > entry["seq"]]
        if len(following) != 1:
            cases.append({"occurrence": occurrence,
                          "admissible": False,
                          "reason": "not_one_exact_target_check"})
            continue
        check = following[0]
        all_method_requests = [e for e in events if e.get("type") == "SEND"
                               and e.get("node") == "client"
                               and e.get("port") == RPC_METHOD]
        requests = [e for e in all_method_requests
                    if e.get("occurrence") == occurrence
                    and entry["seq"] < e["seq"] < check["seq"]]
        request_proofs = []
        for request in requests:
            token = request.get("correlation")
            receives = [e for e in events if e.get("type") == "RECV"
                        and e.get("node") == "master0"
                        and e.get("port") == RPC_METHOD
                        and e.get("correlation") == token
                        and request["seq"] < e["seq"] < check["seq"]]
            call_doors = []
            if len(receives) == 1:
                recv = receives[0]
                call_doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
                              and e.get("node") == "master0"
                              and e.get("site") == SERVER_DOOR
                              and e.get("context") == token
                              and e.get("thread_id") == recv.get("thread_id")
                              and recv["seq"] < e["seq"] < check["seq"]]
            request_proofs.append({
                "client_send_seq": request["seq"],
                "client_method_ordinal": 1 + sum(
                    e["seq"] < request["seq"] for e in all_method_requests),
                "server_recv_seqs": [e["seq"] for e in receives],
                "server_door_seqs": [e["seq"] for e in call_doors],
                "correlation": token,
                "unique_transport_handoff": len(receives) == 1 and len(call_doors) == 1,
            })
        cases.append({
            "occurrence": occurrence,
            "target_seq": check["seq"],
            "target_thread_id": check.get("thread_id"),
            "request_attempts_before_target": len(requests),
            "requests": request_proofs,
            "admissible": bool(request_proofs)
            and request_proofs[0]["unique_transport_handoff"]
            and all(p["unique_transport_handoff"] for p in request_proofs),
        })
    return {"target_invocations": cases,
            "all_first_attempts_unique": bool(cases)
            and all(c["admissible"] for c in cases)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runs = []
    for path in args.trace:
        data = path.read_bytes()
        runs.append({"trace": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                     **inspect_events(_read_events(path))})
    result = {"schema_version": 1, "selector": {
        "client_region": TARGET_REGION,
        "rpc_method": RPC_METHOD,
        "request_attempt": 1,
        "server_node": "master0",
        "server_door": SERVER_DOOR,
    }, "runs": runs,
        "all_runs_first_attempt_unique": all(r["all_first_attempts_unique"] for r in runs)}
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
