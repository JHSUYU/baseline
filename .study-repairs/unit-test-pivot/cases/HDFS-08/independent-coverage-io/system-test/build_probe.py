#!/usr/bin/env python3
"""Compile isolated source-level I/O and Journal guard probes from release JARs."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs08independent.Probe"
SOURCE = CASE / "source/main"
GENERATED = HERE / "generated"
CLASSES = HERE / "probe-classes"


def override(name: str, before: str, after: str) -> Path:
    original = SOURCE / name
    text = original.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise RuntimeError("no Java package in " + str(original))
    text = text[:package.end()] + "\nimport " + PROBE + ";" + text[package.end():]
    count = text.count(before)
    if count != 1:
        raise RuntimeError(f"expected one probe site in {name}, found {count}")
    output = GENERATED / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text.replace(before, after, 1))
    return output


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    journal = override(
        "org/apache/hadoop/hdfs/qjournal/server/Journal.java",
        "    // Invariant 25 from ZAB paper\n"
        "    if (reqInfo.getEpoch() < lastPromisedEpoch.get()) {\n"
        "      throw new IOException(\"IPC's epoch \" + reqInfo.getEpoch() +\n"
        "          \" is less than the last promised epoch \" +\n"
        "          lastPromisedEpoch.get() + \" ; journal id: \" + journalId);",
        "    // Invariant 25 from ZAB paper\n"
        "    final long hdfs08PromisedEpoch = lastPromisedEpoch.get();\n"
        "    Probe.guard(storage.getSingularStorageDir().getCurrentDir(),\n"
        "        journalId, reqInfo.getEpoch(), hdfs08PromisedEpoch,\n"
        "        reqInfo.getIpcSerialNumber());\n"
        "    if (reqInfo.getEpoch() < lastPromisedEpoch.get()) {\n"
        "      IOException hdfs08TargetException = new IOException(\n"
        "          \"IPC's epoch \" + reqInfo.getEpoch() +\n"
        "          \" is less than the last promised epoch \" +\n"
        "          lastPromisedEpoch.get() + \" ; journal id: \" + journalId);\n"
        "      Probe.targetException(hdfs08TargetException);\n"
        "      throw hdfs08TargetException;")
    journal_text = journal.read_text()
    finalize_before = (
        "  public synchronized void finalizeLogSegment(RequestInfo reqInfo, long startTxId,\n"
        "      long endTxId) throws IOException {\n"
        "    checkFormatted();\n"
        "    checkRequest(reqInfo);")
    finalize_after = (
        "  public synchronized void finalizeLogSegment(RequestInfo reqInfo, long startTxId,\n"
        "      long endTxId) throws IOException {\n"
        "    checkFormatted();\n"
        "    Probe.finalizeContext(startTxId, endTxId);\n"
        "    try {\n"
        "      checkRequest(reqInfo);\n"
        "    } finally {\n"
        "      Probe.clearFinalizeContext();\n"
        "    }")
    if journal_text.count(finalize_before) != 1:
        raise RuntimeError("finalizeLogSegment context site not unique")
    journal.write_text(journal_text.replace(finalize_before, finalize_after, 1))
    server = override(
        "org/apache/hadoop/hdfs/qjournal/server/JournalNodeRpcServer.java",
        "  void start() {\n    this.server.start();\n  }",
        "  void start() {\n    this.server.start();\n"
        "    Probe.registerPort(this.server.getListenerAddress().getPort(),\n"
        "        jn.getConf().get(DFSConfigKeys.DFS_JOURNALNODE_EDITS_DIR_KEY));\n"
        "  }")
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
        "      final long timeout, final TimeUnit unit) throws IOException {\n"
        "    synchronized (call) {",
        "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
        "      final long timeout, final TimeUnit unit) throws IOException {\n"
        "    Probe.rpcResponse(connection.remoteId.getAddress().getPort());\n"
        "    synchronized (call) {")
    epoch = override(
        "org/apache/hadoop/hdfs/util/PersistentLongFile.java",
        "    if (value != newVal || !loaded) {\n      writeFile(file, newVal);",
        "    if (value != newVal || !loaded) {\n"
        "      Probe.fileIo(\"EPOCH_FILE_WRITE\", file, \"set\");\n"
        "      writeFile(file, newVal);")
    edit = override(
        "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
        "  public void flushAndSync(boolean durable) throws IOException {\n"
        "    if (fp == null) {",
        "  public void flushAndSync(boolean durable) throws IOException {\n"
        "    Probe.fileIo(\"EDITLOG_FLUSH\", file,\n"
        "        durable ? \"durable\" : \"buffered\");\n"
        "    if (fp == null) {")
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx3g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), str(HERE / "Probe.java"),
               *(str(path) for path in (journal, server, rpc, epoch, edit))]
    with (HERE / "build-probe.log").open("w") as stream:
        compiled = subprocess.run(command, stdout=stream,
                                  stderr=subprocess.STDOUT)
    result = {"exit": compiled.returncode, "probe_classes": str(CLASSES),
              "source_release": "Hadoop 3.4.3 binary source JARs",
              "source_files": [str(path) for path in
                               (journal, server, rpc, epoch, edit)],
              "graphchecker_artifacts_used": False}
    (HERE / "build-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    if compiled.returncode:
        raise SystemExit(compiled.returncode)


if __name__ == "__main__":
    main()
