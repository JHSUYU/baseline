#!/usr/bin/env python3
"""Read-only HBASE-12 source, bytecode, and artifact admission check."""

import hashlib
import json
import struct
import sys
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PORT = "hbase.pb.MasterService.UnassignRegion"
NODE = "master0"
TEST_CLASS = "org/apache/hadoop/hbase/client/TestAdmin2.class"
BASE_CLASS = "org/apache/hadoop/hbase/client/TestAdminBase.class"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def methods_and_superclass(data):
    """Read the class header and method table without starting a JVM."""
    assert data[:4] == b"\xca\xfe\xba\xbe"
    cursor = 8

    def u2():
        nonlocal cursor
        value = struct.unpack_from(">H", data, cursor)[0]
        cursor += 2
        return value

    def u4():
        nonlocal cursor
        value = struct.unpack_from(">I", data, cursor)[0]
        cursor += 4
        return value

    cp = [None] * u2()
    i = 1
    while i < len(cp):
        tag = data[cursor]
        cursor += 1
        if tag == 1:
            length = u2()
            cp[i] = data[cursor:cursor + length].decode("utf-8")
            cursor += length
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            cursor += 4
        elif tag in (5, 6):
            cursor += 8
            i += 1
        elif tag in (7, 8, 16, 19, 20):
            cp[i] = u2()
        elif tag == 15:
            cursor += 3
        else:
            raise AssertionError(f"Unsupported constant pool tag {tag}")
        i += 1

    u2()  # access flags
    u2()  # this class
    superclass = cp[cp[u2()]]
    interface_count = u2()
    cursor += 2 * interface_count

    def skip_members(count):
        nonlocal cursor
        for _ in range(count):
            cursor += 6  # access, name, descriptor
            for _ in range(u2()):
                u2()  # attribute name
                length = u4()
                cursor += length

    skip_members(u2())  # fields
    methods = set()
    for _ in range(u2()):
        u2()  # access flags
        name = cp[u2()]
        descriptor = cp[u2()]
        methods.add((name, descriptor))
        for _ in range(u2()):
            u2()  # attribute name
            length = u4()
            cursor += length
    return superclass, methods


def main():
    config_path = HERE / "HBASE-12.healthy.json"
    config = json.loads(config_path.read_text())
    release = ROOT / "Mallory/dispatch/releases" / config["core_release"]["release_id"]
    assert sha(release / "manifest.json") == config["core_release"]["manifest_sha256"]
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import validate_config

    validate_config(config)
    assert config["calibration_only"] and config["budget"]["trials"] == 1
    assert config["mapping"]["fault_admission_blocked"]
    assert not config["mapping"]["healthy_seed_verified_for_this_stage"]
    assert config["agent_properties"]["auto.io.doors"] is False
    assert config["command"][-2:] == ["org.apache.hadoop.hbase.client.TestAdmin2",
                                      "testShouldUnassignTheRegion"]
    assert config["mapping"]["request_qualified_rpc_port"] == PORT
    assert config["mapping"]["request_qualified_node"] == NODE
    sites = json.loads(Path(config["site_file"]).read_text())
    assert sites["doors"] == []
    assert [entry["line"] for entry in sites["targets"]] == [762, 763]
    for artifact in config["runtime_artifacts"]:
        assert sha(artifact["path"]) == artifact["sha256"], artifact["path"]

    source = Path(config["mapping"]["source_root"])
    paths = {
        "test": source / "hbase-server/src/test/java/org/apache/hadoop/hbase/client/TestAdmin2.java",
        "base": source / "hbase-server/src/test/java/org/apache/hadoop/hbase/client/TestAdminBase.java",
        "admin": source / "hbase-client/src/main/java/org/apache/hadoop/hbase/client/Admin.java",
        "client": source / "hbase-client/src/main/java/org/apache/hadoop/hbase/client/HBaseAdmin.java",
        "handler": source / "hbase-server/src/main/java/org/apache/hadoop/hbase/master/MasterRpcServices.java",
        "target": source / config["target"]["source_path"],
        "original_test": source / "hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/TestRegionMove.java",
    }
    text = {name: path.read_text() for name, path in paths.items()}
    assert sha(paths["test"]) == config["mapping"]["test_source_sha256"]
    assert sha(paths["base"]) == config["mapping"]["test_base_source_sha256"]
    assert sha(paths["target"]) == config["mapping"]["target_source_sha256"]
    method = text["test"].split("public void testShouldUnassignTheRegion()", 1)[1].split("@Test", 1)[0]
    assert "createTableWithDefaultConf(tableName);" in method
    assert "ADMIN.unassign(regionInfo.getRegionName(), true);" in method
    assert "disableTable" not in method and "catch (" not in method
    assert "TEST_UTIL.startMiniCluster(NB_SERVERS);" in text["base"]
    assert "unassign(regionName);" in text["admin"]
    assert "master.unassignRegion(getRpcController(), request);" in text["client"]
    assert "master.getAssignmentManager().unassign(hri);" in text["handler"]
    assert "preTransitCheck(regionNode, STATES_EXPECTED_ON_UNASSIGN_OR_MOVE);" in text["target"]
    assert "if (isTableDisabled(regionNode.getTable()))" in text["target"]
    assert "throw new DoNotRetryIOException(regionNode.getTable()" in text["target"]
    assert "admin.disableTable(tableName);" in text["original_test"]
    assert "catch (DoNotRetryIOException e)" in text["original_test"]

    jar = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6-tests.jar")
    assert sha(jar) == config["mapping"]["test_compiled_jar_sha256"]
    with ZipFile(jar) as archive:
        test_data = archive.read(TEST_CLASS)
        base_data = archive.read(BASE_CLASS)
    assert hashlib.sha256(test_data).hexdigest() == config["mapping"]["test_compiled_class_sha256"]
    assert hashlib.sha256(base_data).hexdigest() == config["mapping"]["test_base_compiled_class_sha256"]
    superclass, methods = methods_and_superclass(test_data)
    assert superclass == "org/apache/hadoop/hbase/client/TestAdminBase"
    assert ("testShouldUnassignTheRegion", "()V") in methods
    base_superclass, base_methods = methods_and_superclass(base_data)
    assert ("setUpBeforeClass", "()V") in base_methods
    assert base_superclass == "java/lang/Object"

    print(json.dumps({"status": "source_bytecode_artifact_preflight_passed",
                      "case_id": "HBASE-12", "config_sha256": sha(config_path),
                      "selector_sha256": sha(HERE / "selector.json"),
                      "source_sha256": {name: sha(path) for name, path in paths.items()},
                      "compiled_test_class_sha256": hashlib.sha256(test_data).hexdigest(),
                      "compiled_base_class_sha256": hashlib.sha256(base_data).hexdigest(),
                      "healthy_run_performed": False, "fault_run_performed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
