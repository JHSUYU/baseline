#!/usr/bin/env python3
"""Read-only, no-JVM source/artifact preflight; does not admit node2 runtime."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    manifest = json.loads((HERE / "sha-manifest.json").read_text())
    assert manifest["case_id"] == "SOLR-37"
    for name, record in manifest["files"].items():
        path = HERE / name
        assert path.stat().st_size == record["bytes"] and sha(path) == record["sha256"], name
    config = json.loads((HERE / "config-healthy-node2.json").read_text())
    request = json.loads((HERE / "admission-request.json").read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    assert request["go"] is False and request["execution_status"] == "not_launched"
    assert request["runner_sha256"] == sha(HERE / "run_campaign.py")
    assert request["modes"]["healthy"]["config_sha256"] == sha(HERE / "config-healthy-node2.json")
    assert config["calibration_only"] is True and config["auto_promote_if_healthy"] is False
    assert config["budget"]["trials"] == 1 and config["case_id"] == "SOLR-37"
    assert config["site_file"] == str(HERE / "sites.json")
    assert len(sites["doors"]) == 1
    assert sites["doors"][0] == {
        "class": "org.apache.solr.common.cloud.ZkStateReader",
        "callee": ("org.apache.solr.common.cloud.SolrZkClient#getData"
                   "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                   "Lorg/apache/zookeeper/data/Stat;Z)[B"),
        "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
    }
    assert {"clazz": "org.apache.solr.common.cloud.ZkStateReader$StateWatcher",
            "descriptor": "(Lorg/apache/zookeeper/Watcher$Event$EventType;)V",
            "method": "refreshAndWatch"} in sites["regions"]
    assert {"org.apache.solr.common.cloud.ZkStateReader",
            "org.apache.solr.common.cloud.ZkStateReader$StateWatcher"}.issubset(config["agent_include"])
    assert config["agent_properties"]["adapter.jar"] == str(
        ROOT / "Mallory/adapters/solr/target/mallory-solr-adapter-v46.jar")
    assert config["command"][1] == str(ROOT / "Mallory/adapters/solr/releases/v46/run_pilot.py")
    for item in config["runtime_artifacts"]:
        assert sha(Path(item["path"])) == item["sha256"], item["path"]
    source = Path(config["mapping"]["inventory_source_root"])
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    assert commit == "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
    target = source / config["target"]["source_path"]
    assert sha(target) == config["mapping"]["target_source_sha256"]
    junit = source / "solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java"
    assert sha(junit) == config["mapping"]["test_source_sha256"]
    watcher = source / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    assert sha(watcher) == config["mapping"]["watcher_source_sha256"]
    lines = watcher.read_text().splitlines()
    for n, snippet in {1384: "fetchCollectionState(coll, this, collectionPath)",
                       1390: "KeeperException.ConnectionLossException",
                       1641: "zkClient.getData(collectionPath, watcher, stat, true)"}.items():
        assert snippet in lines[n - 1], n
    for jar_key, class_key, members in [
        ("compiled_jar", "compiled_class_sha256",
         {"org/apache/solr/update/processor/DistributedZkUpdateProcessor.class":
          config["mapping"]["compiled_class_sha256"]}),
        ("compiled_solrj_jar", "watcher_class_sha256", config["mapping"]["watcher_class_sha256"]),
    ]:
        jar = Path(config["mapping"][jar_key])
        expected_jar = config["mapping"].get(jar_key + "_sha256")
        if expected_jar is not None:
            assert sha(jar) == expected_jar, jar_key
        with zipfile.ZipFile(jar) as archive:
            for member, expected in members.items():
                assert hashlib.sha256(archive.read(member)).hexdigest() == expected, member
    print(json.dumps({"preflight": "passed_static_only", "case_id": "SOLR-37",
                      "source_commit": commit, "config_sha256": sha(HERE / "config-healthy-node2.json"),
                      "sites_sha256": sha(HERE / "sites.json"),
                      "runtime_checkout_verified": False, "go": False}, sort_keys=True))


if __name__ == "__main__":
    main()
