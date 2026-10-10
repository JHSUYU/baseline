#!/usr/bin/env python3
"""GO-gated one-run SOLR-39 preemptive healthy seed on node1."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import preflight

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = (ROOT / "Mallory/dispatch/releases/"
           "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4")
OUT = ROOT / "data/mallory/calibration_solr39_preemptive_healthy_v3_node1/SOLR-39"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    evidence = preflight.inspect()
    if args.preflight_only:
        print(json.dumps(evidence, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("fresh dispatch GO receipt required")
    receipt = json.loads(args.admission_receipt.read_text())
    required = {name: evidence[name] for name in (
        "case_id", "mode", "host", "config_sha256", "inventory_sha256",
        "pins_sha256", "runner_sha256", "selector_runner_sha256",
        "agent_sha256", "intended_output")}
    if not (receipt.get("go") is True and
            isinstance(receipt.get("attempt_id"), str) and receipt["attempt_id"] and
            all(receipt.get(name) == value for name, value in required.items())):
        raise ValueError("dispatch GO receipt absent or does not pin this package")
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("this healthy seed is reserved for node1")
    if OUT.exists():
        raise ValueError("healthy output already exists; no duplicate run")
    processes = subprocess.check_output(["ps", "-u", str(os.getuid()), "-o", "comm="],
                                        text=True).splitlines()
    if any(name.strip() in {"java", "mvn", "javac"} for name in processes):
        raise ValueError("competing user JVM or Maven process")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists():
            raise ValueError("healthy output created while acquiring locks")
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available memory")
        sys.path.insert(0, str(RELEASE))
        from Mallory.core import campaign  # noqa: E402
        config_path = HERE / "config.json"
        campaign.validate_config(json.loads(config_path.read_text()))
        state = campaign.run(config_path, OUT)
        print(json.dumps({"case_id": "SOLR-39", "status": state["status"],
                          "completed_trials": state["completed_trials"]}, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
