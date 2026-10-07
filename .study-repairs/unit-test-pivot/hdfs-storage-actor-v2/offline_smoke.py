#!/usr/bin/env python3
"""Verify patched bytecode and fail-closed selector semantics without a cluster."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import campaign
import run_original

HERE = Path(__file__).resolve().parent


def check_bytecode() -> None:
    run_original.build()
    env = dict(os.environ, JAVA_HOME=str(run_original.JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(run_original.HADOOP / "bin/hadoop"), "classpath", "--glob"],
        text=True, env=env).strip()
    asm = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
    cp = os.pathsep.join((str(run_original.OVERLAY), str(run_original.BUILD / "classes"),
                          str(run_original.TESTS), hadoop_cp,
                          *(str(asm / name / "9.6" / (name + "-9.6.jar")) for name
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
            "sourceKey": actor1 + "/peer=NN0", "occurrence": "rpc", "hitOrdinal": 1}
    assert campaign.related(file1, target)
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
    assert campaign.postfault([applied, target], "HDFS-22", [selected], [applied], True)[0] == [target]
    assert not campaign.postfault([applied, {**target, "actorKey": actor2}],
                                  "HDFS-22", [selected], [applied], True)[0]
    print("Actor, storage volume, peer, order, and post-target checks passed")


def main() -> None:
    check_bytecode()
    check_identity()


if __name__ == "__main__":
    main()
