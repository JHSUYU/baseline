#!/usr/bin/env python3
"""Verify the pinned node0 ACKEPOCH source, bytecode, and campaign inputs."""

import argparse
import hashlib
import json
from pathlib import Path

from Mallory.core.campaign import validate_config


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate_config(config)
    receipt_path = Path(config["source_overlay_receipt"])
    assert sha(receipt_path) == config["source_overlay_receipt_sha256"]
    receipt = json.loads(receipt_path.read_text())
    assert receipt["case_id"] == config["case_id"] == "ZOOKEEPER-06"
    assert receipt["patched_root"] == config["cwd"]
    assert sha(receipt["node0_source_receipt"]) == receipt["node0_source_receipt_sha256"]
    assert sha(receipt["node1_compiled_receipt"]) == receipt["node1_compiled_receipt_sha256"]
    old = json.loads(Path(receipt["node1_compiled_receipt"]).read_text())
    assert old["modified_files"] == receipt["modified_files"]
    assert [row["sha256"] for row in old["compiled_artifacts"]] == [
        row["sha256"] for row in receipt["compiled_artifacts"]]
    root = Path(receipt["patched_root"])
    for name, expected in receipt["modified_files"].items():
        assert sha(root / name) == expected, name
    for row in receipt["compiled_artifacts"]:
        assert sha(row["path"]) == row["sha256"], row["path"]
    assert sha(root / config["mapping"]["test_source_path"]) == receipt["test_source_sha256"]
    assert sha(root / config["mapping"]["target_class_relative"]) == receipt["target_class_sha256"]
    assert config["expected_target_class_sha256"] == receipt["target_class_sha256"]
    for row in config["runtime_artifacts"]:
        assert sha(row["path"]) == row["sha256"], row["path"]
    assert sha(config["agent_jar"]) == config["mapping"]["agent_sha256"]
    if not config["calibration_only"]:
        healthy = Path(config["healthy_receipt"])
        assert sha(healthy) == config["healthy_receipt_sha256"]
        assert json.loads(healthy.read_text())["status"] == "healthy_exact_ackepoch_write_to_target_path"
    print("verified", args.config, len(receipt["compiled_artifacts"]), "classes")


if __name__ == "__main__":
    main()
