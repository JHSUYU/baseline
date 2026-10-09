#!/usr/bin/env python3
"""Check the pinned SOLR-13 healthy selector without starting a JVM."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


HERE = Path(__file__).resolve().parent
CHECK = "org.apache.solr.cloud.api.collections.RoutedAlias#doSynchronous(Lorg/apache/solr/update/AddUpdateCommand;Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;Lorg/apache/solr/core/CoreContainer;)Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;@348:branch:1"


def require(value: bool, message: str) -> None:
    if not value:
        raise SystemExit(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_line(path: Path, line: int, fragment: str) -> None:
    lines = path.read_text().splitlines()
    require(line <= len(lines) and fragment in lines[line - 1],
            f"source control flow changed: {path.name}:{line}")


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    for name, record in manifest["files"].items():
        path = Path(record["path"])
        require(path.is_file() and sha(path) == record["sha256"],
                f"missing or changed {name}: {path}")
    config = json.loads((HERE / "healthy-node2-lane3.json").read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    source = Path(config["cwd"])
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True).strip()
    require(revision == manifest["source_commit"] and not dirty,
            "pinned Solr source commit changed or checkout is dirty")

    require(config["case_id"] == manifest["case_id"] and
            config["cluster_test"] == manifest["selector"], "selected JUnit changed")
    require(config["source_equivalent_root"] == str(source), "source root mismatch")
    require(config["site_file"] == str(HERE / "sites.json"), "site file mismatch")
    require(config["target"]["check_sites"] == [CHECK], "selected check changed")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1, "not one healthy-only trial")
    require(config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True,
            "strict event-time graph flags are missing")
    require(config["agent_jar"] ==
            "/users/ZhenyuLi/baseline/Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar",
            "wrong event-time agent")
    require(config["command"][1] ==
            "/users/ZhenyuLi/baseline/Mallory/adapters/solr/releases/v38/run_pilot.py",
            "wrong JUnit runner")
    require("-Dsolr.disableConfigSetsCreateAuthChecks=true" in
            config["env"]["JAVA_TOOL_OPTIONS"], "ConfigSet setup overlay missing")
    require(config["admission"]["output"] == manifest["output"] and
            config["admission"]["source_lock"] == manifest["source_lock"],
            "output or source lock changed")

    require(sites["doors"] == [{
        "class": "org.apache.solr.common.cloud.ZkStateReader$AliasesManager",
        "method": "applyModificationAndExportToZk",
        "descriptor": "(Ljava/util/function/UnaryOperator;)V",
        "line": 2259,
        "callee": "org.apache.solr.common.cloud.SolrZkClient#setData(Ljava/lang/String;[BIZ)Lorg/apache/zookeeper/data/Stat;",
        "exception_class": "org.apache.zookeeper.KeeperException$BadVersionException",
    }], "typed retry door changed")
    require({(row["clazz"], row["method"], row["line"])
             for row in sites["targets"]} == {
                 ("org.apache.solr.cloud.api.collections.RoutedAlias", "doSynchronous", 348),
                 ("org.apache.solr.cloud.api.collections.RoutedAlias", "doSynchronous", 350),
             }, "target site selection changed")
    require({row["clazz"] for row in sites["regions"]} == {
                "org.apache.solr.cloud.api.collections.RoutedAlias",
                "org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd",
                "org.apache.solr.common.cloud.ZkStateReader$AliasesManager",
            }, "command/target regions changed")

    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"runtime artifact SHA mismatch: {path}")
    for jar_name, classes in manifest["compiled_classes"].items():
        jar_key = "core_jar" if jar_name.startswith("solr-core") else "solrj_jar"
        with zipfile.ZipFile(manifest["files"][jar_key]["path"]) as archive:
            for class_name, expected in classes.items():
                require(hashlib.sha256(archive.read(class_name)).hexdigest() == expected,
                        f"compiled class SHA mismatch: {class_name}")
    require(config["expected_target_class_sha256"] ==
            manifest["compiled_classes"]["solr-core-8.11.4.jar"][
                "org/apache/solr/cloud/api/collections/RoutedAlias.class"],
            "selected target bytecode changed")

    target = Path(manifest["files"]["target_source"]["path"])
    manager = Path(manifest["files"]["zk_state_reader_source"]["path"])
    maintain = Path(manifest["files"]["alias_command_source"]["path"])
    test = Path(manifest["files"]["test_source"]["path"])
    for line, fragment in ((344, "ensureCollection"),
                           (346, "updateParsedCollectionAliases"),
                           (347, "observedCols"),
                           (348, "if (!observedCols.contains"),
                           (350, "throw new SolrException"),
                           (396, "remoteInvoke"),
                           (403, "aliasesManager.update")):
        source_line(target, line, fragment)
    for line, fragment in ((2259, "getZkClient().setData"),
                           (2262, "catch (KeeperException.BadVersionException"),
                           (2270, "update()")):
        source_line(manager, line, fragment)
    source_line(maintain, 173, "addCollectionToAlias")
    source_line(test, 89, "configureCluster(4)")
    source_line(test, 301, "addOneDocSynchCreation")
    source_line(test, 302, "addOneDocSynchCreation")

    print(json.dumps({"status": "source_pinned_healthy_only_ready_for_dispatch_gate",
                      "case_id": config["case_id"], "source_commit": revision,
                      "config_sha256": manifest["files"]["config"]["sha256"],
                      "sites_sha256": manifest["files"]["sites"]["sha256"],
                      "jvm_run": False}, sort_keys=True))


if __name__ == "__main__":
    main()
