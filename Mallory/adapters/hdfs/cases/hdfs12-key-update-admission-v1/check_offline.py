#!/usr/bin/env python3
"""Read-only HDFS-12/14 source, classfile, and healthy-candidate audit."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
HDFS = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs")
CLASSES = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2/hadoop-hdfs-project/hadoop-hdfs/target/classes")
PARSER = HERE.parent / "hdfs29-replica-recovery-admission-v1/verify_bytecode.py"
sys.path.insert(0, str(BASE))

from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def only_call(calls, name, line):
    hits = [c for c in calls if c["method"] == name and c["line"] == line]
    assert len(hits) == 1, (name, line, hits)
    return hits[0]


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    config = json.loads((HERE / "HDFS-12-healthy-only.json").read_text())
    gap14 = json.loads((HERE / "HDFS-14-source-gap.json").read_text())
    sites = json.loads((HERE / "HDFS-12.sites.json").read_text())
    for item in receipt["artifacts"]:
        path = Path(item["path"])
        assert path.is_file() and sha(path) == item["sha256"], path
    head = subprocess.run(["git", "-C", str(CLASSES.parents[3]), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    assert head == receipt["source_commit"]
    validate_config(config)
    verify_runtime_artifacts(config)
    assert config["case_id"] == "HDFS-12" and config["calibration_only"]
    assert config["command"][5] == "-Dtest=TestEncryptedTransfer#testLongLivedClient*"
    assert not config["auto_promote_if_healthy"]
    assert not config["mapping"]["healthy_seed_verified"]
    assert not config["mapping"]["fault_retains_target_verified"]
    assert not config["mapping"]["node_identity_binding_verified"]
    assert config["agent_properties"]["auto.io.doors"] is False
    assert config["reject_coarse_roots"] and config["require_event_time_paths"]
    assert config["healthy_gate"]["require_exact_target_reached"]
    assert config["healthy_gate"]["require_named_target_node"]
    assert config["healthy_gate"]["require_target_exception_absent"]
    assert not config["healthy_gate"]["allow_local_timeline_doors"]
    assert len(sites["doors"]) == 1
    door = sites["doors"][0]
    assert door["method"] == "sendHeartBeat" and door["line"] == 563
    assert door["exception_class"] == "java.io.IOException"
    assert door["callee"].startswith(
        "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB#sendHeartbeat(")
    assert config["target"]["check_sites"][0].endswith("@511:branch:2")
    assert config["target"]["throw_site"].endswith("@514:throw:1")
    assert gap14["selected_check"].endswith("@411:branch:1")
    assert gap14["selected_throw"].endswith("@412:throw:1")
    assert not gap14["healthy_only_config_staged"]

    spec = importlib.util.spec_from_file_location("hdfs29_class_reader", PARSER)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    token_class = CLASSES / "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.class"
    _, methods, pool = parser.parse_class(token_class)
    retrieved = next(m for m in methods if m["name"] == "retrievePassword")
    calls = parser.calls(retrieved, pool)
    assert only_call(calls, "get", 509)["owner"] == "java/util/Map"
    assert only_call(calls, "<init>", 514)["owner"] == "org/apache/hadoop/security/token/SecretManager$InvalidToken"
    pc = next(pc for pc, line in retrieved["lines"] if line == 511)
    assert retrieved["code"][pc + 1] == 0xC7  # ifnonnull after allKeys lookup
    checked = next(m for m in methods if m["name"] == "checkAccess" and
                   m["descriptor"].startswith("(Lorg/apache/hadoop/security/token/Token;") and
                   "[Lorg/apache/hadoop/fs/StorageType;" in m["descriptor"])
    check_calls = parser.calls(checked, pool)
    assert only_call(check_calls, "retrievePassword", 411)["owner"].endswith(
        "/BlockTokenSecretManager")
    assert only_call(check_calls, "isEqual", 411)["owner"] == "java/security/MessageDigest"
    _, actor_methods, actor_pool = parser.parse_class(
        CLASSES / "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class")
    send = next(m for m in actor_methods if m["name"] == "sendHeartBeat")
    assert only_call(parser.calls(send, actor_pool), "sendHeartbeat", 563)["owner"].endswith(
        "/DatanodeProtocolClientSideTranslatorPB")

    root = HDFS / "src/main/java/org/apache/hadoop/hdfs"
    actor = (root / "server/datanode/BPServiceActor.java").read_text()
    offer = actor[actor.index("void offerService()") : actor.index("} // offerService")]
    assert offer.index("resp = sendHeartBeat(requestBlockReportLease)") < offer.index(
        "commandProcessingThread.enqueue(resp.getCommands())")
    assert "catch (IOException e)" in offer and "sleepAfterException();" in offer
    manager = (root / "server/blockmanagement/BlockManager.java").read_text()
    assert "cmds.add(new KeyUpdateCommand(blockTokenSecretManager.exportKeys()))" in manager
    assert "nodeinfo.setNeedKeyUpdate(false)" in manager
    bpos = (root / "server/datanode/BPOfferService.java").read_text()
    assert "case DatanodeProtocol.DNA_ACCESSKEYUPDATE:" in bpos
    assert "dn.blockPoolTokenSecretManager.addKeys(" in bpos
    token = (root / "security/token/block/BlockTokenSecretManager.java").read_text()
    assert "allKeys.get(identifier.getKeyId())" in token
    assert "this.allKeys.put(receivedKeys[i].getKeyId(), receivedKeys[i])" in token
    test = (HDFS / "src/test/java/org/apache/hadoop/hdfs/TestEncryptedTransfer.java").read_text()
    chosen = test[test.index("void testLongLivedClient()") : test.index("void testFileChecksumWithInvalidEncryptionKey()")]
    assert "setKeyUpdateIntervalForTesting(2 * 1000)" in chosen
    assert "setTokenLifetime(2 * 1000)" in chosen and "Thread.sleep(15 * 1000)" in chosen
    assert "@RunWith(Parameterized.class)" in test
    sasl = (root / "protocol/datatransfer/sasl/SaslDataTransferServer.java").read_text()
    assert "blockPoolTokenSecretManager.retrievePassword(" in sasl
    probe = (BASE / "Mallory/instrumentation/src/main/java/edu/uva/liftlab/mallory/instrumentation/MalloryTransformer.java").read_text()
    assert "method.instructions.insertBefore(call, probe);" in probe

    for case in (12, 14):
        trial = BASE / f"data/mallory/calibration/HDFS-{case}/trials/r0000"
        archived = json.loads((trial / "result.json").read_text())
        assert archived["return_code"] == 0 and not archived["feedback"]["target_reached"]
        assert "Tests run: 0, Failures: 0, Errors: 0" in (trial / "stdout.log").read_text()
    with ZipFile(config["agent_properties"]["adapter.jar"]) as jar:
        bridge = jar.read("edu/uva/liftlab/mallory/adapters/hdfs/HdfsMiniClusterTransformer.class")
    assert b"heartbeatResponseProduced" in bridge and b"saslInitialMessageReceived" in bridge
    print("HDFS-12/14 offline selector, bytecode, source, archive, and SHA audit: PASS")


if __name__ == "__main__":
    main()
