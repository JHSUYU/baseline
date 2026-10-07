#!/usr/bin/env python3
"""Record released Hadoop JUnit and case-local adapter hashes without Java."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
HADOOP = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
TEST_JAR = HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"
TEST_CLASS = "org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.class"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with zipfile.ZipFile(TEST_JAR) as archive:
        original_class_sha = hashlib.sha256(archive.read(TEST_CLASS)).hexdigest()
    sources = {name: sha(HERE / name) for name in
               ("RecoveryProbe.java", "PatchRecovery.java", "CoverageRecovery.java",
                "RunOriginalJUnit.java", "run_original.py", "campaign.py", "audit_raw.py",
                "audit_archived_pilots.py")}
    source = (SOURCE / "java" / "org/apache/hadoop/hdfs/server/namenode/ha"
              / "TestPipelinesFailover.java")
    result = {
        "schema": 1,
        "original_junit": "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization",
        "original_test_class_sha256": original_class_sha,
        "original_test_jar_sha256": sha(TEST_JAR),
        "original_test_source_sha256": sha(source),
        "original_test_resource_hdfs_site_xml_sha256": sha(SOURCE / "resources/hdfs-site.xml"),
        "released_production_jar_sha256": {
            "hadoop-hdfs": sha(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"),
            "hadoop-hdfs-client": sha(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"),
            "hadoop-common": sha(HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar"),
        },
        "adapter_sources_sha256": sources,
        "topology_source": "TestPipelinesFailover.java:87,328,418-422; NN_COUNT=3 and newMiniCluster(conf,3)",
        "graphchecker_runtime_used": False,
    }
    temporary = HERE / "provenance.json.tmp"
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    temporary.replace(HERE / "provenance.json")
    print(json.dumps({"test_jar": result["original_test_jar_sha256"],
                      "test_class": original_class_sha,
                      "test_resource": result["original_test_resource_hdfs_site_xml_sha256"]}))


if __name__ == "__main__":
    main()
