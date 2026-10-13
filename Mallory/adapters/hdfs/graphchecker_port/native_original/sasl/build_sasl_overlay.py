#!/usr/bin/env python3
"""Add exact same-JVM HDFS SASL handoffs to an immutable native overlay."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/jre/bin/java")
JAVAC = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/javac")
JAVASSIST = Path.home() / ".m2/repository/org/javassist/javassist/3.30.2-GA/javassist-3.30.2-GA.jar"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-overlay", type=Path, required=True)
    parser.add_argument("--hdfs-client-classes", type=Path, required=True)
    parser.add_argument("--engine-jar", type=Path, required=True)
    parser.add_argument("--classpath-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    native = args.native_overlay.resolve(strict=True)
    client = args.hdfs_client_classes.resolve(strict=True)
    engine = args.engine_jar.resolve(strict=True)
    cp_file = args.classpath_file.resolve(strict=True)
    out = args.out.absolute()
    if out.exists():
        parser.error("refusing to overwrite existing SASL overlay")
    if not (native / "org/apache/hadoop/ipc/NativeHdfsDoors.class").is_file():
        parser.error("input is not a native HDFS overlay")
    for name in ("DataTransferSaslUtil", "SaslDataTransferClient"):
        path = client / "org/apache/hadoop/hdfs/protocol/datatransfer/sasl" / (name + ".class")
        if not path.is_file():
            parser.error("missing original HDFS client class " + name)
    cp_text = cp_file.read_text().strip()
    if not cp_text:
        parser.error("empty exact ordered classpath")

    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".hdfs-sasl-", dir=out.parent))
    try:
        classes = stage / "classes"
        tools = stage / "tools"
        shutil.copytree(native, classes)
        tools.mkdir()
        runtime_source = HERE / "src/org/apache/hadoop/hdfs/protocol/datatransfer/sasl/NativeHdfsSaslDoors.java"
        patch_source = HERE / "src/edu/uva/liftlab/mallory/adapters/hdfs/graphchecker/PatchNativeSasl.java"
        classpath = ":".join((str(engine), str(classes), str(client), cp_text))
        subprocess.run([str(JAVAC), "-source", "8", "-target", "8",
                        "-cp", classpath, "-d", str(classes),
                        str(runtime_source)], check=True)
        subprocess.run([str(JAVAC), "-source", "8", "-target", "8",
                        "-cp", str(JAVASSIST), "-d", str(tools),
                        str(patch_source)], check=True)
        tool_cp = ":".join((str(tools), str(JAVASSIST), classpath))
        subprocess.run([str(JAVA), "-cp", tool_cp,
                        "edu.uva.liftlab.mallory.adapters.hdfs.graphchecker.PatchNativeSasl",
                        str(client), cp_text, str(classes)], check=True)
        patched = [
            "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/DataTransferSaslUtil.class",
            "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class",
            "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer.class",
            "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/NativeHdfsSaslDoors.class",
            "org/apache/hadoop/hdfs/server/balancer/Dispatcher.class",
        ]
        if any(not (classes / name).is_file() for name in patched):
            parser.error("SASL overlay lacks a required patched class")
        receipt = {
            "schema_version": 1,
            "kind": "native_hdfs_sasl_same_jvm_overlay",
            "native_overlay": str(native),
            "hdfs_client_classes": str(client),
            "engine_jar": {"path": str(engine), "sha256": sha(engine)},
            "classpath_file": {"path": str(cp_file), "sha256": sha(cp_file)},
            "javassist_jar": {"path": str(JAVASSIST), "sha256": sha(JAVASSIST)},
            "source_sha256": {str(p.relative_to(HERE)): sha(p)
                              for p in (runtime_source, patch_source)},
            "patched_class_sha256": {name: sha(classes / name) for name in patched},
            "scope": "same JVM MiniCluster; other-process receipt is a blocking gap",
        }
        (classes / "NATIVE_HDFS_SASL_OVERLAY_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        classes.rename(out)
        print(out)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    main()
