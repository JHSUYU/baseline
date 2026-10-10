#!/usr/bin/env python3
"""Offline HDFS-18 source/actor/config preflight; never starts Java."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

BASE = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
SURROGATE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
AGENT = BASE / "Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar"
SURROGATE_ADAPTER = BASE / "Mallory/adapters/hdfs/cases/hdfs26-retry-io-admission-v2/releases/9d828a425cb5f16f1bb02ce53075e3f7fd5ef71aeffca014eb185d77deb71811/adapter.jar"
TARGET_CLASS = SURROGATE / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/blockmanagement/DatanodeDescriptor.class"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(path, expected):
    assert path.is_file(), path
    assert digest(path) == expected, path


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    assert receipt["status"] == "source_overlay_unbuilt_healthy_only"
    assert receipt["actor_verified_by_runtime"] is False
    assert receipt["test_compiled_sha256"] is None
    assert receipt["adapter_jar_sha256"] is None
    require(HERE / "real-heartbeat.patch", receipt["test_patch_sha256"])
    require(HERE / "nn-owner-adapter.patch", receipt["adapter_patch_sha256"])
    for source in receipt["adapter_sources"]:
        require(BASE / source["path"], source["original_sha256"])
    subprocess.run(["git", "apply", "--check", str(HERE / "nn-owner-adapter.patch")],
                   cwd=BASE, check=True, capture_output=True, text=True)

    sys.path.insert(0, str(HERE))
    from prepare_overlay import ORIGINAL, render
    source_receipt = {
        "original_source_sha256": receipt["test_original_sha256"],
        "patched_source_sha256": receipt["test_patched_sha256"],
    }
    render(ORIGINAL.read_bytes(), source_receipt)
    require(TARGET_CLASS, receipt["target_class_sha256"])
    require(AGENT, "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9")
    require(SURROGATE_ADAPTER, "9d828a425cb5f16f1bb02ce53075e3f7fd5ef71aeffca014eb185d77deb71811")

    config = json.loads((HERE / "HDFS-18-healthy-BLOCKED-template.json").read_text())
    assert config["target"]["nodes"] == [receipt["expected_target_actor"]]
    assert config["healthy_gate"]["require_named_target_node"] is True
    assert config["healthy_gate"]["require_exact_target_reached"] is True
    assert config["healthy_gate"]["require_target_exception_absent"] is True
    assert config["calibration_only"] is True
    assert config["auto_promote_if_healthy"] is False
    assert config["mapping"]["full_admission"] is False
    assert config["agent_properties"]["adapter.jar"].endswith("/UNBUILT/adapter.jar")
    assert config["mapping"]["test_source_sha256"] == receipt["test_patched_sha256"]
    assert config["mapping"]["source_overlay_receipt_sha256"] == digest(HERE / "source-receipt.json")
    assert not Path(config["cwd"]).exists(), "dedicated build root must remain unprepared"
    for item in config["runtime_artifacts"]:
        require(Path(item["path"]), item["sha256"])

    # Schema and static frontier only: replace unbuilt paths in memory with
    # existing byte-identical source and a known adapter. This does not attest
    # the required patched adapter or permit a JUnit run.
    surrogate = json.loads(json.dumps(config))
    surrogate["cwd"] = str(SURROGATE)
    surrogate["source_equivalent_root"] = str(SURROGATE)
    surrogate["agent_properties"]["adapter.jar"] = str(SURROGATE_ADAPTER)
    surrogate["mapping"]["adapter_sha256"] = digest(SURROGATE_ADAPTER)
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config
    validate_config(surrogate)
    load_static_frontier(surrogate)
    print(json.dumps({"case_id": "HDFS-18", "status": "offline_preflight_pass",
                      "actor": receipt["expected_target_actor"], "jvm_started": False,
                      "healthy_run_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
