#!/usr/bin/env python3
"""Preflight the exact two-heartbeat-fault diagnostic on node2."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import preflight_hdfs12_v2_pilot as common


CONFIG = common.HERE / "HDFS-12-v2-two-fault-diagnostic.json"
OUTPUT = Path("/tmp/mallory-hdfs12-key-update-v2-two-fault")
CONFIG_SHA = "aed65b43d62ee63b88905f506ebc9749db0c7174513ce26bc9948abd6e6e6e2e"


def main() -> None:
    common.require_hash(CONFIG, CONFIG_SHA)
    config = json.loads(CONFIG.read_text())
    sys.path.insert(0, str(common.RELEASE))
    sys.path.insert(1, str(common.BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config

    validate_config(config)
    load_static_frontier(config)
    sequence = config.get("manual_sequence")
    if (config.get("case_id") != "HDFS-12" or
            config.get("calibration_only") or config.get("auto_promote_if_healthy") or
            config.get("cluster_test") !=
            "org.apache.hadoop.hdfs.TestEncryptedTransfer#testLongLivedClient[0]" or
            config.get("cwd") != str(common.SOURCE) or
            config.get("source_equivalent_root") != str(common.SOURCE) or
            config.get("budget", {}).get("trials") != 1 or
            config.get("budget", {}).get("max_faults_per_trial") != 2 or
            config.get("target", {}).get("nodes") != ["hdfs-cluster-2/dn0"] or
            config.get("mapping", {}).get("status") !=
            "runtime_attested_bounded_two_fault_diagnostic_only" or
            not isinstance(sequence, list) or len(sequence) != 2 or
            [fault.get("point", {}).get("door_ordinal") for fault in sequence] != [5, 6] or
            any(fault.get("point", {}).get("node") != "hdfs-cluster-2/dn0" or
                fault.get("point", {}).get("epoch") != 0 or
                fault.get("fault_type") != "EXCEPTION" or
                fault.get("exception_class") != "java.io.IOException"
                for fault in sequence)):
        raise RuntimeError("not the exact H1/H2 bounded diagnostic")
    if OUTPUT.exists():
        checkpoint = OUTPUT / "checkpoint.json"
        if (not checkpoint.is_file() or
                json.loads(checkpoint.read_text()).get("config_sha256") != CONFIG_SHA):
            raise RuntimeError(f"output exists without matching resumable checkpoint: {OUTPUT}")
    common.require_hash(common.RELEASE / "manifest.json", common.RELEASE_MANIFEST_SHA)
    for name, expected in json.loads((common.RELEASE / "manifest.json").read_text())["files"].items():
        common.require_hash(common.RELEASE / name, expected)
    for artifact in config["runtime_artifacts"]:
        common.require_hash(Path(artifact["path"]), artifact["sha256"])
    reference = json.loads((common.BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if (pinned["digest"] != common.SOURCE_DIGEST or
            common.source_digest(pinned) != common.SOURCE_DIGEST):
        raise RuntimeError("full HDFS source fingerprint changed")
    free = shutil.disk_usage(common.BASE).free
    if free < common.MIN_FREE_BYTES:
        raise RuntimeError(f"node2 disk below diagnostic reserve: {free}")
    print(json.dumps({"status": "preflight_pass", "case_id": "HDFS-12",
                      "config_sha256": CONFIG_SHA,
                      "source_digest": common.SOURCE_DIGEST,
                      "output": str(OUTPUT), "free_disk_bytes": free}, sort_keys=True))


if __name__ == "__main__":
    main()
