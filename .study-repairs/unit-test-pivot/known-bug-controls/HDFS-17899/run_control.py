#!/usr/bin/env python3
"""Run original Hadoop 3.4.3 encrypted Balancer embedded-cluster JUnit."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE_RESOURCES = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
MOCKITO = Path("/users/ZhenyuLi/.m2/repository/org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar")
BYTE_BUDDY = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar")
BYTE_BUDDY_AGENT = Path("/users/ZhenyuLi/.m2/repository/net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar")
OBJENESIS = Path("/users/ZhenyuLi/.m2/repository/org/objenesis/objenesis/3.3/objenesis-3.3.jar")
TEST_CLASS = "org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer"
TEST_METHOD = "testEncryptedBalancer0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--inject", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True)
    BUILD.mkdir(exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"),
        "classpath", "--glob"], env=env, text=True).strip()
    tool_jars = [TESTS, COMMON_TESTS, JUNIT, MOCKITO,
                 BYTE_BUDDY, BYTE_BUDDY_AGENT, OBJENESIS]
    tool_jars += sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    cp = os.pathsep.join([*(str(p) for p in tool_jars), hadoop_cp])
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(BUILD),
        str(HERE / "RunOneJUnit.java")], check=True)
    if args.overlay and not args.overlay.is_dir():
        raise FileNotFoundError(args.overlay)
    run_cp = os.pathsep.join([*(str(p.resolve()) for p in ([args.overlay] if args.overlay else [])),
        str(SOURCE_RESOURCES), str(BUILD), cp])
    command = [str(JDK / "java"), "-ea", "-Xmx3g",
        "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
        "-Dtest.build.data=" + str(scratch / "data"),
        "-Djava.io.tmpdir=" + str(scratch / "tmp"),
        "-Dhadoop.log.dir=" + str(scratch / "logs"),
        "-Dhdfs17899.inject=" + str(args.inject).lower(),
        "-cp", run_cp, "RunOneJUnit", TEST_CLASS, TEST_METHOD]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            rc = subprocess.run(command, cwd=scratch, env=env,
                stdout=log, stderr=subprocess.STDOUT,
                timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    manifest = {"bug": "HDFS-17899", "source_version": "3.4.3",
        "test": TEST_CLASS + "#" + TEST_METHOD,
        "returncode": rc, "elapsed_seconds": round(time.monotonic()-started,3),
        "overlay": str(args.overlay.resolve()) if args.overlay else None,
        "fault_injection_enabled": args.inject,
        "log": str(output / "junit.log"), "graph_used": False,
        "container_used": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest))
    if rc: raise SystemExit(rc)


if __name__ == "__main__":
    main()
