#!/usr/bin/env python3
"""Offline HDFS-37 normal-phase actor/config preflight; no Java process."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True

BASE = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
SURROGATE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
AGENT = BASE / "Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar"
ADAPTER = BASE / "Mallory/adapters/hdfs/cases/hdfs26-retry-io-admission-v2/releases/9d828a425cb5f16f1bb02ce53075e3f7fd5ef71aeffca014eb185d77deb71811/adapter.jar"
TARGET_CLASS = SURROGATE / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataStorage.class"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(path, expected):
    assert path.is_file(), path
    assert digest(path) == expected, path


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    overlay = json.loads((HERE / "source-overlay-receipt.json").read_text())
    assert receipt["test_original_sha256"] == overlay["original_source_sha256"]
    assert receipt["test_patched_sha256"] == overlay["patched_source_sha256"]
    assert receipt["test_patch_sha256"] == overlay["patch_sha256"]
    assert receipt["actor_verified_by_runtime"] is False
    assert receipt["test_compiled_sha256"] is None
    require(HERE / "normal-phase.patch", receipt["test_patch_sha256"])
    require(TARGET_CLASS, receipt["target_class_sha256"])
    require(AGENT, "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9")
    require(ADAPTER, "9d828a425cb5f16f1bb02ce53075e3f7fd5ef71aeffca014eb185d77deb71811")
    subprocess.run(["git", "apply", "--check", str(HERE / "normal-phase.patch")],
                   cwd="/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3",
                   check=True, capture_output=True, text=True)
    sys.path.insert(0, str(HERE))
    from prepare_overlay import ORIGINAL, render
    render(ORIGINAL.read_bytes(), overlay)

    # The pinned adapter already carries early DataStorage registration and
    # the receiver scope around doTransition, which encloses doRollback.
    with zipfile.ZipFile(ADAPTER) as archive:
        hooks = archive.read("edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks.class")
        transformer = archive.read("edu/uva/liftlab/mallory/adapters/hdfs/HdfsMiniClusterTransformer.class")
    for marker in (b"dataNodeStarting", b"dataStorageEnter"):
        assert marker in hooks
    assert b"doTransition" in transformer and b"DataStorage" in transformer

    config = json.loads((HERE / "HDFS-37-healthy-BLOCKED-template.json").read_text())
    assert config["target"]["nodes"] == [receipt["expected_target_actor"]]
    assert config["healthy_gate"]["require_named_target_node"] is True
    assert config["healthy_gate"]["require_exact_target_reached"] is True
    assert config["healthy_gate"]["require_target_exception_absent"] is True
    assert config["calibration_only"] is True
    assert config["auto_promote_if_healthy"] is False
    assert config["mapping"]["full_admission"] is False
    assert config["mapping"]["test_source_sha256"] == receipt["test_patched_sha256"]
    assert config["mapping"]["source_overlay_receipt_sha256"] == digest(HERE / "source-overlay-receipt.json")
    assert not Path(config["cwd"]).exists(), "dedicated build root must remain unprepared"
    for item in config["runtime_artifacts"]:
        require(Path(item["path"]), item["sha256"])

    surrogate = json.loads(json.dumps(config))
    surrogate["cwd"] = str(SURROGATE)
    surrogate["source_equivalent_root"] = str(SURROGATE)
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config
    validate_config(surrogate)
    load_static_frontier(surrogate)
    print(json.dumps({"case_id": "HDFS-37", "status": "offline_preflight_pass",
                      "actor": receipt["expected_target_actor"], "jvm_started": False,
                      "healthy_run_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
