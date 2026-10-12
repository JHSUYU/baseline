#!/usr/bin/env python3
"""Validate the staged HDFS-18 package without building or starting Java."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs18-provided-heartbeat-v1"
SURROGATE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
TARGET_CLASS = SURROGATE / ("hadoop-hdfs-project/hadoop-hdfs/target/classes/"
                            "org/apache/hadoop/hdfs/server/blockmanagement/"
                            "DatanodeDescriptor.class")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def main() -> None:
    sys.path.insert(0, str(HERE))
    from prepare_overlay import ORIGINAL, render
    receipt = json.loads((HERE / "source-overlay-receipt.json").read_text())
    render(ORIGINAL.read_bytes(), receipt)
    require(HERE / "real-heartbeat.patch", receipt["patch_sha256"])
    if "node.injectStorage" in (HERE / "real-heartbeat.patch").read_text():
        raise RuntimeError("direct selected-guard call is forbidden")

    handoff = json.loads((HERE / "handoff.json").read_text())
    for item in handoff["artifacts"]:
        require(Path(item["path"]), item["sha256"])
    require(TARGET_CLASS, handoff["target_class_sha256"])
    release = Path(handoff["core_release"])
    require(release / "manifest.json", handoff["core_release_manifest_sha256"])

    sys.path.insert(0, str(release))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import validate_config, load_static_frontier
    for name, budget in (("HDFS-18-healthy-template.json", (1, 900, 1)),
                         ("HDFS-18-full-BLOCKED-template.json", (80, 3600, 3))):
        config = json.loads((HERE / name).read_text())
        surrogate = json.loads(json.dumps(config))
        surrogate["cwd"] = str(SURROGATE)
        surrogate["source_equivalent_root"] = str(SURROGATE)
        validate_config(surrogate)
        load_static_frontier(surrogate)
        actual = config["budget"]
        if (actual["trials"], actual["seconds"], actual["max_faults_per_trial"]) != budget:
            raise RuntimeError("budget changed")
        if (not config.get("calibration_only") or
                config.get("auto_promote_if_healthy") or
                config["mapping"].get("full_admission") or
                config["mapping"].get("healthy_seed_verified") or
                "-Dmallory.hdfs18.secondProvidedHeartbeat=true" not in config["command"] or
                config["healthy_gate"].get("require_exact_target_reached") is not True or
                config["healthy_gate"].get("require_target_exception_absent") is not True):
            raise RuntimeError("staged gate changed")
        for item in config["runtime_artifacts"]:
            require(Path(item["path"]), item["sha256"])
    print(json.dumps({"case_id": "HDFS-18", "status": "offline_preflight_pass",
                      "workload": "adapted_real_provided_heartbeat",
                      "dedicated_root_created": False, "jvm_started": False,
                      "full_admission": False, "full_budget": [80, 3600, 3]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
