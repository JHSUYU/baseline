#!/usr/bin/env python3
"""No-JVM HDFS-33/34 fresh healthy admission preflight."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
PROVENANCE = HERE / "provenance.json"
EXPECTED_TEST = {
    "HDFS-33": "org.apache.hadoop.hdfs.server.datanode.TestDataNodeHotSwapVolumes#testAddOneNewVolume",
    "HDFS-34": "org.apache.hadoop.hdfs.TestDFSUpgradeFromImage#testUpgradeFromRel22Image",
}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(path, expected):
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed pinned artifact: {path}")


def source_digest(root, reference):
    h = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"missing source path: {path}")
        h.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=tuple(EXPECTED_TEST))
    parser.add_argument("--static", action="store_true", help="verify node0 equivalent source")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("node2 preflight requires node2; use --static here")

    pins = json.loads(PROVENANCE.read_text())
    if pins["stage"] != "node2_fresh_healthy_only":
        raise RuntimeError("package stage changed")
    for spec in pins["pins"].values():
        require(Path(spec["path"]), spec["sha256"])

    runtime_root = Path(pins["node2_source_root"])
    root = Path(pins["static_source_root"]) if args.static else runtime_root
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()
    if head != pins["source_commit"]:
        raise RuntimeError(f"Hadoop commit changed: {head}")
    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    frozen = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if frozen["digest"] != pins["source_digest"] or source_digest(root, frozen) != pins["source_digest"]:
        raise RuntimeError("source digest changed")

    case = args.case
    cfg_path = HERE / f"{case}-node2-healthy-v2.json"
    cfg = json.loads(cfg_path.read_text())
    sites = json.loads((HERE / f"{case}.sites.json").read_text())
    if (cfg["case_id"] != case or cfg["cluster_test"] != EXPECTED_TEST[case] or
            cfg["cwd"] != str(runtime_root) or
            cfg["source_equivalent_root"] != str(runtime_root) or
            cfg["site_file"] != str(HERE / f"{case}.sites.json") or
            cfg["calibration_only"] is not True or
            cfg["auto_promote_if_healthy"] is not False or
            cfg["budget"]["trials"] != 1 or
            cfg["mapping"]["healthy_seed_verified"] is not False or
            cfg["mapping"]["node_identity_binding_verified"] is not False or
            cfg["healthy_gate"]["require_named_target_node"] is not True or
            cfg["healthy_gate"]["require_exact_target_reached"] is not True or
            cfg["healthy_gate"]["require_target_exception_absent"] is not True):
        raise RuntimeError("healthy-only identity or budget gate changed")
    if case == "HDFS-33":
        door = sites["doors"]
        if (len(door) != 1 or door[0]["clazz"] !=
                "org.apache.hadoop.hdfs.server.datanode.StorageLocation" or
                door[0]["method"] != "makeBlockPoolDir" or
                door[0]["line"] != 276 or
                door[0]["exception_class"] != "java.io.IOException" or
                cfg["healthy_gate"]["door_candidate_role"] !=
                "diagnostic_only_no_fault_promotion"):
            raise RuntimeError("HDFS-33 diagnostic directory door changed")
    else:
        if (len(sites["doors"]) != 2 or
                sites["doors"][0]["method"] != "retrieveNamespaceInfo" or
                sites["doors"][0]["line"] != 260 or
                sites["doors"][1]["method"] != "readPropertiesFile" or
                sites["doors"][1]["line"] != 272):
            raise RuntimeError("HDFS-34 retry and VERSION doors changed")

    for spec in cfg["runtime_artifacts"]:
        path = Path(spec["path"])
        if args.static and path.is_relative_to(runtime_root):
            path = root / path.relative_to(runtime_root)
        require(path, spec["sha256"])
    release = Path(cfg["core_release"])
    for relative, expected in json.loads((release / "manifest.json").read_text())["files"].items():
        require(release / relative, expected)
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import load_static_frontier, validate_config
    validation_copy = dict(cfg)
    if args.static:
        validation_copy["cwd"] = str(root)
    validate_config(validation_copy)
    load_static_frontier(validation_copy)

    result = {"schema_version": 1, "case_id": case,
              "status": "static_preflight_pass" if args.static else "preflight_pass",
              "config_sha256": sha(cfg_path), "site_sha256": sha(HERE / f"{case}.sites.json"),
              "source_digest": pins["source_digest"],
              "fresh_named_healthy_admitted": False,
              "full_campaign_admitted": False, "jvm_launched": False}
    text = json.dumps(result, indent=2) + "\n"
    if args.receipt:
        args.receipt.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
