#!/usr/bin/env python3
"""Offline HDFS-37 phase and budget validation; never launches a JUnit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs37-normal-phase-v1"
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
AGENT = BASE / "Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar"
ADAPTER = BASE / "Mallory/adapters/hdfs/cases/hdfs26-retry-io-admission-v2/releases/9d828a425cb5f16f1bb02ce53075e3f7fd5ef71aeffca014eb185d77deb71811/adapter.jar"
TARGET = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs/hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataStorage.class")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def main() -> None:
    receipt = json.loads((HERE / "handoff.json").read_text())
    sys.path.insert(0, str(HERE))
    from prepare_overlay import render, ORIGINAL

    overlay = json.loads((HERE / "source-overlay-receipt.json").read_text())
    render(ORIGINAL.read_bytes(), overlay)
    for item in receipt["artifacts"]:
        require(Path(item["path"]), item["sha256"])
    for relative, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require(RELEASE / relative, expected)
    require(AGENT, receipt["agent_sha256"])
    require(ADAPTER, receipt["adapter_sha256"])
    require(TARGET, receipt["target_class_sha256"])
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config

    for name in ("HDFS-37-healthy-template.json", "HDFS-37-full-BLOCKED-template.json"):
        config = json.loads((HERE / name).read_text())
        # The dedicated source checkout is intentionally not created while
        # another HDFS campaign owns the build lane. Validate schema/sites
        # against the byte-identical existing source, without treating that
        # surrogate path as a runtime attestation.
        surrogate = json.loads(json.dumps(config))
        surrogate["cwd"] = "/users/ZhenyuLi/.mallory-worktrees/hdfs"
        surrogate["source_equivalent_root"] = surrogate["cwd"]
        validate_config(surrogate)
        load_static_frontier(surrogate)
        if (config.get("calibration_only") is not True or
                config.get("auto_promote_if_healthy") is not False or
                config.get("mapping", {}).get("full_admission") is not False or
                "-Dmallory.hdfs37.normalDataNodeRollbackOnly=true" not in config["command"]):
            raise RuntimeError("phase-scoped template is unexpectedly runnable as full")
    budget = json.loads((HERE / "HDFS-37-full-BLOCKED-template.json").read_text())["budget"]
    if (budget["trials"], budget["seconds"], budget["max_faults_per_trial"]) != (80, 3600, 3):
        raise RuntimeError("full budget changed")
    print(json.dumps({"status": "offline_preflight_pass", "case_id": "HDFS-37",
                      "test_overlay": "SHA-verified_unapplied",
                      "full_budget": [80, 3600, 3], "jvm_started": False,
                      "full_admission": False}, sort_keys=True))


if __name__ == "__main__":
    main()
