#!/usr/bin/env python3
"""Read-only source, bytecode, and artifact gate for HBASE-34 v5."""

import hashlib
import json
import subprocess
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
SERVER_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")
JAVAP = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javap"


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method_bytecode(clazz, start, stop):
    output = subprocess.run(
        [JAVAP, "-cp", str(SERVER_JAR), "-c", "-l", "-p", clazz],
        text=True, capture_output=True, check=True,
    ).stdout
    require(start in output and stop in output, "missing bytecode method boundary: " + clazz)
    return output.split(start, 1)[1].split(stop, 1)[0]


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    config = json.loads((HERE / "healthy-v5.json").read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    parent_path = ROOT / "Mallory/adapters/hbase/overlays/hbase34-token-manager-actor-v1/healthy-v4.json"
    parent = json.loads(parent_path.read_text())
    require(digest(parent_path) == manifest["parent_v4_config_sha256"], "parent v4 changed")
    for name, path in (
        ("zk_secret_watcher_source_sha256", SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/ZKSecretWatcher.java"),
        ("token_manager_source_sha256", SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java"),
        ("hbase_server_jar_sha256", SERVER_JAR),
        ("sites_sha256", HERE / "sites.json"),
        ("healthy_config_sha256", HERE / "healthy-v5.json"),
    ):
        require(path.is_file() and digest(path) == manifest[name], "changed or absent " + name)
    require(config["cluster_test"] == parent["cluster_test"] and config["target"] == parent["target"],
            "cluster test or target changed")
    require(config["calibration_only"] and not config["auto_promote_if_healthy"] and
            config["budget"]["trials"] == 1 and not manifest["full_campaign_go"],
            "v5 must be one healthy-only trial")
    require(config["site_file"] == str(HERE / "sites.json") and
            "org.apache.hadoop.hbase.security.token.ZKSecretWatcher" in config["agent_include"],
            "ZKSecretWatcher not selected")
    require(config["agent_properties"]["auto.io.doors"] is False and
            config["agent_properties"]["state.maps"] is True,
            "I/O door or key-map instrumentation changed")
    old_sites = json.loads(Path(parent["site_file"]).read_text())
    require(sites["targets"] == old_sites["targets"] and
            sites["regions"] == old_sites["regions"] + [
                {"clazz": "org.apache.hadoop.hbase.security.token.ZKSecretWatcher",
                 "method": "start", "descriptor": "()V"}],
            "target or ZK start region changed")
    require(len(sites["doors"]) == 2 and
            {(door["line"], door["method"]) for door in sites["doors"]} ==
            {(61, "start"), (63, "start")}, "unexpected typed doors")

    zk_source = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/ZKSecretWatcher.java").read_text()
    manager_source = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java").read_text()
    require("ZKUtil.watchAndCheckExists(watcher, keysParentZNode)" in zk_source and
            "ZKUtil.getChildDataAndWatchForNewChildren(watcher, keysParentZNode)" in zk_source,
            "source call sites changed")
    require("this.zkWatcher.start();" in manager_source and
            "catch (KeeperException ke)" in manager_source and
            'LOG.error("ZooKeeper initialization failed", ke)' in manager_source,
            "manager catch path changed")
    start = method_bytecode("org.apache.hadoop.hbase.security.token.ZKSecretWatcher",
                            "public void start()", "public void nodeCreated")
    manager_start = method_bytecode("org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager",
                                    "public void start()", "public void stop()")
    require("ZKUtil.watchAndCheckExists:(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)Z" in start and
            "ZKUtil.getChildDataAndWatchForNewChildren:(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)Ljava/util/List;" in start and
            "line 61: 19" in start and "line 63: 41" in start,
            "bytecode does not match typed ZK callsite lines")
    require("AuthenticationTokenSecretManager$LeaderElector.start:()V" in manager_start and
            "Class org/apache/zookeeper/KeeperException" in manager_start,
            "bytecode does not catch KeeperException around ZK start")

    sys.path.insert(0, str(Path(config["core_release"])))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    print(json.dumps({"case_id": "HBASE-34", "mode": "healthy_only",
                      "status": "preflight_passed", "typed_doors": [61, 63],
                      "full_campaign_go": False}, sort_keys=True))


if __name__ == "__main__":
    main()
