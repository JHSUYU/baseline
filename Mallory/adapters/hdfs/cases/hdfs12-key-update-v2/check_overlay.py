#!/usr/bin/env python3
"""Offline-only HDFS-12 hook selector check against pinned Hadoop classfiles."""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARSER = HERE.parent / "hdfs29-replica-recovery-admission-v1/verify_bytecode.py"
CLASSES = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2/hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs")
spec = importlib.util.spec_from_file_location("hdfs12_class_reader", PARSER)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def ops(code: bytes):
    pc = 0
    while pc < len(code):
        op = code[pc]
        yield pc, op
        if op == 170:
            start = pc + 1 + ((4 - ((pc + 1) % 4)) % 4)
            low = int.from_bytes(code[start+4:start+8], "big", signed=True)
            high = int.from_bytes(code[start+8:start+12], "big", signed=True)
            pc = start + 12 + 4 * (high - low + 1)
        elif op == 171:
            start = pc + 1 + ((4 - ((pc + 1) % 4)) % 4)
            pairs = int.from_bytes(code[start+4:start+8], "big")
            pc = start + 8 + 8 * pairs
        elif op == 196:
            pc += 6 if code[pc+1] == 132 else 4
        else:
            pc += 1 + reader.OPERANDS.get(op, 0)
    assert pc == len(code)


def method(class_name: str, name: str, descriptor: str):
    path = CLASSES / (class_name + ".class")
    _, methods, pool = reader.parse_class(path)
    matches = [m for m in methods if m["name"] == name and m["descriptor"] == descriptor]
    assert len(matches) == 1, (class_name, name, descriptor, len(matches))
    return matches[0], pool


def call_count(method_row, pool, owner: str, name: str, line: int | None = None):
    hits = [call for call in reader.calls(method_row, pool)
            if call["owner"] == owner and call["method"] == name
            and (line is None or call["line"] == line)]
    assert len(hits) == 1, (owner, name, line, hits)


def main():
    token = "security/token/block/BlockTokenSecretManager"
    update, cp = method(token, "updateKeys", "()Z")
    assert sum(op == 172 for _, op in ops(update["code"])) == 2
    create, cp = method(token, "createPassword",
                        "(Lorg/apache/hadoop/hdfs/security/token/block/BlockTokenIdentifier;)[B")
    assert sum(op == 176 for _, op in ops(create["code"])) == 1
    call_count(create, cp, "org/apache/hadoop/hdfs/security/token/block/BlockTokenIdentifier",
               "setKeyId", 485)
    added, cp = method(token, "addKeys",
                       "(Lorg/apache/hadoop/hdfs/security/token/block/ExportedBlockKeys;)V")
    assert sum(op == 177 for _, op in ops(added["code"])) == 2
    call_count(added, cp, "org/apache/hadoop/hdfs/security/token/block/ExportedBlockKeys",
               "getAllKeys")
    lookup, cp = method(token, "retrievePassword",
                        "(Lorg/apache/hadoop/hdfs/security/token/block/BlockTokenIdentifier;)[B")
    call_count(lookup, cp, "java/util/Map", "get", 509)
    monitor, cp = method("server/blockmanagement/HeartbeatManager$Monitor", "run", "()V")
    call_count(monitor, cp, "org/apache/hadoop/hdfs/server/blockmanagement/DatanodeDescriptor",
               "setNeedKeyUpdate", 554)
    setter, cp = method("server/blockmanagement/DatanodeDescriptor", "setNeedKeyUpdate", "(Z)V")
    assert sum(op == 177 for _, op in ops(setter["code"])) == 1
    command, cp = method("server/blockmanagement/BlockManager", "addKeyUpdateCommand",
                         "(Ljava/util/List;Lorg/apache/hadoop/hdfs/server/blockmanagement/DatanodeDescriptor;)V")
    call_count(command, cp, "org/apache/hadoop/hdfs/server/blockmanagement/DatanodeDescriptor",
               "setNeedKeyUpdate", 1665)
    heartbeat, cp = method("server/datanode/BPServiceActor", "sendHeartBeat",
                           "(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;")
    call_count(heartbeat, cp,
               "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB",
               "sendHeartbeat", 563)
    registration, _ = method("server/datanode/BPOfferService", "registrationSucceeded",
                             "(Lorg/apache/hadoop/hdfs/server/datanode/BPServiceActor;Lorg/apache/hadoop/hdfs/server/protocol/DatanodeRegistration;)V")
    assert registration["code"]

    overlay = HERE / "overlay"
    probe = (overlay / "Probe.java").read_text()
    hooks = (overlay / "Hdfs12KeyHooks.java").read_text()
    transformer = (overlay / "HdfsMiniClusterTransformer.java").read_text()
    bridge = (overlay / "HdfsHooks.java").read_text()
    assert 'event("HDFS12_KEY"' in probe and '"token_id"' in probe
    assert 'event("HDFS12_KEY_STATE"' in probe and '"state_token"' in probe
    assert 'invoke(key, "getKey")' not in hooks and 'invoke(identifier, "getBytes")' in hooks
    for hook in ("rotation", "pending", "commandPrepared", "added", "lookup",
                 "minted", "heartbeatAttempt"):
        assert f'"{hook}"' in transformer, hook
    assert '"lookupResult"' in transformer and 'lookupResult(Object value' in hooks
    assert '"serviceActorEnter"' in transformer and '"sendHeartBeat"' in transformer
    assert 'Method method = type.getDeclaredMethod(name)' in hooks
    assert 'actor = ACTOR_DATANODE.get()' in bridge
    assert 'Probe.regionEnter(region)' in bridge and 'Probe.regionExit(region)' in bridge
    assert 'heartbeatMonitorEnter' in transformer and 'heartbeatMonitorEnter' in bridge
    assert 'Hdfs12KeyHooks.dnBound(dn)' in bridge
    print("PASS: HDFS-12 scoped overlay selectors match pinned classfiles; no JVM started")


if __name__ == "__main__":
    main()
