#!/usr/bin/env python3
"""Read-only HBASE-34 v6 source, bytecode, trace, and artifact gate."""

import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PREVIOUS = ROOT / "Mallory/adapters/hbase/pilot/hbase34-zk-start-v5"
ARCHIVE = ROOT / "data/mallory/healthy_observations/HBASE-34-zk-start-healthy-v5"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
SERVER_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")
JAVAP = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javap"


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    config = json.loads((HERE / "healthy-v6.json").read_text())
    previous = json.loads((PREVIOUS / "healthy-v5.json").read_text())
    for key, path in (
        ("v5_config_sha256", PREVIOUS / "healthy-v5.json"),
        ("v5_result_sha256", ARCHIVE / "result.json"),
        ("v5_events_gzip_sha256", ARCHIVE / "trials/r0000/events.jsonl.gz"),
        ("jvm_cluster_util_source_sha256", SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/util/JVMClusterUtil.java"),
        ("hbase_server_jar_sha256", SERVER_JAR),
        ("overlay_jar_sha256", Path(manifest["overlay_jar_path"])),
        ("sites_sha256", HERE / "sites.json"),
        ("healthy_config_sha256", HERE / "healthy-v6.json"),
    ):
        require(path.is_file() and digest(path) == manifest[key], "changed or absent " + key)
    raw = gzip.decompress((ARCHIVE / "trials/r0000/events.jsonl.gz").read_bytes())
    require(hashlib.sha256(raw).hexdigest() == manifest["v5_raw_events_sha256"],
            "v5 raw events changed")
    events = [json.loads(line) for line in raw.splitlines()]
    doors = [event for event in events if event.get("type") == "DOOR_OBSERVED"]
    targets = [event for event in events if event.get("type") == "TARGET_CHECK" and
               event.get("site", "").endswith("@159:branch:7")]
    writes = [event for event in events if event.get("type") == "STATE_WRITE" and
              event.get("site", "").endswith("addKey(Lorg/apache/hadoop/hbase/security/token/AuthenticationKey;)V@189:map:1")]
    reads = [event for event in events if event.get("type") == "STATE_READ" and
             event.get("site", "").endswith("retrievePassword(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B@137:map:1")]
    require([event["seq"] for event in doors] == [2, 3, 7, 8] and
            all(event["node"] == "unknown" for event in doors) and
            len(targets) == 1 and targets[0]["seq"] == 219 and targets[0]["node"] == "rs0",
            "v5 actor-gap trace changed")
    require(len(writes) == len(reads) == 1 and writes[0]["seq"] == 9 and
            reads[0]["seq"] == 218 and
            all(writes[0][field] == reads[0][field] for field in ("object", "key", "version")),
            "v5 exact key-map identity changed")

    require(config["cluster_test"] == previous["cluster_test"] and
            config["target"] == previous["target"] and
            json.loads((HERE / "sites.json").read_text()) ==
            json.loads((PREVIOUS / "sites.json").read_text()),
            "test, target, or I/O catalog changed")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1 and not manifest["full_campaign_go"],
            "v6 must remain one healthy-only JUnit")
    require("org.apache.hadoop.hbase.util.JVMClusterUtil" in config["agent_include"] and
            "edu.uva.liftlab.mallory.hbase.ctoractor.CtorActorTransformer" in
            config["agent_properties"]["adapter.transformers"] and
            manifest["overlay_jar_path"] in config["agent_properties"]["adapter.jars"] and
            manifest["overlay_jar_path"] in config["command"][config["command"].index("-cp") + 1],
            "constructor transformer not selected")
    with ZipFile(manifest["overlay_jar_path"]) as jar:
        require("edu/uva/liftlab/mallory/hbase/ctoractor/CtorActorTransformer.class" in jar.namelist() and
                "edu/uva/liftlab/mallory/hbase/ctoractor/CtorActorHooks.class" in jar.namelist(),
                "overlay class absent")
    source = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/util/JVMClusterUtil.java").read_text()
    require("server = ctor.newInstance(c);" in source and
            "return new JVMClusterUtil.RegionServerThread(server, index);" in source and
            "server = hmc.getConstructor(Configuration.class).newInstance(c);" in source and
            "return new JVMClusterUtil.MasterThread(server, index);" in source,
            "indexed source construction path changed")
    bytecode = subprocess.run([JAVAP, "-cp", str(SERVER_JAR), "-c", "-l", "-p",
                               "org.apache.hadoop.hbase.util.JVMClusterUtil"],
                              text=True, capture_output=True, check=True).stdout
    require(bytecode.count("Constructor.newInstance:([Ljava/lang/Object;)Ljava/lang/Object;") >= 2 and
            "createRegionServerThread(org.apache.hadoop.conf.Configuration" in bytecode and
            "createMasterThread(org.apache.hadoop.conf.Configuration" in bytecode,
            "indexed factory bytecode changed")
    sys.path.insert(0, str(Path(config["core_release"])))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    print(json.dumps({"case_id": "HBASE-34", "mode": "healthy_only", "status": "preflight_passed",
                      "v5_door_actor": "unknown", "v5_target_actor": "rs0",
                      "same_map_object_key_version": True, "full_campaign_go": False}, sort_keys=True))


if __name__ == "__main__":
    main()
