#!/usr/bin/env python3
"""Read-only pins and fresh-output check for the future HDFS-20 healthy run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys


BASE = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CONFIG = HERE / "HDFS-20-response-scope-healthy-v1.json"
OUTPUT = Path("/tmp/mallory-hdfs20-heartbeat-response-scope-v1-node2-healthy")
LOCAL_SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
SOURCE_REFERENCE = BASE / "Mallory/dispatch/source_reference.json"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
AGENT_ID = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
ADAPTER_ID = "4c1a3809830e6fc50538b3a830cb07936aa3c443633d4734f439e0b2a93979f9"
CORE_ID = "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
MIN_FREE_BYTES = 6_000_000_000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed pinned artifact: {path}")


def source_digest(root: Path, reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"missing HDFS source: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", help="run local checks without node2/JVM")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime preflight requires node2 dispatch admission")

    manifest = json.loads((HERE / "package-manifest.json").read_text())
    if manifest.get("case_id") != "HDFS-20" or manifest.get("stage") != "healthy_only_pending_dispatch":
        raise RuntimeError("wrong immutable package manifest")
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)
    config = json.loads(CONFIG.read_text())
    source = Path(config["cwd"])
    selected_source = LOCAL_SOURCE if args.static else source

    if (config.get("case_id") != "HDFS-20" or
            config.get("cluster_test") !=
            "org.apache.hadoop.hdfs.server.namenode.ha.TestStandbyIsHot#testStandbyIsHot" or
            config.get("calibration_only") is not True or
            config.get("auto_promote_if_healthy") is not False or
            config.get("budget", {}).get("trials") != 1 or
            config.get("budget", {}).get("max_faults_per_trial") != 1 or
            config.get("reject_coarse_roots") is not True or
            config.get("require_event_time_paths") is not True or
            config.get("healthy_gate", {}).get("require_exact_target_reached") is not True or
            config.get("healthy_gate", {}).get("require_named_target_node") is not True or
            config.get("healthy_gate", {}).get("require_target_exception_absent") is not True or
            config.get("cwd") != "/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8" or
            config.get("source_equivalent_root") != config.get("cwd") or
            config.get("mapping", {}).get("baseline_source_commit") !=
            "9d3ca265cf5eeaaf788385efdd69671df0804fff"):
        raise RuntimeError("not the pinned HDFS-20 response-scope healthy config")
    mapping = config["mapping"]
    if (mapping["agent_sha256"] != AGENT_ID or
            mapping["adapter_sha256"] != ADAPTER_ID or
            mapping["core_release_id"] != CORE_ID):
        raise RuntimeError("runtime release pins changed")
    if (config["agent_jar"] != str(BASE / "Mallory/instrumentation/releases" / AGENT_ID /
                                   "mallory-agent.jar") or
            config["agent_properties"]["adapter.jar"] !=
            str(BASE / "Mallory/adapters/hdfs/cases/heartbeat-response-scope-v1/releases" /
                ADAPTER_ID / "mallory-hdfs-adapter.jar") or
            config["core_release"] != str(BASE / "Mallory/dispatch/releases" / CORE_ID) or
            config["site_file"] !=
            str(BASE / "Mallory/adapters/hdfs/cases/heartbeat-door-v1/HDFS-20.sites.json")):
        raise RuntimeError("agent, adapter, core, or site selector changed")
    release = Path(config["core_release"])
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import validate_config
    validation_copy = dict(config)
    if args.static:
        validation_copy["cwd"] = str(LOCAL_SOURCE)
    validate_config(validation_copy)

    agent_release = Path(config["agent_jar"]).parent
    require_hash(agent_release / "manifest.json", mapping["agent_manifest_sha256"])
    require_hash(Path(config["agent_jar"]), AGENT_ID)
    adapter_release = Path(config["agent_properties"]["adapter.jar"]).parent
    require_hash(adapter_release / "manifest.json", mapping["adapter_manifest_sha256"])
    adapter_manifest = json.loads((adapter_release / "manifest.json").read_text())
    for name, expected in adapter_manifest["files_sha256"].items():
        require_hash(adapter_release / name, expected)
    require_hash(release / "manifest.json", mapping["core_manifest_sha256"])
    core_manifest = json.loads((release / "manifest.json").read_text())
    for name, expected in core_manifest["files"].items():
        require_hash(release / name, expected)

    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(source):
            if path.suffix == ".class":
                continue  # The pinned compiled bytecode is checked on node2.
            path = LOCAL_SOURCE / path.relative_to(source)
        require_hash(path, artifact["sha256"])
    require_hash(SOURCE_REFERENCE, mapping["source_reference_sha256"])
    reference = json.loads(SOURCE_REFERENCE.read_text())["roots"][str(LOCAL_SOURCE)]
    if reference["digest"] != SOURCE_DIGEST or source_digest(selected_source, reference) != SOURCE_DIGEST:
        raise RuntimeError("HDFS source fingerprint changed")

    if not args.static:
        if OUTPUT.exists():
            raise RuntimeError(f"fresh healthy output path already exists: {OUTPUT}")
        free = shutil.disk_usage(BASE).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"node2 disk below healthy-run reserve: {free}")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": "HDFS-20", "source_root": str(selected_source),
                      "source_digest": SOURCE_DIGEST, "output": str(OUTPUT),
                      "fresh_output_required": True}, sort_keys=True))


if __name__ == "__main__":
    main()
