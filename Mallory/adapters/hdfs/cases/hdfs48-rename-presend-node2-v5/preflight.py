#!/usr/bin/env python3
"""Read-only SHA and scope gate for the isolated HDFS-48 one-fault run."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
V4 = HERE.parent / "hdfs48-rename-presend-node2-v4"
CONFIG = HERE / "HDFS-48-node2-one-fault-full-v5.json"
RECEIPT = BASE / "data/mallory/evidence_archives/HDFS-48-rename-presend-healthy-v4.receipt.json"
ARCHIVE = BASE / "data/mallory/evidence_archives/HDFS-48-rename-presend-healthy-v4.tar.gz"
AUDIT = BASE / "data/mallory/quality_reviews/HDFS-48-rename-presend-v4.strict-audit.json"
DOOR = "hdfs:client-send-rpc-request:rename"
PIN = {
    "receipt": "0fe0af3ad2ac745fc12cadcd0c20237012ddf232db5b0a8f9e94edc55e2c3067",
    "archive": "b6a6e56ccef4992b18b960f8d5731f656da8cbb268232fd88d2b066277524974",
    "audit": "a4d3f69a337595b17f04f3d93718c545a2cafabedc9bb616bc211f201685e688",
    "v4_config": "e1bdb92396bca32295190fa769de55122a818e6c22019ffa3e60ae9ba47330bb",
    "v4_manifest": "518a8cac80f3366516a1823fe0fb803edda2fad91b161e4a8b3a4d0ac0cde33f",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed SHA-bound file: {path}")


def check(runtime: bool = False) -> dict:
    if runtime and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime admission requires node2")
    require(RECEIPT, PIN["receipt"])
    require(ARCHIVE, PIN["archive"])
    require(AUDIT, PIN["audit"])
    require(V4 / "HDFS-48-node2-healthy-v4.json", PIN["v4_config"])
    require(V4 / "package-manifest.json", PIN["v4_manifest"])
    receipt = json.loads(RECEIPT.read_text())
    audit = json.loads(AUDIT.read_text())
    cfg = json.loads(CONFIG.read_text())
    manifest = json.loads((HERE / "package-manifest.json").read_text())
    for name, digest in manifest["files"].items():
        require(HERE / name, digest)
    v4_manifest = json.loads((V4 / "package-manifest.json").read_text())
    for name, digest in v4_manifest["files"].items():
        require(V4 / name, digest)
    for row in cfg["runtime_artifacts"]:
        require(Path(row["path"]), row["sha256"])
    if (receipt.get("kind") != "healthy_only" or
            receipt.get("case_id") != "HDFS-48" or
            receipt.get("archive_sha256") != PIN["archive"] or
            receipt.get("strict_audit_sha256") != PIN["audit"] or
            receipt.get("member_count") != 15 or
            receipt.get("fault_trials_completed") != 0 or
            audit.get("healthy_gate_passed") is not True or
            audit.get("offline_causal_gate_passed") is not True or
            len(audit.get("strict_method_correlation_path_witnesses", [])) != 1):
        raise RuntimeError("v4 healthy path receipt is not a strict one-door witness")
    gate = cfg.get("healthy_gate", {})
    budget = cfg.get("budget", {})
    if (cfg.get("case_id") != "HDFS-48" or cfg.get("calibration_only") is not False or
            cfg.get("auto_promote_if_healthy") is not True or
            cfg.get("explore_outside_closure") is not False or
            cfg.get("fault_types") != ["EXCEPTION"] or
            cfg.get("static_fault_sites") != [DOOR] or
            cfg.get("agent_properties", {}).get("auto.io.doors") is not False or
            cfg.get("site_file") != str(V4 / "HDFS-48.sites.json") or
            cfg.get("cwd") != "/users/ZhenyuLi/.mallory-worktrees/hdfs48-rename-presend-v4" or
            cfg.get("require_event_time_paths") is not True or
            cfg.get("reject_coarse_roots") is not True or
            cfg.get("allow_local_timeline_doors") is not False or
            gate.get("door_site") != DOOR or
            gate.get("v4_receipt_sha256") != PIN["receipt"] or
            gate.get("v4_archive_sha256") != PIN["archive"] or
            cfg.get("target", {}).get("nodes") != ["hdfs-cluster-1/nn0"] or
            budget.get("trials") != 1 or budget.get("max_faults_per_trial") != 1 or
            budget.get("trial_timeout_seconds") != 180 or
            budget.get("seconds") != 420):
        raise RuntimeError("v5 exact-door or one-fault bounds changed")
    if json.loads((V4 / "HDFS-48.sites.json").read_text()).get("doors") != []:
        raise RuntimeError("unexpected additional static door")
    sys.path[:0] = [cfg["core_release"], str(BASE)]
    from Mallory.core.campaign import validate_config
    candidate = dict(cfg)
    if not runtime:
        candidate["cwd"] = ("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8"
                            if socket.gethostname().split(".")[0] == "node2" else
                            "/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
    validate_config(candidate)
    if runtime:
        sys.path.insert(0, str(V4))
        from prepare_node2 import verify
        verify(Path(cfg["cwd"]), json.loads((V4 / "build-receipt.json").read_text()))
        if Path("/tmp/mallory-hdfs48-rename-presend-node2-full-v5").exists():
            raise RuntimeError("v5 output exists; review before reuse")
    return {"status": "runtime_preflight_pass" if runtime else "static_preflight_pass",
            "case_id": "HDFS-48", "v4_receipt_sha256": PIN["receipt"],
            "full_config_sha256": sha(CONFIG), "jvm_started": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.runtime), sort_keys=True))
