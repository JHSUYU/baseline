#!/usr/bin/env python3
"""Read-only HBASE-34 actor-overlay admission; does not start a JVM or test."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    manifest = json.loads((HERE / "manifest.json").read_text())
    config = json.loads((HERE / "healthy-v4.json").read_text())
    previous = json.loads((ROOT / "Mallory/adapters/hbase/pilot/hbase34-kdc-classpath-v3/healthy.json").read_text())
    for entry in manifest["pinned_files"]:
        path = Path(entry["path"])
        require(path.is_file() and sha256(path) == entry["sha256"],
                "missing or changed pinned file: " + str(path))
    require(sha256(HERE / "healthy-v4.json") == manifest["healthy_config_sha256"],
            "healthy v4 config changed")
    require(config["case_id"] == "HBASE-34" and config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and config["budget"]["trials"] == 1,
            "v4 must remain one healthy-only trial")
    for key in ("cluster_test", "target", "site_file", "expected_target_class_sha256"):
        require(config[key] == previous[key], "v3/v4 selection changed: " + key)
    require(config["agent_properties"]["adapter.transformers"] ==
            "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer,"
            "edu.uva.liftlab.mallory.hbase.tokenmanager.TokenManagerActorTransformer",
            "actor transformer not selected after HBase adapter")
    overlay = next(x for x in config["runtime_artifacts"] if x["path"].endswith("/overlay.jar"))
    require(overlay["sha256"] == manifest["overlay_jar_sha256"] and
            Path(overlay["path"]).is_file() and
            sha256(Path(overlay["path"])) == manifest["overlay_jar_sha256"],
            "actor overlay artifact changed")
    require(overlay["path"] in config["agent_properties"]["adapter.jars"] and
            overlay["path"] in config["command"][config["command"].index("-cp") + 1],
            "actor overlay absent from adapter or workload classpath")
    source_root = Path(config["source_equivalent_root"])
    token_source = (source_root / "hbase-server/src/main/java/org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.java").read_text()
    listener_source = (source_root / "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKListener.java").read_text()
    rpc_source = (source_root / "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc/RpcServer.java").read_text()
    adapter_source = (ROOT / "Mallory/adapters/hbase/src/main/java/edu/uva/liftlab/mallory/hbase/HBaseHooks.java").read_text()
    require("new ZKSecretWatcher(conf, zk, this)" in token_source and
            "protected ZKWatcher watcher;" in listener_source and
            "server.getZooKeeper()" in rpc_source and
            "Probe.registerNode(watcher, node, 0)" in adapter_source,
            "exact watcher ownership chain missing from pinned sources")
    require(config["mapping"]["node_identity_binding_verified"] is False and
            config["mapping"]["full_campaign_gate"].startswith("HOLD"),
            "future full campaign gate removed")
    return {"case_id": "HBASE-34", "go": True, "mode": "healthy_only",
            "actor_binding": "exact secret-manager ZKWatcher receiver alias",
            "full_campaign_go": False,
            "config_sha256": manifest["healthy_config_sha256"],
            "overlay_jar_sha256": manifest["overlay_jar_sha256"]}


def verify_prior_evidence():
    pinned = json.loads((HERE / "manifest.json").read_text())["prior_v3_evidence"]
    for key in ("checkpoint", "result", "events"):
        path = Path(pinned[key + "_path"])
        require(path.is_file() and sha256(path) == pinned[key + "_sha256"],
                "v3 evidence absent or changed: " + str(path))
    checkpoint = json.loads(Path(pinned["checkpoint_path"]).read_text())
    result = json.loads(Path(pinned["result_path"]).read_text())
    require(checkpoint["status"] == "healthy_node_identity_missing" and
            checkpoint["completed_trials"] == [0], "v3 checkpoint changed")
    junit = result["junit_validation"]
    require(junit["status"] == "passed" and junit["tests"] == 1 and
            junit["succeeded"] == 1 and junit["failures"] == 0 and junit["errors"] == 0,
            "v3 JUnit receipt changed")
    events = [json.loads(line) for line in gzip.open(pinned["events_path"], "rt")]
    targets = [event for event in events if event["type"] == "TARGET_CHECK"]
    doors = [event for event in events if event["type"] == "DOOR_OBSERVED"]
    require(len(targets) == 1 and targets[0]["seq"] == 234 and
            targets[0]["node"] == "unknown" and targets[0]["thread"] == pinned["target_thread"]
            and targets[0]["site"].endswith("@159:branch:7"),
            "v3 exact target evidence changed")
    require(len(doors) == pinned["door_count"], "v3 door count changed")
    return {"prior_v3_evidence_verified": True, "target_seq": 234,
            "target_node": "unknown", "door_count": len(doors)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-prior-evidence", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.verify_prior_evidence:
        result.update(verify_prior_evidence())
    print(json.dumps(result, indent=2, sort_keys=True))
