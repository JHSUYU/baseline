#!/usr/bin/env python3
"""Build an isolated actor-aware HDFS-01 overlay; never start a cluster."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile


HERE = Path(__file__).resolve().parent
LEGACY_SRC = HERE.parent / "probe/src"
BUILD = HERE / "build"
CLASSES = BUILD / "classes"
OVERLAY = BUILD / "overlay"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
HADOOP = Path.home() / ".baseline-deps/hadoop-3.4.3"
ASM = Path.home() / ".m2/repository/org/ow2/asm"
ASM_JARS = [ASM / name / "9.6" / f"{name}-9.6.jar" for name in
            ("asm", "asm-tree", "asm-commons", "asm-util", "asm-analysis")]
INPUTS = {
    "org/apache/hadoop/hdfs/DFSInputStream": HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar",
    "org/apache/hadoop/hdfs/DFSClient": HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar",
    "org/apache/hadoop/hdfs/client/impl/BlockReaderRemote": HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar",
    "org/apache/hadoop/ipc/Client": HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar",
}


def run(command: list[str], cp: str) -> str:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=False)
    if completed.returncode:
        raise RuntimeError(f"exit {completed.returncode}: {command}\n{completed.stdout}")
    return completed.stdout


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    OVERLAY.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    jacoco_core = Path.home() / ".m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar"
    test_jar = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
    junit = HADOOP / "share/hadoop/tools/lib/junit-4.13.2.jar"
    cp = os.pathsep.join([str(CLASSES), hadoop_cp, str(jacoco_core),
                          str(test_jar), str(junit), *(str(jar) for jar in ASM_JARS)])
    sources = sorted((HERE / "src").glob("*.java"))
    sources.extend([LEGACY_SRC / "RunJUnitMethod.java",
                    LEGACY_SRC / "CoverageHdfs50.java"])
    run([str(JDK / "javac"), "-cp", cp, "-d", str(CLASSES),
         *(str(path) for path in sources)], cp)
    (OVERLAY / "Hdfs01ActorProbe.class").write_bytes(
        (CLASSES / "Hdfs01ActorProbe.class").read_bytes())
    inputs = []
    for name, jar in INPUTS.items():
        with zipfile.ZipFile(jar) as archive:
            original = archive.read(name + ".class")
        input_file = BUILD / "input" / (name + ".class")
        input_file.parent.mkdir(parents=True, exist_ok=True)
        input_file.write_bytes(original)
        output = run([str(JDK / "java"), "-cp", cp, "PatchHdfs01Actor",
                      str(input_file), name, str(OVERLAY)], cp)
        if name + ".class" not in output:
            raise RuntimeError(f"patcher did not report {name}")
        patched = OVERLAY / (name + ".class")
        # The verifier prints diagnostics even when its main returns zero.
        verification = run([str(JDK / "java"), "-cp", os.pathsep.join(
            [str(OVERLAY), cp]), "org.objectweb.asm.util.CheckClassAdapter",
            name.replace("/", ".")], cp)
        if verification.strip():
            raise RuntimeError(f"bytecode verifier reported {name}: {verification}")
        inputs.append({"class": name, "source_jar": str(jar),
                       "original_sha256": hashlib.sha256(original).hexdigest(),
                       "overlay_sha256": hashlib.sha256(patched.read_bytes()).hexdigest()})
    result = {"case_id": "HDFS-01", "original_junit":
              "org.apache.hadoop.hdfs.TestPread#testPreadDFS",
              "build_only": True, "input_classes": inputs,
              "actor_probe_sha256": hashlib.sha256(
                  (OVERLAY / "Hdfs01ActorProbe.class").read_bytes()).hexdigest()}
    (BUILD / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"verified_classes": len(inputs),
                      "receipt": str(BUILD / "receipt.json")}))


if __name__ == "__main__":
    main()
