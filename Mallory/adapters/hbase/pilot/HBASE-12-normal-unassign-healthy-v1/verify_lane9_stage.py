#!/usr/bin/env python3
"""Read-only node1 lane9 HBASE-12 normal-unassign admission preflight."""

import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
CONFIG = HERE / "HBASE-12.lane9-healthy.json"
OUTPUT = ROOT / "data/mallory/calibration_v33/HBASE-12"


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
    assert not config["mapping"]["healthy_seed_verified_for_this_stage"]
    assert config["mapping"]["isolation_lane"] == "lane9-next"
    assert config["cluster_test"] == (
        "org.apache.hadoop.hbase.client.TestAdmin2#testShouldUnassignTheRegion")
    assert config["command"][-2:] == ["org.apache.hadoop.hbase.client.TestAdmin2",
                                      "testShouldUnassignTheRegion"]
    assert config["mapping"]["request_qualified_rpc_port"] == (
        "hbase.pb.MasterService.UnassignRegion")
    assert config["mapping"]["request_qualified_node"] == "master0"
    assert not OUTPUT.exists()
    for artifact in config["runtime_artifacts"]:
        assert sha(artifact["path"]) == artifact["sha256"], artifact["path"]
    site = json.loads(Path(config["site_file"]).read_text())
    assert site["doors"] == []
    assert [target["line"] for target in site["targets"]] == [762, 763]
    for root in [Path(config["mapping"]["source_root"]),
                 Path(config["source_equivalent_root"])]:
        assert sha(root / "hbase-server/src/test/java/org/apache/hadoop/hbase/client/"
                   "TestAdmin2.java") == config["mapping"]["test_source_sha256"]
        assert sha(root / "hbase-server/src/test/java/org/apache/hadoop/hbase/client/"
                   "TestAdminBase.java") == config["mapping"]["test_base_source_sha256"]
        assert sha(root / config["target"]["source_path"]) == (
            config["mapping"]["target_source_sha256"])
    jar = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/"
               "hbase-server-2.6.6-tests.jar")
    assert sha(jar) == config["mapping"]["test_compiled_jar_sha256"]
    with ZipFile(jar) as archive:
        data = archive.read("org/apache/hadoop/hbase/client/TestAdmin2.class")
    assert hashlib.sha256(data).hexdigest() == config["mapping"]["test_compiled_class_sha256"]
    print(json.dumps({"status": "lane9_healthy_stage_preflight_passed",
                      "case_id": "HBASE-12", "config_sha256": sha(CONFIG),
                      "site_sha256": sha(config["site_file"]),
                      "source_equivalent_root": config["source_equivalent_root"],
                      "output_absent": True, "runtime_artifact_count": len(config["runtime_artifacts"]),
                      "healthy_run_performed": False}, sort_keys=True))


if __name__ == "__main__":
    main()
