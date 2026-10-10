#!/usr/bin/env python3
"""Verify the SOLR-09 one-JUnit healthy role probe without starting a JVM."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
CORE = ROOT / "Mallory/adapters/solr/cases/SOLR-09/runtime-role-v1/work"
DOOR = ("org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler"
        "#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1")
CHECK = ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd"
         "#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;Ljava/lang/String;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;Ljava/lang/String;"
         "Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V@277:branch:7")
ROLE = "delete-replica-deletecore"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def line(path: Path, number: int, fragment: str) -> None:
    rows = path.read_text().splitlines()
    require(len(rows) >= number and fragment in rows[number - 1],
            f"source changed at {path}:{number}")


def main() -> dict:
    manifest = json.loads((HERE / "manifest.json").read_text())
    config = json.loads((HERE / "config.json").read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    require(manifest["case_id"] == config["case_id"] == "SOLR-09", "wrong case")
    for label, record in manifest["files"].items():
        path = Path(record["path"])
        require(path.is_file() and sha(path) == record["sha256"],
                f"missing or changed {label}: {path}")
    source = Path(config["cwd"])
    require(subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    text=True).strip() == manifest["source_commit"],
            "source revision changed")
    require(not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"],
                                        text=True).strip(), "source checkout is dirty")
    require(config["cluster_test"] ==
            "org.apache.solr.cloud.DeleteReplicaTest#deleteReplicaAndVerifyDirectoryCleanup",
            "unchanged cluster JUnit selector changed")
    require(config["target"]["check_sites"] == [CHECK] and
            config["target"]["source_line"] == 278 and
            config["expected_target_class_sha256"] == manifest["classes"]["target"],
            "exact target changed")
    require(config["site_file"] == str(HERE / "sites.json") and
            sites["doors"] == [manifest["door"]] and
            {(row["clazz"], row["line"]) for row in sites["targets"]} == {
                ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd", 277),
                ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd", 278)},
            "exact typed door or target catalog changed")
    require(config["agent_jar"] == manifest["files"]["role_agent"]["path"] and
            config["agent_properties"]["adapter.jar"] ==
            manifest["files"]["adapter"]["path"] and
            config["command"][1] == manifest["files"]["v38_junit_runner"]["path"],
            "pinned runtime changed")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"] == {"trials": 1, "seconds": 900,
                                  "trial_timeout_seconds": 480,
                                  "max_faults_per_trial": 1} and
            config["require_event_time_paths"] is False and
            config["reject_coarse_roots"] is True,
            "healthy-only bounds changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"runtime artifact changed: {path}")
    sys.path.insert(0, str(CORE))
    from Mallory.core import campaign  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(CORE),
            "wrong campaign core imported")
    campaign.validate_config(config)
    target = source / config["target"]["source_path"]
    overseer = source / "solr/core/src/java/org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler.java"
    test = source / "solr/core/src/test/org/apache/solr/cloud/DeleteReplicaTest.java"
    for number, fragment in ((251, "sendShardRequest"), (257, "processResponses"),
                             (260, "waitForCoreNodeGone"), (264, "deleteCoreNode"),
                             (265, "waitForCoreNodeGone"), (266, "return Boolean.FALSE"),
                             (277, "if (!callable.call())"), (278, "throw new SolrException")):
        line(target, number, fragment)
    for number, fragment in ((434, "zkStateReader.waitForState"),
                             (443, "catch (TimeoutException e)"), (444, "return false"),
                             (457, "offerStateUpdate")):
        line(overseer, number, fragment)
    for number, fragment in ((78, "configureCluster(4)"),
                             (149, "deleteReplicaAndVerifyDirectoryCleanup"),
                             (152, "createCollection"), (161, "deleteReplica")):
        line(test, number, fragment)
    role_java = Path(manifest["files"]["role_registry_source"]["path"])
    require(ROLE in role_java.read_text() and DOOR in role_java.read_text(),
            "role registry no longer binds selected wait site")
    with zipfile.ZipFile(manifest["files"]["core_jar"]["path"]) as archive:
        for member, expected in manifest["classes"].items():
            name = {"target": "org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class",
                    "door_owner": "org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler.class"}[member]
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected,
                    f"compiled class changed: {name}")
    request = json.loads((HERE / "admission-request.json").read_text())
    require(request["go"] is False and request["mode"] == "healthy" and
            request["config_sha256"] == sha(HERE / "config.json") and
            request["runner_sha256"] == sha(HERE / "run_healthy.py"),
            "admission request changed")
    receipt = {"status": "offline_preflight_passed_healthy_only", "case_id": "SOLR-09",
               "selector": config["cluster_test"], "target": CHECK, "door": DOOR,
               "role": ROLE, "config_sha256": sha(HERE / "config.json"),
               "jvm_run": False}
    print(json.dumps(receipt, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
