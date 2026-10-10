#!/usr/bin/env python3
"""Read-only HDFS-31 source, trace, and diagnostic receipt check; no JVM."""

import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
receipt = json.loads((HERE / "source-review.json").read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact(name):
    hits = [Path(row["path"]) for row in receipt["artifacts"]
            if Path(row["path"]).name == name]
    assert len(hits) == 1, (name, hits)
    return hits[0]


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    assert manifest["case_id"] == "HDFS-31" and manifest["status"] == "source_only_no_jvm_no_fault_admission"
    for name, expected in manifest["files"].items():
        assert sha(HERE / name) == expected
    assert receipt["case_id"] == "HDFS-31"
    assert receipt["status"] == "named_healthy_target_confirmed_typed_io_predicate_effect_gap"
    assert not receipt["fault_admitted"] and not receipt["full_admitted"]
    assert not receipt["jvm_started_by_this_audit"]
    for row in receipt["artifacts"]:
        path = Path(row["path"])
        assert path.is_file() and sha(path) == row["sha256"], path
    source = artifact("DataNode.java").read_text()
    manager = artifact("BlockPoolManager.java").read_text()
    actor = artifact("BPServiceActor.java").read_text()
    test = artifact("TestDiskError.java").read_text()
    method = test[test.index("void testDataTransferWhenBytesPerChecksumIsZero()"):]
    assert method.index("raFile.writeByte(0)") < method.index("raFile.writeInt(0)")
    assert method.index("raFile.writeInt(0)") < method.index("cluster.startDataNodes(")
    assert method.index("cluster.startDataNodes(") < method.index("dn0.transferBlock(block,")
    transfer = source[source.index("void transferBlock(ExtendedBlock block,"):]
    assert transfer.index("getBPOSForBlock(block)") < transfer.index("data.checkBlock(block")
    guard = source[source.index("private BPOfferService getBPOSForBlock("):]
    assert "blockPoolManager.get(block.getBlockPoolId())" in guard
    assert "if (bpos == null)" in guard
    assert "bpByBlockPoolId.put(bpos.getBlockPoolId(), bpos)" in manager
    assert "return bpByBlockPoolId.get(bpid)" in manager
    assert "bpByBlockPoolId.remove(t.getBlockPoolId())" in manager
    assert "blockPoolManager.remove(bpos)" in source
    catch = actor[actor.index("} catch (IOException e) {", actor.index("private void offerService()")):]
    assert "sleepAfterException();" in catch

    trial = artifact("events.jsonl.gz").parent
    result = json.loads((trial / "result.json").read_text())
    junit = result["junit_validation"]
    assert (junit["tests"], junit["failures"], junit["errors"]) == (1, 0, 0)
    with gzip.open(trial / "events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK"
              and "DataNode#getBPOSForBlock" in e.get("site", "")]
    assert [(e["seq"], e["node"], e["epoch"], e["outcome"]) for e in checks] == [
        (139, "hdfs-cluster-1/dn0", 0, "TAKEN")]
    assert not any(e.get("type") == "TARGET_THROW" and
                   "DataNode#getBPOSForBlock" in e.get("site", "") for e in events)
    doors = [e["seq"] for e in events if e.get("type") == "DOOR_OBSERVED"
             and "BPServiceActor#sendHeartBeat" in e.get("site", "")
             and e.get("node") == "hdfs-cluster-1/dn0"]
    assert doors == [20, 141]
    assert not any(e.get("type") in ("STATE_READ", "STATE_WRITE") for e in events)

    config = json.loads(artifact("HDFS-31-node2-map-healthy-v3.json").read_text())
    assert config["calibration_only"] and not config["auto_promote_if_healthy"]
    assert config["budget"]["trials"] == 1
    assert config["agent_properties"]["state.maps"] is True
    assert "org.apache.hadoop.hdfs.server.datanode.BlockPoolManager" in config["agent_include"]
    print("PASS: HDFS-31 named healthy target, pretarget heartbeat, source gap, and map diagnostic pins; no JVM")


if __name__ == "__main__":
    main()
