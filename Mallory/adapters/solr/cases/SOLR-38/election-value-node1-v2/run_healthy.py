#!/usr/bin/env python3
"""GO-gated node1 offline javac build and one unchanged SOLR-38 cluster JUnit."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import preflight
import build_adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = HERE.parent / "election-field-healthy-node2-v1"
OUT = preflight.OUT
GO = HERE / "admission-healthy-node1.json"
CONFIG = HERE / "config-generated-node1.json"
ADAPTER = build_adapter.OUT
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_go(receipt: Path, meta: dict) -> None:
    if receipt.resolve() != GO:
        raise ValueError("case-local dispatch GO path required")
    grant = json.loads(receipt.read_text(encoding="utf-8"))
    for key in ("case_id", "host", "mode", "source_manifest_sha256",
                "runner_sha256", "intended_output"):
        if grant.get(key) != meta[key]:
            raise ValueError(f"dispatch GO differs: {key}")
    if grant.get("go") is not True or grant.get("scope") != "one_healthy_junit_no_fault":
        raise ValueError("dispatch did not authorize this bounded diagnostic")


def generated_config() -> dict:
    config = json.loads((BASE / "config-healthy-node2.json").read_text(encoding="utf-8"))
    original = config["agent_properties"]["adapter.jar"]
    config["revision"] = "SOLR-38-election-value-healthy-node1-v2"
    config["admission"]["host"] = "node1"
    config["admission"]["scope"] = "healthy_value_diagnostic_only"
    config["admission"]["intended_output"] = str(OUT)
    config["agent_properties"]["adapter.jar"] = str(ADAPTER)
    config["env"]["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    config["env"]["MALLORY_SOLR_AGENT_JAR"] = str(build_adapter.AGENT)
    config["command"][1] = str(HERE / "run_pilot.py")
    config["mapping"]["election_adapter_sha256"] = sha(ADAPTER)
    config["mapping"]["value_diagnostic_adapter_sha256"] = sha(ADAPTER)
    config["mapping"]["value_diagnostic_runner_sha256"] = sha(HERE / "run_pilot.py")
    config["mapping"]["value_diagnostic_builder_sha256"] = sha(HERE / "build_adapter.py")
    for artifact in config["runtime_artifacts"]:
        if artifact["path"] == original:
            artifact.update(path=str(ADAPTER), sha256=sha(ADAPTER))
    config["runtime_artifacts"].append(
        {"path": str(HERE / "run_pilot.py"), "sha256": sha(HERE / "run_pilot.py")})
    config["runtime_artifacts"].append(
        {"path": str(HERE / "build_adapter.py"), "sha256": sha(HERE / "build_adapter.py")})
    if config.get("agent_jar") != str(build_adapter.AGENT):
        raise ValueError("controller agent differs from the pinned direct runner")
    if config["budget"]["trials"] != 1 or not config["calibration_only"]:
        raise ValueError("healthy-only bound changed")
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    meta = preflight.main()
    if args.preflight_only:
        print(json.dumps(meta, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("node1 dispatch GO receipt required")
    check_go(args.admission_receipt, meta)
    if socket.gethostname().split(".", 1)[0] != "node1" or OUT.exists():
        raise ValueError("node1 and fresh healthy output required")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        processes = subprocess.check_output(
            ["ps", "-u", str(os.getuid()), "-o", "comm="], text=True).splitlines()
        if any(name.strip() in {"java", "mvn"} for name in processes):
            raise ValueError("competing user JVM or Maven process")
        if OUT.exists() or shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("output exists or insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available memory")
        built = build_adapter.build()
        if not ADAPTER.is_file() or built["adapter_sha256"] != sha(ADAPTER):
            raise ValueError("diagnostic adapter was not built")
        config = generated_config()
        sys.path.insert(0, str(RELEASE))
        from Mallory.core import campaign
        campaign.validate_config(config)
        CONFIG.write_text(json.dumps(config, sort_keys=True, indent=2) + "\n",
                          encoding="utf-8")
        state = campaign.run(CONFIG, OUT, calibration_only=True)
        print(json.dumps({"case_id": "SOLR-38", "status": state["status"],
                          "completed_trials": state["completed_trials"],
                          "adapter_sha256": sha(ADAPTER)}, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
