#!/usr/bin/env python3
"""Static pin check for the ZOOKEEPER-04 healthy-only package; never runs JUnit."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / "stage-manifest.json").read_text())
config = json.loads((HERE / "healthy.json").read_text())

for name, pin in manifest["files"].items():
    path = Path(pin["path"])
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != pin["sha256"]:
        raise SystemExit(f"SHA mismatch: {name}: {actual}")

assert manifest["case_id"] == config["case_id"] == "ZOOKEEPER-04"
assert config["calibration_only"] and not config["auto_promote_if_healthy"]
assert config["cluster_test"] == "org.apache.zookeeper.test.QuorumTest#testLeaderShutdown"
assert config["target"]["nodes"] == ["zk1", "zk2", "zk3", "zk4", "zk5"]
assert config["agent_jar"] == manifest["files"]["agent_jar"]["path"]
assert config["site_file"] == manifest["files"]["site_catalog"]["path"]
assert config["mapping"]["test_source_sha256"] == manifest["files"]["zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java"]["sha256"]
assert config["expected_target_class_sha256"] == manifest["files"]["zookeeper-server/target/classes/org/apache/zookeeper/server/ZooKeeperServer.class"]["sha256"]
assert config["mapping"]["test_class_sha256"] == manifest["files"]["zookeeper-server/target/test-classes/org/apache/zookeeper/test/QuorumTest.class"]["sha256"]
assert Path(config["core_release"]).is_dir()

test = Path(manifest["files"]["zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java"]["path"]).read_text()
method = test.split("public void testLeaderShutdown()", 1)[1].split("@Test", 1)[0]
assert method.count("zk.setData(") == 2
assert "f.getSocket().shutdownInput()" in method
assert "zk.create(" in method
print("PASS: pins and source shape; JUnit not run")
