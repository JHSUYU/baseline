#!/usr/bin/env python3
"""Verify HDFS-12's indexed MiniCluster full run and prior key-path evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


BASE = Path("/users/ZhenyuLi/baseline")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs12-key-update-full-v3"
PRIOR = BASE / "Mallory/adapters/hdfs/cases/hdfs12-key-update-v2"
CONFIG = HERE / "HDFS-12-node2-full-v3.json"
OUTPUT = Path("/tmp/mallory-hdfs12-key-update-v3-full")
HEALTHY = BASE / "data/mallory/calibration_hdfs12_key_v2/HDFS-12"
PILOT = BASE / "data/mallory/calibration_hdfs12_key_v2_pilot/HDFS-12"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "e695aefef696f08613b4de570f43e786895dae4ee6e1d1099334f52b2ea7248d"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
RELEASE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
MIN_FREE_BYTES = 6_000_000_000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def source_digest(reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = SOURCE / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source file missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def verify_raw(root: Path, manifest: Path) -> None:
    receipt = json.loads(manifest.read_text())
    expected = receipt.get("files")
    if not isinstance(expected, dict) or not expected:
        raise RuntimeError(f"raw SHA manifest malformed: {manifest}")
    found = {str(path.relative_to(root)) for path in root.rglob("*")
             if path.is_file() and path.name != ".campaign.lock"}
    if found != set(expected):
        raise RuntimeError(f"raw file list changed: {root}")
    for relative, digest in expected.items():
        require_hash(root / relative, digest)


def main() -> None:
    require_hash(CONFIG, CONFIG_SHA)
    config = json.loads(CONFIG.read_text())
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import (load_static_frontier, validate_config,
                                       verify_validated_recovery_sites)

    validate_config(config)
    load_static_frontier(config)
    verify_validated_recovery_sites(config)
    budget = config["budget"]
    if (config.get("case_id") != "HDFS-12" or
            config.get("cluster_test") !=
            "org.apache.hadoop.hdfs.TestEncryptedTransfer#testLongLivedClient[0]" or
            config.get("calibration_only") is not False or
            config.get("auto_promote_if_healthy") is not True or
            config.get("mapping", {}).get("status") != "runtime_attested" or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"],
             budget["trial_timeout_seconds"]) != (80, 3600, 3, 240) or
            config.get("reject_coarse_roots") is not False or
            config.get("require_event_time_paths") is not False or
            config.get("explore_outside_closure") is not True or
            config.get("healthy_gate", {}).get("allow_local_timeline_doors") is not True or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE)):
        raise RuntimeError("not the exact indexed HDFS-12 full campaign")
    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)
    for artifact in config["runtime_artifacts"]:
        require_hash(Path(artifact["path"]), artifact["sha256"])
    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(pinned) != SOURCE_DIGEST:
        raise RuntimeError("full HDFS source fingerprint changed")

    attestation = config["calibration_attestation"]
    verify_raw(HEALTHY, PRIOR / "HDFS-12-v2-raw-sha-manifest.json")
    verify_raw(PILOT, PRIOR / "HDFS-12-v2-one-fault-raw-sha-manifest.json")
    require_hash(HEALTHY / "trials/r0000/result.json",
                 attestation["healthy_result_sha256"])
    require_hash(HEALTHY / "result.json", attestation["healthy_summary_sha256"])
    require_hash(HEALTHY / "offline-causal-audit.json",
                 attestation["healthy_causal_audit"]["sha256"])
    require_hash(Path(attestation["case_local_observed_path"]["path"]),
                 attestation["case_local_observed_path"]["sha256"])
    healthy = json.loads((HEALTHY / "result.json").read_text())
    trial = json.loads((HEALTHY / "trials/r0000/result.json").read_text())
    audit = json.loads((HEALTHY / "offline-causal-audit.json").read_text())
    if (healthy.get("status") != "calibration_complete" or
            healthy.get("healthy_seed_valid") is not True or
            healthy.get("exact_exception_trials") != 0 or
            healthy.get("runtime_attestation", {}).get("valid") is not True or
            trial.get("junit_validation", {}).get("tests") != 1 or
            trial.get("junit_validation", {}).get("status") != "passed" or
            trial.get("feedback", {}).get("target_reached") is not True or
            trial.get("feedback", {}).get("target_threw") is not False or
            audit.get("campaign_result_sha256") != sha(HEALTHY / "result.json") or
            audit.get("report_gate_passed") is not False):
        raise RuntimeError("case-local healthy evidence changed or generic gap concealed")
    pilot = json.loads((PILOT / "trials/r0001/result.json").read_text())
    if (pilot.get("feedback", {}).get("all_faults_effective") is not True or
            pilot.get("feedback", {}).get("target_reached") is not True or
            pilot.get("feedback", {}).get("target_threw") is not False):
        raise RuntimeError("prior effective target-retaining pilot changed")
    if OUTPUT.exists():
        require_hash(OUTPUT / "config.json", CONFIG_SHA)
        if not (OUTPUT / "checkpoint.json").is_file():
            raise RuntimeError("existing output has no resumable checkpoint")
    free = shutil.disk_usage(BASE).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"node2 disk below full campaign reserve: {free}")
    print(json.dumps({"status": "preflight_pass", "case_id": "HDFS-12",
                      "config_sha256": CONFIG_SHA, "source_digest": SOURCE_DIGEST,
                      "output": str(OUTPUT), "resuming": OUTPUT.exists(),
                      "free_disk_bytes": free, "generic_healthy_audit_gate": False,
                      "case_local_healthy_path": "SHA-verified"}, sort_keys=True))


if __name__ == "__main__":
    main()
