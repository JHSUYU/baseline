#!/usr/bin/env python3
"""Run unchanged TestDFSStartupVersions.testVersions without GraphChecker."""
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
CASE = HERE.parent
BUILD = HERE / "build"
OVERLAY = BUILD / "overlay"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / x / "9.6" / (x + "-9.6.jar") for x in ("asm", "asm-tree", "asm-commons")]
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
RESOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")


def build() -> None:
    sources = list((HERE / "src").glob("*.java"))
    marker = BUILD / "built.json"
    if marker.is_file() and marker.stat().st_mtime > max(p.stat().st_mtime for p in sources):
        return
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / "classes"
    classes.mkdir(exist_ok=True)
    junit = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
    cp = os.pathsep.join(map(str, [*ASM_JARS, JACOCO_CORE, TESTS, HDFS, CLIENT, COMMON, junit]))
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(classes), *map(str, sources)], check=True)
    OVERLAY.mkdir(exist_ok=True)
    shutil.copy2(classes / "Hdfs22Probe.class", OVERLAY / "Hdfs22Probe.class")
    for name, jar in (("org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage", HDFS),
                      ("org/apache/hadoop/hdfs/server/datanode/DataStorage", HDFS),
                      ("org/apache/hadoop/ipc/Client", COMMON)):
        input_class = BUILD / "input" / (name + ".class")
        input_class.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(jar) as archive:
            input_class.write_bytes(archive.read(name + ".class"))
        subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join((str(classes), cp)),
                        "PatchHdfs22", str(input_class), name, str(OVERLAY)], check=True)
    marker.write_text(json.dumps({"source": [str(p) for p in sources]}) + "\n")


def main() -> None:
    # A coordinator can request migration after the active trial returns.
    # A later trial exits before its JVM starts, leaving a recoverable current
    # selector in the atomic checkpoint without repeating an executed test.
    if (HERE / "evidence/migrate-stop-after-current").is_file():
        raise SystemExit("Migration stop requested before starting the next JUnit")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args()
    build()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for suffix in ("data", "tmp", "logs"):
        (scratch / suffix).mkdir(parents=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env, text=True).strip()
    m2 = Path("/users/ZhenyuLi/.m2/repository")
    test_dependencies = [m2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
                         m2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
                         m2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
                         m2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar"]
    cp = os.pathsep.join((str(OVERLAY), str(BUILD / "classes"), str(RESOURCE), str(TESTS),
                          str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
                          hadoop_cp, *(str(p) for p in test_dependencies),
                          *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    cmd = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
           "-Djava.net.preferIPv4Stack=true", "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
           "-Dtest.build.data=" + str(scratch / "data"), "-Djava.io.tmpdir=" + str(scratch / "tmp"),
           "-Dhadoop.log.dir=" + str(scratch / "logs"),
           "-Dhdfs22.independent.trace=" + str(out / "runtime_trace.jsonl"),
           "-javaagent:" + str(JACOCO) + "=destfile=" + str(out / "jacoco.exec")
           + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false",
           *(["-Dhdfs22.independent.plan=" + str(args.plan.resolve())] if args.plan else []),
           "-cp", cp, "RunJUnitMethod", "org.apache.hadoop.hdfs.TestDFSStartupVersions", "testVersions"]
    start = time.monotonic()
    with (out / "junit.log").open("w") as log:
        try:
            status = subprocess.run(cmd, cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=args.timeout, check=False).returncode
        except subprocess.TimeoutExpired:
            status = 124
    manifest = {"case_id": "HDFS-22/HDFS-23/HDFS-25/HDFS-34/HDFS-35",
                "test": "org.apache.hadoop.hdfs.TestDFSStartupVersions#testVersions",
                "returncode": status, "elapsed_seconds": round(time.monotonic() - start, 3),
                "trace": str(out / "runtime_trace.jsonl"), "coverage": str(out / "jacoco.exec"),
                "plan": str(args.plan.resolve()) if args.plan else None}
    if (out / "jacoco.exec").is_file() and (out / "jacoco.exec").stat().st_size:
        covered = out / "covered_probes.txt"
        with covered.open("w") as stream:
            subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join((str(BUILD / "classes"), str(JACOCO_CORE), *(str(p) for p in ASM_JARS))),
                            "CoverageHdfs50", str(out / "jacoco.exec"), str(OVERLAY), str(HDFS), str(CLIENT), str(COMMON)],
                           stdout=stream, check=True)
        manifest["covered_probes"] = str(covered)
        for category in ("probes", "methods", "branch_counts", "lines"):
            filename = covered if category == "probes" else out / ("covered_" + category + ".txt")
            manifest["covered_" + category + "_count"] = sum(1 for _ in filename.open())
    tmp = out / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2) + "\n")
    tmp.replace(out / "manifest.json")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
