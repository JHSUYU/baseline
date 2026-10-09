#!/usr/bin/env python3
"""Run one unchanged Hadoop 3.4.3 EC-checksum JUnit with a target-only trace."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "hdfs54-original-ec-feasibility"
SCRATCH = OUTPUT / "scratch"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/hdfs31-independent-source")
HDFS54 = HERE.parents[1] / "cases/HDFS-54"
CORE = HERE.parents[1] / "core-fuzzer/build-original-hdfs-junit"
TEST_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
HDFS_CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
       for name in ("asm", "asm-tree", "asm-commons")]
CLASS_NAME = "org/apache/hadoop/hdfs/FileChecksumHelper$StripedFileNonStripedChecksumComputer.class"
TEST_CLASS = "org.apache.hadoop.hdfs.TestFileChecksum"
TEST_METHOD = "testStripedAndReplicatedFileChecksum2[0]"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUTPUT.mkdir(exist_ok=True)
    for name in ("data", "tmp", "logs"):
        (SCRATCH / name).mkdir(parents=True, exist_ok=True)
    overlay = OUTPUT / "overlay"
    original_class = OUTPUT / "input" / CLASS_NAME
    original_class.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(HDFS_CLIENT) as jar:
        original_class.write_bytes(jar.read(CLASS_NAME))
    asm_cp = os.pathsep.join([str(HDFS54 / "build"), *(str(p) for p in ASM)])
    subprocess.run([str(JDK / "java"), "-cp", asm_cp, "PatchStripedCheck",
                    str(original_class), str(overlay)], check=True)
    shutil.copy2(HDFS54 / "build/Hdfs11Probe.class", overlay / "Hdfs11Probe.class")

    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"),
                                         "classpath", "--glob"],
                                        env=env, text=True).strip()
    resource = SOURCE / "hadoop-hdfs-project/hadoop-hdfs/src/test/resources"
    cp = os.pathsep.join([str(overlay), str(CORE), str(resource),
                          str(TEST_JAR), str(COMMON_TESTS), hadoop_cp,
                          *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))])
    assert not any("graphchecker" in part.lower() or "causynth" in part.lower()
                   for part in cp.split(os.pathsep))
    trace = OUTPUT / "runtime_trace.jsonl"
    junit_log = OUTPUT / "junit.log"
    command = [str(JDK / "java"), "-ea", "-Xmx3g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(SCRATCH / "data"),
               "-Djava.io.tmpdir=" + str(SCRATCH / "tmp"),
               "-Dhadoop.log.dir=" + str(SCRATCH / "logs"),
               "-Dhdfs11.trace=" + str(trace),
               "-javaagent:" + str(JACOCO) + "=destfile=" + str(OUTPUT / "jacoco.exec")
               + ",includes=org.apache.hadoop.hdfs.*,dumponexit=true,append=false",
               "-cp", cp, "RunOriginalHdfsJUnit", TEST_CLASS, TEST_METHOD]
    start = time.monotonic()
    with junit_log.open("w") as log:
        try:
            status = subprocess.run(command, cwd=SCRATCH, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=180,
                                    check=False).returncode
        except subprocess.TimeoutExpired:
            status = 124
    events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    check = [event for event in events if event.get("event") == "STRIPED_CHECK"]
    result = {"test": TEST_CLASS + "#" + TEST_METHOD,
              "source_tag": "rel/release-3.4.3",
              "original_test_jar_sha256": sha256(TEST_JAR),
              "original_target_class_sha256": sha256(original_class),
              "target_only_overlay": True, "changed_original_junit": False,
              "returncode": status, "elapsed_seconds": round(time.monotonic()-start, 3),
              "target_check_events": len(check),
              "target_check_true": sum(bool(event["completed"]) for event in check),
              "target_check_false": sum(not event["completed"] for event in check),
              "jacoco_exec_bytes": (OUTPUT / "jacoco.exec").stat().st_size
              if (OUTPUT / "jacoco.exec").exists() else 0,
              "trace": str(trace), "junit_log": str(junit_log)}
    (OUTPUT / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
