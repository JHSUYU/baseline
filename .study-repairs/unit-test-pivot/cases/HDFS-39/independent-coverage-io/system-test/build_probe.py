#!/usr/bin/env python3
"""Compile case-local source probes from pristine Hadoop 3.4.3 sources."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs39independent.Probe"
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
        """      if (lastBlock != null) {
        if (lastBlock.getBlockUCState() == BlockUCState.COMMITTED) {
          throw new RetriableException(
              new NotReplicatedYetException("append: lastBlock="
                  + lastBlock + " of src=" + path
                  + " is COMMITTED but not yet COMPLETE."));
        } else if (lastBlock.isComplete()
""",
        """      if (lastBlock != null) {
        final BlockUCState hdfs39State = lastBlock.getBlockUCState();
        final boolean hdfs39Committed = hdfs39State == BlockUCState.COMMITTED;
        Probe.guard(hdfs39Committed, path, lastBlock.getBlockId(),
            hdfs39State.name());
        if (hdfs39Committed) {
          RetriableException hdfs39Target = new RetriableException(
              new NotReplicatedYetException("append: lastBlock="
                  + lastBlock + " of src=" + path
                  + " is COMMITTED but not yet COMPLETE."));
          Probe.targetException(hdfs39Target);
          throw hdfs39Target;
        } else if (lastBlock.isComplete()
""")
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        """  private Writable getRpcResponse(final Call call, final Connection connection,
      final long timeout, final TimeUnit unit) throws IOException {
    synchronized (call) {""",
        """  private Writable getRpcResponse(final Call call, final Connection connection,
      final long timeout, final TimeUnit unit) throws IOException {
    Probe.io("RPC_RESPONSE", "Client.getRpcResponse");
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
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), str(HERE / "Probe.java"), str(target),
               str(rpc), str(file_io)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream,
                                   stderr=subprocess.STDOUT)
    record = {"exit": completed.returncode, "probe_classes": str(CLASSES),
              "original_sources": [str(SOURCE / path) for path in (
                  "org/apache/hadoop/hdfs/server/namenode/FSDirAppendOp.java",
                  "org/apache/hadoop/ipc/Client.java",
                  "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java")],
              "instrumentation": "isolated source-level probes; no GraphChecker or graph artifacts"}
    (HERE / "build-probe.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
