#!/usr/bin/env python3
"""Read-only HDFS-30 source, classfile, and archived-seed admission check."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
HDFS = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs")
CLASSES = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2/hadoop-hdfs-project/hadoop-hdfs/target/classes")
PARSER = HERE.parent / "hdfs29-replica-recovery-admission-v1/verify_bytecode.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method_calls(parser, owner, method_name):
    _, methods, pool = parser.parse_class(CLASSES / f"org/apache/hadoop/hdfs/server/datanode/{owner}.class")
    method = next(m for m in methods if m["name"] == method_name)
    return method, parser.calls(method, pool)


def only_call(calls, name, line):
    matches = [c for c in calls if c["method"] == name and c["line"] == line]
    assert len(matches) == 1, (name, line, matches)
    return matches[0]


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    selector = json.loads((HERE / "selector.json").read_text())
    for item in receipt["artifacts"]:
        path = Path(item["path"])
        assert path.is_file() and sha(path) == item["sha256"], path
    assert receipt["source_commit"] == subprocess.run(
        ["git", "-C", str(CLASSES.parents[3]), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    assert selector["case_id"] == "HDFS-30"
    assert selector["selected_check"].endswith("@582:branch:2")
    assert selector["selected_throw"].endswith("@583:throw:1")
    assert selector["status"].startswith("offline_source_review_nonterminal")
    assert not selector["live_jvm_started"] and not selector["fault_or_full_admitted"]

    spec = importlib.util.spec_from_file_location("hdfs29_class_reader", PARSER)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    worker, worker_calls = method_calls(parser, "BlockRecoveryWorker", "getActiveNamenodeForBP")
    assert only_call(worker_calls, "getActiveNN", 581)["owner"].endswith("/BPOfferService")
    start = next(pc for pc, line in worker["lines"] if line == 582)
    assert worker["code"][start + 1] == 0xC7  # ifnonnull: selected null branch
    assert next(line for pc, line in worker["lines"] if line == 583) == 583

    _, heart_calls = method_calls(parser, "BPServiceActor", "sendHeartBeat")
    assert only_call(heart_calls, "sendHeartbeat", 563)["owner"].endswith(
        "/DatanodeProtocolClientSideTranslatorPB")
    _, offer_calls = method_calls(parser, "BPServiceActor", "offerService")
    send = only_call(offer_calls, "sendHeartBeat", 703)
    update = only_call(offer_calls, "updateActorStatesFromHeartbeat", 725)
    commands = only_call(offer_calls, "getCommands", 737)
    assert send["pc"] < update["pc"] < commands["pc"]
    _, active_calls = method_calls(parser, "BPOfferService", "processCommandFromActive")
    assert only_call(active_calls, "recoverBlocks", 776)["owner"].endswith(
        "/BlockRecoveryWorker")

    actor = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java").read_text()
    offer = actor[actor.index("void offerService()") : actor.index("} // offerService")]
    assert offer.index("resp = sendHeartBeat(requestBlockReportLease)") < offer.index(
        "bpos.updateActorStatesFromHeartbeat(") < offer.index("commandProcessingThread.enqueue(resp.getCommands())")
    assert "catch (IOException e)" in offer and "sleepAfterException();" in offer
    bpos = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java").read_text()
    assert "bpServiceToActive = null;" in bpos
    assert "bpServiceToActive = actor;" in bpos
    assert "if (isActiveActor)" in bpos and "return processCommandFromActive(cmd, nnSocketAddress)" in bpos
    worker_source = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.java").read_text()
    assert "DatanodeProtocolClientSideTranslatorPB activeNN = bpos.getActiveNN();" in worker_source
    assert "getActiveNamenodeForBP(block.getBlockPoolId())" in worker_source
    test = (HDFS / "src/test/java/org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.java").read_text()
    alternate = test[test.index("void testLeaseRecoveryAfterFailover()") : test.index("void testFailoverRightBeforeCommitSynchronization()")]
    assert "newMiniCluster(conf, 3)" in alternate and "loopRecoverLease(fsOtherUser, TEST_PATH)" in alternate
    assert "DelayAnswer" not in alternate

    result = json.loads(Path(receipt["archive_result"]).read_text())
    feedback = result["feedback"]
    assert result["return_code"] == 0 and not result["timed_out"]
    assert feedback["target_reached"] and not feedback["target_threw"]
    instances = feedback["target_instances"]
    assert len(instances) == 2 and all(x["node"] == "unknown" for x in instances)
    assert all(x["site"].endswith("@582:branch:2") for x in feedback["target_identity_gaps"])
    stdout = Path(receipt["archive_stdout"]).read_text()
    assert "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0" in stdout

    with ZipFile(receipt["adapter_jar"]) as jar:
        transformer = jar.read("edu/uva/liftlab/mallory/adapters/hdfs/HdfsMiniClusterTransformer.class")
    assert b"blockRecoveryTaskEnter" in transformer
    assert b"heartbeatResponseProduced" not in transformer
    assert b"heartbeatStatusEnter" not in transformer
    print("HDFS-30 offline source, bytecode, archived reach, and SHA audit: PASS")


if __name__ == "__main__":
    main()
