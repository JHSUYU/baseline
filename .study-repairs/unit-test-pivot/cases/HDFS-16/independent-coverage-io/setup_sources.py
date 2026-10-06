#!/usr/bin/env python3
"""Extract pristine Hadoop 3.4.3 sources for HDFS-16."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


CASE = Path(__file__).resolve().parent
DIST = Path.home() / ".baseline-deps/hadoop-3.4.3/share/hadoop"
HDFS = DIST / "hdfs/sources"
COMMON = DIST / "common/sources"
FILES = (
    (HDFS / "hadoop-hdfs-3.4.3-sources.jar",
     "org/apache/hadoop/hdfs/server/blockmanagement/BlockInfo.java", "main"),
    (HDFS / "hadoop-hdfs-3.4.3-sources.jar",
     "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream.java", "main"),
    (COMMON / "hadoop-common-3.4.3-sources.jar",
     "org/apache/hadoop/ipc/Client.java", "main"),
    (HDFS / "hadoop-hdfs-3.4.3-test-sources.jar",
     "org/apache/hadoop/hdfs/TestClientProtocolForPipelineRecovery.java", "test"),
    (HDFS / "hadoop-hdfs-3.4.3-test-sources.jar",
     "hdfs-site.xml", "test-resources"),
)


def main() -> None:
    records = []
    for jar, member, kind in FILES:
        with zipfile.ZipFile(jar) as archive:
            data = archive.read(member)
        target = CASE / "source" / kind / member
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.read_bytes() != data:
            raise RuntimeError("source snapshot differs: " + str(target))
        target.write_bytes(data)
        records.append({"source_jar": str(jar), "member": member,
                        "snapshot": str(target.relative_to(CASE)),
                        "sha256": hashlib.sha256(data).hexdigest()})
    result = {"upstream": "Apache Hadoop 3.4.3 distribution source JARs",
              "graphchecker_artifacts_used": False, "files": records}
    (CASE / "source-provenance.json").write_text(
        json.dumps(result, indent=2) + "\n")
    print(json.dumps({"source_files": len(records),
                      "source_root": str(CASE / "source")}))


if __name__ == "__main__":
    main()
