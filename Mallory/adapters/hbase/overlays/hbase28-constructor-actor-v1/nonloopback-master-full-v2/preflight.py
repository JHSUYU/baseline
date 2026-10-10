#!/usr/bin/env python3
"""JVM-free SHA, source, healthy-evidence, and config gate for HBASE-28."""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from pathlib import Path

from healthy_gate import CHECK, DOOR, EXCEPTION, require, sha, verify_pair

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
BASE = HERE.parent
SOURCE_HEALTHY = BASE / "nonloopback-master-healthy-v1"
SOURCE_SITES = BASE / "observation-v2/sites.json"
PRIOR_NODE0 = REPO / "data/mallory/healthy_observations/HBASE-28-nonloopback-master-healthy-v1"
PRIOR_NODE1 = REPO / "data/mallory/calibration_hbase28_nonloopback_master_v1/HBASE-28"
OUTPUT = REPO / "data/mallory/cases/HBASE-28/campaigns/nonloopback-master-full-v2"
RELEASE_ID = "224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1"
RELEASE_SHA = "76529af210390ebaea94685d46e66cccf168c61e144903137aeaca0767dd636c"


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def preflight(node1: bool) -> None:
    manifest = read(HERE / "stage-manifest.json")
    config = read(HERE / "config.json")
    healthy = read(SOURCE_HEALTHY / "config.json")
    prior = read(HERE / "prior-healthy-evidence.json")
    require(manifest["case_id"] == "HBASE-28" and
            manifest["target_host"] == "node1" and
            manifest["output_path"] == str(OUTPUT) and
            manifest["status"] == "staged_no_jvm", "wrong package identity")
    for name, digest in manifest["files"].items():
        require(sha(HERE / name) == digest, f"package SHA mismatch: {name}")
    allowed = {"budget", "calibration_only", "auto_promote_if_healthy",
               "allow_local_timeline_doors", "require_event_time_paths",
               "reject_coarse_roots", "explore_outside_closure",
               "candidate_status", "core_release"}
    require({k: v for k, v in config.items() if k not in allowed} ==
            {k: v for k, v in healthy.items() if k not in allowed},
            "full config changed source/test/artifact identity")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
              "max_faults_per_trial": 3, "trial_timeout_seconds": 600} and
            config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["allow_local_timeline_doors"] is True and
            config["require_event_time_paths"] is False and
            config["reject_coarse_roots"] is True and
            config["explore_outside_closure"] is False,
            "full budget or admission policy changed")
    require(config["target"]["check_sites"] == [CHECK] and
            config["site_file"] == str(SOURCE_SITES) and
            sha(HERE / "sites.json") == sha(SOURCE_SITES) and
            read(SOURCE_SITES)["doors"] == [{
                "clazz": "org.apache.hadoop.hbase.util.Addressing",
                "method": "isLocalAddress", "descriptor": "(Ljava/net/InetAddress;)Z",
                "line": 148,
                "callee": "java.net.NetworkInterface#getByInetAddress"
                          "(Ljava/net/InetAddress;)Ljava/net/NetworkInterface;",
                "exception_class": EXCEPTION}],
            "exact typed door or target changed")
    release = REPO / "Mallory/dispatch/releases" / RELEASE_ID
    require(config["core_release"] == {"release_id": RELEASE_ID,
            "path": str(release), "manifest_sha256": RELEASE_SHA} and
            sha(release / "manifest.json") == RELEASE_SHA,
            "scheduler release changed")
    for name, digest in read(release / "manifest.json")["files"].items():
        require(sha(release / name) == digest, f"release SHA mismatch: {name}")
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    # Reuse the source/class/JUnit/IP review from the frozen healthy package.
    sys.path.insert(0, str(SOURCE_HEALTHY))
    import importlib.util
    spec = importlib.util.spec_from_file_location("hbase28_healthy_preflight",
                                                   SOURCE_HEALTHY / "preflight.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.preflight(node1)
    require(prior["case_id"] == "HBASE-28" and
            prior["fresh_full_r0000_required"] is True and
            prior["typed_door_seq"] + 1 == prior["target_check_seq"],
            "sealed healthy source receipt changed")
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        for name, digest in prior["files"].items():
            require(sha(PRIOR_NODE1 / name) == digest,
                    f"node1 healthy evidence changed: {name}")
        verdict = verify_pair(PRIOR_NODE1, require_local_timeline=False)
        require(verdict["door_seq"] == prior["typed_door_seq"] and
                verdict["target_seq"] == prior["target_check_seq"],
                "prior typed door/check changed")
        for artifact in config["runtime_artifacts"]:
            require(sha(Path(artifact["path"])) == artifact["sha256"],
                    f"runtime artifact changed: {artifact['path']}")
    else:
        for name, digest in prior["files"].items():
            require(sha(PRIOR_NODE0 / name) == digest,
                    f"node0 sealed healthy evidence changed: {name}")
    print("PASS HBASE-28 full-v2 JVM-free preflight")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    args = parser.parse_args()
    try:
        preflight(args.node1)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise SystemExit(f"HBASE-28 full-v2 preflight gap: {exc}")
