#!/usr/bin/env python3
"""Run the Hadoop 3.4.3 TestBlockRecovery2 original embedded-cluster JUnit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
SOURCE_RESOURCES = HADOOP / "share/hadoop/hdfs/sources"
MOCKITO = Path("/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar")
BYTE_BUDDY = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar")
BYTE_BUDDY_AGENT = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar")
OBJENESIS = Path("/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar")
TEST_CLASS = "org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2"
TEST_METHOD = "testRecoveryTimeout"
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
HDFS_CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
            for name in ("asm", "asm-tree", "asm-commons")]
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
WORKER = "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.class"
TASK = "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker$RecoveryTaskContiguous.class"
RECORD = "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker$BlockRecord.class"
CLUSTER = "org/apache/hadoop/hdfs/MiniDFSCluster.class"
IPC = "org/apache/hadoop/ipc/Client$Connection.class"
DATASET = "org/apache/hadoop/hdfs/server/datanode/fsdataset/impl/FsDatasetImpl.class"
BPOS = "org/apache/hadoop/hdfs/server/datanode/BPOfferService.class"


def build_instrumentation(hadoop_cp: str) -> Path:
    overlay = BUILD / "overlay"
    marker = BUILD / "instrumented-built"
    sources = [HERE / name for name in
               ("RecoveryProbe.java", "PatchRecovery.java", "CoverageRecovery.java")]
    if marker.is_file() and marker.stat().st_mtime > max(p.stat().st_mtime for p in sources):
        return overlay
    overlay.mkdir(parents=True, exist_ok=True)
    classpath = os.pathsep.join((hadoop_cp, str(TESTS), str(COMMON_TESTS),
                                 *(str(p) for p in ASM_JARS), str(JACOCO_CORE)))
    subprocess.run([str(JDK / "javac"), "-cp", classpath, "-d", str(BUILD),
                    *(str(p) for p in sources)], check=True)
    shutil.copy2(BUILD / "RecoveryProbe.class", overlay / "RecoveryProbe.class")
    shutil.copy2(BUILD / "RecoveryProbe$Context.class",
                 overlay / "RecoveryProbe$Context.class")
    shutil.copy2(BUILD / "RecoveryProbe$ServerContext.class",
                 overlay / "RecoveryProbe$ServerContext.class")
    for archive_path, names in ((HDFS, (WORKER, TASK, RECORD, DATASET, BPOS)),
                                (TESTS, (CLUSTER,)), (COMMON, (IPC,))):
        with zipfile.ZipFile(archive_path) as archive:
            for name in names:
                input_class = BUILD / "input" / name
                input_class.parent.mkdir(parents=True, exist_ok=True)
                input_class.write_bytes(archive.read(name))
                subprocess.run([str(JDK / "java"), "-cp",
                                os.pathsep.join((str(BUILD), classpath)),
                                "PatchRecovery", str(input_class), str(overlay)], check=True)
    marker.write_text("released Hadoop 3.4.3 classes, case-local ASM, no GraphChecker\n")
    return overlay


def overlay_digest(overlay: Path) -> str:
    value = hashlib.sha256()
    for file in sorted(overlay.rglob("*.class")):
        value.update(str(file.relative_to(overlay)).encode())
        value.update(file.read_bytes())
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--instrument", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--test-class", default=TEST_CLASS)
    parser.add_argument("--test-method", default=TEST_METHOD)
    parser.add_argument("--test-resources", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for leaf in ("manifest.json", "runtime_trace.jsonl", "jacoco.exec",
                 "covered_probes.txt", "covered_methods.txt",
                 "covered_branch_counts.txt", "covered_lines.txt"):
        (output / leaf).unlink(missing_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True)
    BUILD.mkdir(exist_ok=True)
    source = HERE / "RunOriginalJUnit.java"
    class_file = BUILD / "RunOriginalJUnit.class"
    if not class_file.exists() or class_file.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(JDK / "javac"), "-cp", str(JUNIT), "-d", str(BUILD),
                        str(source)], check=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env, text=True).strip()
    overlay = build_instrumentation(hadoop_cp) if args.instrument else None
    classpath = os.pathsep.join((*(str(p) for p in ([overlay] if overlay else [])),
                                 str(BUILD),
                                 *([str(args.test_resources.resolve())]
                                   if args.test_resources else []),
                                 str(TESTS), str(COMMON_TESTS),
                                 str(SOURCE_RESOURCES), hadoop_cp,
                                 *(str(p) for p in (MOCKITO, BYTE_BUDDY,
                                                    BYTE_BUDDY_AGENT, OBJENESIS)),
                                 *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    command = [str(JDK / "java"), "-ea", "-Xverify:all", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               *(["-Dhdfs.recovery.trace=" + str(output / "runtime_trace.jsonl"),
                  "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
                  + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false"]
                 if args.instrument else []),
               *(["-Dhdfs.recovery.plan=" + str(args.plan.resolve())] if args.plan else []),
               "-cp", classpath, "RunOriginalJUnit", args.test_class, args.test_method]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            code = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    manifest = {"cases": ["HDFS-28", "HDFS-29", "HDFS-30"],
                "test": args.test_class + "#" + args.test_method,
                "test_resources": (str(args.test_resources.resolve())
                                   if args.test_resources else None),
                "original_distribution": str(HADOOP),
                "returncode": code,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "timeout_seconds": args.timeout,
                "timeout_exceeded": code == 124,
                "instrumented": args.instrument,
                "overlay_digest": overlay_digest(overlay) if overlay else None,
                "graphchecker_runtime_used": False,
                "log": str(output / "junit.log"),
                "trace": str(output / "runtime_trace.jsonl") if args.instrument else None,
                "coverage": str(output / "jacoco.exec") if args.instrument else None,
                "plan": str(args.plan.resolve()) if args.plan else None}
    if args.instrument and (output / "jacoco.exec").is_file():
        with (output / "covered_probes.txt").open("w") as covered:
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), str(JACOCO_CORE),
                                             *(str(p) for p in ASM_JARS))),
                            "CoverageRecovery", str(output / "jacoco.exec"),
                            str(overlay), str(HDFS), str(HDFS_CLIENT), str(COMMON)],
                           stdout=covered, check=True)
        for category in ("probes", "methods", "branch_counts", "lines"):
            path = output / ("covered_" + category + ".txt")
            manifest["covered_" + category + "_count"] = sum(1 for _ in path.open())
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(manifest))
    if code != 0:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
