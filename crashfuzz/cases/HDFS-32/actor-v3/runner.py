#!/usr/bin/env python3
"""Unmodified Hadoop 3.4.3 JUnit with case-local ASM and JaCoCo hooks."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
CLASSES = BUILD / "classes"
OVERLAY = BUILD / "overlay"
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
M2 = Path("/users/ZhenyuLi/.m2/repository")
ASM = M2 / "org/ow2/asm/asm/9.6/asm-9.6.jar"
ASM_TREE = M2 / "org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar"
ASM_COMMONS = M2 / "org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar"
JACOCO = M2 / "org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar"
JACOCO_CORE = M2 / "org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar"
HDFS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"
CLIENT = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"
COMMON = HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"
TESTS = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
JUNIT = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
TEST = "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDeleteBlockPool"
PATCHED = (
    ("org/apache/hadoop/hdfs/MiniDFSCluster", TESTS),
    ("org/apache/hadoop/hdfs/server/datanode/DataNode", HDFS),
    ("org/apache/hadoop/hdfs/server/datanode/BPServiceActor", HDFS),
    ("org/apache/hadoop/hdfs/server/datanode/BlockPoolManager", HDFS),
    ("org/apache/hadoop/hdfs/server/datanode/fsdataset/impl/FsDatasetImpl", HDFS),
    ("org/apache/hadoop/ipc/Client", COMMON),
)
PROBE = "org/apache/hadoop/hdfs/server/datanode/Hdfs32V3Probe"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cp_base() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    return subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                   env=env, text=True).strip()


def build() -> dict:
    sources = sorted((HERE / "src").glob("*.java"))
    fingerprints = {p.name: sha(p) for p in sources}
    marker = BUILD / "built.json"
    if marker.is_file():
        prior = json.loads(marker.read_text())
        if prior.get("source_sha256") == fingerprints and all(
                (OVERLAY / (name + ".class")).is_file() for name, _ in PATCHED):
            return prior
    CLASSES.mkdir(parents=True, exist_ok=True)
    OVERLAY.mkdir(parents=True, exist_ok=True)
    compile_cp = os.pathsep.join((cp_base(), str(ASM), str(ASM_TREE), str(JACOCO_CORE),
                                  str(TESTS), str(HDFS), str(CLIENT), str(COMMON), str(JUNIT)))
    with (BUILD / "compile.log").open("w") as log:
        subprocess.run([str(JDK / "javac"), "-J-Xmx2g", "-cp", compile_cp,
                        "-d", str(CLASSES), *(str(p) for p in sources)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    (OVERLAY / PROBE).parent.mkdir(parents=True, exist_ok=True)
    for probe_class in (CLASSES / PROBE).parent.glob("Hdfs32V3Probe*.class"):
        shutil.copy2(probe_class, (OVERLAY / PROBE).parent / probe_class.name)
    input_hashes = {}
    patch_cp = os.pathsep.join((str(CLASSES), str(ASM), str(ASM_TREE)))
    with (BUILD / "patch.log").open("w") as log:
        for name, archive in PATCHED:
            raw = BUILD / "input" / (name + ".class")
            raw.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as jar:
                raw.write_bytes(jar.read(name + ".class"))
            input_hashes[name] = sha(raw)
            subprocess.run([str(JDK / "java"), "-cp", patch_cp,
                            "PatchHdfs32V3", str(raw), name, str(OVERLAY)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    record = {"schema": 1, "source_sha256": fingerprints,
              "original_class_sha256": input_hashes,
              "overlay_sha256": {name: sha(OVERLAY / (name + ".class"))
                                 for name, _ in PATCHED},
              "probe_sha256": sha(OVERLAY / (PROBE + ".class")),
              "source_commit": "9d50c6884666e794e45102260a4017bb31802e1b"}
    pending = marker.with_suffix(".json.tmp")
    pending.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    pending.replace(marker)
    return record


def production_classes() -> set[str]:
    output: set[str] = set()
    for archive in (HDFS, CLIENT, COMMON):
        with zipfile.ZipFile(archive) as jar:
            output.update(n[:-6] for n in jar.namelist() if n.endswith(".class"))
    return output


def run(output: Path, plan: Path | None, timeout: int) -> dict:
    built = build()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    for suffix in ("data", "tmp", "logs"):
        (scratch / suffix).mkdir(parents=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    extra = [M2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
             M2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
             M2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
             M2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar"]
    classpath = os.pathsep.join((str(OVERLAY), str(CLASSES), str(HERE / "test-resources"),
                                 str(TESTS), str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
                                 cp_base(), *(str(p) for p in extra),
                                 *(str(p) for p in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    if any(word in classpath.lower() for word in ("graphchecker", "skeleton", "causynth")):
        raise RuntimeError("unexpected graph tool in original-JUnit classpath")
    trace = output / "runtime_trace.jsonl"
    command = [str(JDK / "java"), "-ea", "-Xverify:all", "-Xmx3g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-Dhdfs32.v3.trace=" + str(trace),
               "-Dhdfs32.v3.plan=" + (str(plan) if plan else ""),
               "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec")
               + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false",
               "-cp", classpath, "RunJUnitMethod",
               "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool", "testDeleteBlockPool"]
    start = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            code = subprocess.run(command, cwd=scratch, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    elapsed = round(time.monotonic() - start, 3)
    manifest = {"schema": 1, "test": TEST, "junit_exit": code,
                "elapsed_seconds": elapsed, "instrumented": True,
                "graphchecker_runtime_used": False,
                "original_test_jar_sha256": sha(TESTS),
                "original_hdfs_jar_sha256": sha(HDFS),
                "original_common_jar_sha256": sha(COMMON),
                "classpath_sha256": hashlib.sha256(classpath.encode()).hexdigest(),
                "build": built, "plan_sha256": sha(plan) if plan else None}
    exec_file = output / "jacoco.exec"
    if exec_file.is_file() and exec_file.stat().st_size:
        with (output / "covered_probes.txt").open("w") as stream:
            subprocess.run([str(JDK / "java"), "-cp", os.pathsep.join(
                (str(CLASSES), str(JACOCO_CORE), str(ASM), str(ASM_TREE), str(ASM_COMMONS))),
                "CoverageHdfs32", str(exec_file), str(OVERLAY), str(HDFS),
                str(CLIENT), str(COMMON)], stdout=stream, check=True)
        membership = production_classes()
        probes = output / "covered_probes.txt"
        rows = [row for row in probes.read_text().splitlines()
                if row.split("#", 1)[0] in membership]
        probes.write_text("\n".join(rows) + ("\n" if rows else ""))
        manifest["covered_probes"] = len(rows)
    pending = output / "manifest.json.tmp"
    pending.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    pending.replace(output / "manifest.json")
    print(json.dumps({"output": str(output), "junit_exit": code,
                      "elapsed_seconds": elapsed}), flush=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.build:
        print(json.dumps(build(), sort_keys=True))
    elif args.output:
        run(args.output.resolve(), args.plan.resolve() if args.plan else None, args.timeout)
    else:
        parser.error("choose --build or --output")


if __name__ == "__main__":
    main()
