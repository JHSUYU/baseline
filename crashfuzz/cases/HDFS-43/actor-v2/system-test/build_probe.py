#!/usr/bin/env python3
"""Compile isolated source probes around released Hadoop 3.4.3 classes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs43actor.Probe"
SOURCE = CASE / "source"
GENERATED = HERE / "generated"
CLASSES = HERE / "probe-classes"


def override(name: str, before: str, after: str, test: bool = False) -> Path:
    original = SOURCE / ("test" if test else "main") / name
    body = original.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", body)
    if not package:
        raise RuntimeError(f"no Java package in {original}")
    body = body[:package.end()] + "\nimport " + PROBE + ";" + body[package.end():]
    if body.count(before) != 1:
        raise RuntimeError(f"expected one exact probe site in {original}: {body.count(before)}")
    output = GENERATED / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body.replace(before, after, 1))
    return output


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    target = override(
        "org/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp.java",
        """          final long truncateLength = file.computeFileSize(false, false)
              + truncatedBlock.getNumBytes();
          if (newLength == truncateLength) {
            return new TruncateResult(false, fsd.getAuditFileInfo(iip));
          } else {
            throw new AlreadyBeingCreatedException(
                RecoverLeaseOp.TRUNCATE_FILE.getExceptionMessage(src,
                    clientName, clientMachine, src + " is being truncated."));
          }
""",
        """          final long truncateLength = file.computeFileSize(false, false)
              + truncatedBlock.getNumBytes();
          Probe.guard(src, last.getBlockId(), truncatedBlock.getBlockId(),
              last.getBlockUCState().name(), newLength, truncateLength);
          if (newLength == truncateLength) {
            return new TruncateResult(false, fsd.getAuditFileInfo(iip));
          } else {
            AlreadyBeingCreatedException hdfs43Target =
                new AlreadyBeingCreatedException(
                    RecoverLeaseOp.TRUNCATE_FILE.getExceptionMessage(src,
                        clientName, clientMachine, src + " is being truncated."));
            Probe.targetException(hdfs43Target);
            throw hdfs43Target;
          }
""")
    target_body = target.read_text()
    last_block_site = "      final BlockInfo last = file.getLastBlock();"
    if target_body.count(last_block_site) != 1:
        raise RuntimeError("expected one truncate file/block binding site")
    target.write_text(target_body.replace(
        last_block_site,
        last_block_site + "\n      Probe.truncateFileBlock(src, "
        "last == null ? -1L : last.getBlockId(), newLength);", 1))
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        """  private Writable getRpcResponse(final Call call, final Connection connection,
      final long timeout, final TimeUnit unit) throws IOException {
    synchronized (call) {""",
        """  private Writable getRpcResponse(final Call call, final Connection connection,
      final long timeout, final TimeUnit unit) throws IOException {
    Probe.rpcResponse(call.id, clientId,
        String.valueOf(connection.getRemoteAddress()),
        connection.getRemoteAddress().getPort());
    synchronized (call) {""")
    truncate_rpc = override(
        "org/apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB.java",
        """    return ipc(() -> rpcProxy.truncate(null, req).getResult());
""",
        """    Probe.truncateContext(src, newLength);
    try {
      return ipc(() -> rpcProxy.truncate(null, req).getResult());
    } finally {
      Probe.clearContext();
    }
""")
    dn_report = override(
        "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java",
        """    ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));
""",
        """    long hdfs43BlockId = -1L;
    boolean hdfs43MultipleBlocks = false;
    for (StorageReceivedDeletedBlocks hdfs43Storage : receivedAndDeletedBlocks) {
      for (ReceivedDeletedBlockInfo hdfs43Info : hdfs43Storage.getBlocks()) {
        long hdfs43Next = hdfs43Info.getBlock().getBlockId();
        if (hdfs43BlockId >= 0L && hdfs43BlockId != hdfs43Next) {
          hdfs43MultipleBlocks = true;
        }
        hdfs43BlockId = hdfs43Next;
      }
    }
    Probe.blockReportContext(registration.getDatanodeUuid(),
        hdfs43MultipleBlocks ? -1L : hdfs43BlockId);
    try {
      ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));
    } finally {
      Probe.clearContext();
    }
""")
    original_test = (SOURCE / "test/org/apache/hadoop/hdfs/server/namenode/"
                     "TestFileTruncate.java")
    test = original_test.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", test)
    if not package:
        raise RuntimeError("original JUnit package is missing")
    test = test[:package.end()] + "\nimport " + PROBE + ";" + test[package.end():]
    setup = """        .waitSafeMode(true)
        .build();
    fs = cluster.getFileSystem();"""
    if test.count(setup) != 1:
        raise RuntimeError("expected one original MiniDFSCluster fixture")
    test = test.replace(setup, """        .waitSafeMode(true)
        .build();
    Probe.registerNameNode(cluster.getNameNodePort());
    Probe.registerDatanodes(cluster.getDataNodes());
    fs = cluster.getFileSystem();""", 1)
    owner_start = test.index("  public void testTruncateTwiceTogether()")
    owner_end = test.index("  public void testTruncateWithOtherOperations()", owner_start)
    owner = test[owner_start:owner_end]
    for before, after in (
        ("    Thread t = new Thread(() -> {",
         "    Probe.markPhase(\"firstTruncate\");\n    Thread t = new Thread(() -> {"),
        ("    LambdaTestUtils.intercept(RemoteException.class,",
         "    Probe.markPhase(\"secondTruncate\");\n"
         "    LambdaTestUtils.intercept(RemoteException.class,")):
        if owner.count(before) != 1:
            raise RuntimeError(f"expected one original JUnit phase site: {before}")
        owner = owner.replace(before, after, 1)
    test = test[:owner_start] + owner + test[owner_end:]
    test_override = GENERATED / "org/apache/hadoop/hdfs/server/namenode/TestFileTruncate.java"
    test_override.parent.mkdir(parents=True, exist_ok=True)
    test_override.write_text(test)
    sources = [HERE / "Probe.java", target, rpc, truncate_rpc, dn_report,
               test_override]
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx3g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), *(str(path) for path in sources)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
    receipt = {"exit": completed.returncode,
               "original_sources": {str(path.relative_to(CASE)): hashlib.sha256(
                   path.read_bytes()).hexdigest() for path in SOURCE.rglob("*.java")},
               "generated_sources": {str(path.relative_to(HERE)): hashlib.sha256(
                   path.read_bytes()).hexdigest() for path in sources},
               "probe_classes": str(CLASSES),
               "instrumentation": "case-local source overrides around released classes; original JUnit operations and assertions unchanged; no graph"}
    (HERE / "build-probe.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
