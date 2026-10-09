#!/usr/bin/env python3
"""Read-only HDFS-34 source, fixture, bytecode, and config admission check."""

import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts


SOURCE_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
HDFS = SOURCE_ROOT / "hadoop-hdfs-project/hadoop-hdfs"
MAIN = HDFS / "src/main/java"
CLASSES = HDFS / "target/classes"
TEST = HDFS / "src/test/java/org/apache/hadoop/hdfs/TestDFSUpgradeFromImage.java"
CLASS_ROOT = "org/apache/hadoop/hdfs/"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def javap(path):
    return subprocess.run(["javap", "-c", "-l", "-p", str(path)],
                          check=True, capture_output=True, text=True).stdout


def method_body(disassembly, signature):
    start = disassembly.index(signature)
    next_method = re.search(r"(?m)^  [^\n]+\([^\n]*\)(?: throws [^\n]*)?;$",
                            disassembly[start + len(signature):])
    if next_method is None:
        return disassembly[start:]
    return disassembly[start:start + len(signature) + next_method.start()]


def version_fields(data):
    fields = {}
    for line in data.decode("utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    return fields


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    config = json.loads((HERE / "HDFS-34-healthy-only.json").read_text())
    site = json.loads((HERE / "HDFS-34.sites.json").read_text())
    assert receipt["source_commit"] == subprocess.run(
        ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    for artifact in receipt["artifacts"]:
        path = Path(artifact["path"])
        assert path.is_file() and sha(path) == artifact["sha256"], path
    validate_config(config)
    verify_runtime_artifacts(config)
    assert config["cluster_test"] == (
        "org.apache.hadoop.hdfs.TestDFSUpgradeFromImage#testUpgradeFromRel22Image")
    assert config["calibration_only"] and config["auto_promote_if_healthy"] is False
    assert config["mapping"]["healthy_seed_verified"] is False
    assert config["mapping"]["verified_healthy_probe"] is None
    assert config["mapping"]["node_identity_binding_verified"] is False
    assert config["healthy_gate"]["require_target_exception_absent"] is True
    assert config["healthy_gate"]["require_named_target_node"] is True
    assert config["reject_coarse_roots"] and config["require_event_time_paths"]
    assert config["healthy_gate"]["minimum_healthy_observed_path_doors"] >= 1
    assert "org.apache.hadoop.hdfs.server.common.StorageInfo" in config["agent_include"]

    assert len(site["doors"]) == 2
    assert any(door["clazz"].endswith("BPServiceActor") and
               door["line"] == 260 and "#versionRequest()" in door["callee"]
               for door in site["doors"])
    assert any(door["clazz"].endswith("StorageInfo") and
               door["line"] == 272 and
               door["callee"] == "java.util.Properties#load(Ljava/io/InputStream;)V"
               for door in site["doors"])
    assert config["target"]["source_line"] == 744
    assert config["target"]["check_sites"][0].endswith("@739:branch:5")
    assert config["target"]["throw_site"].endswith("@744:throw:1")

    test_source = TEST.read_text()
    assert "void testUpgradeFromRel22Image()" in test_source
    assert "unpackStorage(HADOOP22_IMAGE, HADOOP_DFS_DIR_TXT)" in test_source
    assert "numDataNodes(4)" in test_source
    assert "bld.format(false).startupOption(StartupOption.UPGRADE)" in test_source
    assert "readProperties(sd);" in (MAIN / (CLASS_ROOT +
        "server/datanode/DataStorage.java")).read_text()

    data = javap(CLASSES / (CLASS_ROOT + "server/datanode/DataStorage.class"))
    transition = method_body(data, "private boolean doTransition(")
    assert "readProperties:(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V" in transition
    assert "Incompatible namespaceIDs in" in transition
    assert transition.index("readProperties:(") < transition.index("Incompatible namespaceIDs in")
    assert "line 739:" in transition and "line 744:" in transition
    code, lines = transition.split("    LineNumberTable:", 1)
    guard_start = int(re.search(r"line 739: (\d+)", lines).group(1))
    guard_end = int(re.search(r"line 740: (\d+)", lines).group(1))
    branches = [(int(offset), opcode) for offset, opcode in
                re.findall(r"(?m)^\s*(\d+):\s+(if\w+|tableswitch|lookupswitch)\b", code)]
    guard = [offset for offset, _ in branches if guard_start <= offset < guard_end]
    assert len(guard) == 1 and sum(offset <= guard[0] for offset, _ in branches) == 5
    throw_start = int(re.search(r"line 744: (\d+)", lines).group(1))
    throw_end = int(re.search(r"line 748: (\d+)", lines).group(1))
    assert re.search(rf"(?m)^\s*{throw_end - 1}: athrow$", code)
    assert throw_start < throw_end
    actor = method_body(javap(CLASSES / (CLASS_ROOT +
        "server/datanode/BPServiceActor.class")),
        "org.apache.hadoop.hdfs.server.protocol.NamespaceInfo retrieveNamespaceInfo(")
    assert "DatanodeProtocolClientSideTranslatorPB.versionRequest:" in actor
    assert "line 260:" in actor and "java/io/IOException" in actor
    info = method_body(javap(CLASSES / (CLASS_ROOT +
        "server/common/StorageInfo.class")),
        "public static java.util.Properties readPropertiesFile(")
    assert "java/util/Properties.load:(Ljava/io/InputStream;)V" in info
    assert "line 272:" in info
    assert "testUpgradeFromRel22Image()" in javap(HDFS / "target/test-classes" /
        (CLASS_ROOT + "TestDFSUpgradeFromImage.class"))

    archive = HDFS / "target/test-classes/hadoop-22-dfs-dir.tgz"
    ns_ids = set()
    dn_current = 0
    nn_current = 0
    with tarfile.open(archive, "r:gz") as content:
        for member in content:
            if not member.isfile() or not member.name.endswith("/current/VERSION"):
                continue
            if "/data/" not in member.name and "/name-" not in member.name:
                continue
            fields = version_fields(content.extractfile(member).read())
            ns_ids.add(fields["namespaceID"])
            assert fields["layoutVersion"] == "-33", member.name
            if "/data/" in member.name:
                dn_current += 1
            else:
                nn_current += 1
        assert not any("BP-" in member.name and member.name.endswith("/VERSION")
                       for member in content.getmembers())
    assert ns_ids == {"-386152743"} and dn_current == 8 and nn_current == 2
    print("HDFS-34 source/JUnit, typed door, fixture, bytecode, and SHA preflight: PASS")


if __name__ == "__main__":
    main()
