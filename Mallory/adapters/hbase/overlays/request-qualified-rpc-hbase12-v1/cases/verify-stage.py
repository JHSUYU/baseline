#!/usr/bin/env python3
"""Read-only node1 HBASE-12 scoped-RPC healthy admission preflight."""

import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path("/users/ZhenyuLi/baseline")
OVERLAY = ROOT / "Mallory/adapters/hbase/overlays/request-qualified-rpc-hbase12-v1"
CONFIG = OVERLAY / "cases/HBASE-12.scoped-healthy.json"
OUTPUT = ROOT / "data/mallory/calibration_hbase12_scoped_graph_v1/HBASE-12"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    config = json.loads(CONFIG.read_text())
    release = ROOT / "Mallory/dispatch/releases" / config["core_release"]["release_id"]
    assert sha(release / "manifest.json") == config["core_release"]["manifest_sha256"]
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import validate_config

    validate_config(config)
    assert config["case_id"] == "HBASE-12" and config["calibration_only"]
    assert config["budget"]["trials"] == 1
    assert config["mapping"]["fault_admission_blocked"]
    assert config["require_event_time_paths"] and not config["allow_local_timeline_doors"]
    assert config["mapping"]["request_qualified_rpc_port"] == (
        "hbase.pb.MasterService.UnassignRegion")
    assert config["mapping"]["request_qualified_node"] == "master0"
    assert config["command"][-2:] == ["org.apache.hadoop.hbase.client.TestAdmin2",
                                      "testShouldUnassignTheRegion"]
    assert config["command"][5] == "-Dmallory.hbase.rpc.door.case=HBASE-12"
    assert config["agent_properties"]["adapter.transformers"].endswith(
        "hbase12.RequestQualifiedRpcTransformer")
    assert not OUTPUT.exists()
    for artifact in config["runtime_artifacts"]:
        assert sha(artifact["path"]) == artifact["sha256"], artifact["path"]
    site = json.loads(Path(config["site_file"]).read_text())
    assert site["doors"] == []
    assert [target["line"] for target in site["targets"]] == [762, 763]
    for source in [Path(config["mapping"]["source_root"]),
                   Path(config["source_equivalent_root"])]:
        assert sha(source / "hbase-server/src/test/java/org/apache/hadoop/hbase/client/"
                   "TestAdmin2.java") == config["mapping"]["test_source_sha256"]
        assert sha(source / config["target"]["source_path"]) == (
            config["mapping"]["target_source_sha256"])
    jar = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/"
               "hbase-server-2.6.6-tests.jar")
    with ZipFile(jar) as archive:
        test_data = archive.read("org/apache/hadoop/hbase/client/TestAdmin2.class")
    assert hashlib.sha256(test_data).hexdigest() == (
        config["mapping"]["test_compiled_class_sha256"])
    print(json.dumps({"status": "node1_scoped_healthy_preflight_passed",
                      "case_id": "HBASE-12", "config_sha256": sha(CONFIG),
                      "site_sha256": sha(config["site_file"]),
                      "overlay_jar_sha256": sha(config["runtime_artifacts"][2]["path"]),
                      "runtime_artifact_count": len(config["runtime_artifacts"]),
                      "output_absent": True, "healthy_run_performed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
