#!/usr/bin/env python3
"""Run an unchanged Hadoop 3.4.3 embedded-cluster JUnit for source-map calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build-original-hdfs-junit"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
RESOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")


def build() -> None:
    source = HERE / "RunOriginalHdfsJUnit.java"
    target = BUILD / "RunOriginalHdfsJUnit.class"
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return
    BUILD.mkdir(parents=True, exist_ok=True)
    junit = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
    subprocess.run([str(JDK / "javac"), "-cp", str(junit), "-d", str(BUILD),
                    str(source)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--test-class", required=True)
    parser.add_argument("--test-method", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    build()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for suffix in ("data", "tmp", "logs"):
        (scratch / suffix).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                         env=env, text=True).strip()
    m2 = Path("/users/ZhenyuLi/.m2/repository")
    extra = [m2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
             m2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
             m2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
             m2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar"]
    cp = os.pathsep.join([str(BUILD), str(RESOURCE), str(TESTS),
                          str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
                          hadoop_cp, *(str(path) for path in extra),
                          *(str(path) for path in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))])
    assert not any(("graphchecker" in part.lower() or "causynth" in part.lower())
                   and part.lower().endswith(".jar") for part in cp.split(os.pathsep))
    command = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
               + ",includes=org.apache.hadoop.hdfs.*,dumponexit=true,append=false",
               "-cp", cp, "RunOriginalHdfsJUnit", args.test_class, args.test_method]
    start = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            status = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=args.timeout,
                                    check=False).returncode
        except subprocess.TimeoutExpired:
            status = 124
    manifest = {"case_id": args.case_id, "cluster_test": args.test_class + "#" + args.test_method,
                "returncode": status, "elapsed_seconds": round(time.monotonic() - start, 3),
                "classpath_sha256": hashlib.sha256(cp.encode()).hexdigest(),
                "original_test_jar_sha256": hashlib.sha256(TESTS.read_bytes()).hexdigest(),
                "jacoco_exec": str(output / "jacoco.exec"),
                "junit_log": str(output / "junit.log"),
                "graphchecker_runtime": False, "target_probe": False}
    temp = output / "manifest.json.tmp"
    temp.write_text(json.dumps(manifest, indent=2) + "\n")
    temp.replace(output / "manifest.json")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
