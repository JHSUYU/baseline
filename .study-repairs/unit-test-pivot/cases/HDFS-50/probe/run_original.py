#!/usr/bin/env python3
"""Run Hadoop 3.4.3's unchanged TestSnapshotCommands.testCreateSnapshot."""
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
OVERLAY = BUILD / "overlay"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
RUNNER = Path("/users/ZhenyuLi/.graphchecker-builds/unit-test-core-fe6105e3d-ddecf20edbf4.jar")
TEST_RESOURCES = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / component / "9.6" / (component + "-9.6.jar") for component in ("asm", "asm-tree", "asm-commons")]
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
TARGET = "org/apache/hadoop/hdfs/server/namenode/snapshot/DirectorySnapshottableFeature"
RPC = "org/apache/hadoop/ipc/Client"
FILE = "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream"
HDFS_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
COMMON_JAR = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
HDFS_CLIENT_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"


def build() -> None:
    marker = BUILD / "built.json"
    sources = [HERE / "src/Hdfs50Probe.java", HERE / "src/PatchHdfs50.java", HERE / "src/CoverageHdfs50.java"]
    if marker.is_file() and marker.stat().st_mtime > max(p.stat().st_mtime for p in sources):
        return
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / "classes"
    classes.mkdir(exist_ok=True)
    cp = os.pathsep.join(map(str, [*ASM_JARS, JACOCO_CORE]))
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(classes), *map(str, sources)], check=True)
    OVERLAY.mkdir(exist_ok=True)
    shutil.copy2(classes / "Hdfs50Probe.class", OVERLAY / "Hdfs50Probe.class")
    for name, archive in ((TARGET, HDFS_JAR), (RPC, COMMON_JAR), (FILE, HDFS_JAR)):
        input_class = BUILD / "input" / (name + ".class")
        input_class.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as jar:
            input_class.write_bytes(jar.read(name + ".class"))
        subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join([str(classes), cp]),
                        "PatchHdfs50", str(input_class), name, str(OVERLAY)], check=True)
    marker.write_text(json.dumps({"targets": [TARGET, RPC, FILE], "sources": [str(p) for p in sources]}) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    build()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for part in ("data", "tmp"):
        (scratch / part).mkdir(parents=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                      env=env, text=True).strip()
    test_cp = os.pathsep.join([str(TEST_RESOURCES), str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
                               str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"), base_cp,
                               *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))])
    cp = os.pathsep.join((str(OVERLAY), str(RUNNER), test_cp))
    trace = output / "runtime_trace.jsonl"
    coverage = output / "jacoco.exec"
    cmd = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
           "-Djava.net.preferIPv4Stack=true", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
           "-Dtest.build.data=" + str(scratch / "data"), "-Djava.io.tmpdir=" + str(scratch / "tmp"),
           "-Dhdfs50.trace=" + str(trace),
           "-javaagent:" + str(JACOCO) + "=destfile=" + str(coverage)
           + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true",
           *(["-Dhdfs50.plan=" + str(args.plan.resolve())] if args.plan else []),
           "-cp", cp, "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
           "org.apache.hadoop.hdfs.TestSnapshotCommands", "testCreateSnapshot"]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            status = subprocess.run(cmd, cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=args.timeout, check=False).returncode
        except subprocess.TimeoutExpired:
            status = 124
    manifest = {"case_id": "HDFS-50", "test": "org.apache.hadoop.hdfs.TestSnapshotCommands#testCreateSnapshot",
                "source_version": "Hadoop 3.4.3", "returncode": status,
                "elapsed_seconds": round(time.monotonic() - started, 3), "trace": str(trace),
                "coverage": str(coverage), "fault_plan": str(args.plan.resolve()) if args.plan else None,
                "log": str(output / "junit.log")}
    if coverage.is_file() and coverage.stat().st_size:
        covered = output / "covered_probes.txt"
        with covered.open("w") as stream:
            subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join((str(BUILD / "classes"), str(JACOCO_CORE), *(str(p) for p in ASM_JARS))),
                            "CoverageHdfs50", str(coverage), str(OVERLAY), str(HDFS_JAR),
                            str(HDFS_CLIENT_JAR), str(COMMON_JAR)], stdout=stream, check=True)
        manifest["covered_probes"] = str(covered)
        manifest["covered_probe_count"] = sum(1 for _ in covered.open())
        manifest["covered_method_count"] = sum(1 for _ in (output / "covered_methods.txt").open())
        manifest["covered_branch_count"] = sum(1 for _ in (output / "covered_branch_counts.txt").open())
        manifest["covered_line_count"] = sum(1 for _ in (output / "covered_lines.txt").open())
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
