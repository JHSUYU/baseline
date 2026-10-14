#!/usr/bin/env python3
"""Rebind the generic HDFS IPC overlay to original GraphChecker, immutably."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
BRIDGE = HERE / "templates/MalloryEmbeddedIpcBridge.java"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_bridge():
    return BRIDGE.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-overlay", type=Path, required=True)
    parser.add_argument("--engine-jar", type=Path, required=True)
    parser.add_argument("--classpath-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source_overlay = args.source_overlay.resolve(strict=True)
    engine = args.engine_jar.resolve(strict=True)
    ordered_cp_file = args.classpath_file.resolve(strict=True)
    out = args.out.absolute()
    if out.exists():
        parser.error("refusing to overwrite an existing native overlay")
    if not (source_overlay / "org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.class").is_file():
        parser.error("source overlay lacks the generic HDFS bridge")
    ordered_cp = ordered_cp_file.read_text().strip()
    if not ordered_cp:
        parser.error("empty ordered classpath")

    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".hdfs-native-", dir=out.parent))
    try:
        shutil.copytree(source_overlay, stage / "classes", dirs_exist_ok=True)
        generated = stage / "generated/org/apache/hadoop/ipc/MalloryEmbeddedIpcBridge.java"
        generated.parent.mkdir(parents=True)
        generated.write_text(source_bridge())
        sources = [generated]
        sources += sorted((HERE / "src").rglob("*.java"))
        java8 = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/javac")
        cp = ":".join((str(engine), str(stage / "classes"), ordered_cp))
        subprocess.run([str(java8), "-source", "8", "-target", "8",
                        "-cp", cp, "-d", str(stage / "classes")]
                       + [str(p) for p in sources], check=True)
        classes = stage / "classes"
        assert (classes / "org/apache/hadoop/ipc/NativeHdfsDoors.class").is_file()
        assert (classes / "edu/uva/liftlab/graphchecker/runtime/NativeHdfsJUnitRunner.class").is_file()
        receipt = {
            "schema_version": 1,
            "kind": "original_graphchecker_hdfs_native_overlay",
            "source_overlay": str(source_overlay),
            "engine_jar": {"path": str(engine), "sha256": digest(engine)},
            "ordered_classpath_file": {"path": str(ordered_cp_file),
                                       "sha256": digest(ordered_cp_file)},
            "bridge_source_sha256": digest(BRIDGE),
            "native_source_hashes": {str(p.relative_to(HERE)): digest(p)
                                     for p in sources[1:]},
            "generated_bridge_sha256": digest(generated),
            "compiled_class_hashes": {
                str(p.relative_to(classes)): digest(p)
                for p in sorted(classes.rglob("*.class"))
            },
        }
        (classes / "NATIVE_HDFS_OVERLAY_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        classes.rename(out)
        print(out)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    main()
