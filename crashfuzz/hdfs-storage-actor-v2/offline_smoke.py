#!/usr/bin/env python3
"""Verify patched bytecode and fail-closed selector semantics without a cluster."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import campaign
import calibrate
import run_original

HERE = Path(__file__).resolve().parent


def check_bytecode() -> None:
    run_original.build()
    env = dict(os.environ, JAVA_HOME=str(run_original.JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(run_original.HADOOP / "bin/hadoop"), "classpath", "--glob"],
        text=True, env=env).strip()
    asm = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
    def asm_jar(name: str) -> Path:
        repository = asm / name / "9.6" / (name + "-9.6.jar")
        local = HERE / "build/verification-lib" / (name + "-9.6.jar")
        path = repository if repository.is_file() else local
        if not path.is_file():
            raise FileNotFoundError(f"missing ASM verifier dependency: {name}")
        return path
    cp = os.pathsep.join((str(run_original.OVERLAY), str(run_original.BUILD / "classes"),
                          str(run_original.TESTS), hadoop_cp,
                          *(str(asm_jar(name)) for name
                            in ("asm", "asm-tree", "asm-util", "asm-analysis"))))
    patched = ("org/apache/hadoop/hdfs/MiniDFSCluster",
               "org/apache/hadoop/hdfs/server/datanode/DataNode",
               "org/apache/hadoop/hdfs/server/datanode/BPServiceActor",
               "org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage",
               "org/apache/hadoop/hdfs/server/datanode/DataStorage",
               "org/apache/hadoop/ipc/Client")
    for name in patched:
        path = run_original.OVERLAY / (name + ".class")
        result = subprocess.run([str(run_original.JDK / "java"), "-cp", cp,
                                 "org.objectweb.asm.util.CheckClassAdapter", str(path)],
                                text=True, capture_output=True, env=env)
        if result.returncode != 0 or result.stdout or result.stderr:
            raise AssertionError(f"ASM verification failed for {name}:\n"
                                 + result.stdout + result.stderr)
    print(f"ASM-verified {len(patched)} patched classes")


def check_identity() -> None:
    assert campaign.storage_volume("dfs/datanodeMaster/current/BP-ID") == "dfs/datanodeMaster"
    assert campaign.storage_volume("dfs/data1/current/BP-ID/current") == "dfs/data1"
    actor1 = "episode=7/dn=1/dirs=dfs/data1,dfs/data2"
    actor2 = "episode=8/dn=1/dirs=dfs/data1,dfs/data2"
    target = {"event": "TARGET_CHECK", "seq": 30, "caseId": "HDFS-22",
              "actorKey": actor1, "storageKey": "dfs/data1/current/BP-ID/current"}
    file1 = {"event": "FAULT_POINT_OBSERVED", "seq": 10,
             "marker": "FAULT:HDFS_BP_FILE:DN_VERSION_READ", "siteId": "DataStorage.readProperties",
             "actorKey": actor1, "storageKey": "dfs/data1", "sourceKey": actor1 + "/storage=dfs/data1",
             "occurrence": "file", "hitOrdinal": 1}
    rpc1 = {"event": "FAULT_POINT_OBSERVED", "seq": 11,
            "marker": "FAULT:HDFS_BP_RPC:RESPONSE", "siteId": "Client.getRpcResponse",
            "actorKey": actor1, "storageKey": "unbound", "peerRole": "NN0",
            "endpointRaw": "localhost/127.0.0.1:40000",
            "actorNamenodeRaw": "localhost/127.0.0.1:40000",
            "sourceKey": actor1 + "/peer=NN0", "occurrence": "rpc", "hitOrdinal": 1}
    assert campaign.related(file1, target)
    assert calibrate.target_throw_signature({"caseId": "HDFS-37", "actorKey": actor1,
        "storageKey": "dfs/data1/current/BP-ID", "exception": "IOException"}) == (
            "HDFS-37", actor1, "dfs/data1", "IOException")
    assert campaign.related(rpc1, target)
    assert not campaign.related({**file1, "actorKey": actor2}, target)
    assert not campaign.related({**file1, "storageKey": "dfs/data2"}, target)
    assert not campaign.related({**rpc1, "peerRole": "unbound"}, target)
    assert not campaign.related({**rpc1, "seq": 31}, target)
    assert campaign.eligible_io([file1, rpc1, target], ("HDFS-22",)) == [file1, rpc1]
    selected = campaign.selector(rpc1, "IOException")
    applied = {**rpc1, "event": "FAULT_APPLIED", "faultType": "IOException", "faultIndex": 0}
    assert campaign.exact_applied([selected], [applied])[0]
    assert not campaign.exact_applied([selected], [{**applied, "actorKey": actor2}])[0]
    assert not campaign.exact_applied([selected], [{**applied, "peerRole": "unbound"}])[0]
    assert not campaign.exact_applied([selected], [{**applied, "storageKey": "dfs/data1"}])[0]
    assert not campaign.exact_applied([selected], [{**applied,
        "actorNamenodeRaw": "localhost/127.0.0.1:40001"}])[0]
    assert not campaign.exact_applied([selected], [applied, {**rpc1,
        "endpointRaw": "localhost/127.0.0.1:40001"}])[0]
    assert campaign.postfault([applied, target], "HDFS-22", [selected], [applied], True)[0] == [target]
    assert not campaign.postfault([applied, {**target, "actorKey": actor2}],
                                  "HDFS-22", [selected], [applied], True)[0]
    second = {**target, "caseId": "HDFS-23", "seq": 31}
    trace = [file1, rpc1, target, second]
    receipt = {"stable_selectors_by_case": {
        case: [list((rpc1["marker"], rpc1["siteId"], rpc1["sourceKey"], rpc1["hitOrdinal"]))]
        for case in ("HDFS-22", "HDFS-23")}}
    queue = campaign.initial_queue(receipt, trace, ("HDFS-22", "HDFS-23"))
    assert len(queue) == len(campaign.RPC_FAULTS)
    assert all(entry["cases"] == ["HDFS-22", "HDFS-23"] for entry in queue)
    assert all(entry["sequence"][0]["actorKey"] == actor1 for entry in queue)
    state = {"case_ids": ["HDFS-22"], "effective_by_case": {"HDFS-22": 80},
             "budget": {"goal_by_case": {"HDFS-22": 80},
                        "faults_by_case": {"HDFS-22": 8}},
             "effective_history": {"HDFS-22": [
                 {"coverage_gain": {"branch_counts": int(i == 79)},
                  "new_io_families": 0} for i in range(80)]},
             "completion_order": []}
    campaign.advance_goals(state)
    assert state["budget"]["goal_by_case"]["HDFS-22"] == 128
    assert state["budget"]["faults_by_case"]["HDFS-22"] == 10
    # A completed sequence is never selected again, including after restart.
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint = Path(temporary) / "state.json"
        queue_state = {"queue": queue, "completed": {queue[0]["id"]: {}},
                       "completion_order": [queue[0]["id"]], "in_flight": None,
                       "effective_by_case": {"HDFS-22": 0, "HDFS-23": 0},
                       "budget": {"goal_by_case": {"HDFS-22": 80, "HDFS-23": 80}}}
        campaign.write_json(checkpoint, queue_state)
        reloaded = __import__("json").loads(checkpoint.read_text())
        chosen = campaign.pick(reloaded)
        assert chosen["id"] != queue[0]["id"]
    rpc_entry = next(entry for entry in queue if "RPC:" in entry["sequence"][0]["marker"])
    file_entry = {**rpc_entry, "id": "file-choice", "score": rpc_entry["score"] + 10,
                  "sequence": [{**rpc_entry["sequence"][0], "marker": "FAULT:HDFS_BP_FILE:VERSION_READ"}]}
    lost = {str(i): {"item": file_entry, "result": {
        "exact_order_applied": True,
        "by_case": {"HDFS-22": {"valid_for_feedback": False}}}} for i in range(3)}
    adaptive = {"in_flight": None, "completion_order": list(lost), "completed": lost,
                "queue": [file_entry, rpc_entry],
                "effective_by_case": {"HDFS-22": 0},
                "budget": {"goal_by_case": {"HDFS-22": 80}}}
    assert campaign.pick(adaptive)["id"] == rpc_entry["id"]
    deep = {**rpc_entry, "id": "deep-episode-one", "score": 1250,
            "cases": ["HDFS-22"]}
    hdfs34 = {**rpc_entry, "id": "hdfs34-episode-three", "score": 998,
              "cases": ["HDFS-34"]}
    balanced = {**adaptive, "queue": [deep, hdfs34], "in_flight": None,
                "effective_by_case": {"HDFS-22": 3, "HDFS-34": 0},
                "budget": {"goal_by_case": {"HDFS-22": 80, "HDFS-34": 80}}}
    assert campaign.pick(balanced)["id"] == hdfs34["id"]
    print("Actor, storage volume, peer, order, and post-target checks passed")


def main() -> None:
    check_bytecode()
    check_identity()


if __name__ == "__main__":
    main()
