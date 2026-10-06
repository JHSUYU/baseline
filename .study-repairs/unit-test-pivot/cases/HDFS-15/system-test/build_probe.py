#!/usr/bin/env python3
"""Compile case-local source probes for the exact guard and observed I/O."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from run_original import CASE, HERE, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs15baseline.Probe"
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
    block = override(
        "org/apache/hadoop/hdfs/server/blockmanagement/BlockInfo.java",
        ("    Preconditions.checkState(!isComplete());\n    uc.commit();",
         "    final boolean hdfs15Allowed = !isComplete();\n"
         "    Probe.guard(hdfs15Allowed, getBlockId(), block.getBlockId());\n"
         "    try {\n"
         "      Preconditions.checkState(hdfs15Allowed);\n"
         "    } catch (IllegalStateException hdfs15TargetException) {\n"
         "      Probe.targetException(hdfs15TargetException);\n"
         "      throw hdfs15TargetException;\n"
         "    }\n"
         "    uc.commit();"))
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
               "-d", str(CLASSES), str(HERE / "Probe.java"), str(block),
               str(rpc), str(file_io)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream,
                                   stderr=subprocess.STDOUT)
    record = {"exit": completed.returncode, "probe_classes": str(CLASSES),
              "original_sources": [str(SOURCE / path) for path in (
                  "org/apache/hadoop/hdfs/server/blockmanagement/BlockInfo.java",
                  "org/apache/hadoop/ipc/Client.java",
                  "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java")],
              "instrumentation": "isolated source-level probes; no GraphChecker or graph artifacts"}
    (HERE / "build-probe.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
