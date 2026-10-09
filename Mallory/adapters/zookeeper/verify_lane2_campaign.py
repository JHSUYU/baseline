#!/usr/bin/env python3
"""Verify pinned ZooKeeper lane2 inputs immediately before a fault campaign."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from Mallory.dispatch.scheduler import verify_runtime_artifacts
from Mallory.dispatch.verify_sources import overlay_receipt, sha256_file


def verify(path: Path, *, healthy_only: bool = False) -> None:
    config = json.loads(path.read_text(encoding="utf-8"))
    receipt_path = Path(config["source_overlay_receipt"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    row = {"case_id": config["case_id"],
           "provenance": {"source_root": receipt["base_root"]}}
    patched_root, _ = overlay_receipt(row, config)
    if patched_root != Path(config["cwd"]).resolve():
        raise ValueError("Campaign cwd differs from attested ZooKeeper overlay")
    mapping = config["mapping"]
    test_relative = Path(mapping.get("test_source_path",
                                     "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java"))
    class_relative = Path(mapping.get("target_class_relative",
                                      "zookeeper-server/target/classes/org/apache/zookeeper/server/SessionTrackerImpl.class"))
    if any(relative.is_absolute() or ".." in relative.parts
           for relative in (test_relative, class_relative)):
        raise ValueError("ZooKeeper source or class mapping escapes patched root")
    target_source = patched_root / config["target"]["source_path"]
    test_source = patched_root / test_relative
    if (sha256_file(target_source) != config["mapping"]["target_source_sha256"] or
            sha256_file(test_source) != config["mapping"]["test_source_sha256"]):
        raise ValueError("Selected target or JUnit source differs from pinned mapping")
    verify_runtime_artifacts(config)
    target = patched_root / class_relative
    if sha256_file(target) != config["expected_target_class_sha256"]:
        raise ValueError("Target class differs from pinned loaded-class expectation")
    if "-Dmallory.test.dir={trial_dir}/test-data" not in config["command"]:
        raise ValueError("Campaign does not isolate ZooKeeper test data by trial")
    if healthy_only:
        if not config.get("calibration_only") or config.get("auto_promote_if_healthy"):
            raise ValueError("Expected a non-promoting healthy calibration")
    elif not config.get("auto_promote_if_healthy") or config.get("calibration_only"):
        raise ValueError("Campaign has no strict healthy attestation gate")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--healthy-only", action="store_true")
    args = parser.parse_args()
    verify(args.config.resolve(), healthy_only=args.healthy_only)
