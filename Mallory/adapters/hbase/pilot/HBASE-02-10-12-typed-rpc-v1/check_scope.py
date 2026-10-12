#!/usr/bin/env python3
"""Offline proof that the current generic RPC door lacks a method-qualified identity."""

import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
DOOR = (
    "org.apache.hadoop.hbase.ipc.RpcServer#call"
    "(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
    "Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)"
    "Lorg/apache/hadoop/hbase/util/Pair;@447:door:1"
)


def main():
    probe = (ROOT / "Mallory/instrumentation/src/main/java/edu/uva/liftlab/"
             "mallory/instrumentation/Probe.java").read_text()
    hooks = (ROOT / "Mallory/adapters/hbase/src/main/java/edu/uva/liftlab/"
             "mallory/hbase/HBaseHooks.java").read_text()
    assert 'event("DOOR_OBSERVED", site, fields("hit", hit, "door_ordinal", doorOrdinal' in probe
    assert 'String port = methodName(rpcCall);' in hooks
    assert 'Probe.receiveScope("hbase-rpc", token, methodName(rpcCall)' in hooks

    result = []
    for number in ("02", "10", "12"):
        path = (ROOT / f"data/mallory/calibration_v2/HBASE-{number}/trials/r0000/"
                "events.jsonl.gz")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            events = [json.loads(line) for line in stream]
        receives = {e.get("context"): e for e in events
                    if e.get("type") == "RECV" and e.get("site") == "hbase:RpcServer.call"}
        doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
                 and e.get("site") == DOOR]
        assert doors
        assert all("port" not in e for e in doors)
        joined = [(d, receives[d["context"]]) for d in doors
                  if d.get("context") in receives]
        assert joined
        assert all(d["node"] == r["node"] and r.get("port") for d, r in joined)
        result.append({"case_id": f"HBASE-{number}", "generic_doors": len(doors),
                       "joined_receives": len(joined),
                       "door_has_port": False,
                       "request_ports": sorted({r["port"] for _, r in joined})})
    print(json.dumps({"status": "generic_door_not_request_scoped", "cases": result},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
