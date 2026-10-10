#!/usr/bin/env python3
"""Verify the pinned HDFS-18 healthy package without starting a JVM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
MANIFEST = HERE / "package-manifest.json"
REFERENCE = BASE / "Mallory/dispatch/source_reference.json"
ORIGINAL = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed pinned artifact: {path}")


def source_digest(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"missing source path: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true",
                        help="verify package pins and original source on this host")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime preflight is scoped to node2")

    pins = json.loads(MANIFEST.read_text())
    config_path = HERE / "HDFS-18-node2-healthy-v4.json"
    sites_path = HERE / "HDFS-18.sites.json"
    require(config_path, pins["config_sha256"])
    require(sites_path, pins["site_sha256"])
    require(Path(pins["adapter_jar_path"]), pins["adapter_jar_sha256"])
    ref = json.loads(REFERENCE.read_text())["roots"][str(ORIGINAL)]
    if ref["commit"] != pins["source_commit"] or ref["digest"] != pins["original_full_source_digest"]:
        raise RuntimeError("frozen Hadoop source reference changed")
    root = ORIGINAL if args.static else Path(pins["source_root"])
    expected = pins["original_full_source_digest"] if args.static else pins["patched_full_source_digest"]
    if source_digest(root, ref["paths"]) != expected:
        raise RuntimeError("full Hadoop source snapshot differs from pin")
    if not args.static:
        if sha(Path(pins["compiled_target_archive_path"])) != pins["compiled_target_archive_sha256"]:
            raise RuntimeError("compiled target archive changed")
        require(root / pins["test_source_relative"], pins["test_source_sha256"])
        require(root / pins["test_class_relative"], pins["test_class_sha256"])
        require(root / pins["target_class_relative"], pins["target_class_sha256"])

    config = json.loads(config_path.read_text())
    sites = json.loads(sites_path.read_text())
    if (config["case_id"] != "HDFS-18" or
            config["cwd"] != pins["source_root"] or
            config["source_equivalent_root"] != pins["source_root"] or
            config["site_file"] != str(sites_path) or
            config["cluster_test"] !=
            "org.apache.hadoop.hdfs.server.aliasmap.TestSecureAliasMap#testSecureConnectionToAliasMap" or
            config["calibration_only"] is not True or
            config["auto_promote_if_healthy"] is not False or
            config["budget"]["trials"] != 1 or
            config["target"]["nodes"] != ["hdfs-cluster-1/nn0"] or
            config["healthy_gate"]["require_named_target_node"] is not True or
            config["healthy_gate"]["require_exact_target_reached"] is not True or
            config["healthy_gate"]["require_target_exception_absent"] is not True or
            config["mapping"]["full_admission"] is not False or
            config["mapping"]["healthy_seed_verified"] is not False or
            len(sites["doors"]) != 1 or
            sites["doors"][0]["method"] != "sendHeartBeat" or
            sites["doors"][0]["line"] != 563 or
            sites["doors"][0]["exception_class"] != "java.io.IOException"):
        raise RuntimeError("HDFS-18 healthy-only target, door, or budget changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(Path(pins["source_root"])):
            continue
        require(path, artifact["sha256"])
    release = Path(config["core_release"])
    manifest = json.loads((release / "manifest.json").read_text())
    for relative, expected_sha in manifest["files"].items():
        require(release / relative, expected_sha)
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import load_static_frontier, validate_config
    candidate = json.loads(json.dumps(config))
    if args.static:
        candidate["cwd"] = str(ORIGINAL)
        candidate["source_equivalent_root"] = str(ORIGINAL)
        candidate["runtime_artifacts"] = [a for a in candidate["runtime_artifacts"]
                                           if not Path(a["path"]).is_relative_to(Path(pins["source_root"]))]
    validate_config(candidate)
    load_static_frontier(candidate)
    print(json.dumps({"case_id": "HDFS-18",
                      "status": "static_preflight_pass" if args.static else "preflight_pass",
                      "healthy_admitted": False, "full_admitted": False,
                      "jvm_started": False, "source_digest": expected}, sort_keys=True))


if __name__ == "__main__":
    main()
