#!/usr/bin/env python3
"""Read-only HDFS-34 v3 healthy-stage admission. No Hadoop JVM starts here."""

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
CONFIG = HERE / "HDFS-34-node2-healthy-v3.json"
SITES = HERE / "HDFS-34.sites.json"
PROVENANCE = BASE / "Mallory/adapters/hdfs/cases/hdfs33-34-fresh-healthy-v2/provenance.json"
SOURCE_FILES = (
    HERE / "adapter/src/main/java/edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks.java",
    HERE / "adapter/src/main/java/edu/uva/liftlab/mallory/adapters/hdfs/HdfsMiniClusterTransformer.java",
)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path, expected):
    path = Path(path)
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"Missing or changed artifact: {path}")


def source_digest(root, reference):
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"Missing frozen source: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", help="Use the node0 equivalent Hadoop tree")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("The runtime preflight is node2-only; use --static on node0")

    receipt = json.loads((HERE / "source-receipt.json").read_text())
    cfg = json.loads(CONFIG.read_text())
    sites = json.loads(SITES.read_text())
    prior = json.loads(PROVENANCE.read_text())
    runtime_root = Path(prior["node2_source_root"])
    static_root = Path(prior["static_source_root"])
    source_root = static_root if args.static else runtime_root
    if (receipt["config_sha256"] != sha(CONFIG) or
            receipt["site_sha256"] != sha(SITES) or
            cfg["case_id"] != "HDFS-34" or
            cfg["cluster_test"] !=
            "org.apache.hadoop.hdfs.TestDFSUpgradeFromImage#testUpgradeFromRel22Image" or
            cfg["calibration_only"] is not True or
            cfg["auto_promote_if_healthy"] is not False or
            cfg["budget"]["trials"] != 1 or
            cfg["healthy_gate"]["require_named_target_node"] is not True):
        raise RuntimeError("Healthy-only configuration changed")
    if (cfg["site_file"] != str(SITES) or
            cfg["agent_properties"]["adapter.jar"] != str(HERE / "release/adapter.jar") or
            cfg["healthy_gate"]["require_nonempty_observed_graph_path"] is not True or
            cfg["require_event_time_paths"] is not True or
            cfg["reject_coarse_roots"] is not True or
            sites["doors"][0]["method"] != "retrieveNamespaceInfo" or
            sites["doors"][0]["line"] != 260 or
            sites["doors"][0]["exception_class"] != "java.io.IOException"):
        raise RuntimeError("Typed-door or strict path gate changed")
    for path, expected in zip(SOURCE_FILES, receipt["adapter_sources_sha256"]):
        require(path, expected)
    require(HERE / "release/adapter.jar", receipt["adapter_sha256"])
    for artifact in cfg["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(runtime_root):
            path = source_root / path.relative_to(runtime_root)
        require(path, artifact["sha256"])

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    frozen = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if frozen["commit"] != receipt["hadoop_commit"] or frozen["digest"] != receipt["source_digest"]:
        raise RuntimeError("Frozen Hadoop reference changed")
    if source_digest(source_root, frozen) != receipt["source_digest"]:
        raise RuntimeError("Hadoop source digest changed")
    if (source_root / ".git/HEAD").is_file():
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source_root,
                                         text=True).strip()
        if actual != receipt["hadoop_commit"]:
            raise RuntimeError("Hadoop Git commit changed")

    release = Path(cfg["core_release"])
    for relative, expected in json.loads((release / "manifest.json").read_text())["files"].items():
        require(release / relative, expected)
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import load_static_frontier, validate_config
    validation = dict(cfg)
    if args.static:
        validation["cwd"] = str(source_root)
    validate_config(validation)
    load_static_frontier(validation)
    print(json.dumps({"case_id": "HDFS-34", "status": "preflight_pass",
                      "source_root": str(source_root), "adapter_sha256": receipt["adapter_sha256"],
                      "config_sha256": sha(CONFIG), "full_campaign_admitted": False,
                      "hadoop_jvm_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
