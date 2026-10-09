#!/usr/bin/env python3
"""Compile case-local source probes from pristine Hadoop 3.4.3 sources."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs40independent.Probe"
SOURCE = CASE / "source/main"
GENERATED = HERE / "generated"
CLASSES = HERE / "probe-classes"


def override(name: str, before: str, after: str) -> Path:
    original = SOURCE / name
    text = original.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise RuntimeError(f"no Java package declaration in {original}")
    text = text[:package.end()] + "\nimport " + PROBE + ";" + text[package.end():]
    if text.count(before) != 1:
        raise RuntimeError(f"expected one probe site in {original}: {text.count(before)}")
    text = text.replace(before, after, 1)
    output = GENERATED / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return output


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    target = override(
        "org/apache/hadoop/hdfs/server/namenode/FSDirAppendOp.java",
        """        } else if (lastBlock.isComplete()
          && !blockManager.isSufficientlyReplicated(lastBlock)) {
          throw new IOException("append: lastBlock=" + lastBlock + " of src="
              + path + " is not sufficiently replicated yet.");
        }
""",
        """        } else {
          final boolean hdfs40Complete = lastBlock.isComplete();
          final boolean hdfs40Sufficient = !hdfs40Complete ||
              blockManager.isSufficientlyReplicated(lastBlock);
          Probe.guard(hdfs40Complete, hdfs40Sufficient, path,
              lastBlock.getBlockId(), lastBlock.getBlockUCState().name());
          if (hdfs40Complete && !hdfs40Sufficient) {
            IOException hdfs40Target = new IOException(
                "append: lastBlock=" + lastBlock + " of src=" + path
                + " is not sufficiently replicated yet.");
            Probe.targetException(hdfs40Target);
            throw hdfs40Target;
          }
        }
""")
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        """  private Writable getRpcResponse(final Call call, final Connection connection,
      final long timeout, final TimeUnit unit) throws IOException {
    synchronized (call) {""",
        """  private Writable getRpcResponse(final Call call, final Connection connection,
      final long timeout, final TimeUnit unit) throws IOException {
    Probe.io("RPC_RESPONSE_WAIT", "Client.getRpcResponse");
    synchronized (call) {""")
    generated_rpc = rpc.read_text()
    send_site = "        connection.sendRpcRequest(call);                 // send the rpc request"
    if generated_rpc.count(send_site) != 1:
        raise RuntimeError("expected one Hadoop IPC send boundary")
    rpc.write_text(generated_rpc.replace(
        send_site,
        "        Probe.io(\"RPC_SEND\", \"Client.sendRpcRequest\");\n" +
        send_site, 1))
    file_io = override(
        "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
        """  public void flushAndSync(boolean durable) throws IOException {
    if (fp == null) {""",
        """  public void flushAndSync(boolean durable) throws IOException {
    Probe.io("FILE_FLUSH", durable ? "durable" : "buffered");
    if (fp == null) {""")
    append_rpc = override(
        "org/apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB.java",
        """    AppendResponseProto res = ipc(() -> rpcProxy.append(null, req));
""",
        """    Probe.requestContext("append:" + src);
    AppendResponseProto res;
    try {
      res = ipc(() -> rpcProxy.append(null, req));
    } finally {
      Probe.clearRequestContext();
    }
""")
    block_rpc = override(
        "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java",
        """    ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));
""",
        """    long hdfs40BlockId = -1L;
    for (StorageReceivedDeletedBlocks hdfs40Storage : receivedAndDeletedBlocks) {
      for (ReceivedDeletedBlockInfo hdfs40Info : hdfs40Storage.getBlocks()) {
        hdfs40BlockId = hdfs40Info.getBlock().getBlockId();
        break;
      }
      if (hdfs40BlockId >= 0L) {
        break;
      }
    }
    Probe.requestContext("blockReceivedAndDeleted:block=" + hdfs40BlockId);
    Probe.requestSource(registration.getDatanodeUuid());
    try {
      ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));
    } finally {
      Probe.clearRequestSource();
      Probe.clearRequestContext();
    }
""")
    original_test = SOURCE.parent / "test/org/apache/hadoop/hdfs/TestFileAppend.java"
    test_text = original_test.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", test_text)
    if package is None:
        raise RuntimeError("missing original TestFileAppend package")
    test_text = test_text[:package.end()] + "\nimport " + PROBE + ";" + test_text[package.end():]
    before_test = """  public void testFailedAppendBlockRejection() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.set("dfs.client.block.write.replace-datanode-on-failure.enable",
        "false");
    File builderBaseDir = new File(GenericTestUtils.getRandomizedTempPath());
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf, builderBaseDir)
        .numDataNodes(3).build();
"""
    after_test = before_test + "    Probe.registerDatanodes(cluster.getDataNodes());\n"
    if test_text.count(before_test) != 1:
        raise RuntimeError("expected one original TestFileAppend owner fixture")
    test_text = test_text.replace(before_test, after_test, 1)
    before_stop = "      DataNodeProperties dnProp = cluster.stopDataNode(0);"
    if test_text.count(before_stop) < 1:
        raise RuntimeError("original DataNode stop not found")
    owner_start = test_text.index("  public void testFailedAppendBlockRejection()")
    owner_end = test_text.index("  public void testMultiAppend2()", owner_start)
    owner = test_text[owner_start:owner_end]
    if owner.count(before_stop) != 1:
        raise RuntimeError("expected one original stop in selected JUnit")
    owner = owner.replace(before_stop, before_stop +
                          "\n      Probe.markPhase(\"afterDn0Stop\");", 1)
    test_text = test_text[:owner_start] + owner + test_text[owner_end:]
    test_override = GENERATED / "org/apache/hadoop/hdfs/TestFileAppend.java"
    test_override.parent.mkdir(parents=True, exist_ok=True)
    test_override.write_text(test_text)
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), str(HERE / "Probe.java"), str(target),
               str(rpc), str(file_io), str(append_rpc), str(block_rpc),
               str(test_override)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream,
                                   stderr=subprocess.STDOUT)
    record = {"exit": completed.returncode, "probe_classes": str(CLASSES),
              "original_sources": [str(SOURCE / path) for path in (
                  "org/apache/hadoop/hdfs/server/namenode/FSDirAppendOp.java",
                  "org/apache/hadoop/ipc/Client.java",
                  "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
                  "org/apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB.java",
                  "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java")],
              "original_test_source": str(original_test),
              "instrumentation": "isolated source-level probes plus read-only test fixture DN-index map; original JUnit operations and assertions unchanged; no GraphChecker or graph artifacts"}
    (HERE / "build-probe.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
