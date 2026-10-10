#!/usr/bin/env python3
"""Stage HBASE-34 v6 with indexed MiniCluster constructor actor scopes."""

import copy
import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PREVIOUS = ROOT / "Mallory/adapters/hbase/pilot/hbase34-zk-start-v5"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
ARCHIVE = ROOT / "data/mallory/healthy_observations/HBASE-34-zk-start-healthy-v5"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_once(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if digest(source) != digest(destination):
            raise SystemExit("refusing to replace existing " + str(destination))
    else:
        shutil.copyfile(source, destination)


def write_once(path, content):
    if path.exists():
        if path.read_text() != content:
            raise SystemExit("refusing to replace existing " + str(path))
    else:
        path.write_text(content)


def main():
    built = HERE / "target/mallory-hbase-construction-actor.jar"
    if not built.is_file():
        raise SystemExit("run `mvn -o -q test package` in this directory first")
    release = HERE / "releases" / digest(built)[:16] / "overlay.jar"
    copy_once(built, release)
    old_site = PREVIOUS / "sites.json"
    new_site = HERE / "sites.json"
    copy_once(old_site, new_site)

    previous = json.loads((PREVIOUS / "healthy-v5.json").read_text())
    config = copy.deepcopy(previous)
    config["revision"] = "HBASE-34-indexed-constructor-actor-v6-healthy"
    config["site_file"] = str(new_site)
    config["agent_include"].append("org.apache.hadoop.hbase.util.JVMClusterUtil")
    config["agent_properties"]["adapter.jars"] += "," + str(release)
    config["agent_properties"]["adapter.transformers"] += ",edu.uva.liftlab.mallory.hbase.ctoractor.CtorActorTransformer"
    cp_index = config["command"].index("-cp") + 1
    config["command"][cp_index] = str(release) + ":" + config["command"][cp_index]
    config["mapping"].update({
        "status": "pending_indexed_constructor_healthy_only_v6",
        "healthy_seed_verified": False,
        "node_identity_binding_verified": False,
        "actor_binding": "JVMClusterUtil.createRegionServerThread/createMasterThread explicit index scopes the reflected server constructor before ZKSecretWatcher.start",
        "full_campaign_gate": "HOLD until typed rs0 ZK start door precedes same-map key write/read target with an observed event-time path, and injected trial retains exact rs0 target",
    })
    config["runtime_artifacts"] = [
        item for item in config["runtime_artifacts"]
        if item["path"] != str(old_site)
    ]
    config["runtime_artifacts"].extend([
        {"path": str(new_site), "sha256": digest(new_site)},
        {"path": str(release), "sha256": digest(release)},
    ])
    config_path = HERE / "healthy-v6.json"
    write_once(config_path, json.dumps(config, indent=2, sort_keys=True) + "\n")

    manifest = {
        "case_id": "HBASE-34",
        "kind": "isolated_healthy_only_indexed_constructor_actor_probe",
        "v5_config_sha256": digest(PREVIOUS / "healthy-v5.json"),
        "v5_result_sha256": digest(ARCHIVE / "result.json"),
        "v5_events_gzip_sha256": digest(ARCHIVE / "trials/r0000/events.jsonl.gz"),
        "v5_raw_events_sha256": json.loads((ARCHIVE / "trials/r0000/result.json").read_text())["events_sha256"],
        "source_git_revision": "d5f63f523c065f963992ea4e74db268d17816631",
        "jvm_cluster_util_source_sha256": digest(SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/util/JVMClusterUtil.java"),
        "hbase_server_jar_sha256": digest(Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")),
        "overlay_jar_sha256": digest(release),
        "overlay_jar_path": str(release),
        "sites_sha256": digest(new_site),
        "healthy_config_sha256": digest(config_path),
        "full_campaign_go": False,
    }
    write_once(HERE / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"case_id": "HBASE-34", "status": "staged_healthy_only_v6",
                      "config_sha256": manifest["healthy_config_sha256"],
                      "overlay_sha256": manifest["overlay_jar_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
