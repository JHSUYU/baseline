#!/usr/bin/env python3
"""Check the SOLR-09 healthy selector and its immutable inputs without a JVM."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


HERE = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node2", action="store_true",
                        help="check the strict node2 lane3 selector")
    args = parser.parse_args()
    manifest = json.loads((HERE / ("manifest-node2-lane3.json" if args.node2
                                  else "manifest.json")).read_text())
    for name, record in manifest["files"].items():
        path = Path(record["path"])
        require(path.is_file(), f"missing {name}: {path}")
        require(sha256(path.read_bytes()) == record["sha256"],
                f"SHA-256 mismatch for {name}: {path}")

    config = json.loads((HERE / ("healthy-node2-lane3.json" if args.node2
                                 else "healthy.json")).read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    source = Path(config["cwd"])
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    require(revision == manifest["source_commit"], "Solr source commit mismatch")
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True).strip()
    require(not dirty, "Solr source checkout is dirty")

    require(config["case_id"] == manifest["case_id"], "wrong case ID")
    require(config["cluster_test"] == manifest["selector"], "wrong JUnit selector")
    require(config["source_equivalent_root"] == str(source), "source root mismatch")
    require(config["site_file"] == str(HERE / "sites.json"), "site file mismatch")
    require(config["calibration_only"] is True, "config is not healthy only")
    require(config["auto_promote_if_healthy"] is False, "automatic promotion enabled")
    require(config["budget"]["trials"] == 1, "healthy budget is not one trial")
    require(config["expected_target_class_sha256"] ==
            manifest["compiled_classes"]["core_jar"][
                "org/apache/solr/cloud/api/collections/DeleteReplicaCmd.class"],
            "target class binding mismatch")
    if args.node2:
        require(config["require_event_time_paths"] is True,
                "strict event-time paths are disabled")
        require(config["reject_coarse_roots"] is True,
                "coarse roots are enabled")
        require(config["allow_local_timeline_doors"] is True,
                "local timeline diagnostic is disabled")
        require(config["agent_jar"] ==
                "/users/ZhenyuLi/baseline/Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar",
                "wrong event-time agent")
        require(config["command"][1] ==
                "/users/ZhenyuLi/baseline/Mallory/adapters/solr/releases/v38/run_pilot.py",
                "wrong Solr JUnit runner")

    door = sites["doors"]
    require(len(door) == 1, "expected one exact typed coordination wait door")
    require(door[0] == {
        "class": "org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler",
        "method": "waitForCoreNodeGone",
        "descriptor": "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z",
        "line": 434,
        "callee": "org.apache.solr.common.cloud.ZkStateReader#waitForState(Ljava/lang/String;JLjava/util/concurrent/TimeUnit;Ljava/util/function/Predicate;)V",
        "exception_class": "java.util.concurrent.TimeoutException",
    }, "typed wait door changed")
    require({(row["clazz"], row["method"], row["line"])
             for row in sites["targets"]} == {
                 ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd", "deleteCore", 277),
                 ("org.apache.solr.cloud.api.collections.DeleteReplicaCmd", "deleteCore", 278),
             }, "target selection changed")

    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file(), f"missing runtime artifact: {path}")
        require(sha256(path.read_bytes()) == artifact["sha256"],
                f"runtime artifact SHA-256 mismatch: {path}")

    core_jar = Path(manifest["files"]["core_jar"]["path"])
    with zipfile.ZipFile(core_jar) as archive:
        for name, expected in manifest["compiled_classes"]["core_jar"].items():
            require(sha256(archive.read(name)) == expected,
                    f"compiled class SHA-256 mismatch: {name}")

    print(json.dumps({
        "status": ("strict_node2_healthy_only_ready_for_dispatch" if args.node2
                   else "source_pinned_candidate_requires_runtime_upgrade"),
        "case_id": config["case_id"],
        "source_commit": revision,
        "config_sha256": manifest["files"]["config"]["sha256"],
        "sites_sha256": manifest["files"]["sites"]["sha256"],
        "jvm_run": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
