"""Stage an independent, pinned Balancer repeated-RPC campaign config.

This is a no-JVM transformation of the terminal PEER-V2 config. It keeps the
JUnit, static map, weave, runtime classpath, and exact target unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

SOURCE_CONFIG_SHA256 = "da96c526b1cfdd35208d2adf6ad477be161b1097f9214322ce33b3703ca16c10"
NEW_CASE_ID = "HDFS-11-TIMING-LIFETIME-REPEATED-RPC-V1"
LOCAL_ROOT = Path("/run/user/20003/mallory-hdfs-balancer-short-lifetime-repeat-v1")


def derive(source: dict) -> dict:
    if (source.get("case_id") != "HDFS-11-TIMING-LIFETIME-PEER-V2" or
            source.get("junit") != {"class":
            "org.apache.hadoop.hdfs.server.balancer.TestBalancerWithEncryptedTransfer",
            "method": "testEncryptedBalancer0"} or
            source.get("budget", {}).get("max_faults_per_trial") != 6 or
            source.get("recording", {}).get("multi_target_max_anchors") != 4 or
            source.get("recording", {}).get("control_plane_peer_policy") !=
            "same_peer_pretarget_late_repeated_quarter"):
        raise ValueError("frozen PEER-V2 identity or scope differs")
    config = copy.deepcopy(source)
    config["case_id"] = NEW_CASE_ID
    config["budget"] = {"fault_trials": 128,
                        "max_faults_per_trial": 12,
                        "seconds": 14400}
    config["recording"]["repeated_rpc_occurrence_policy"] = (
        "repeated_rpc_pretarget_v1")
    config["runner"]["local_artifact_root"] = str(LOCAL_ROOT / "raw")
    config["runner"]["local_work_root"] = str(LOCAL_ROOT / "work")
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_CONFIG_SHA256:
        raise ValueError("frozen PEER-V2 config SHA-256 mismatch")
    config = derive(json.loads(raw))
    # The staging step writes only a reviewable config. A separate capacity
    # gate must create private roots and approve each later JVM trial.
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, sort_keys=True, indent=2) + "\n")
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
