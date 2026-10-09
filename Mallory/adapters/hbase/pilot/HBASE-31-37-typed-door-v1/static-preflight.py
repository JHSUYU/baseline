#!/usr/bin/env python3
"""Verify source-only HBASE-31/37 healthy configurations without starting a JVM cluster."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    receipt = json.loads((HERE / "receipt.json").read_text())
    for name, expected in receipt["files"].items():
        if digest(HERE / name) != expected:
            raise ValueError(f"staged file hash mismatch: {name}")
    for name, expected in receipt["source_hashes"].items():
        source = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6") / name
        if digest(source) != expected:
            raise ValueError(f"source hash mismatch: {name}")
    source_root = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
    commit = subprocess.check_output(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != receipt["source_commit"]:
        raise ValueError("source commit mismatch")
    for case in ("HBASE-31", "HBASE-37"):
        config = json.loads((HERE / f"{case}.healthy.json").read_text())
        sites = json.loads((HERE / f"{case}.sites.json").read_text())
        if not (config["calibration_only"] and not config["auto_promote_if_healthy"]
                and config["require_event_time_paths"]
                and config["reject_coarse_roots"]
                and not config["allow_local_timeline_doors"]
                and not config["agent_properties"]["auto.io.doors"]
                and config["mapping"]["fault_admission_blocked"]):
            raise ValueError(f"unsafe healthy-only gate: {case}")
        if len(sites["doors"]) != 1 or config["site_file"] != str(HERE / f"{case}.sites.json"):
            raise ValueError(f"door catalog mismatch: {case}")
        if digest(config["agent_jar"]) != receipt["runtime_hashes"][config["agent_jar"]]:
            raise ValueError(f"agent hash mismatch: {case}")
        for artifact in config["runtime_artifacts"]:
            if digest(artifact["path"]) != artifact["sha256"]:
                raise ValueError(f"runtime artifact hash mismatch: {artifact['path']}")
        print(f"{case}: source-only preflight passed")
    gap = json.loads((HERE / "HBASE-37-fault-model-gap.json").read_text())
    if gap["classification"] != "source_review_fault_model_gap" or gap["terminal"]:
        raise ValueError("HBASE-37 gap classification mismatch")


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        print(f"preflight failed: {error}", file=sys.stderr)
        sys.exit(1)
