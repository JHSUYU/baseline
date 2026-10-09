#!/usr/bin/env python3
"""Resumable HDFS-54 embedded-cluster stale-key checksum calibration."""

import argparse
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
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3") / (
    "hadoop-hdfs-project/hadoop-hdfs-client/src/main/java/"
    "org/apache/hadoop/hdfs/FileChecksumHelper.java")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
HDFS_CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
            for name in ("asm", "asm-tree", "asm-commons")]
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
TARGET_CLASS = "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.class"
SASL_CLASS = "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer.class"
STRIPED_CLASS = "org/apache/hadoop/hdfs/FileChecksumHelper$StripedFileNonStripedChecksumComputer.class"


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_atomic(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def patched_source(classpath):
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
        raise RuntimeError("source guard changed; cannot apply HDFS-17897 fix control")
    patched = original[:begin] + section.replace(old, new) + original[end:]
    patched_path = BUILD / "patched-src/org/apache/hadoop/hdfs/FileChecksumHelper.java"
    patched_path.parent.mkdir(parents=True, exist_ok=True)
    patched_path.write_text(patched)
    patched_overlay = BUILD / "fixed-classes"
    patched_overlay.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", classpath,
                    "-d", str(patched_overlay), str(patched_path)], check=True)
    return patched_overlay


def build(mode, classpath):
    BUILD.mkdir(exist_ok=True)
    asm_cp = os.pathsep.join(str(p) for p in ASM_JARS)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", classpath,
                    "-d", str(BUILD), str(HERE / "StripedChecksumStaleKeyControl.java")], check=True)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp",
                    os.pathsep.join((asm_cp, str(JACOCO_CORE))), "-d", str(BUILD),
                    *(str(HERE / source) for source in
                      ("Hdfs11Probe.java", "PatchHdfs11.java", "PatchStripedCheck.java",
                       "CoverageHdfs11.java"))], check=True)
    overlay = BUILD / (mode + "-overlay")
    shutil.rmtree(overlay, ignore_errors=True)
    overlay.mkdir(parents=True)
    shutil.copy2(BUILD / "Hdfs11Probe.class", overlay / "Hdfs11Probe.class")
    with zipfile.ZipFile(HDFS) as jar:
        for name in (TARGET_CLASS, SASL_CLASS):
            source_class = BUILD / "input" / name
            source_class.parent.mkdir(parents=True, exist_ok=True)
            source_class.write_bytes(jar.read(name))
            subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join((str(BUILD), asm_cp)),
                            "PatchHdfs11", str(source_class), str(overlay)], check=True)
    if mode == "fixed":
        fixed = patched_source(classpath)
        for item in fixed.rglob("*.class"):
            relative = item.relative_to(fixed)
            target = overlay / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        striped_input = fixed / STRIPED_CLASS
    else:
        with zipfile.ZipFile(HDFS_CLIENT) as jar:
            striped_input = BUILD / "input" / STRIPED_CLASS
            striped_input.parent.mkdir(parents=True, exist_ok=True)
            striped_input.write_bytes(jar.read(STRIPED_CLASS))
    subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join((str(BUILD), asm_cp)),
                    "PatchStripedCheck", str(striped_input), str(overlay),
                    *(["allow-missing-catch"] if mode == "fixed" else [])], check=True)
    return overlay


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("original", "fixed"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for leaf in ("manifest.json", "runtime_trace.jsonl", "jacoco.exec", "junit.log",
                 "covered_probes.txt", "covered_methods.txt", "covered_branch_counts.txt",
                 "covered_lines.txt"):
        (output / leaf).unlink(missing_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                        env=env, text=True).strip()
    tools = [TESTS, COMMON_TESTS, JUNIT]
    tools += sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    classpath = os.pathsep.join([*(str(p) for p in tools), hadoop_cp])
    overlay = build(args.mode, classpath)
    run_cp = os.pathsep.join((str(overlay), str(BUILD), classpath))
    command = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-Dhdfs17897.expectFixed=" + str(args.mode == "fixed").lower(),
               "-Dhdfs11.trace=" + str(output / "runtime_trace.jsonl"),
               "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
               + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false",
               *(["-Dhdfs11.plan=" + str(args.plan.resolve())] if args.plan else []),
               "-cp", run_cp, "org.junit.runner.JUnitCore",
               "org.apache.hadoop.hdfs.StripedChecksumStaleKeyControl"]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            rc = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    manifest = {"case_id": "HDFS-54", "linked_upstream_case": "HDFS-11",
                "known_bug": "HDFS-17897", "new_bug": False,
                "mode": args.mode, "returncode": rc,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "source_sha256": checksum(SOURCE),
                "target_site": "FileChecksumHelper$StripedFileNonStripedChecksumComputer.checksumBlocks#L629",
                "test": "StripedChecksumStaleKeyControl#stripedChecksumAfterEncryptionKeyExpires",
                "graph_used": False, "container_used": False,
                "plan": str(args.plan.resolve()) if args.plan else None,
                "java_main": "org.junit.runner.JUnitCore org.apache.hadoop.hdfs.StripedChecksumStaleKeyControl",
                "classpath_sha256": hashlib.sha256(run_cp.encode()).hexdigest()}
    if (output / "jacoco.exec").exists():
        with (output / "covered_probes.txt").open("w") as covered:
            subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join(
                (str(BUILD), str(JACOCO_CORE), *(str(p) for p in ASM_JARS))),
                "CoverageHdfs11", str(output / "jacoco.exec"), str(overlay),
                str(HDFS), str(HDFS_CLIENT), str(COMMON)], stdout=covered, check=True)
        for category in ("probes", "methods", "branch_counts", "lines"):
            path = output / ("covered_" + category + ".txt")
            manifest["covered_" + category] = sum(1 for _ in path.open())
    write_atomic(output / "manifest.json", manifest)
    print(json.dumps(manifest))
    if rc != 0:
        raise SystemExit(rc)


if __name__ == "__main__":
    main()
