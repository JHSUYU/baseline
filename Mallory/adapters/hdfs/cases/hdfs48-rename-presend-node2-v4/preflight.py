#!/usr/bin/env python3
"""Read-only package, target, actor, and instrumentation preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys

from source_identity import verify_original


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
CONFIG = HERE / "HDFS-48-node2-healthy-v4.json"
SITES = HERE / "HDFS-48.sites.json"
DOOR = "hdfs:client-send-rpc-request:rename"
TARGET = "hdfs-cluster-1/nn0"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed pinned file: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime preflight requires node2")
    cfg = json.loads(CONFIG.read_text())
    receipt = json.loads((HERE / "build-receipt.json").read_text())
    sites = json.loads(SITES.read_text())
    manifest = json.loads((HERE / "package-manifest.json").read_text())
    if manifest.get("case_id") != "HDFS-48" or manifest.get("stage") != "node2_healthy_pending_dispatch":
        raise RuntimeError("package manifest identity changed")
    for name, expected in manifest["files"].items():
        require(HERE / name, expected)
    require(HERE / "patched-test/TestRenameWithSnapshots.java", receipt["patched_test_source_sha256"])
    require(HERE / "release/TestRenameWithSnapshots.class", receipt["patched_test_class_sha256"])
    require(HERE / "release/mallory-hdfs-adapter.jar", receipt["adapter_jar_sha256"])
    require(Path(cfg["agent_jar"]), receipt["agent_jar_sha256"])
    if (cfg.get("case_id") != "HDFS-48" or
            cfg.get("cluster_test") != "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots#testRenameUndo_1" or
            cfg.get("site_file") != str(SITES) or
            cfg.get("cwd") != "/users/ZhenyuLi/.mallory-worktrees/hdfs48-rename-presend-v4" or
            cfg.get("expected_target_class_sha256") != receipt["target_class_sha256"] or
            cfg.get("agent_properties", {}).get("adapter.jar") != str(HERE / "release/mallory-hdfs-adapter.jar") or
            cfg.get("agent_properties", {}).get("auto.io.doors") is not False or
            cfg.get("require_event_time_paths") is not True or
            cfg.get("reject_coarse_roots") is not True or
            cfg.get("allow_local_timeline_doors") is not False or
            cfg.get("calibration_only") is not True or
            cfg.get("auto_promote_if_healthy") is not False or
            cfg.get("target", {}).get("nodes") != [TARGET] or
            cfg.get("healthy_gate", {}).get("door_site") != DOOR or
            cfg.get("mapping", {}).get("runtime_identity_proof") !=
                "established_full_source_digest_and_selected_sha256" or
            any(cfg.get("mapping", {}).get(key) != receipt[key] for key in
                ("source_full_digest_sha256", "source_reference_sha256",
                 "target_source_sha256", "client_source_sha256",
                 "client_class_sha256", "original_test_class_sha256")) or
            "org.apache.hadoop.ipc.Client$Connection" not in cfg.get("agent_include", []) or
            cfg.get("budget", {}).get("trials") != 1):
        raise RuntimeError("healthy configuration identity changed")
    if sites.get("doors") != [] or sites.get("targets") != json.loads(
            (BASE / "Mallory/cases/HDFS-48.sites.json").read_text())["targets"]:
        raise RuntimeError("exact target catalog changed")
    hooks = (HERE / "source/HdfsHooks.java").read_text()
    transformer = (HERE / "source/HdfsMiniClusterTransformer.java").read_text()
    test = (HERE / "patched-test/TestRenameWithSnapshots.java").read_text()
    if (hooks.count('"org.apache.hadoop.hdfs.protocol.ClientProtocol.rename"') != 1 or
            hooks.count(f'Probe.beforeDoor("{DOOR}"') != 1 or
            transformer.count('"rpcBeforeRenameSend"') != 1 or
            transformer.index('"rpcBeforeRenameSend"') > transformer.index('"rpcSend"') or
            'conf.setBoolean("dfs.client.retry.policy.enabled", true);' not in test or
            'conf.set("dfs.client.retry.policy.spec", "20,1");' not in test):
        raise RuntimeError("rename method filter, pre-send ordering, or retry policy changed")
    for row in cfg["runtime_artifacts"]:
        require(Path(row["path"]), row["sha256"])
    sys.path[:0] = [cfg["core_release"], str(BASE)]
    from Mallory.core.campaign import validate_config
    if args.static:
        candidate = dict(cfg)
        candidate["cwd"] = ("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8"
                            if socket.gethostname().split(".")[0] == "node2" else
                            "/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
        verify_original(Path(candidate["cwd"]), receipt)
        validate_config(candidate)
    else:
        validate_config(cfg)
        verify_original(Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8"), receipt)
        root = Path(cfg["cwd"])
        for path, key in (("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.java", "patched_test_source_sha256"),
                          ("hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.class", "patched_test_class_sha256"),
                          ("hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/namenode/INodeDirectory.class", "target_class_sha256")):
            require(root / path, receipt[key])
        if Path("/tmp/mallory-hdfs48-rename-presend-node2-healthy-v4").exists():
            raise RuntimeError("healthy output already exists; review before rerun")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "runtime_preflight_pass",
                      "case_id": "HDFS-48", "node2_jvm_started": False,
                      "healthy_admitted": False,
                      "adapter_jar_sha256": receipt["adapter_jar_sha256"],
                      "test_class_sha256": receipt["patched_test_class_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
