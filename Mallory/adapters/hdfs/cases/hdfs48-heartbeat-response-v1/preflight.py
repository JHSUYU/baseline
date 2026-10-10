#!/usr/bin/env python3
"""Static admission for the unchanged HDFS-48 heartbeat-response healthy probe.

This script reads files and Git metadata only. It never starts Hadoop, Maven,
the agent, or a fault trial.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "HDFS-48-healthy-only.json"
SITES = HERE / "HDFS-48.sites.json"
PINS = HERE / "provenance.json"
SELECTOR = "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots#testRenameUndo_1"
TARGET = "org.apache.hadoop.hdfs.server.namenode.INodeDirectory"
DOOR_CALLEE = ("org.apache.hadoop.ipc.Client#getRpcResponse"
               "(Lorg/apache/hadoop/ipc/Client$Call;"
               "Lorg/apache/hadoop/ipc/Client$Connection;"
               "JLjava/util/concurrent/TimeUnit;)"
               "Lorg/apache/hadoop/io/Writable;")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, message, errors):
    if not ok:
        errors.append(message)


def audit():
    errors = []
    pins = json.loads(PINS.read_text())
    cfg = json.loads(CONFIG.read_text())
    sites = json.loads(SITES.read_text())
    check(pins["case_id"] == cfg["case_id"] == "HDFS-48", "case mismatch", errors)
    for label, spec in pins["pins"].items():
        path = Path(spec["path"])
        check(path.is_file(), f"missing {label}: {path}", errors)
        if path.is_file():
            check(sha256(path) == spec["sha256"], f"sha256 mismatch: {label}", errors)

    source_root = Path(pins["source_root"])
    if source_root.is_dir():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_root,
                              capture_output=True, text=True, check=False)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=source_root,
                               capture_output=True, text=True, check=False)
        check(head.returncode == 0 and head.stdout.strip() == pins["source_commit"],
              "Hadoop source commit mismatch", errors)
        check(dirty.returncode == 0 and not dirty.stdout.strip(),
              "Hadoop source root is dirty", errors)
    else:
        errors.append("Hadoop source root missing")

    check(cfg["cluster_test"] == SELECTOR, "selector changed", errors)
    check(cfg["cwd"] == str(source_root), "source root changed", errors)
    check(cfg.get("calibration_only") is True and
          cfg.get("auto_promote_if_healthy") is False and
          cfg["budget"]["trials"] == 1,
          "not restricted to one healthy calibration", errors)
    check("-Dtest=TestRenameWithSnapshots#testRenameUndo_1" in cfg["command"],
          "Maven selector changed", errors)
    check(cfg["site_file"] == str(SITES), "site file mismatch", errors)
    check(cfg["agent_jar"] == pins["pins"]["agent_jar"]["path"],
          "agent pin mismatch", errors)
    check(cfg["agent_properties"]["adapter.jar"] == pins["pins"]["adapter_jar"]["path"],
          "adapter pin mismatch", errors)
    check(str(Path(cfg["core_release"]) / "manifest.json") ==
          pins["pins"]["core_release_manifest"]["path"],
          "core release pin mismatch", errors)
    check(cfg["expected_target_class_sha256"] == pins["pins"]["target_class"]["sha256"],
          "target class pin mismatch", errors)
    for owner in [TARGET, "org.apache.hadoop.ipc.Client",
                  "org.apache.hadoop.hdfs.server.datanode.BPServiceActor"]:
        check(owner in cfg["agent_include"], f"agent include missing {owner}", errors)
    check(cfg["target"]["nodes"] == ["hdfs-cluster-1/nn0"],
          "named target changed", errors)
    check(len(sites["doors"]) == 1, "expected one explicit response door", errors)
    if len(sites["doors"]) == 1:
        door = sites["doors"][0]
        check(door["clazz"] == "org.apache.hadoop.ipc.Client" and
              door["method"] == "call" and door["line"] == 1529 and
              door["callee"] == DOOR_CALLEE and
              door["exception_class"] == "java.io.IOException",
              "response door identity changed", errors)
    check(sites["targets"] == json.loads((HERE.parents[4] /
        "Mallory/cases/HDFS-48.sites.json").read_text())["targets"],
        "target sites changed", errors)
    check(not any(k in cfg for k in ("fault_plan", "plan", "faults")),
          "fault plan present in healthy config", errors)
    return {"schema_version": 1, "case_id": "HDFS-48",
            "kind": "static_healthy_admission", "passed": not errors,
            "errors": errors, "runtime_status": "not_started",
            "config_sha256": sha256(CONFIG), "sites_sha256": sha256(SITES),
            "provenance_sha256": sha256(PINS)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path,
                        help="write a static-only JSON receipt")
    args = parser.parse_args()
    result = audit()
    rendered = json.dumps(result, indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(rendered)
    print(rendered, end="")
    raise SystemExit(0 if result["passed"] else 1)
