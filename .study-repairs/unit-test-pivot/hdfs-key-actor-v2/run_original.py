#!/usr/bin/env python3
"""Run an unchanged Hadoop 3.4.3 parameterized MiniDFSCluster JUnit child.

Build and JUnit execution start JVMs. A host coordinator must release a slot
before this command is run. Outputs are append-only by directory name.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
OVERLAY = BUILD / "overlay"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / x / "9.6" / (x + "-9.6.jar")
            for x in ("asm", "asm-tree", "asm-commons", "asm-util", "asm-analysis")]
JACOCO_AGENT = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
M2 = Path("/users/ZhenyuLi/.m2/repository")
TEST_CLASS = "org.apache.hadoop.hdfs.TestEncryptedTransfer"
TESTS_BY_CASE = {
    "HDFS-11": "testEncryptedReadDefaultAlgorithmCipherSuite",
    "HDFS-12": "testLongLivedClient",
}
CLASSES = {
    "org/apache/hadoop/hdfs/MiniDFSCluster": TESTS,
    "org/apache/hadoop/hdfs/server/datanode/DataNode": HDFS,
    "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager": HDFS,
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer": HDFS,
}


def digest() -> str:
    h = hashlib.sha256()
    for path in sorted(OVERLAY.rglob("*.class")):
        h.update(str(path.relative_to(OVERLAY)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def build() -> None:
    sources = [HERE / name for name in ("HdfsKeyActorProbe.java", "PatchHdfsKeyActor.java",
                                        "RunOriginalJUnit.java", "CoverageHdfs11.java")]
    marker = BUILD / "built.json"
    if marker.exists() and marker.stat().st_mtime > max(p.stat().st_mtime for p in sources):
        return
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / "classes"
    classes.mkdir(exist_ok=True)
    cp = os.pathsep.join(map(str, [*ASM_JARS, JACOCO_CORE, JUNIT, HDFS, CLIENT,
                                   COMMON, TESTS, COMMON_TESTS]))
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(classes),
                    *map(str, sources)], check=True)
    OVERLAY.mkdir(exist_ok=True)
    (OVERLAY / "HdfsKeyActorProbe.class").write_bytes(
        (classes / "HdfsKeyActorProbe.class").read_bytes())
    for nested in classes.glob("HdfsKeyActorProbe$*.class"):
        (OVERLAY / nested.name).write_bytes(nested.read_bytes())
    for name, jar in CLASSES.items():
        path = BUILD / "input" / (name + ".class")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(jar) as archive:
            path.write_bytes(archive.read(name + ".class"))
        subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join((str(classes), cp)),
                        "PatchHdfsKeyActor", str(path), str(OVERLAY)], check=True)
    marker.write_text(json.dumps({"sources": [str(p) for p in sources],
                                  "digest_sha256": digest()}, sort_keys=True) + "\n")


def run(args: argparse.Namespace) -> dict:
    build()
    out = args.output.resolve()
    if (out / "manifest.json").exists():
        raise FileExistsError(f"completed run must not be overwritten: {out}")
    out.mkdir(parents=True, exist_ok=True)
    for leaf in ("runtime_trace.jsonl", "jacoco.exec", "junit.log", "covered_probes.txt",
                 "covered_methods.txt", "covered_branch_counts.txt", "covered_lines.txt"):
        (out / leaf).unlink(missing_ok=True)
    scratch = out / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for name in ("data", "tmp", "logs"):
        (scratch / name).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env, text=True).strip()
    extras = [
        M2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
        M2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
        M2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
        M2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar",
    ]
    cp = os.pathsep.join((str(OVERLAY), str(BUILD / "classes"), str(TESTS),
                          str(COMMON_TESTS), str(HADOOP / "share/hadoop/hdfs/sources"),
                          hadoop_cp, *map(str, extras),
                          *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    cmd = [str(JDK / "java"), "-ea", "-Xverify:all", "-Xmx3g",
           "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
           "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
           "-Dtest.build.data=" + str(scratch / "data"),
           "-Djava.io.tmpdir=" + str(scratch / "tmp"),
           "-Dhadoop.log.dir=" + str(scratch / "logs"),
           "-DhdfsKey.v2.trace=" + str(out / "runtime_trace.jsonl"),
           "-javaagent:" + str(JACOCO_AGENT) + "=destfile=" + str(out / "jacoco.exec")
           + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false",
           *(["-DhdfsKey.v2.plan=" + str(args.plan.resolve())] if args.plan else []),
           "-cp", cp, "RunOriginalJUnit", TEST_CLASS, args.method,
           args.parameter]
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    peak_rss_kib = 0
    with (out / "junit.log").open("w") as log:
        process = subprocess.Popen(cmd, cwd=scratch, env=env, stdout=log,
                                   stderr=subprocess.STDOUT)
        while True:
            status_file = Path(f"/proc/{process.pid}/status")
            try:
                for line in status_file.read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        peak_rss_kib = max(peak_rss_kib, int(line.split()[1]))
                        break
            except FileNotFoundError:
                pass
            try:
                returncode = process.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started >= args.timeout:
                    process.kill()
                    process.wait()
                    returncode = 124
                    break
    manifest = {
        "schema": "hdfs-key-actor-v2-run-1", "case_id": args.case,
        "test": f"{TEST_CLASS}#{args.method}[{args.parameter}]",
        "returncode": returncode, "elapsed_seconds": round(time.monotonic() - started, 3),
        "peak_junit_rss_kib": peak_rss_kib,
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "instrumentation_digest_sha256": digest(),
        "trace": str(out / "runtime_trace.jsonl"),
        "coverage": str(out / "jacoco.exec"),
        "plan": str(args.plan.resolve()) if args.plan else None,
        "graphchecker_runtime_used": False,
    }
    if (out / "jacoco.exec").is_file() and (out / "jacoco.exec").stat().st_size:
        with (out / "covered_probes.txt").open("w") as stream:
            subprocess.run([str(JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD / "classes"), str(JACOCO_CORE),
                                             *map(str, ASM_JARS))),
                            "CoverageHdfs11", str(out / "jacoco.exec"),
                            str(OVERLAY), str(HDFS), str(CLIENT), str(COMMON)],
                           stdout=stream, check=True)
        for category in ("probes", "methods", "branch_counts", "lines"):
            path = out / ("covered_" + category + ".txt")
            manifest["covered_" + category + "_count"] = sum(1 for _ in path.open())
    tmp = out / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    tmp.replace(out / "manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=TESTS_BY_CASE, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method")
    parser.add_argument("--parameter", choices=("0", "1"), default="0")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args()
    if args.method is None:
        args.method = TESTS_BY_CASE[args.case]
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    main()
