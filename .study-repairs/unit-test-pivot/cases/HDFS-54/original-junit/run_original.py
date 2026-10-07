#!/usr/bin/env python3
"""One isolated original TestFileChecksum execution with checksum RPC fault hooks."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar")
ASM_ROOT = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM = [ASM_ROOT / name / "9.6" / (name + "-9.6.jar")
       for name in ("asm", "asm-tree", "asm-commons")]
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
COMMON_TESTS = HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
RESOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources")
CLASS_NAME = "org/apache/hadoop/hdfs/FileChecksumHelper$StripedFileNonStripedChecksumComputer.class"
TEST_CLASS = "org.apache.hadoop.hdfs.TestFileChecksum"
TEST_METHOD = "testStripedAndReplicatedFileChecksum2[0]"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def classpath():
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop = subprocess.check_output([str(HADOOP / "bin/hadoop"),
                                      "classpath", "--glob"], env=env, text=True).strip()
    return os.pathsep.join([str(BUILD / "overlay"), str(BUILD), str(RESOURCE),
                            str(TESTS), str(COMMON_TESTS), hadoop,
                            *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))])


def build():
    BUILD.mkdir(exist_ok=True)
    original = BUILD / "input" / CLASS_NAME
    original.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CLIENT) as jar:
        original.write_bytes(jar.read(CLASS_NAME))
    cp = classpath()
    asm_cp = os.pathsep.join(str(p) for p in ASM)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", cp,
                    "-d", str(BUILD), str(HERE / "Hdfs54OriginalProbe.java"),
                    str(HERE / "RunOriginalHdfs54JUnit.java")], check=True)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp", asm_cp,
                    "-d", str(BUILD), str(HERE / "PatchHdfs54Original.java")], check=True)
    subprocess.run([str(JDK / "javac"), "-proc:none", "-cp",
                    os.pathsep.join([str(JACOCO_CORE), asm_cp]),
                    "-d", str(BUILD), str(HERE / "CoverageHdfs54Original.java")], check=True)
    subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join([str(BUILD), asm_cp]),
                    "PatchHdfs54Original", str(original), str(BUILD / "overlay")], check=True)
    shutil.copy2(BUILD / "Hdfs54OriginalProbe.class", BUILD / "overlay/Hdfs54OriginalProbe.class")
    shutil.copy2(BUILD / "Hdfs54OriginalProbe$Context.class",
                 BUILD / "overlay/Hdfs54OriginalProbe$Context.class")
    return {"original_class_sha256": digest(original),
            "original_test_jar_sha256": digest(TESTS),
            "overlay_class_sha256": digest(BUILD / "overlay" / CLASS_NAME)}


def run(output, plan, timeout, keep_scratch):
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True, exist_ok=True)
    cp = classpath()
    assert not any(("graphchecker" in part.lower() or "causynth" in part.lower())
                   and part.lower().endswith(".jar") for part in cp.split(os.pathsep))
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    trace = output / "runtime_trace.jsonl"
    log = output / "junit.log"
    for old in (trace, log, output / "jacoco.exec"):
        old.unlink(missing_ok=True)
    command = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-Dhdfs54.original.trace=" + str(trace),
               "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
               + ",includes=org.apache.hadoop.hdfs.*,dumponexit=true,append=false",
               *(["-Dhdfs54.original.plan=" + str(plan.resolve())] if plan else []),
               "-cp", cp, "RunOriginalHdfs54JUnit", TEST_CLASS, TEST_METHOD]
    start = time.monotonic()
    with log.open("w") as stream:
        try:
            rc = subprocess.run(command, cwd=scratch, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout,
                                check=False).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    seconds = round(time.monotonic() - start, 3)
    if not keep_scratch:
        shutil.rmtree(scratch, ignore_errors=True)
    events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    applied = [e for e in events if e.get("event") == "FAULT_APPLIED"]
    matched = [e for e in events if e.get("event") == "FAULT_MATCHED"]
    target = [e for e in events if e.get("event") == "TARGET_CHECK"]
    planned = [line for line in plan.read_text().splitlines() if line.strip()] if plan else []
    last_seq = applied[-1]["seq"] if applied else -1
    target_post = [e for e in target if e["seq"] > last_seq]
    strict = len(planned) == len(matched) == len(applied) and all(
        event["planIndex"] == i for i, event in enumerate(applied))
    log_text = log.read_text(errors="replace")
    junit_match = re.search(r"Original JUnit runs=(\d+) failures=(\d+) ignored=(\d+)", log_text)
    junit = {"runs": int(junit_match.group(1)), "failures": int(junit_match.group(2)),
             "ignored": int(junit_match.group(3))} if junit_match else None
    coverage = {"probes": 0, "methods": 0, "branch_counts": 0}
    if (output / "jacoco.exec").exists() and (output / "jacoco.exec").stat().st_size:
        args = [str(JDK / "java"), "-cp", os.pathsep.join([str(BUILD), str(JACOCO_CORE),
                 *(str(p) for p in ASM)]), "CoverageHdfs54Original",
                 str(output / "jacoco.exec"), str(BUILD / "overlay"),
                 str(HDFS), str(CLIENT), str(COMMON)]
        with (output / "covered_probes.txt").open("w") as stream:
            subprocess.run(args, stdout=stream, stderr=subprocess.PIPE, check=True)
        production_classes = set()
        for jar_path in (HDFS, CLIENT, COMMON):
            with zipfile.ZipFile(jar_path) as jar:
                production_classes.update(name[:-6] for name in jar.namelist()
                                          if name.endswith(".class"))
        production_classes.update(str(path.relative_to(BUILD / "overlay"))[:-6]
                                  for path in (BUILD / "overlay").rglob("*.class"))
        probe_file = output / "covered_probes.txt"
        raw_probes = probe_file.read_text().splitlines()
        probe_file.write_text("\n".join(line for line in raw_probes
                                        if line.split("#", 1)[0] in production_classes) + "\n")
        for kind, filename in (("probes", "covered_probes.txt"),
                               ("methods", "covered_methods.txt"),
                               ("branch_counts", "covered_branch_counts.txt")):
            coverage[kind] = len((output / filename).read_text().splitlines())
    manifest = {"test": TEST_CLASS + "#" + TEST_METHOD,
                "source_tag": "rel/release-3.4.3", "original_test_unmodified": True,
                "graph_used": False, "test_jar_sha256": digest(TESTS),
                "overlay_class_sha256": digest(BUILD / "overlay" / CLASS_NAME),
                "plan": str(plan) if plan else None,
                "requested_faults": len(planned), "matched_faults": len(matched),
                "applied_faults": len(applied), "strict_ordered": strict,
                "target_checks": len(target), "target_after_final_fault": len(target_post),
                "target_false_after_final_fault": sum(not e["completed"] for e in target_post),
                "observed_io": sum(e.get("event") == "IO_OBSERVED" for e in events),
                "elapsed_seconds": seconds, "junit_exit": rc, "junit": junit,
                "coverage": coverage, "trace": str(trace), "junit_log": str(log)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--keep-scratch", action="store_true")
    args = parser.parse_args()
    if args.build_only:
        print(json.dumps(build()))
    else:
        if args.output is None:parser.error("--output required")
        if not (BUILD / "overlay" / CLASS_NAME).exists():build()
        run(args.output.resolve(), args.plan, args.timeout, args.keep_scratch)


if __name__ == "__main__":
    main()
