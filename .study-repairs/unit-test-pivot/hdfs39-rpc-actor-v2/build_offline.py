#!/usr/bin/env python3
"""Compile an isolated sender-aware HDFS-39 overlay; never run cluster JUnit."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent / "cases/HDFS-39/independent-coverage-io"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE_JAR = HADOOP / "share/hadoop/hdfs/sources/hadoop-hdfs-3.4.3-sources.jar"
CLIENT_SOURCE_JAR = HADOOP / "share/hadoop/hdfs/sources/hadoop-hdfs-client-3.4.3-sources.jar"
BUILD = HERE / "build"
GENERATED = BUILD / "generated"
OVERLAY = BUILD / "overlay"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / name / "9.6" / f"{name}-9.6.jar" for name in
            ("asm", "asm-tree", "asm-commons", "asm-util", "asm-analysis")]
PROBE = "org.apache.hadoop.hdfs.hdfs39independent.Probe"
CLIENT = "org/apache/hadoop/ipc/Client.java"
DN_TRANSLATOR = "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java"
CLIENT_TRANSLATOR = "org/apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB.java"
TEST = "org/apache/hadoop/hdfs/TestFileAppend.java"
TARGET = "org/apache/hadoop/hdfs/server/namenode/FSDirAppendOp.java"
FILE_IO = "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java"


def exact(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise RuntimeError(f"expected one released source site; found {text.count(before)}: {before[:90]}")
    return text.replace(before, after, 1)


def import_probe(text: str) -> str:
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise RuntimeError("released source has no package")
    return text[:package.end()] + "\nimport " + PROBE + ";" + text[package.end():]


def jar_source(name: str) -> tuple[str, bytes]:
    found = None
    for jar in (SOURCE_JAR, CLIENT_SOURCE_JAR):
        with zipfile.ZipFile(jar) as archive:
            if name in archive.namelist():
                found = archive.read(name)
                break
    if found is None:
        raise FileNotFoundError(name)
    original = found
    return import_probe(original.decode("utf-8")), original


def make_client() -> str:
    text = import_probe((CASE / "source/main" / CLIENT).read_text())
    text = exact(text,
        "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
        "      final long timeout, final TimeUnit unit) throws IOException {\n"
        "    synchronized (call) {",
        "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
        "      final long timeout, final TimeUnit unit) throws IOException {\n"
        "    Probe.rpcIo(\"RPC_RESPONSE_WAIT\", connection.getRemoteAddress().getPort());\n"
        "    synchronized (call) {")
    site = "        connection.sendRpcRequest(call);                 // send the rpc request"
    return exact(text, site,
        '        Probe.rpcIo("RPC_SEND", connection.getRemoteAddress().getPort());\n' + site)


def make_dn_translator() -> tuple[str, bytes]:
    text, raw = jar_source(DN_TRANSLATOR)
    before = "    ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));"
    after = """    java.util.SortedSet<Long> hdfs39BlockIds =
        new java.util.TreeSet<Long>();
    for (StorageReceivedDeletedBlocks hdfs39Storage : receivedAndDeletedBlocks) {
      for (ReceivedDeletedBlockInfo hdfs39Info : hdfs39Storage.getBlocks()) {
        hdfs39BlockIds.add(hdfs39Info.getBlock().getBlockId());
      }
    }
    Probe.Source hdfs39PreviousSource = Probe.requestSource(registration);
    String hdfs39PreviousContext = Probe.requestContext(
        "blockReceivedAndDeleted:blocks=" + hdfs39BlockIds.toString());
    try {
      ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));
    } finally {
      Probe.restoreRequestContext(hdfs39PreviousContext);
      Probe.restoreRequestSource(hdfs39PreviousSource);
    }"""
    return exact(text, before, after), raw


def make_client_translator() -> tuple[str, bytes]:
    text, raw = jar_source(CLIENT_TRANSLATOR)
    before = "    AppendResponseProto res = ipc(() -> rpcProxy.append(null, req));"
    after = """    String hdfs39PreviousContext = Probe.requestContext("append:" + src);
    AppendResponseProto res;
    try {
      res = ipc(() -> rpcProxy.append(null, req));
    } finally {
      Probe.restoreRequestContext(hdfs39PreviousContext);
    }"""
    return exact(text, before, after), raw


def make_test() -> str:
    text = import_probe((CASE / "source/test" / TEST).read_text())
    before = """    final MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf,
        builderBaseDir).numDataNodes(4).build();
    final DistributedFileSystem fs = cluster.getFileSystem();"""
    after = """    final MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf,
        builderBaseDir).numDataNodes(4).build();
    Probe.registerCluster(cluster.getDataNodes(),
        cluster.getNameNode().getNameNodeAddress().getPort(),
        cluster.getNamesystem().getBlockPoolId());
    final DistributedFileSystem fs = cluster.getFileSystem();"""
    return exact(text, before, after)


def make_target() -> str:
    text = import_probe((CASE / "source/main" / TARGET).read_text())
    before = """      if (lastBlock != null) {
        if (lastBlock.getBlockUCState() == BlockUCState.COMMITTED) {
          throw new RetriableException(
              new NotReplicatedYetException("append: lastBlock="
                  + lastBlock + " of src=" + path
                  + " is COMMITTED but not yet COMPLETE."));
        } else if (lastBlock.isComplete()
"""
    after = """      if (lastBlock != null) {
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
"""
    return exact(text, before, after)


def make_file_io() -> str:
    text = import_probe((CASE / "source/main" / FILE_IO).read_text())
    return exact(text,
        "  public void flushAndSync(boolean durable) throws IOException {\n"
        "    if (fp == null) {",
        "  public void flushAndSync(boolean durable) throws IOException {\n"
        '    Probe.io("FILE_FLUSH", durable ? "durable" : "buffered");\n'
        "    if (fp == null) {")


def make_coverage_dump() -> str:
    source = (CASE / "system-test/CoverageDump.java").read_text()
    source = exact(source, "public final class CoverageDump {",
                   "public final class CoverageDumpV2 {")
    source = exact(source,
        "for (String name : new String[] {TARGET, EDIT_LOG}) {",
        "for (String name : new String[] {TARGET, EDIT_LOG,\n"
        "        \"org/apache/hadoop/ipc/Client\",\n"
        "        \"org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB\",\n"
        "        \"org/apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB\"}) {")
    source = exact(source,
        'path.equals(EDIT_LOG + ".class")) {',
        'path.equals(EDIT_LOG + ".class") ||\n'
        '              path.equals("org/apache/hadoop/ipc/Client.class") ||\n'
        '              path.equals("org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.class") ||\n'
        '              path.equals("org/apache/hadoop/hdfs/protocolPB/ClientNamenodeProtocolTranslatorPB.class")) {')
    return source


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "strict_receipt.py"), "--self-test"],
                   check=True)
    GENERATED.mkdir(parents=True, exist_ok=True)
    OVERLAY.mkdir(parents=True, exist_ok=True)
    sources = {
        CLIENT: make_client(),
        TEST: make_test(),
        TARGET: make_target(),
        FILE_IO: make_file_io(),
    }
    sources[DN_TRANSLATOR], dn_raw = make_dn_translator()
    sources[CLIENT_TRANSLATOR], client_raw = make_client_translator()
    generated = []
    for name, source in sources.items():
        output = GENERATED / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(source)
        generated.append(output)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    deps = [CASE / "deps" / name for name in
            ("mockito-core-4.9.0.jar", "byte-buddy-1.12.16.jar",
             "byte-buddy-agent-1.12.16.jar", "objenesis-3.3.jar")]
    if any(not path.is_file() for path in deps):
        raise RuntimeError("original JUnit compiler dependencies missing")
    tools = sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    cp = os.pathsep.join((str(OVERLAY), str(CASE / "source/test-resources"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(path) for path in deps), base_cp,
        *(str(path) for path in tools)))
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", cp,
               "-d", str(OVERLAY), str(HERE / "Probe.java"),
               str(HERE / "ProbeSmoke.java"),
               str(CASE / "system-test/OriginalHdfs39Test.java"),
               *(str(path) for path in generated)]
    result = subprocess.run(command, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (BUILD / "compile.log").write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(f"javac failed; see {BUILD / 'compile.log'}")
    coverage_classes = BUILD / "coverage-classes"
    coverage_classes.mkdir(parents=True, exist_ok=True)
    coverage_cp = os.pathsep.join(str(path) for path in
                                  sorted((CASE / "deps").glob("*.jar")))
    coverage_source = GENERATED / "CoverageDumpV2.java"
    coverage_source.write_text(make_coverage_dump())
    subprocess.run([str(JDK / "javac"), "-cp", coverage_cp,
                    "-d", str(coverage_classes),
                    str(coverage_source)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    required = {
        "org.apache.hadoop.ipc.Client": ("Probe.rpcIo",),
        "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB":
            ("Probe.requestSource", "Probe.requestContext", "Probe.restoreRequestSource"),
        "org.apache.hadoop.hdfs.protocolPB.ClientNamenodeProtocolTranslatorPB":
            ("Probe.requestContext", "Probe.restoreRequestContext"),
        "org.apache.hadoop.hdfs.TestFileAppend": ("Probe.registerCluster",),
        "org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp":
            ("Probe.guard", "Probe.targetException"),
        "org.apache.hadoop.hdfs.server.namenode.EditLogFileOutputStream": ("Probe.io",),
    }
    verify_cp = os.pathsep.join((cp, *(str(path) for path in ASM_JARS)))
    for name, hooks in required.items():
        code = subprocess.check_output([str(JDK / "javap"), "-cp", str(OVERLAY),
                                        "-c", "-private", name], text=True)
        if any(hook not in code for hook in hooks):
            raise RuntimeError(f"missing hook in {name}: {hooks}")
        if name == "org.apache.hadoop.ipc.Client" and code.count("Probe.rpcIo") != 2:
            raise RuntimeError("expected one send and one response hook")
        if name == "org.apache.hadoop.ipc.Client" and "Probe.io" in code:
            raise RuntimeError("coarse RPC hook remains")
        classname = name.replace(".", "/")
        verified = subprocess.run(
            [str(JDK / "java"), "-cp", verify_cp,
             "org.objectweb.asm.util.CheckClassAdapter", str(OVERLAY / (classname + ".class"))],
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if verified.stdout.strip() or verified.stderr.strip():
            raise RuntimeError(f"ASM verify failed for {name}: {verified.stdout}{verified.stderr}")
    smoke_plan = BUILD / "smoke-plan.tsv"
    smoke_trace = BUILD / "smoke-trace.jsonl"
    smoke_plan.write_text("RPC_SEND\tDatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"
                          "[blockReceivedAndDeleted:blocks=[7]]\tnn0<-dn1\t1\tEOFException\n")
    smoke = subprocess.run([str(JDK / "java"), "-cp", cp,
                            "org.apache.hadoop.hdfs.hdfs39independent.ProbeSmoke",
                            str(smoke_plan), str(smoke_trace)],
                           check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    events = [json.loads(line) for line in smoke_trace.read_text().splitlines()]
    applied = [event for event in events if event["event"] == "FAULT_APPLIED"]
    observed = [event for event in events if event["event"] == "IO_OBSERVED"]
    unbound = [event for event in events if event["event"] == "RPC_ACTOR_UNBOUND"]
    guards = [event for event in events if event["event"] == "TARGET_GUARD"]
    if (len(applied) != 1 or applied[0]["endpoint"] != "nn0<-dn1"
            or applied[0]["peerPort"] != 19001
            or applied[0]["sourceUuid"] != "uuid-1"
            or applied[0]["blockPoolId"] != "bp-one"
            or [(event["endpoint"], event["ordinal"]) for event in observed]
            != [("nn0<-dn0", 1), ("nn0<-dn1", 1)]
            or len(unbound) != 4 or len(guards) != 1
            or guards[0]["path"] != "/testMultipleAppend/foo"
            or guards[0]["blockId"] != 7
            or len([e for e in events if e["event"] == "DN_ROLE_MAP"]) != 4):
        raise RuntimeError(f"actor smoke mismatch: {smoke.stdout} {events}")
    receipt = {"case": "HDFS-39", "mode": "offline_only",
               "original_dn_translator_sha256": sha(dn_raw),
               "original_client_translator_sha256": sha(client_raw),
               "generated_source_sha256": {name: sha(source.encode()) for name, source in sources.items()},
               "probe_sha256": sha((HERE / "Probe.java").read_bytes()),
               "status": "javac_asm_actor_smoke_pass", "cluster_junit_runs": 0,
               "overlay": str(OVERLAY)}
    (BUILD / "offline-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
