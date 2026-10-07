#!/usr/bin/env python3
"""Compile an isolated Hadoop 3.4.3 HDFS-16 DN actor overlay; no JUnit run."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent / "cases/HDFS-16/independent-coverage-io"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / name / "9.6" / f"{name}-9.6.jar" for name in
            ("asm", "asm-tree", "asm-commons", "asm-util", "asm-analysis")]
SOURCE_JAR = HADOOP / "share/hadoop/hdfs/sources/hadoop-hdfs-3.4.3-sources.jar"
OLD_CLASSES = CASE / "system-test/probe-classes"
BUILD = HERE / "build"
GENERATED = BUILD / "generated"
OVERLAY = BUILD / "overlay"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
PROBE = "org.apache.hadoop.hdfs.hdfs16independent.Probe"
CLIENT_PATH = "org/apache/hadoop/ipc/Client.java"
TRANSLATOR_PATH = "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB.java"


def exact(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError(f"expected one source site for {before!r}, found {text.count(before)}")
    return text.replace(before, after)


def import_probe(text: str) -> str:
    package = re.search(r"(?m)^package [\w.]+;$", text)
    if package is None:
        raise ValueError("package declaration absent")
    return text[:package.end()] + "\nimport " + PROBE + ";" + text[package.end():]


def client_source() -> str:
    text = (CASE / "source/main" / CLIENT_PATH).read_text()
    text = import_probe(text)
    return exact(text,
        "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
        "      final long timeout, final TimeUnit unit) throws IOException {\n"
        "    synchronized (call) {",
        "  private Writable getRpcResponse(final Call call, final Connection connection,\n"
        "      final long timeout, final TimeUnit unit) throws IOException {\n"
        "    Probe.rpcResponse(connection.remoteId.getAddress().getPort());\n"
        "    synchronized (call) {")


def translator_source() -> tuple[str, bytes]:
    with zipfile.ZipFile(SOURCE_JAR) as archive:
        raw = archive.read(TRANSLATOR_PATH)
    text = import_probe(raw.decode("utf-8"))
    text = exact(text,
        "  public DatanodeProtocolClientSideTranslatorPB(InetSocketAddress nameNodeAddr,\n"
        "      Configuration conf) throws IOException {\n"
        "    RPC.setProtocolEngine(conf, DatanodeProtocolPB.class,",
        "  public DatanodeProtocolClientSideTranslatorPB(InetSocketAddress nameNodeAddr,\n"
        "      Configuration conf) throws IOException {\n"
        "    Probe.registerNnPort(nameNodeAddr.getPort());\n"
        "    RPC.setProtocolEngine(conf, DatanodeProtocolPB.class,")
    # Each of these synchronous calls carries a DatanodeRegistration. Limit
    # binding to the actual IPC statement and restore in finally on exceptions.
    calls = (
        'resp = ipc(() -> rpcProxy.registerDatanode(NULL_CONTROLLER, builder.build()));',
        'resp = ipc(() -> rpcProxy.sendHeartbeat(NULL_CONTROLLER, builder.build()));',
        'resp = ipc(() -> rpcProxy.blockReport(NULL_CONTROLLER, builder.build()));',
        'resp = ipc(() -> rpcProxy.cacheReport(NULL_CONTROLLER, builder.build()));',
        'ipc(() -> rpcProxy.blockReceivedAndDeleted(NULL_CONTROLLER, builder.build()));',
        'ipc(() -> rpcProxy.errorReport(NULL_CONTROLLER, req));',
    )
    for call in calls:
        indent = "    "
        wrapped = ("String hdfs16PriorActor = Probe.bindDatanodeRpc(registration);\n"
                   + indent + "try {\n"
                   + indent + "  " + call + "\n"
                   + indent + "} finally {\n"
                   + indent + "  Probe.restoreDatanodeRpc(hdfs16PriorActor);\n"
                   + indent + "}")
        text = exact(text, call, wrapped)
    return text, raw


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    subprocess.run([sys.executable, str(HERE / "strict_receipt.py"), "--self-test"], check=True)
    if not OLD_CLASSES.is_dir():
        raise RuntimeError("historical probe classes unavailable")
    GENERATED.mkdir(parents=True, exist_ok=True)
    OVERLAY.mkdir(parents=True, exist_ok=True)
    for old in OLD_CLASSES.rglob("*.class"):
        dest = OVERLAY / old.relative_to(OLD_CLASSES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, dest)
    generated_client = GENERATED / CLIENT_PATH
    generated_translator = GENERATED / TRANSLATOR_PATH
    for path in (generated_client, generated_translator):
        path.parent.mkdir(parents=True, exist_ok=True)
    client = client_source()
    translator, translator_raw = translator_source()
    generated_client.write_text(client)
    generated_translator.write_text(translator)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    dependencies = sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    cp = os.pathsep.join((str(OVERLAY), base_cp,
        *(str(path) for path in dependencies)))
    command = [str(JDK / "javac"), "-J-Xmx2g", "-cp", cp,
               "-d", str(OVERLAY), str(HERE / "Probe.java"),
               str(HERE / "ProbeSmoke.java"),
               str(generated_client), str(generated_translator)]
    compile_run = subprocess.run(command, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (BUILD / "compile.log").write_text(compile_run.stdout)
    if compile_run.returncode:
        raise RuntimeError(f"javac failed; see {BUILD / 'compile.log'}")
    # The source-derived overlay must contain exactly the three new entrypoints.
    disasm = subprocess.check_output(
        [str(JDK / "javap"), "-cp", str(OVERLAY), "-c", "-private",
         "org.apache.hadoop.ipc.Client"], text=True)
    if disasm.count("Probe.rpcResponse") != 1 or "Probe.io" in disasm:
        raise RuntimeError("Client still uses coarse RPC hook")
    translator_disasm = subprocess.check_output(
        [str(JDK / "javap"), "-cp", str(OVERLAY), "-c", "-private",
         "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB"], text=True)
    if translator_disasm.count("Probe.bindDatanodeRpc") != 6:
        raise RuntimeError("translator DN RPC bind count drift")
    if translator_disasm.count("Probe.registerNnPort") != 1:
        raise RuntimeError("translator NN endpoint registration drift")
    verify_cp = os.pathsep.join((cp, *(str(path) for path in ASM_JARS)))
    for name in ("org/apache/hadoop/ipc/Client",
                 "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB",
                 "org/apache/hadoop/hdfs/hdfs16independent/Probe"):
        verified = subprocess.run(
            [str(JDK / "java"), "-cp", verify_cp,
             "org.objectweb.asm.util.CheckClassAdapter",
             str(OVERLAY / (name + ".class"))],
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if verified.stdout.strip() or verified.stderr.strip():
            raise RuntimeError(f"ASM verification failed for {name}: {verified.stdout}{verified.stderr}")
    # javap also parses the target/file hook classes copied unchanged.
    for name, required in (("org.apache.hadoop.hdfs.server.blockmanagement.BlockInfo",
                            ("Probe.guard", "Probe.targetException")),
                           ("org.apache.hadoop.hdfs.server.namenode.EditLogFileOutputStream",
                            ("Probe.io",))):
        prior_hook = subprocess.check_output(
            [str(JDK / "javap"), "-cp", str(OVERLAY), "-c", name], text=True)
        if any(hook not in prior_hook for hook in required):
            raise RuntimeError(f"historical target/file hooks missing in {name}")
    smoke_plan = BUILD / "smoke-plan.tsv"
    smoke_trace = BUILD / "smoke-trace.jsonl"
    smoke_plan.write_text("RPC_RESPONSE\tother\tdn:dn-one|bp:bp-one\t2\tEOFException\n")
    smoke_run = subprocess.run([str(JDK / "java"), "-cp", cp,
                                "ProbeSmoke", str(smoke_plan), str(smoke_trace)],
                               check=True, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    events = [json.loads(line) for line in smoke_trace.read_text().splitlines()]
    applied = [event for event in events if event["event"] == "FAULT_APPLIED"]
    observed = [event for event in events if event["event"] == "IO_OBSERVED"]
    guards = [event for event in events if event["event"] == "TARGET_GUARD"]
    if (len(applied) != 1 or applied[0]["senderActor"] != "dn:dn-one|bp:bp-one"
        or applied[0]["ordinal"] != 2 or applied[0]["peerPort"] != 19001
        or [(event["senderActor"], event["ordinal"]) for event in observed]
           != [("dn:dn-one|bp:bp-one", 1), ("dn:dn-one|bp:bp-one", 2),
               ("dn:dn-two|bp:bp-one", 1)]
        or len(guards) != 1 or guards[0]["blockId"] != 7
        or guards[0]["proposedGenerationStamp"] != 1002):
        raise RuntimeError(f"sender/target smoke failed: {smoke_run.stdout} {events}")
    receipt = {
        "case": "HDFS-16", "mode": "offline_compile_only",
        "source_jar": str(SOURCE_JAR),
        "original_translator_sha256": sha(translator_raw),
        "generated_translator_sha256": sha(translator.encode()),
        "generated_client_sha256": sha(client.encode()),
        "probe_sha256": sha((HERE / "Probe.java").read_bytes()),
        "translator_bound_rpc_methods": 6,
        "known_nn_endpoint_smoke": "pass",
        "sender_actor_and_target_context_smoke": "pass",
        "client_coarse_rpc_hooks": 0,
        "overlay": str(OVERLAY), "status": "compile_asm_verification_and_sender_smoke_pass",
    }
    (BUILD / "offline-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
