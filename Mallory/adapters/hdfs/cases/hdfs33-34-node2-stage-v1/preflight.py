#!/usr/bin/env python3
"""Static, SHA-bound node2 admission check. This does not start Hadoop."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs33-34-node2-stage-v1"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(row: dict) -> None:
    path = Path(row["path"])
    if not path.is_file() or digest(path) != row["sha256"]:
        raise RuntimeError(f"missing or changed SHA-pinned artifact: {path}")


def source_digest(reference: dict) -> str:
    h = hashlib.sha256()
    for relative in reference["paths"]:
        path = SOURCE / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(digest(path))
        else:
            raise RuntimeError(f"source path missing: {path}")
        h.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return h.hexdigest()


def main(case: str) -> None:
    if case not in ("HDFS-33", "HDFS-34"):
        raise RuntimeError("case must be HDFS-33 or HDFS-34")
    handoff = json.loads((HERE / "handoff.json").read_text())
    if handoff["status"] != "healthy_only_staged_full_admission_blocked":
        raise RuntimeError("handoff state changed")
    for field in ("core_release", "agent", "adapter_33", "adapter_34"):
        require(handoff[field])
    release_manifest = json.loads((RELEASE / "manifest.json").read_text())
    for relative, expected in release_manifest["files"].items():
        require({"path": str(RELEASE / relative), "sha256": expected})
    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != handoff["source_digest"] or source_digest(pinned) != handoff["source_digest"]:
        raise RuntimeError("node2 source fingerprint changed")

    row = next(item for item in handoff["healthy_cases"] if item["case_id"] == case)
    for field in ("config", "original_config", "target_class", "test_class", "source_review"):
        require(row[field])
    config = json.loads(Path(row["config"]["path"]).read_text())
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config

    validate_config(config)
    load_static_frontier(config)
    for artifact in config["runtime_artifacts"]:
        require(artifact)
    if (config["case_id"] != case or config["cwd"] != str(SOURCE) or
            config["source_equivalent_root"] != str(SOURCE) or
            config["calibration_only"] is not True or
            config["auto_promote_if_healthy"] is not False or
            config["mapping"]["status"] != "node2_healthy_pending" or
            config["expected_target_class_sha256"] != row["target_class"]["sha256"]):
        raise RuntimeError("not the staged healthy-only candidate")
    print(json.dumps({"status": "preflight_pass", "case_id": case,
                      "config_sha256": row["config"]["sha256"],
                      "source_digest": handoff["source_digest"],
                      "full_campaign_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: preflight.py HDFS-33|HDFS-34")
    main(sys.argv[1])
