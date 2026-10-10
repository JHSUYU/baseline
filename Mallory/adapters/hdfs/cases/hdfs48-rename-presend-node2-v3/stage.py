#!/usr/bin/env python3
"""Freeze the HDFS-48 rename door and retrying JUnit in this case only.

This prepares source files and the isolated adapter build. It never changes
the shared HDFS adapter, Hadoop checkout, or starts a Hadoop test.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
ADAPTER = BASE / "Mallory/adapters/hdfs"
HADOOP = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
JAVA_PACKAGE = Path("edu/uva/liftlab/mallory/adapters/hdfs")
AGENT = BASE / ("Mallory/instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
TEST_REL = Path("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/"
                "hdfs/server/namenode/snapshot/TestRenameWithSnapshots.java")
SOURCE_HASHES = {
    "HdfsHooks.java": "7f416f4d10d310292a9d9d471287b410dd7f7427f45625537238f449425e23d8",
    "HdfsMiniClusterTransformer.java":
        "6940e8a45f6e0f25aa5d24509c5d8b28a38f004d3c4a0b046f27e99b9bc4763b",
}
TEST_SHA = "58c382b17db4855ebc3e105feb72232c086126e3ecb8a71dc8919d5967c8af00"
AGENT_SHA = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected one anchor; found {text.count(old)}: {old[:75]}")
    return text.replace(old, new, 1)


def main() -> None:
    if sha(AGENT) != AGENT_SHA or sha(HADOOP / TEST_REL) != TEST_SHA:
        raise RuntimeError("pinned agent or Hadoop test changed")
    source = ADAPTER / "src/main/java" / JAVA_PACKAGE
    for name, expected in SOURCE_HASHES.items():
        if sha(source / name) != expected:
            raise RuntimeError(f"shared adapter source changed before snapshot: {name}")

    hooks = (source / "HdfsHooks.java").read_text()
    hooks = replace_once(
        hooks, "  public static void rpcSend(Object connection, Object call) {\n",
        "  /** Observe only a ClientProtocol.rename request before it is queued. */\n"
        "  public static void rpcBeforeRenameSend(Object call) {\n"
        "    final Object request;\n"
        "    try { request = field(call, \"rpcRequest\"); }\n"
        "    catch (ReflectiveOperationException failure) {\n"
        "      throw new IllegalStateException(\"HDFS client RPC request unavailable\", failure);\n"
        "    }\n"
        "    if (request == null || !request.getClass().getName().equals(\n"
        "        \"org.apache.hadoop.ipc.ProtobufRpcEngine2$RpcProtobufRequest\")) return;\n"
        "    if (!\"org.apache.hadoop.hdfs.protocol.ClientProtocol.rename\"\n"
        "        .equals(request.toString())) return;\n"
        "    Probe.beforeDoor(\"hdfs:client-send-rpc-request:rename\",\n"
        "        \"java.io.IOException\");\n"
        "  }\n\n"
        "  public static void rpcSend(Object connection, Object call) {\n")
    transformer = (source / "HdfsMiniClusterTransformer.java").read_text()
    transformer = replace_once(
        transformer,
        "          && method.desc.startsWith(\"(Lorg/apache/hadoop/ipc/Client$Call;)\")) {\n"
        "        InsnList hook = new InsnList();\n"
        "        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));\n",
        "          && method.desc.startsWith(\"(Lorg/apache/hadoop/ipc/Client$Call;)\")) {\n"
        "        InsnList hook = new InsnList();\n"
        "        // A local pre-send fault must not emit a fictitious SEND.\n"
        "        hook.add(new VarInsnNode(Opcodes.ALOAD, 1));\n"
        "        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,\n"
        "            \"rpcBeforeRenameSend\", \"(Ljava/lang/Object;)V\", false));\n"
        "        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));\n")
    test = (HADOOP / TEST_REL).read_text()
    test = replace_once(
        test,
        "  @Before\n  public void setUp() throws Exception {\n"
        "    conf.setLong(DFSConfigKeys.DFS_BLOCK_SIZE_KEY, BLOCKSIZE);\n",
        "  @Before\n  public void setUp() throws Exception {\n"
        "    // Retry one locally failed rename request after pre-send injection.\n"
        "    conf.setBoolean(\"dfs.client.retry.policy.enabled\", true);\n"
        "    conf.set(\"dfs.client.retry.policy.spec\", \"20,1\");\n"
        "    conf.setLong(DFSConfigKeys.DFS_BLOCK_SIZE_KEY, BLOCKSIZE);\n")

    frozen_source = HERE / "source"
    frozen_source.mkdir(parents=True, exist_ok=True)
    (frozen_source / "HdfsHooks.java").write_text(hooks)
    (frozen_source / "HdfsMiniClusterTransformer.java").write_text(transformer)
    (HERE / "patched-test" / TEST_REL.name).write_text(test)

    build = HERE / "build"
    build_source = build / "src/main/java" / JAVA_PACKAGE
    build_source.mkdir(parents=True, exist_ok=True)
    for name in SOURCE_HASHES:
        shutil.copy2(frozen_source / name, build_source / name)
    pom = (ADAPTER / "pom.xml").read_text()
    pom = replace_once(pom,
                       "${project.basedir}/../../instrumentation/target/mallory-agent.jar",
                       "${project.basedir}/lib/mallory-agent.jar")
    (build / "pom.xml").write_text(pom)
    shutil.copy2(AGENT, build / "lib/mallory-agent.jar")
    print("staged isolated HDFS-48 adapter sources and retrying JUnit source")


if __name__ == "__main__":
    main()
