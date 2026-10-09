#!/usr/bin/env python3
"""Read-only source and archived-evidence verifier for HDFS-48."""

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
REPO = HERE.parents[4]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def need(text, *pieces):
    for piece in pieces:
        assert piece in text, piece


def main():
    receipt = read_json(HERE / "source-admission-v2.json")
    head = subprocess.run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                          check=True, text=True, capture_output=True).stdout.strip()
    assert head == receipt["hadoop_commit"]
    for item in receipt["sha_pins"]:
        path = Path(item["path"])
        assert path.is_file() and sha(path) == item["sha256"], path

    hdfs = SOURCE / "hadoop-hdfs-project/hadoop-hdfs"
    common = SOURCE / "hadoop-common-project/hadoop-common"
    test = (hdfs / "src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot"
            / "TestRenameWithSnapshots.java").read_text()
    inode = (hdfs / "src/main/java/org/apache/hadoop/hdfs/server/namenode"
             / "INodeDirectory.java").read_text()
    rename = (hdfs / "src/main/java/org/apache/hadoop/hdfs/server/namenode"
              / "FSDirRenameOp.java").read_text()
    client = (common / "src/main/java/org/apache/hadoop/ipc/Client.java").read_text()
    protobuf = (common / "src/main/java/org/apache/hadoop/ipc/ProtobufRpcEngine2.java").read_text()
    retry = (common / "src/main/java/org/apache/hadoop/io/retry/RetryUtils.java").read_text()
    need(test, "void testRenameUndo_1() throws Exception", "root.replaceChild(dir2, mockDir2",
         "boolean result = hdfs.rename(foo, newfoo)", "assertFalse(result)")
    need(inode, "Preconditions.checkState(oldChild == children.get(i)",
         "replaceChild(oldChild, ref, null)")
    need(rename, "srcParent", ".replaceChild4ReferenceWithName(srcChild, srcLatestSnapshotId)")
    need(client, "connection.addCall(call)", "connection.sendRpcRequest(call)",
         "rpcRequestQueue.offer(Pair.of(call, buf)")
    assert client.index("connection.addCall(call)") > client.index("private synchronized boolean addCall(")
    need(protobuf, "header.getDeclaringClassProtocolName()", "header.getMethodName()",
         "throw new ServiceException(e)")
    need(retry, "e instanceof RemoteException", "e instanceof IOException || e instanceof ServiceException")
    test_patch = (HERE / "hadoop-test-retry.patch").read_text()
    need(test_patch, 'conf.setBoolean("dfs.client.retry.policy.enabled", true)',
         'conf.set("dfs.client.retry.policy.spec", "20,1")')
    adapter_patch = (HERE / "hdfs-adapter-client-door.patch").read_text()
    need(adapter_patch, '"rpcBeforeSend"', '"rpcSend"')
    assert adapter_patch.index('"rpcBeforeSend"') < adapter_patch.index('"rpcSend"')
    hooks_patch = (HERE / "hdfs-hooks-client-door.patch").read_text()
    need(hooks_patch, '"hdfs:client-send-rpc-request:" + method',
         '"java.io.IOException"')

    healthy = read_json(REPO / "data/mallory/calibration_v14_node0/HDFS-48/result.json")
    trial = read_json(REPO / "data/mallory/calibration_v14_node0/HDFS-48/trials/r0000/result.json")
    pilot = read_json(REPO / "data/mallory/pilots_v14/HDFS-48-nn-only/result.json")
    assert healthy["healthy_seed_valid"] is True
    junit = healthy["healthy_junit_validation"]
    assert tuple(junit[k] for k in ("tests", "failures", "errors")) == (1, 0, 0)
    feedback = trial["feedback"]
    assert feedback["target_reached"] is True and feedback["target_threw"] is False
    assert feedback["target_identity_complete"] is True
    assert any(item["node"] == "hdfs-cluster-1/nn0" for item in feedback["target_instances"])
    assert pilot["fault_trials_completed"] == pilot["strict_injected_trials"] == 10
    assert pilot["strict_target_trials"] == pilot["exact_exception_trials"] == 0
    print("HDFS-48 source admission and archived identity/fault gap: PASS")


if __name__ == "__main__":
    main()
