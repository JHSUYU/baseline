#!/usr/bin/env python3
"""Run the original HDFS-48 JUnit with exact target and observed IPC hooks."""

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
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
            for name in ("asm", "asm-tree", "asm-commons")]
HDFS_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
COMMON_JAR = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
CLIENT_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
OVERLAY = BUILD / "overlay"
RESOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")
CLASS = "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots"
METHOD = "testRenameUndo_1"


def build_runner() -> None:
    sources = sorted((HERE / "src").glob("*.java"))
    marker = BUILD / "built.json"
    if marker.is_file() and marker.stat().st_mtime >= max(p.stat().st_mtime for p in sources):
        return
    classes = BUILD / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    junit = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
    cp = os.pathsep.join(map(str, [junit, *ASM_JARS, JACOCO_CORE, HDFS_JAR, COMMON_JAR, CLIENT_JAR]))
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(classes),
                    *(str(source) for source in sources)], check=True)
    OVERLAY.mkdir(parents=True, exist_ok=True)
    shutil.copy2(classes / "Hdfs48Probe.class", OVERLAY / "Hdfs48Probe.class")
    for name, jar in (("org/apache/hadoop/hdfs/server/namenode/INodeDirectory", HDFS_JAR),
                      ("org/apache/hadoop/ipc/Client", COMMON_JAR)):
        original = BUILD / "input" / (name + ".class")
        original.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(jar) as archive:
            original.write_bytes(archive.read(name + ".class"))
        subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join([str(classes), *map(str, ASM_JARS)]),
                        "PatchHdfs48", str(original), name, str(OVERLAY)], check=True)
    marker.write_text(json.dumps({"sources": [str(p) for p in sources]}) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--plan", type=str, default="")
    args = parser.parse_args()
    build_runner()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for name in ("data", "tmp", "logs"):
        (scratch / name).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"),
                                         "classpath", "--glob"], env=env,
                                        text=True).strip()
    m2 = Path("/users/ZhenyuLi/.m2/repository")
    extra = [m2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
             m2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
             m2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
             m2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar"]
    common_tests = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
    cp = os.pathsep.join([str(OVERLAY), str(BUILD / "classes"), str(RESOURCE), str(TESTS),
                          str(common_tests), hadoop_cp,
                          *(str(path) for path in extra),
                          *(str(path) for path in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))])
    command = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-Dhdfs48.trace=" + str(output / "runtime_trace.tsv"),
               "-Dhdfs48.plan=" + args.plan,
               "-javaagent:" + str(JACOCO) + "=destfile=" +
               str(output / "jacoco.exec") +
               ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false",
               "-cp", cp, "RunJUnitMethod", CLASS, METHOD]
    start = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            exit_code = subprocess.run(command, cwd=scratch, env=env,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       timeout=args.timeout, check=False).returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    result = {"case_id": "HDFS-48", "cluster_test": CLASS + "#" + METHOD,
              "returncode": exit_code,
              "elapsed_seconds": round(time.monotonic() - start, 3),
              "coverage": str(output / "jacoco.exec"),
              "junit_log": str(output / "junit.log"),
              "instrumentation": "released_jar_case_local_asm_target_and_ipc",
              "trace": str(output / "runtime_trace.tsv"), "plan": args.plan}
    if (output / "jacoco.exec").is_file() and (output / "jacoco.exec").stat().st_size:
        covered = output / "covered_probes.txt"
        with covered.open("w") as stream:
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join([str(BUILD / "classes"), str(JACOCO_CORE),
                                             *(str(p) for p in ASM_JARS)]),
                            "CoverageHdfs50", str(output / "jacoco.exec"),
                            str(OVERLAY), str(HDFS_JAR), str(CLIENT_JAR), str(COMMON_JAR)],
                           stdout=stream, check=True)
        result["covered_probes"] = str(covered)
        result["covered_probes_count"] = sum(1 for _ in covered.open())
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
