#!/usr/bin/env python3
"""Compile case-local source probes for the exact guard and observed I/O."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs21independent.Probe"
SOURCE = CASE / "source/main"
GENERATED = HERE / "generated"
CLASSES = HERE / "probe-classes"


def override(name: str, replacement: tuple[str, str]) -> Path:
    original = SOURCE / name
    text = original.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise RuntimeError(f"no Java package declaration in {original}")
    text = text[:package.end()] + "\nimport " + PROBE + ";" + text[package.end():]
    before, after = replacement
    if text.count(before) != 1:
        raise RuntimeError(f"expected one probe site in {original}: {text.count(before)}")
    text = text.replace(before, after, 1)
    output = GENERATED / name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return output


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    actor = override(
        "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java",
        ("    String minimumNameNodeVersion = dnConf.getMinimumNameNodeVersion();\n"
         "    if (VersionUtil.compareVersions(nnVersion, minimumNameNodeVersion) < 0) {",
         "    String minimumNameNodeVersion = dnConf.getMinimumNameNodeVersion();\n"
         "    final boolean hdfs21Allowed =\n"
         "        VersionUtil.compareVersions(nnVersion, minimumNameNodeVersion) >= 0;\n"
         "    Probe.guard(hdfs21Allowed, this, nnVersion, minimumNameNodeVersion);\n"
         "    if (!hdfs21Allowed) {"))
    generated = actor.read_text()
    constructor_end = ("    commandProcessingThread = new CommandProcessingThread(this);\n"
                       "    commandProcessingThread.start();\n"
                       "  }")
    if generated.count(constructor_end) != 1:
        raise RuntimeError("expected one BPServiceActor constructor end")
    generated = generated.replace(constructor_end,
                                  constructor_end.replace("  }",
                                                          "    Probe.actorCreated(this);\n"
                                                          "  }"), 1)
    throw_site = ("      LOG.warn(ive.getMessage());\n"
                  "      throw ive;")
    if generated.count(throw_site) != 1:
        raise RuntimeError("expected one IncorrectVersionException throw")
    actor.write_text(generated.replace(
        throw_site, "      LOG.warn(ive.getMessage());\n"
                    "      Probe.targetException(ive);\n"
                    "      throw ive;", 1))
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        ("  private Writable getRpcResponse(final Call call, final Connection connection,\n"
         "      final long timeout, final TimeUnit unit) throws IOException {\n"
         "    synchronized (call) {",
         "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
         "      final long timeout, final TimeUnit unit) throws IOException {\n"
         "    Probe.io(\"RPC_RESPONSE\", \"Client.getRpcResponse\");\n"
         "    synchronized (call) {"))
    file_io = override(
        "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
        ("  public void flushAndSync(boolean durable) throws IOException {\n"
         "    if (fp == null) {",
         "  public void flushAndSync(boolean durable) throws IOException {\n"
         "    Probe.io(\"FILE_FLUSH\", durable ? \"durable\" : \"buffered\");\n"
         "    if (fp == null) {"))
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), str(HERE / "Probe.java"), str(actor),
               str(rpc), str(file_io)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream,
                                   stderr=subprocess.STDOUT)
    record = {"exit": completed.returncode, "probe_classes": str(CLASSES),
              "original_sources": [str(SOURCE / path) for path in (
                  "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java",
                  "org/apache/hadoop/ipc/Client.java",
                  "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java")],
              "instrumentation": "isolated source-level probes; no GraphChecker or graph artifacts"}
    (HERE / "build-probe.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
