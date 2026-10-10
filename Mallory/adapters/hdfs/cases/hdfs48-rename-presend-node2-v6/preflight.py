#!/usr/bin/env python3
"""Read-only v6 source, budget, recovery and sealed v5 input gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket

from seed_continuation import ARCHIVE, CONFIG, HERE, MEMBERS, PIN, RECEIPT, require
from strict_policy import BASE, CORE, DOOR, campaign

V4 = HERE.parent / "hdfs48-rename-presend-node2-v4"
V5 = HERE.parent / "hdfs48-rename-presend-node2-v5"
RECOVERY = HERE / "recovery/v5-r0001-result.json"
RECOVERY_SHA = "462376b0656a3c78af27e8bea460d0fbca2a2d4d542276c28e269f348016624e"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(runtime: bool = False) -> dict:
    if runtime and socket.gethostname().split(".")[0] != "node2":
        raise ValueError("runtime preflight requires node2")
    for path, digest in ((ARCHIVE, PIN["archive"]), (RECEIPT, PIN["receipt"]),
                         (MEMBERS, PIN["members"]), (RECOVERY, RECOVERY_SHA)):
        require(path, digest)
    receipt = json.loads(RECEIPT.read_text())
    manifest = json.loads((HERE / "package-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        require(HERE / name, expected)
    cfg = json.loads(CONFIG.read_text())
    prior = json.loads((V5 / "HDFS-48-node2-one-fault-full-v5.json").read_text())
    if (receipt.get("strict_injected_trials") != 1 or
            receipt.get("strict_target_trials") != 1 or
            receipt.get("exact_exception_trials") != 0 or
            cfg.get("case_id") != "HDFS-48" or
            cfg.get("agent_jar") != prior.get("agent_jar") or
            cfg.get("core_release") != str(CORE) or
            cfg.get("cwd") != prior.get("cwd") or
            cfg.get("target") != prior.get("target") or
            cfg.get("command") != prior.get("command") or
            cfg.get("agent_properties") != prior.get("agent_properties") or
            cfg.get("site_file") != prior.get("site_file") or
            cfg.get("static_fault_sites") != [DOOR] or
            cfg.get("fault_types") != ["EXCEPTION"] or
            cfg.get("explore_outside_closure") is not False or
            cfg.get("allow_local_timeline_doors") is not False or
            cfg.get("reject_coarse_roots") is not True or
            cfg.get("require_event_time_paths") is not True or
            cfg.get("auto_promote_if_healthy") is not True or
            cfg.get("calibration_only") is not False or
            cfg.get("budget", {}).get("trials") != 80 or
            cfg.get("budget", {}).get("seconds") != 3600 or
            cfg.get("budget", {}).get("max_faults_per_trial") != 3 or
            cfg.get("budget", {}).get("trial_timeout_seconds") != 180 or
            cfg.get("validated_recovery_sites") != [{"site": DOOR, "evidence": [{
                "trial_result": str(RECOVERY), "sha256": RECOVERY_SHA}]}] or
            cfg.get("mapping", {}).get("v5_fault_trial_result_sha256") != RECOVERY_SHA or
            cfg.get("mapping", {}).get("v5_remote_sha_index_sha256") !=
                "30f038940bf383b48fa7ecbb7ea126f530962ebbf2f6fc2bd2f6935bcc0a838a"):
        raise ValueError("v6 replay or exact-door bounds changed")
    for row in cfg["runtime_artifacts"]:
        require(Path(row["path"]), row["sha256"])
    candidate = dict(cfg)
    if not runtime:
        candidate["cwd"] = ("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8"
                            if socket.gethostname().split(".")[0] == "node2" else
                            "/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
    campaign.validate_config(candidate)
    campaign.verify_validated_recovery_sites(cfg)
    if runtime:
        from sys import path as sys_path
        sys_path.insert(0, str(V4))
        from prepare_node2 import verify
        verify(Path(cfg["cwd"]), json.loads((V4 / "build-receipt.json").read_text()))
    return {"status": "runtime_preflight_pass" if runtime else "static_preflight_pass",
            "case_id": "HDFS-48", "v5_archive_sha256": PIN["archive"],
            "v6_config_sha256": sha(CONFIG), "jvm_started": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.runtime), sort_keys=True))
