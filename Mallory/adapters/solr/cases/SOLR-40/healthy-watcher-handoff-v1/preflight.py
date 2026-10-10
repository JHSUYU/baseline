#!/usr/bin/env python3
"""Offline-only static preflight for the SOLR-40 watcher handoff trial."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1"
CHECK = "org.apache.solr.update.processor.RoutedAliasUpdateProcessor#getAliasProps(Lorg/apache/solr/request/SolrQueryRequest;Ljava/lang/String;)Ljava/util/Map;@132:branch:1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_line(path: Path, number: int, fragment: str) -> None:
    rows = path.read_text().splitlines()
    require(len(rows) >= number and fragment in rows[number - 1],
            f"source line changed: {path}:{number}")


def main() -> dict:
    manifest = read(HERE / "manifest.json")
    require(manifest["case_id"] == "SOLR-40", "wrong case manifest")
    for label, record in manifest["files"].items():
        path = Path(record["path"])
        require(path.is_file() and sha(path) == record["sha256"],
                f"missing or changed {label}: {path}")
    config = read(HERE / "config.json")
    sites = read(HERE / "sites.json")
    source = Path(config["cwd"])
    require(config["case_id"] == "SOLR-40" and
            config["cluster_test"] == "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test",
            "selected JUnit changed")
    require(config["target"]["check_sites"] == [CHECK] and
            config["expected_target_class_sha256"] == manifest["classes"]["target"],
            "selected target changed")
    require(config["calibration_only"] is True and config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1 and config["fault_types"] == ["EXCEPTION"],
            "healthy-only restriction changed")
    require(config["agent_properties"]["state.fields"] is True and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "watcher handoff observation settings changed")
    require(config["site_file"] == str(HERE / "sites.json") and
            config["command"][1] == str(ROOT / "Mallory/adapters/solr/cases/SOLR-40/full-v1/run_pilot.py") and
            config["command"][2:5] == ["SOLR-40", "--source", str(source)],
            "case-local site or JUnit runner changed")
    require(config["source_equivalent_root"] == str(source) and source.is_dir(),
            "pinned Solr source unavailable")
    require(subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    text=True).strip() == manifest["source_commit"] and
            not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"],
                                        text=True).strip(), "Solr source revision or cleanliness changed")
    require("-Dsolr.disableConfigSetsCreateAuthChecks=true" in config["env"]["JAVA_TOOL_OPTIONS"] and
            config["env"]["MALLORY_SOLR_AWAITSFIX"] == "1", "passing JUnit fixture flags changed")
    require(sites["doors"] == [manifest["door"]] and
            [(row["clazz"], row["line"]) for row in sites["targets"]] == [
                ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor", 132),
                ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor", 133)] and
            {(row["clazz"], row["method"]) for row in sites["regions"]} == {
                ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager", "process"),
                ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager", "setIfNewer"),
                ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager", "getAliases"),
                ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor", "getAliasProps"),
            }, "door, target, or handoff regions changed")
    require("org.apache.solr.common.cloud.ZkStateReader$AliasesManager" in config["agent_include"] and
            "org.apache.solr.update.processor.RoutedAliasUpdateProcessor" in config["agent_include"],
            "handoff classes not instrumented")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"runtime artifact changed: {path}")
    core = config["mapping"]["pinned_core"]
    require(Path(core["root"]).resolve() == PINNED, "pinned core path changed")
    for rel, digest in core["files"].items():
        require(sha(PINNED / rel) == digest, f"pinned core changed: {rel}")
    sys.path.insert(0, str(PINNED))
    from Mallory.core import campaign  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(PINNED), "wrong campaign core loaded")
    campaign.validate_config(config)

    for name, rel in (("test", "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"),
                      ("target", "solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java"),
                      ("watcher", "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java")):
        require(sha(source / rel) == config["mapping"][f"{name}_source_sha256"],
                f"{name} source changed")
    with zipfile.ZipFile(config["mapping"]["target_compiled_jar"]) as archive:
        target = archive.read("org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class")
    with zipfile.ZipFile(config["mapping"]["watcher_compiled_jar"]) as archive:
        watcher = archive.read("org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class")
    require(hashlib.sha256(target).hexdigest() == manifest["classes"]["target"] and
            hashlib.sha256(watcher).hexdigest() == manifest["classes"]["watcher"],
            "compiled target or watcher class changed")
    processor = source / config["target"]["source_path"]
    reader = source / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    test = source / "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"
    for number, fragment in ((120, "getAliasProps"), (131, "getCollectionAliasProperties"),
                             (132, "aliasProperties.isEmpty"), (133, "newAliasMustExistException")):
        source_line(processor, number, fragment)
    for number, fragment in ((2223, "volatile read"), (2312, "zkClient.getData"),
                             (2314, "setIfNewer"), (2317, "ConnectionLossException"),
                             (2342, "aliases = newAliases")):
        source_line(reader, number, fragment)
    for number, fragment in ((89, "configureCluster(4)"), (132, "createTimeRoutedAlias"),
                             (138, "solrClient.add(alias"), (139, "solrClient.commit(alias)")):
        source_line(test, number, fragment)
    prior = read(Path(manifest["files"]["solr10_prior_healthy"]["path"]))
    require(prior["pilot_test"] == config["cluster_test"] and prior["healthy_seed_verified"] is True and
            prior["junit"]["status"] == "passed" and prior["junit"]["tests"] == 1,
            "passing selector baseline changed")
    request = read(HERE / "admission-request.json")
    require(request["go"] is False and request["mode"] == "healthy" and
            request["config_sha256"] == sha(HERE / "config.json"), "admission request changed")
    result = {"status": "offline_preflight_passed_healthy_only", "case_id": "SOLR-40",
              "door": DOOR, "target": CHECK, "config_sha256": sha(HERE / "config.json"),
              "sites_sha256": sha(HERE / "sites.json"), "jvm_run": False}
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
