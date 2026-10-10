#!/usr/bin/env python3
"""Stage an immutable HBASE-34 healthy probe for pretarget ZK key loading."""

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
PARENT = ROOT / "Mallory/adapters/hbase/overlays/hbase34-token-manager-actor-v1"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, contents):
    if path.exists():
        if path.read_text() != contents:
            raise SystemExit("refusing to replace existing " + str(path))
    else:
        path.write_text(contents)


def main():
    parent = json.loads((PARENT / "healthy-v4.json").read_text())
    sites = {
        "targets": copy.deepcopy(json.loads(Path(parent["site_file"]).read_text())["targets"]),
        "regions": copy.deepcopy(json.loads(Path(parent["site_file"]).read_text())["regions"]) + [
            {"clazz": "org.apache.hadoop.hbase.security.token.ZKSecretWatcher",
             "method": "start", "descriptor": "()V"},
        ],
        "doors": [
            {
                "clazz": "org.apache.hadoop.hbase.security.token.ZKSecretWatcher",
                "method": "start",
                "descriptor": "()V",
                "line": 61,
                "callee": "org.apache.hadoop.hbase.zookeeper.ZKUtil#watchAndCheckExists(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)Z",
                "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
            },
            {
                "clazz": "org.apache.hadoop.hbase.security.token.ZKSecretWatcher",
                "method": "start",
                "descriptor": "()V",
                "line": 63,
                "callee": "org.apache.hadoop.hbase.zookeeper.ZKUtil#getChildDataAndWatchForNewChildren(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)Ljava/util/List;",
                "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
            },
        ],
        "nodeBindings": [],
    }
    site_path = HERE / "sites.json"
    write_once(site_path, json.dumps(sites, indent=2, sort_keys=True) + "\n")

    config = copy.deepcopy(parent)
    config["revision"] = "HBASE-34-persistent-key-ZK-start-v5-healthy"
    config["site_file"] = str(site_path)
    config["agent_include"].append("org.apache.hadoop.hbase.security.token.ZKSecretWatcher")
    config["agent_properties"]["auto.io.doors"] = False
    config["agent_properties"]["state.maps"] = True
    config["mapping"].update({
        "status": "pending_pretarget_ZK_start_healthy_only_v5",
        "healthy_seed_verified": False,
        "node_identity_binding_verified": False,
        "full_campaign_gate": "HOLD until exact rs0 ZKSecretWatcher.start typed door, exact rs0 target, and event-time key-read-to-target relation are observed; a fault trial must retain the target",
        "source_path": "ZKSecretWatcher.start: register listener; watchAndCheckExists@61; conditional getChildDataAndWatchForNewChildren@63; KeeperException exits to AuthenticationTokenSecretManager.start catch@103-105 without watcher.abort",
    })
    config["runtime_artifacts"] = [
        item for item in config["runtime_artifacts"]
        if item["path"] != parent["site_file"]
    ]
    config["runtime_artifacts"].append({"path": str(site_path), "sha256": digest(site_path)})
    config_path = HERE / "healthy-v5.json"
    write_once(config_path, json.dumps(config, indent=2, sort_keys=True) + "\n")

    manifest = {
        "case_id": "HBASE-34",
        "kind": "isolated_healthy_only_pretarget_ZK_start_probe",
        "parent_v4_config_sha256": digest(PARENT / "healthy-v4.json"),
        "parent_v4_result_node1_sha256": "a8952762e4d783a9e5a8145cae2c10cb11a636390e2a2bf770f6e5d86c22ca15",
        "parent_v4_events_node1_sha256": "a88c48d35371a1b20259f8f394c598aab83edc4020b07967c02539cdad8e5d75",
        "source_git_revision": "d5f63f523c065f963992ea4e74db268d17816631",
        "zk_secret_watcher_source_sha256": digest(SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/ZKSecretWatcher.java"),
        "token_manager_source_sha256": digest(SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java"),
        "hbase_server_jar_sha256": digest(Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")),
        "sites_sha256": digest(site_path),
        "healthy_config_sha256": digest(config_path),
        "full_campaign_go": False,
    }
    write_once(HERE / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_id": "HBASE-34", "status": "staged_healthy_only", "config_sha256": manifest["healthy_config_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
