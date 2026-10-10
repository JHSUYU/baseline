#!/usr/bin/env python3
"""Read-only pins and shape checks for the HDFS-31 map diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import socket


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
CONFIG = HERE / "HDFS-31-node2-map-healthy-v3.json"
SITES = HERE / "HDFS-31.sites.json"
SOURCE_NODE0 = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
SOURCE_NODE2 = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
ORIGINAL = BASE / "Mallory/adapters/hdfs/cases/hdfs31-dn-receiver-v2/HDFS-31-node2-healthy-v2.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    host = socket.gethostname().split(".")[0]
    if not args.static and host != "node2":
        raise RuntimeError("runtime preflight must run on node2")
    source = SOURCE_NODE0 if args.static and host != "node2" else SOURCE_NODE2
    manifest = json.loads((HERE / "manifest.json").read_text())
    if (manifest.get("case_id"), manifest.get("status")) != (
        "HDFS-31", "isolated_healthy_only_no_jvm"
    ):
        raise RuntimeError("manifest identity changed")
    for relative, expected in manifest["files"].items():
        require(HERE / relative, expected)
    require(ORIGINAL, "162c6476640ad50a909fdab4c2d9efe3e22ee83360f9e3dfc63f9f0ca155bb97")
    cfg = json.loads(CONFIG.read_text())
    original = json.loads(ORIGINAL.read_text())
    sites = json.loads(SITES.read_text())
    old_sites = json.loads((ORIGINAL.parent / "HDFS-31.sites.json").read_text())
    expected = json.loads(json.dumps(original))
    expected["agent_include"].append("org.apache.hadoop.hdfs.server.datanode.BlockPoolManager")
    expected["mapping"] = cfg["mapping"]
    expected["site_file"] = str(SITES)
    expected["runtime_artifacts"] = cfg["runtime_artifacts"]
    expected["source_review"] = cfg["source_review"]
    if cfg != expected:
        raise RuntimeError("healthy diagnostic changed fields beyond isolated map scope")
    if cfg["budget"]["trials"] != 1 or not cfg["calibration_only"] or cfg["auto_promote_if_healthy"]:
        raise RuntimeError("diagnostic must remain healthy-only")
    if cfg["agent_properties"].get("state.maps") is not True:
        raise RuntimeError("map state tracing disabled")
    if sites["targets"] != old_sites["targets"] or sites["doors"] != old_sites["doors"]:
        raise RuntimeError("target or door catalog changed")
    if sites["regions"][: len(old_sites["regions"])] != old_sites["regions"]:
        raise RuntimeError("original target region changed")
    if len(sites["regions"]) != len(old_sites["regions"]) + 3:
        raise RuntimeError("expected three added map regions")
    for row in cfg["runtime_artifacts"]:
        path = Path(row["path"])
        if args.static and path.is_relative_to(SOURCE_NODE2):
            path = source / path.relative_to(SOURCE_NODE2)
        require(path, row["sha256"])
    bp_source = source / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolManager.java"
    bp_class = source / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/BlockPoolManager.class"
    require(bp_source, "1d3bae5753526ca1bfc9dec3a5e63820564db49c9dedd32b4b7fd5f1f8ad423a")
    require(bp_class, "a806b5f5801d589ec481ffbebf2be994832d1f67b1c9a270c76e27cfa42c6c29")
    print(json.dumps({"case_id": "HDFS-31", "status": "static_preflight_pass",
                      "config_sha256": sha(CONFIG), "site_sha256": sha(SITES),
                      "jvm_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
