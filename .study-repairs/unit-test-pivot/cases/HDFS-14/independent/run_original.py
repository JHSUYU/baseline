#!/usr/bin/env python3
"""Run the HDFS-14 original embedded-cluster JUnit without GraphChecker."""

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
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
MOCKITO = Path("/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar")
BYTE_BUDDY = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar")
BYTE_BUDDY_AGENT = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar")
OBJENESIS = Path("/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar")
SOURCE_RESOURCES = HADOOP / "share/hadoop/hdfs/sources"
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
            for name in ("asm", "asm-tree", "asm-commons")]
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
TARGET_CLASS = "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.class"
SASL_CLASS = "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer.class"
HDFS_CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
TEST_CLASS = "org.apache.hadoop.hdfs.TestEncryptedTransfer"
TEST_METHOD = "testEncryptedReadDefaultAlgorithmCipherSuite"


def build_instrumentation() -> Path:
    overlay = BUILD / "overlay"
    marker = BUILD / "instrumented-built"
    sources = [HERE / name for name in
               ("Hdfs14Probe.java", "PatchHdfs14.java", "CoverageHdfs14.java")]
    if marker.is_file() and marker.stat().st_mtime > max(p.stat().st_mtime for p in sources):
        return overlay
    overlay.mkdir(parents=True, exist_ok=True)
    classpath = os.pathsep.join(str(p) for p in [*ASM_JARS, JACOCO_CORE])
    subprocess.run([str(JDK / "javac"), "-cp", classpath, "-d", str(BUILD),
                    *(str(p) for p in sources)], check=True)
    shutil.copy2(BUILD / "Hdfs14Probe.class", overlay / "Hdfs14Probe.class")
    with zipfile.ZipFile(HDFS) as archive:
        for name in (TARGET_CLASS, SASL_CLASS):
            input_class = BUILD / "input" / name
            input_class.parent.mkdir(parents=True, exist_ok=True)
            input_class.write_bytes(archive.read(name))
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), classpath)), "PatchHdfs14",
                            str(input_class), str(overlay)], check=True)
    marker.write_text("released HDFS 3.4.3 target class; case-local ASM probe\n")
    return overlay


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--parameter", default="0", choices=("0", "1"))
    parser.add_argument("--method", default=TEST_METHOD)
    parser.add_argument("--timeout", default=360, type=int)
    parser.add_argument("--instrument", action="store_true")
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # An interrupted campaign can replay an active sequence in the same run
    # directory. Remove its previous observation before starting that replay.
    for leaf in ("manifest.json", "runtime_trace.jsonl", "jacoco.exec",
                 "covered_probes.txt", "covered_methods.txt",
                 "covered_branch_counts.txt", "covered_lines.txt"):
        (output / leaf).unlink(missing_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True)

    BUILD.mkdir(exist_ok=True)
    class_file = BUILD / "RunOriginalJUnit.class"
    source = HERE / "RunOriginalJUnit.java"
    if not class_file.exists() or class_file.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(JDK / "javac"), "-cp", str(JUNIT), "-d", str(BUILD),
                        str(source)], check=True)

    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                        env=env, text=True).strip()
    overlay = build_instrumentation() if args.instrument else None
    classpath = os.pathsep.join((*(str(p) for p in ([overlay] if overlay else [])),
                                 str(BUILD), str(TESTS), str(COMMON_TESTS),
                                 str(SOURCE_RESOURCES), hadoop_cp,
                                 *(str(p) for p in (MOCKITO, BYTE_BUDDY,
                                                    BYTE_BUDDY_AGENT, OBJENESIS)),
                                 *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    command = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               *(["-Dhdfs14.trace=" + str(output / "runtime_trace.jsonl"),
                  "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
                  + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false"]
                 if args.instrument else []),
               *(["-Dhdfs14.plan=" + str(args.plan.resolve())] if args.plan else []),
               "-cp", classpath, "RunOriginalJUnit", TEST_CLASS, args.method,
               args.parameter]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            exit_code = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    manifest = {"case_id": "HDFS-14", "test": TEST_CLASS + "#" + args.method
                + "[" + args.parameter + "]", "returncode": exit_code,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "log": str(output / "junit.log"), "original_distribution": str(HADOOP),
                "graphchecker_runtime_used": False,
                "instrumented": args.instrument,
                "trace": str(output / "runtime_trace.jsonl") if args.instrument else None,
                "coverage": str(output / "jacoco.exec") if args.instrument else None,
                "plan": str(args.plan.resolve()) if args.plan else None}
    if args.instrument and (output / "jacoco.exec").is_file():
        with (output / "covered_probes.txt").open("w") as covered:
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), str(JACOCO_CORE),
                                             *(str(p) for p in ASM_JARS))),
                            "CoverageHdfs14", str(output / "jacoco.exec"),
                            str(overlay), str(HDFS), str(HDFS_CLIENT), str(COMMON)],
                           stdout=covered, check=True)
        for category in ("probes", "methods", "branch_counts", "lines"):
            path = output / ("covered_" + category + ".txt")
            manifest["covered_" + category + "_count"] = sum(1 for _ in path.open())
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(manifest))
    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
