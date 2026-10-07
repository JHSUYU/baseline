#!/usr/bin/env python3
"""Compile case-local source probes for the exact guard and observed I/O."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import zipfile

from run_original import CASE, HERE, HADOOP, JDK, classpath

PROBE = "org.apache.hadoop.hdfs.hdfs16independent.Probe"
REGISTRY = "org.apache.hadoop.hdfs.hdfs16independent.Hdfs16ActorRegistry"
SOURCE = CASE / "source/main"
GENERATED = HERE / "generated"
CLASSES = HERE / "probe-classes"


def override(name: str, replacement: tuple[str, str]) -> Path:
    original = SOURCE / name
    text = original.read_text()
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise RuntimeError(f"no Java package declaration in {original}")
    text = (text[:package.end()] + "\nimport " + PROBE + ";\nimport "
            + REGISTRY + ";" + text[package.end():])
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
        ("    Preconditions.checkState(uc != null && !isComplete());\n"
         "    // Set the generation stamp for the block.",
         "    final boolean hdfs16Allowed = uc != null && !isComplete();\n"
         "    Probe.guard(hdfs16Allowed, getBlockId(), getGenerationStamp(),\n"
         "        genStamp, uc != null);\n"
         "    try {\n"
         "      Preconditions.checkState(hdfs16Allowed);\n"
         "    } catch (IllegalStateException hdfs16TargetException) {\n"
         "      Probe.targetException(hdfs16TargetException);\n"
         "      throw hdfs16TargetException;\n"
         "    }\n"
         "    // Set the generation stamp for the block."))
    rpc = override(
        "org/apache/hadoop/ipc/Client.java",
        ("  private Writable getRpcResponse(final Call call, final Connection connection,\n"
         "      final long timeout, final TimeUnit unit) throws IOException {\n"
         "    synchronized (call) {",
         "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
         "      final long timeout, final TimeUnit unit) throws IOException {\n"
         "    Probe.io(\"RPC_RESPONSE\", \"Client.getRpcResponse\",\n"
         "        connection.getRemoteAddress(), call.id);\n"
         "    synchronized (call) {"))
    file_io = override(
        "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
        ("  public void flushAndSync(boolean durable) throws IOException {\n"
         "    if (fp == null) {",
         "  public void flushAndSync(boolean durable) throws IOException {\n"
         "    Probe.io(\"FILE_FLUSH\", durable ? \"durable\" : \"buffered\",\n"
         "        null, -1);\n"
         "    if (fp == null) {"))
    registration = override(
        "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java",
        ("  public DatanodeRegistration registerDatanode(DatanodeRegistration registration\n"
         "      ) throws IOException {\n"
         "    RegisterDatanodeRequestProto.Builder builder = RegisterDatanodeRequestProto\n"
         "        .newBuilder().setRegistration(PBHelper.convert(registration));\n"
         "    RegisterDatanodeResponseProto resp;\n"
         "    resp = ipc(() -> rpcProxy.registerDatanode(NULL_CONTROLLER, builder.build()));\n\n"
         "    return PBHelper.convert(resp.getRegistration());\n"
         "  }",
         "  public DatanodeRegistration registerDatanode(DatanodeRegistration registration\n"
         "      ) throws IOException {\n"
         "    Hdfs16ActorRegistry.beginRegistration(registration);\n"
         "    try {\n"
         "      RegisterDatanodeRequestProto.Builder builder = RegisterDatanodeRequestProto\n"
         "          .newBuilder().setRegistration(PBHelper.convert(registration));\n"
         "      RegisterDatanodeResponseProto resp;\n"
         "      resp = ipc(() -> rpcProxy.registerDatanode(NULL_CONTROLLER, builder.build()));\n\n"
         "      return PBHelper.convert(resp.getRegistration());\n"
         "    } finally {\n"
         "      Hdfs16ActorRegistry.endRegistration();\n"
         "    }\n"
         "  }"))
    cp = classpath()
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", str(CLASSES) + ":" + cp,
               "-d", str(CLASSES), str(HERE / "Probe.java"),
               str(HERE / "Hdfs16ActorRegistry.java"), str(block),
               str(rpc), str(file_io), str(registration)]
    with (HERE / "build-probe.log").open("w") as stream:
        completed = subprocess.run(command, stdout=stream,
                                   stderr=subprocess.STDOUT)
    record = {"exit": completed.returncode, "probe_classes": str(CLASSES),
              "original_sources": [str(SOURCE / path) for path in (
                  "org/apache/hadoop/hdfs/server/blockmanagement/BlockInfo.java",
                  "org/apache/hadoop/ipc/Client.java",
                  "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java",
                  "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java")],
              "instrumentation": "isolated source-level probes; no GraphChecker or graph artifacts"}
    if completed.returncode == 0:
        actor_classes = HERE / "actor-patch-classes"
        actor_classes.mkdir(parents=True, exist_ok=True)
        asm = ":".join(str(CASE / "deps" / name) for name in (
            "asm-9.10.1.jar", "asm-tree-9.10.1.jar"))
        subprocess.run([str(JDK / "javac"), "-cp", asm, "-d", str(actor_classes),
                        str(HERE / "PatchHdfs16Actor.java")], check=True)
        archives = (
            ("org/apache/hadoop/hdfs/MiniDFSCluster", "hadoop-hdfs-3.4.3-tests.jar"),
            ("org/apache/hadoop/hdfs/server/datanode/DataNode", "hadoop-hdfs-3.4.3.jar"),
            ("org/apache/hadoop/hdfs/server/datanode/BPServiceActor", "hadoop-hdfs-3.4.3.jar"),
        )
        raw = HERE / "actor-patch-input"
        (HERE / "build-actor.log").write_text("")
        for internal, archive in archives:
            jar = HADOOP / "share/hadoop/hdfs" / archive
            target = raw / (internal + ".class")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(jar) as source:
                target.write_bytes(source.read(internal + ".class"))
            patched = subprocess.run(
                [str(JDK / "java"), "-cp", str(actor_classes) + ":" + asm,
                 "PatchHdfs16Actor", str(target), internal, str(CLASSES)],
                capture_output=True, text=True)
            with (HERE / "build-actor.log").open("a") as stream:
                stream.write(patched.stdout + patched.stderr)
            if patched.returncode:
                raise RuntimeError("actor patch failed for " + internal)
        record["actor_patch"] = "three original Hadoop classes patched"
    (HERE / "build-probe.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
