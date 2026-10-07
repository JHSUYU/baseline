#!/usr/bin/env python3
"""Build separate HDFS-07/09/10 endpoint-aware overlays without running JUnit."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "cases"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
PROTO = next((HADOOP / "share/hadoop/hdfs/lib").glob("hadoop-shaded-protobuf*.jar"))
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / name / "9.6" / f"{name}-9.6.jar" for name in
            ("asm", "asm-tree", "asm-commons", "asm-util", "asm-analysis")]
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/java")
JAVAC = JAVA.with_name("javac")


def exact_replace(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"expected one source replacement, got {text.count(old)} for {old!r}")
    return text.replace(old, new)


def adapted_probe(case: str) -> str:
    source = (BASE / f"HDFS-{case}" / "independent/src" /
              f"Hdfs{case}Probe.java").read_text()
    old = re.search(r"  public static void ipcResponse\(\) throws IOException \{.*?\n  \}",
                    source, re.DOTALL)
    if old is None:
        raise ValueError(f"HDFS-{case} IPC probe signature changed")
    new = ("  public static void ipcResponse(int port) throws IOException {\n"
           "    String source = QjmRpcActor.resolve(port);\n"
           "    if (source == null) {\n"
           '      emit("RPC_ACTOR_UNBOUND", ",\\\"port\\\":" + port);\n'
           "      return; // An unrelated/unknown RPC is never an injection point.\n"
           "    }\n"
           '    emit("RPC_PEER_RESOLVED", ",\\\"port\\\":" + port + ",\\\"journalNode\\\":" + q(source));\n'
           '    io("FAULT:HDFS_QJM_RPC:RESPONSE", "Client.getRpcResponse", source);\n'
           "  }")
    source = source[:old.start()] + new + source[old.end():]
    register = ("  public static void registerPort(int port, String storageRoot) {\n"
                "    QjmRpcActor.registerPort(port, storageRoot);\n"
                "    String actor = QjmRpcActor.resolve(port);\n"
                '    emit("NODE_PORT_REGISTER", ",\\\"port\\\":" + port + ",\\\"journalNode\\\":" + q(actor)\n'
                '        + ",\\\"storageRoot\\\":" + q(storageRoot));\n'
                "  }\n\n")
    source = source.replace("  public static void ipcResponse(int port)",
                            register + "  public static void ipcResponse(int port)", 1)
    if case in ("09", "10"):
        field = "allowed" if case == "09" else "epochsEqual"
        old_field = f'        + ",\\"{field}\\":"'
        new_field = ('        + ",\\"journalNode\\":" + q(QjmRpcActor.targetActor())'
                     f' + ",\\"{field}\\":"')
        source = exact_replace(source, old_field, new_field)
        # The return/throw records follow the same thread-bound check. The check
        # event itself carries the actor used for strict post-fault matching.
    return source


def build(case: str) -> None:
    if case not in ("07", "09", "10"):
        raise ValueError(case)
    prior = BASE / f"HDFS-{case}" / "independent/build/overlay"
    if not prior.is_dir():
        raise RuntimeError(f"prior case overlay unavailable: {prior}")
    work = HERE / "build" / f"HDFS-{case}"
    generated = work / "src"
    classes = work / "classes"
    overlay = work / "overlay"
    generated.mkdir(parents=True, exist_ok=True)
    classes.mkdir(parents=True, exist_ok=True)
    overlay.mkdir(parents=True, exist_ok=True)
    # Preserve the case-local target/file hooks; the V2 overlay is self-contained.
    for old_class in prior.rglob("*.class"):
        copied = overlay / old_class.relative_to(prior)
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_class, copied)
    probe = f"Hdfs{case}Probe"
    (generated / f"{probe}.java").write_text(adapted_probe(case))
    cp = ":".join(map(str, [*ASM_JARS, HDFS, CLIENT, COMMON, PROTO]))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=dict(os.environ, JAVA_HOME=str(JAVA.parent.parent)), text=True).strip()
    subprocess.run([str(JAVAC), "-cp", cp, "-d", str(classes),
                    str(HERE / "QjmRpcActor.java"), str(HERE / "QjmRpcActorSmoke.java"),
                    str(HERE / "PatchQjmRpcActorV2.java"), str(generated / f"{probe}.java")],
                   check=True)
    subprocess.run([str(JAVA), "-cp", str(classes), "QjmRpcActorSmoke"], check=True)
    shutil.copy2(classes / f"{probe}.class", overlay / f"{probe}.class")
    shutil.copy2(classes / "QjmRpcActor.class", overlay / "QjmRpcActor.class")
    names = ["org/apache/hadoop/ipc/Client",
             "org/apache/hadoop/hdfs/qjournal/server/JournalNodeRpcServer"]
    if case in ("09", "10"):
        names.append("org/apache/hadoop/hdfs/qjournal/server/Journal")
    for name in names:
        source_file = prior / (name + ".class")
        if name.endswith("JournalNodeRpcServer"):
            source_file = work / "input" / (name + ".class")
            source_file.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(HDFS) as archive:
                source_file.write_bytes(archive.read(name + ".class"))
        if not source_file.is_file():
            raise RuntimeError(f"required original case hook missing: {source_file}")
        subprocess.run([str(JAVA), "-cp", f"{classes}:{cp}", "PatchQjmRpcActorV2",
                        str(source_file), name, probe, str(overlay)], check=True)
        # CheckClassAdapter validates the offline bytecode without a cluster.
        verified = subprocess.run(
            [str(JAVA), "-cp", f"{overlay}:{classes}:{cp}:{hadoop_cp}",
             "org.objectweb.asm.util.CheckClassAdapter", str(overlay / (name + ".class"))],
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if verified.stdout.strip() or verified.stderr.strip():
            raise RuntimeError(f"ASM verification failed for {name}: {verified.stdout}{verified.stderr}")
    print(f"HDFS-{case} offline overlay PASS: {overlay}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*", default=["07", "09", "10"])
    args = parser.parse_args()
    subprocess.run([sys.executable, str(HERE / "strict_receipt.py"), "--self-test"], check=True)
    for case in args.cases:
        build(case)
