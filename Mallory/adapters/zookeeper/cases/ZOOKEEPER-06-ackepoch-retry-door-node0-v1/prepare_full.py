#!/usr/bin/env python3
"""Create the pinned full config after one local exact-path healthy receipt."""

import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    package = Path(__file__).resolve().parent
    healthy = Path("/users/ZhenyuLi/baseline/data/mallory/calibration/ZOOKEEPER-06/ackepoch-retry-door-node0-healthy-v1")
    receipt_path = Path("/users/ZhenyuLi/baseline/data/mallory/admissions/ZOOKEEPER-06-ackepoch-retry-door-node0-healthy-v1.json")
    destination = package / "full.json"
    if destination.exists():
        raise FileExistsError(destination)
    receipt = json.loads(receipt_path.read_text())
    assert receipt["case_id"] == "ZOOKEEPER-06"
    assert receipt["status"] == "healthy_exact_ackepoch_write_to_target_path"
    assert sha(healthy / "result.json") == receipt["campaign_result_sha256"]
    assert sha(healthy / "offline-causal-audit.json") == receipt["offline_audit_sha256"]
    assert sha(healthy / "trials/r0000/events.jsonl.gz") == receipt["trace_gzip_sha256"]
    config = json.loads((package / "healthy.json").read_text())
    assert sha(package / "healthy.json") == "6c94d0f1074dfdcba7467b57d51fd7a09eb8c96254a6ffe6be84bec126dc0f3c"
    config["calibration_only"] = False
    config["auto_promote_if_healthy"] = True
    config["budget"] = {
        "trials": 80, "seconds": 3600, "max_faults_per_trial": 3,
        "trial_timeout_seconds": 180,
        "trial_timeout_basis": "unchanged_QuorumRestartTest_healthy_ceiling",
    }
    config["healthy_receipt"] = str(receipt_path)
    config["healthy_receipt_sha256"] = sha(receipt_path)
    config["mapping"]["healthy_seed_verified"] = True
    config["mapping"]["node_identity_binding_verified"] = True
    config["mapping"]["status"] = "node0_exact_ackepoch_healthy_attested_full_campaign"
    config["fault_types"] = ["EXCEPTION"]
    config["explore_outside_closure"] = False
    config["candidate_replays"] = 0
    destination.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print("full_config_sha256", sha(destination))


if __name__ == "__main__":
    main()
