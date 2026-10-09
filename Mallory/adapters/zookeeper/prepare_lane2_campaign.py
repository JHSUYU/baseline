#!/usr/bin/env python3
"""Pin an already calibrated ZooKeeper target to the isolated lane2 overlay."""

import argparse
import hashlib
import json
from pathlib import Path


TARGET_CLASS = Path("zookeeper-server/target/classes/org/apache/zookeeper/server/SessionTrackerImpl.class")
CASES = {"ZOOKEEPER-02", "ZOOKEEPER-03"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(case_config: Path, lane_root: Path, overlay_receipt: Path,
            agent_jar: Path, output: Path) -> None:
    config = json.loads(case_config.read_text(encoding="utf-8"))
    if config.get("case_id") not in CASES:
        raise ValueError("Only the validated ZOOKEEPER-02/-03 alternate is supported")
    if config.get("cluster_test") != "org.apache.zookeeper.test.QuorumTest#testMultiToFollower":
        raise ValueError("Selected cluster workload changed")
    receipt = json.loads(overlay_receipt.read_text(encoding="utf-8"))
    if receipt.get("patched_root") != str(lane_root):
        raise ValueError("Overlay receipt describes a different source root")
    class_file = lane_root / TARGET_CLASS
    class_sha = sha(class_file)
    if class_sha != config.get("expected_target_class_sha256"):
        raise ValueError("Lane2 target class differs from verified healthy target class")
    if not any(row.get("path") == str(class_file) and row.get("sha256") == class_sha
               for row in receipt.get("compiled_artifacts", [])):
        raise ValueError("Lane2 target class is missing from the overlay receipt")
    site_file = Path(config["site_file"])
    agent_sha = sha(agent_jar)
    config["cwd"] = str(lane_root)
    config["calibration_only"] = False
    config["auto_promote_if_healthy"] = True
    config["command"] = [item for item in config["command"] if not item.startswith("-Dmallory.test.dir=")]
    config["command"].insert(-1, "-Dmallory.test.dir={trial_dir}/test-data")
    config["agent_jar"] = str(agent_jar)
    config["expected_target_class_sha256"] = class_sha
    config["source_overlay_receipt"] = str(overlay_receipt)
    config["source_overlay_receipt_sha256"] = sha(overlay_receipt)
    config["mapping"]["source_root"] = str(lane_root)
    config["mapping"]["compiled_artifact"] = str(lane_root / "zookeeper-server/target/classes")
    config["mapping"]["compiled_class_sha256"] = class_sha
    config["mapping"]["agent_sha256"] = agent_sha
    config["mapping"]["healthy_seed_verified"] = False
    config["mapping"]["status"] = "lane2_source_pinned_pending_runtime_attestation"
    config["runtime_artifacts"] = [
        {"path": str(agent_jar), "sha256": agent_sha},
        {"path": str(site_file), "sha256": sha(site_file)},
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_config", type=Path)
    parser.add_argument("lane_root", type=Path)
    parser.add_argument("overlay_receipt", type=Path)
    parser.add_argument("agent_jar", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.case_config.resolve(), args.lane_root.resolve(),
            args.overlay_receipt.resolve(), args.agent_jar.resolve(), args.output.resolve())
