#!/usr/bin/env python3
"""Check the HBASE-28 case package without starting HBase or using Git metadata."""

import argparse
import hashlib
import json
import pathlib
import zipfile


HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE.parents[4]
SOURCE = pathlib.Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require_hash(path, expected):
    assert path.is_file(), f"missing: {path}"
    assert digest(path) == expected, f"SHA mismatch: {path}"


def verify(mode):
    manifest = json.loads((HERE / "stage-manifest.json").read_text())
    for row in manifest["files"]:
        path = pathlib.Path(row["path"])
        require_hash(path if path.is_absolute() else BASE / path, row["sha256"])
    config = json.loads((HERE / f"HBASE-28.constructor-actor-{mode}.json").read_text())
    assert config["case_id"] == "HBASE-28"
    assert config["cluster_test"] == "org.apache.hadoop.hbase.TestInfoServers#testInfoServersRedirect"
    assert config["expected_target_class_sha256"] == config["source_pins"]["target_class_sha256"]
    assert "org.apache.hadoop.hbase.util.JVMClusterUtil" in config["agent_include"]
    assert "ConstructorActorTransformer" in config["agent_properties"]["adapter.transformers"]
    assert config["budget"]["max_faults_per_trial"] == 3
    assert config["calibration_only"] == (mode == "healthy")
    if mode == "full":
        assert not config.get("stage_only"), "full config awaits healthy admission"
        assert config["budget"]["trials"] == 80
        assert config["budget"]["seconds"] == 3600
    for row in config["runtime_artifacts"]:
        require_hash(pathlib.Path(row["path"]), row["sha256"])
    pins = config["source_pins"]
    require_hash(SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/regionserver/HRegionServer.java", pins["target_source_sha256"])
    require_hash(SOURCE / "hbase-server/src/test/java/org/apache/hadoop/hbase/TestInfoServers.java", pins["test_source_sha256"])
    require_hash(SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/util/JVMClusterUtil.java", pins["factory_source_sha256"])
    release = config["core_release"]
    require_hash(pathlib.Path(release["path"]) / "manifest.json", release["manifest_sha256"])
    server_jar = pathlib.Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")
    with zipfile.ZipFile(server_jar) as archive:
        clazz = archive.read("org/apache/hadoop/hbase/regionserver/HRegionServer.class")
    assert hashlib.sha256(clazz).hexdigest() == pins["target_class_sha256"]
    return {"case_id": "HBASE-28", "mode": mode, "pins": len(manifest["files"]),
            "core_release": release["release_id"], "status": "verified"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("healthy", "full"), required=True)
    print(json.dumps(verify(parser.parse_args().mode), sort_keys=True))
