#!/usr/bin/env python3
"""Isolated embedded-cluster control for Hadoop 3.4.3 HDFS-17897."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3") / (
    "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/"
    "org/apache/hadoop/hdfs/FileChecksumHelper.java")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"


def patched_source(cp):
    original = SOURCE.read_text()
    begin = original.index("    private boolean checksumBlockGroup(")
    end = original.index("    private void tryDatanode(", begin)
    section = original[begin:end]
    old = """        } catch (IOException ie) {
          LOG.warn("src={}" + ", datanodes[{}]={}",
              getSrc(), j, datanodes[j], ie);
        }
"""
    new = """        } catch (InvalidEncryptionKeyException iee) {
          if (bgIdx > getLastRetriedIndex()) {
            LOG.debug("Invalid encryption key for striped block group; retry once", iee);
            setLastRetriedIndex(bgIdx);
            done = true;
            bgIdx--;
            System.out.println("CONTROL patched_clear_and_retry_bg=" + bgIdx);
            getClient().clearDataEncryptionKey();
          }
        } catch (IOException ie) {
          LOG.warn("src={}" + ", datanodes[{}]={}",
              getSrc(), j, datanodes[j], ie);
        }
"""
    if section.count(old) != 1:
        raise RuntimeError("source guard changed; cannot apply 17897 control patch")
    patched = original[:begin] + section.replace(old, new) + original[end:]
    source = BUILD / "patched-src/org/apache/hadoop/hdfs/FileChecksumHelper.java"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(patched)
    overlay = BUILD / "patched-overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", cp,
                    "-d", str(overlay), str(source)], check=True)
    return overlay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("original", "fixed"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for name in ("data", "tmp", "logs"):
        (scratch / name).mkdir(parents=True)
    BUILD.mkdir(exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    tools = [TESTS, COMMON_TESTS, JUNIT]
    tools += sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    cp = os.pathsep.join([*(str(p) for p in tools), hadoop_cp])
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", cp,
                    "-d", str(BUILD),
                    str(HERE / "StripedChecksumStaleKeyControl.java")], check=True)
    overlay = patched_source(cp) if args.mode == "fixed" else None
    run_cp = os.pathsep.join([*(str(p) for p in ([overlay] if overlay else [])),
                               str(BUILD), cp])
    command = [str(JDK / "java"), "-ea", "-Xmx3g",
               "-Djava.net.preferIPv4Stack=true", "-Djava.awt.headless=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-Dhdfs17897.expectFixed=" + str(args.mode == "fixed").lower(),
               "-cp", run_cp, "org.junit.runner.JUnitCore",
               "org.apache.hadoop.hdfs.StripedChecksumStaleKeyControl"]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            rc = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                stderr=subprocess.STDOUT,
                                timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    manifest = {"bug": "HDFS-17897", "source_version": "3.4.3",
                "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "mode": args.mode, "returncode": rc,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "log": str(output / "junit.log"),
                "original_junit_basis": "TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey",
                "workload_change": "XOR-2-1 striped file instead of replicated file",
                "graph_used": False, "container_used": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))
    if rc != 0:
        raise SystemExit(rc)


if __name__ == "__main__":
    main()
