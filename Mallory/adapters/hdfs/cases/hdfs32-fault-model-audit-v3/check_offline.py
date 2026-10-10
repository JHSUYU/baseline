#!/usr/bin/env python3
"""Read-only HDFS-32 source, request, and target receipt check; no JVM."""

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
    assert manifest["case_id"] == "HDFS-32" and manifest["status"] == "source_only_no_jvm_no_fault_admission"
    for name, expected in manifest["files"].items():
        assert sha(HERE / name) == expected
    assert receipt["case_id"] == "HDFS-32"
    assert receipt["status"] == "named_healthy_target_confirmed_no_suitable_current_typed_io_fault_model"
    assert not receipt["fault_admitted"] and not receipt["full_admitted"]
    assert not receipt["jvm_started_by_this_audit"]
    for row in receipt["artifacts"]:
        path = Path(row["path"])
        assert path.is_file() and sha(path) == row["sha256"], path
    source = artifact("DataNode.java").read_text()
    manager = artifact("BlockPoolManager.java").read_text()
    bpos = artifact("BPOfferService.java").read_text()
    actor = artifact("BPServiceActor.java").read_text()
    test = artifact("TestDeleteBlockPool.java").read_text()
    method = test[test.index("void testDfsAdminDeleteBlockPool()"):]
    assert method.index("dn1.refreshNamenodes(nn1Conf)") < method.index(
        "assertEquals(1, dn1.getAllBpOs().size())")
    assert method.index("assertEquals(1, dn1.getAllBpOs().size())") < method.index(
        'String[] args = { "-deleteBlockPool", dn1Address, bpid2 }')
    assert method.index('String[] args = { "-deleteBlockPool", dn1Address, bpid2 }') < method.index(
        'String[] forceArgs = { "-deleteBlockPool", dn1Address, bpid2, "force" }')
    refresh = manager[manager.index("private void doRefreshNamenodes("):]
    assert "bpos.stop();" in refresh and "bpos.join();" in refresh
    assert refresh.index("bpos.stop();") < refresh.index("bpos.join();")
    remove = manager[manager.index("synchronized void remove(BPOfferService t)"):]
    assert remove.index("offerServices.remove(t)") < remove.index(
        "bpByBlockPoolId.remove(t.getBlockPoolId())")
    assert "if (bpServices.isEmpty())" in bpos and "dn.shutdownBlockPool(this)" in bpos
    assert "blockPoolManager.remove(bpos)" in source
    guard = source[source.index("public void deleteBlockPool(String blockPoolId, boolean force)"):]
    assert guard.index("blockPoolManager.get(blockPoolId)") < guard.index(
        "data.deleteBlockPool(blockPoolId, force)")
    catch = actor[actor.index("} catch (IOException e) {", actor.index("private void offerService()")):]
    assert "sleepAfterException();" in catch
    join = actor[actor.index("void join() {", actor.index("//This must be called only by blockPoolManager")):]
    assert "} catch (InterruptedException ie) { }" in join
    original = test[test.index("void testDeleteBlockPool()"):test.index("void testDfsAdminDeleteBlockPool()")]
    assert "dn1.deleteBlockPool(bpid1, true)" in original and "catch (IOException expected)" in original

    trial = artifact("events.jsonl.gz").parent
    result = json.loads((trial / "result.json").read_text())
    junit = result["junit_validation"]
    assert (junit["tests"], junit["failures"], junit["errors"]) == (1, 0, 0)
    with gzip.open(trial / "events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK"
              and "DataNode#deleteBlockPool" in e.get("site", "")]
    assert [(e["seq"], e["node"], e["epoch"], e["outcome"]) for e in checks] == [
        (165, "hdfs-cluster-1/dn0", 0, "TAKEN"),
        (174, "hdfs-cluster-1/dn0", 0, "TAKEN")]
    assert not any(e.get("type") == "TARGET_THROW" and
                   "DataNode#deleteBlockPool" in e.get("site", "") for e in events)
    doors = [e["seq"] for e in events if e.get("type") == "DOOR_OBSERVED"
             and "BPServiceActor#sendHeartBeat" in e.get("site", "")
             and e.get("node") == "hdfs-cluster-1/dn0"]
    assert doors == [39, 40]
    request = json.loads(artifact("healthy-receipt.json").read_text())
    assert request["request_target_pairing_complete"]
    assert [(pair["target_check_seq"], pair["force_from_pinned_source_order"])
            for pair in request["request_pairs"]] == [(165, False), (174, True)]
    assert request["request_pairs"][0]["response"].endswith(".error")
    assert not request["request_pairs"][1]["response"].endswith(".error")

    config = json.loads(artifact("HDFS-32-node2-full-v2.json").read_text())
    assert config["agent_properties"]["auto.io.doors"] is False
    assert len(json.loads(artifact("HDFS-32.sites.json").read_text())["doors"]) == 1
    print("PASS: HDFS-32 named healthy requests, refresh/remove ordering, and typed-I/O gap; no JVM")


if __name__ == "__main__":
    main()
