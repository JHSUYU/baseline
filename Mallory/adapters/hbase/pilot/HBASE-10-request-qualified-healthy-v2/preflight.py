#!/usr/bin/env python3
"""Read-only HBASE-10 admission check using source, bytecode, and archived trace."""

import gzip
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from Mallory.core.campaign import validate_config  # noqa: E402

HERE = Path(__file__).resolve().parent
CASE = "HBASE-10"
PORT = "hbase.pb.MasterService.UnassignRegion"
NODE = "master0"
GENERIC_DOOR = (
    "org.apache.hadoop.hbase.ipc.RpcServer#call"
    "(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
    "Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)"
    "Lorg/apache/hadoop/hbase/util/Pair;@447:door:1"
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    config_path = HERE / "HBASE-10.healthy.json"
    config = json.loads(config_path.read_text())
    validate_config(config)
    assert config["calibration_only"] and config["budget"]["trials"] == 1
    assert config["agent_properties"]["auto.io.doors"] is False
    assert config["mapping"]["request_qualified_rpc_port"] == PORT
    assert config["mapping"]["request_qualified_node"] == NODE
    assert config["mapping"]["fault_admission_blocked"]
    site = json.loads(Path(config["site_file"]).read_text())
    assert site["doors"] == []
    for artifact in config["runtime_artifacts"]:
        assert sha(artifact["path"]) == artifact["sha256"]

    source = Path(config["mapping"]["source_root"])
    paths = {
        "target": source / config["target"]["source_path"],
        "test": source / "hbase-server/src/test/java/org/apache/hadoop/hbase/"
                         "regionserver/TestRegionMove.java",
        "handler": source / "hbase-server/src/main/java/org/apache/hadoop/hbase/"
                            "master/MasterRpcServices.java",
        "rpc": source / "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc/"
                        "RpcServer.java",
        "client": source / "hbase-client/src/main/java/org/apache/hadoop/hbase/"
                           "client/HBaseAdmin.java",
    }
    snippets = {
        "target": "if (regionNode.getProcedure() != null)",
        "test": "admin.unassign(regionToMove.getRegionName(), true);",
        "handler": "master.getAssignmentManager().unassign(hri);",
        "rpc": "call.getService().callBlockingMethod(md, controller, param)",
        "client": "return caller.callWithRetries(callable, operationTimeout);",
    }
    for name, path in paths.items():
        assert snippets[name] in path.read_text(), name

    jar = Path(config["mapping"]["compiled_jar"])
    with ZipFile(jar) as archive:
        target = archive.read("org/apache/hadoop/hbase/master/assignment/AssignmentManager.class")
    assert hashlib.sha256(target).hexdigest() == config["expected_target_class_sha256"]

    old = ROOT / "data/mallory/calibration_v2/HBASE-10/trials/r0000"
    historical = json.loads((old / "result.json").read_text())
    assert historical["junit_validation"]["status"] == "passed"
    events = [json.loads(line) for line in gzip.open(old / "events.jsonl.gz", "rt")]
    receives = [event for event in events if event.get("type") == "RECV"
                and event.get("port") == PORT and event.get("node") == NODE]
    assert len(receives) == 1
    receive = receives[0]
    context = receive["context"]
    door = [event for event in events if event.get("type") == "DOOR_OBSERVED"
            and event.get("site") == GENERIC_DOOR and event.get("node") == NODE
            and event.get("context") == context]
    checks = [event for event in events if event.get("type") == "TARGET_CHECK"
              and event.get("site") in config["target"]["check_sites"]
              and event.get("node") == NODE and event.get("context") == context]
    throws = [event for event in events if event.get("type") == "TARGET_THROW"
              and event.get("site") == config["target"]["throw_site"]]
    assert len(door) == len(checks) == 1 and not throws
    assert receive["seq"] < door[0]["seq"] < checks[0]["seq"]
    print(json.dumps({"status": "source_bytecode_trace_preflight_passed",
                      "case_id": CASE, "config_sha256": sha(config_path),
                      "source_sha256": {name: sha(path) for name, path in paths.items()},
                      "historical_events_sha256": sha(old / "events.jsonl.gz"),
                      "historical_junit": "passed", "named_actor": NODE,
                      "rpc_port": PORT, "context": context,
                      "event_order": [receive["seq"], door[0]["seq"], checks[0]["seq"]],
                      "exact_target_throw_count": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
