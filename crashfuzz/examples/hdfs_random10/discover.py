"""Run one healthy HDFS trial with all ten selected methods instrumented."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from adhoc_crashfuzz.campaign import Campaign, Settings  # noqa: E402
from adhoc_crashfuzz.graph import read_events  # noqa: E402
from adhoc_crashfuzz.model import FaultSequence  # noqa: E402


TRANSPORT_METHODS = {
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient#newSocketSend",
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient#socketSend",
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient#peerSend",
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer#receive",
    "org/apache/hadoop/hdfs/server/datanode/DataXceiver#run",
    "org/apache/hadoop/ipc/Client$Connection#sendRpcRequest",
    "org/apache/hadoop/ipc/Client$Connection#receiveRpcResponse",
    "org/apache/hadoop/ipc/Client$Call#setRpcResponse",
    "org/apache/hadoop/ipc/Client#getRpcResponse",
    "org/apache/hadoop/ipc/Server$Connection#processRpcRequest",
    "org/apache/hadoop/ipc/Server$Responder#doRespond",
    "org/apache/hadoop/ipc/Server$RpcCall#run",
}


def main() -> None:
    os.environ["ADHOCFUZZ_ENABLE_ASSERTIONS"] = "1"
    os.environ["ADHOCFUZZ_HDFS_SITE_EXTRAS"] = json.dumps({
        "dfs.namenode.acls.enabled": "true",
        "dfs.namenode.path.based.cache.refresh.interval.ms": 1000,
    })
    selection = json.loads((HERE / "selected10.json").read_text())
    methods = {row["agent_method"].split("(", 1)[0]
               for row in selection["sites"]} | TRANSPORT_METHODS
    classes = {method.split("#", 1)[0] for method in methods}
    config = HERE / "agent-discovery.properties"
    config.write_text("\n".join([
        "include.classes=" + ",".join(sorted(classes)),
        "method.rules=" + ",".join(sorted(methods)),
        "point.entries=", "trace.fields=false", "trace.branches=false",
        "target.guard=", "target.throw=", "adapter.hdfs.datatransfer=true",
        "adapter.hadoop.rpc=true", "",
    ]))
    os.environ["ADHOCFUZZ_AGENT_PROPERTIES"] = str(config)
    base = Settings.from_file(HERE / "campaign.json")
    output = HERE / "out_discovery_extended"
    trial = Campaign(replace(base, output_dir=output))._trial(
        FaultSequence(), "discovery")
    events = read_events(output / "runs" / trial.run_id / "traces")
    entered = {event.site for event in events if event.kind == "METHOD_ENTER"}
    throws = {event.site for event in events if event.kind == "THROW"}
    rows = []
    for row in selection["sites"]:
        rows.append({
            "draw": row["draw"], "site_id": row["site_id"],
            "agent_method": row["agent_method"],
            "method_entered": row["agent_method"] in entered,
            "source_line_throw_observed": row["target_throw"] in throws,
        })
    report = {"run_id": trial.run_id,
              "workload_returncode": trial.workload.returncode,
              "checker_returncode": None if trial.checker is None
              else trial.checker.returncode,
              "rows": rows}
    (output / "coverage.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
