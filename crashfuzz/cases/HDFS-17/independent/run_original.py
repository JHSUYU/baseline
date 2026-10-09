#!/usr/bin/env python3
"""Run the released HDFS-17 cluster JUnit in a fresh local test directory.

This is the workload reachability step. It does not count as a fault trial.
"""

from __future__ import annotations

import argparse
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
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
TEST_SOURCES = HADOOP / "share/hadoop/hdfs/sources/hadoop-hdfs-3.4.3-test-sources.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
MOCKITO = Path("/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar")
BYTE_BUDDY = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar")
BYTE_BUDDY_AGENT = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar")
OBJENESIS = Path("/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar")
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
HDFS_CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
            for name in ("asm", "asm-tree", "asm-commons")]
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
TARGET_CLASS = "org/apache/hadoop/hdfs/server/blockmanagement/BlockManager$StatefulBlockInfo.class"
RPC_CLASS = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class"
TEST_CLASS = "org.apache.hadoop.hdfs.server.namenode.TestAddStripedBlocks"
TEST_METHOD = "testAddUCReplica"


def build_instrumentation() -> Path:
    overlay = BUILD / "overlay"
    marker = BUILD / "instrumented-built"
    sources = [HERE / name for name in
               ("Hdfs17Probe.java", "PatchHdfs17.java", "CoverageHdfs17.java")]
    if marker.is_file() and marker.stat().st_mtime > max(p.stat().st_mtime for p in sources):
        return overlay
    overlay.mkdir(parents=True, exist_ok=True)
    classpath = os.pathsep.join(str(p) for p in [*ASM_JARS, JACOCO_CORE])
    subprocess.run([str(JDK / "javac"), "-cp", classpath, "-d", str(BUILD),
                    *(str(p) for p in sources)], check=True)
    shutil.copy2(BUILD / "Hdfs17Probe.class", overlay / "Hdfs17Probe.class")
    with zipfile.ZipFile(HDFS) as archive:
        for name in (TARGET_CLASS, RPC_CLASS):
            input_class = BUILD / "input" / name
            input_class.parent.mkdir(parents=True, exist_ok=True)
            input_class.write_bytes(archive.read(name))
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), classpath)), "PatchHdfs17",
                            str(input_class), str(overlay)], check=True)
    marker.write_text("released HDFS 3.4.3; case-local ASM target and block-report hooks\n")
    return overlay


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--instrument", action="store_true")
    parser.add_argument("--plan", type=Path)
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
    resources = BUILD / "test-resources"
    resources.mkdir(exist_ok=True)
    with zipfile.ZipFile(TEST_SOURCES) as archive:
        (resources / "hdfs-site.xml").write_bytes(archive.read("hdfs-site.xml"))
    helper = HERE / "RunOriginalJUnit.java"
    compiled = BUILD / "RunOriginalJUnit.class"
    if not compiled.exists() or compiled.stat().st_mtime < helper.stat().st_mtime:
        subprocess.run([str(JDK / "javac"), "-cp", str(JUNIT), "-d", str(BUILD),
                        str(helper)], check=True)

    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                        env=env, text=True).strip()
    overlay = build_instrumentation() if args.instrument else None
    classpath = os.pathsep.join((*(str(p) for p in ([overlay] if overlay else [])),
                                 str(BUILD), str(resources), str(TESTS),
                                 str(COMMON_TESTS), str(HADOOP / "share/hadoop/hdfs/sources"),
                                 hadoop_cp, *(str(p) for p in
                                              (MOCKITO, BYTE_BUDDY, BYTE_BUDDY_AGENT,
                                               OBJENESIS)),
                                 *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib")
                                                           .glob("*.jar")))))
    command = [str(JDK / "java"), "-ea", "-Xmx4g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               *(["-Dhdfs17.trace=" + str(output / "runtime_trace.jsonl"),
                  "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
                  + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false"]
                 if args.instrument else []),
               *(["-Dhdfs17.plan=" + str(args.plan.resolve())] if args.plan else []),
               "-cp", classpath, "RunOriginalJUnit", TEST_CLASS, TEST_METHOD, "-"]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            returncode = subprocess.run(command, cwd=scratch, env=env,
                                        stdout=log, stderr=subprocess.STDOUT,
                                        timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            returncode = 124
    manifest = {"case_id": "HDFS-17", "test": TEST_CLASS + "#" + TEST_METHOD,
                "returncode": returncode,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "original_distribution": str(HADOOP),
                "graphchecker_runtime_used": False,
                "instrumented": args.instrument,
                "fault_plan": str(args.plan.resolve()) if args.plan else None,
                "log": str(output / "junit.log")}
    if args.instrument and (output / "jacoco.exec").is_file():
        with (output / "covered_probes.txt").open("w") as covered:
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), str(JACOCO_CORE),
                                             *(str(p) for p in ASM_JARS))),
                            "CoverageHdfs17", str(output / "jacoco.exec"),
                            str(overlay), str(HDFS), str(HDFS_CLIENT), str(COMMON)],
                           stdout=covered, check=True)
        for category in ("probes", "methods", "branch_counts", "lines"):
            path = output / ("covered_" + category + ".txt")
            manifest["covered_" + category + "_count"] = sum(1 for _ in path.open())
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(manifest))
    if returncode:
        raise SystemExit(returncode)


if __name__ == "__main__":
    main()
