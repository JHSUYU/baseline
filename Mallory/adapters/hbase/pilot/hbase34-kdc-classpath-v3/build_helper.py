#!/usr/bin/env python3
"""Build the one missing HBase HTTP test helper from pinned HBase 2.6.6 source."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6/hbase-http/src/test/java/org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.java")
SOURCE_SHA256 = "e0da02491b79296c459499c6f1e0e354ade9261dc5e7e0801ca5bbaf9d1bfa55"
PARENT_CONFIG = HERE.parent / "hbase34-kdc-classpath-v2/healthy.json"
JAVAC = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/javac")
CLASS = "org/apache/hadoop/hbase/http/ssl/KeyStoreTestUtil.class"
OUTPUT = HERE / "runtime/key-store-test-util.jar"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> str:
    if not SOURCE.is_file() or sha(SOURCE) != SOURCE_SHA256:
        raise ValueError("pinned HBase 2.6.6 helper source changed")
    parent = json.loads(PARENT_CONFIG.read_text())
    command = parent["command"]
    classpath = command[command.index("-cp") + 1]
    with tempfile.TemporaryDirectory(prefix="mallory-hbase34-helper-") as tmp:
        work = Path(tmp)
        subprocess.run([str(JAVAC), "-source", "8", "-target", "8", "-g:none",
                        "-cp", classpath, "-d", str(work), str(SOURCE)], check=True)
        compiled = (work / CLASS).read_bytes()
    if compiled[:4] != b"\xca\xfe\xba\xbe" or int.from_bytes(compiled[6:8], "big") != 52:
        raise ValueError("helper is not a Java 8 class")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo(CLASS, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    with zipfile.ZipFile(OUTPUT, "w") as archive:
        archive.writestr(info, compiled)
    return sha(OUTPUT)


if __name__ == "__main__":
    print(build())
