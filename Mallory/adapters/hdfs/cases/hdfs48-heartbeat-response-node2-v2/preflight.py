#!/usr/bin/env python3
"""Read-only HDFS-48 heartbeat healthy admission on equivalent node2 source."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs48-heartbeat-response-node2-v2"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
ORIGINAL = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
CONFIG = HERE / "HDFS-48-node2-healthy-v2.json"
SITES = HERE / "HDFS-48.sites.json"
PINS = HERE / "node2-provenance.json"
OUTPUT = Path("/tmp/mallory-hdfs48-heartbeat-response-node2-healthy-v2")
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
CONFIG_SHA = "c535841283a0075b1a380f9066f6446a2948c6458b3af0367730a41f9e42be7e"
ORIGINAL_SHA = "f76398f56342d641e0e028776edfb81b7a4aabd73178c64906f09d3cb2e69abd"
CORE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
SELECTOR = "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots#testRenameUndo_1"
DOOR_CALLEE = ("org.apache.hadoop.ipc.Client#getRpcResponse"
               "(Lorg/apache/hadoop/ipc/Client$Call;"
               "Lorg/apache/hadoop/ipc/Client$Connection;"
               "JLjava/util/concurrent/TimeUnit;)"
               "Lorg/apache/hadoop/io/Writable;")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed SHA-pinned artifact: {path}")


def source_digest(root: Path, reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source path missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", help="use the host's equivalent source without Java")
    args = parser.parse_args()
    host = socket.gethostname().split(".")[0]
    if not args.static and host != "node2":
        raise RuntimeError("runtime preflight must run on node2")
    root = SOURCE if host == "node2" else MIRROR

    manifest = json.loads((HERE / "package-manifest.json").read_text())
    if manifest.get("case_id") != "HDFS-48" or manifest.get("stage") != "node2_healthy_pending_dispatch":
        raise RuntimeError("package manifest changed")
    for relative, expected in manifest["files"].items():
        require_hash(HERE / relative, expected)
    require_hash(CONFIG, CONFIG_SHA)
    require_hash(HERE / "original-provenance.json", ORIGINAL_SHA)
    require_hash(CORE / "manifest.json", CORE_MANIFEST_SHA)
    for relative, expected in json.loads((CORE / "manifest.json").read_text())["files"].items():
        require_hash(CORE / relative, expected)

    original = json.loads((HERE / "original-provenance.json").read_text())
    pins = json.loads(PINS.read_text())
    cfg = json.loads(CONFIG.read_text())
    sites = json.loads(SITES.read_text())
    if (pins.get("source_commit") != original.get("source_commit") or
            pins.get("source_commit") != "9d50c6884666e794e45102260a4017bb31802e1b" or
            pins.get("source_root") != str(SOURCE) or
            pins.get("source_digest") != SOURCE_DIGEST or
            pins.get("original_source_root") != str(ORIGINAL) or
            pins.get("original_provenance_sha256") != ORIGINAL_SHA or
            set(pins["pins"]) != set(original["pins"])):
        raise RuntimeError("node2 provenance mapping changed")
    for label, spec in pins["pins"].items():
        old = original["pins"][label]
        if label != "healthy_config" and spec["sha256"] != old["sha256"]:
            raise RuntimeError(f"original SHA changed for {label}")
        path = Path(spec["path"])
        if old["path"].startswith(str(ORIGINAL) + "/"):
            expected = SOURCE / Path(old["path"]).relative_to(ORIGINAL)
            if path != expected:
                raise RuntimeError(f"source mapping changed for {label}")
            if args.static:
                path = root / path.relative_to(SOURCE)
        require_hash(path, spec["sha256"])

    if (cfg.get("case_id") != "HDFS-48" or cfg.get("cluster_test") != SELECTOR or
            cfg.get("cwd") != str(SOURCE) or cfg.get("source_equivalent_root") != str(SOURCE) or
            cfg.get("site_file") != str(SITES) or
            cfg.get("calibration_only") is not True or
            cfg.get("auto_promote_if_healthy") is not False or
            (cfg["budget"]["trials"], cfg["budget"]["seconds"],
             cfg["budget"]["max_faults_per_trial"], cfg["budget"]["trial_timeout_seconds"]) !=
            (1, 360, 1, 240) or
            cfg.get("expected_target_class_sha256") != pins["pins"]["target_class"]["sha256"] or
            cfg["agent_properties"].get("adapter.jar") != pins["pins"]["adapter_jar"]["path"] or
            cfg.get("agent_jar") != pins["pins"]["agent_jar"]["path"] or
            cfg.get("target", {}).get("nodes") != ["hdfs-cluster-1/nn0"] or
            cfg.get("healthy_gate", {}).get("require_named_target_node") is not True or
            cfg.get("healthy_gate", {}).get("require_exact_target_reached") is not True or
            cfg.get("healthy_gate", {}).get("require_target_exception_absent") is not True or
            "-Dtest=TestRenameWithSnapshots#testRenameUndo_1" not in cfg.get("command", [])):
        raise RuntimeError("healthy config changed")
    if len(sites.get("doors", [])) != 1:
        raise RuntimeError("expected one typed response door")
    door = sites["doors"][0]
    if (door.get("clazz") != "org.apache.hadoop.ipc.Client" or
            door.get("method") != "call" or door.get("line") != 1529 or
            door.get("callee") != DOOR_CALLEE or
            door.get("exception_class") != "java.io.IOException"):
        raise RuntimeError("typed response door changed")
    baseline_sites = json.loads((BASE / "Mallory/cases/HDFS-48.sites.json").read_text())
    if sites["targets"] != baseline_sites["targets"]:
        raise RuntimeError("selected target sites changed")

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(CORE), str(BASE)]
    from Mallory.core.campaign import load_static_frontier, validate_config
    validation = dict(cfg)
    if args.static:
        validation["cwd"] = str(root)
    validate_config(validation)
    load_static_frontier(validation)
    for row in cfg.get("runtime_artifacts", []):
        require_hash(Path(row["path"]), row["sha256"])

    if not args.static:
        if OUTPUT.exists():
            raise RuntimeError(f"fresh healthy output already exists: {OUTPUT}")
        free = shutil.disk_usage("/tmp").free
        if free < 6_000_000_000:
            raise RuntimeError(f"node2 scratch below reserve: {free}")
    print(json.dumps({"case_id": "HDFS-48", "status": "static_preflight_pass" if args.static else "preflight_pass",
                      "config_sha256": CONFIG_SHA, "source_digest": SOURCE_DIGEST,
                      "source_root": str(root), "output": str(OUTPUT),
                      "jvm_started": False, "healthy_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
