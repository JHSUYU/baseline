#!/usr/bin/env python3
"""GO-gated one-trial SOLR-39 healthy observation on independent node1."""

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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
BASE = HERE.parent / "healthy-source-admission-v2"
OUT = ROOT / "data/mallory/calibration_solr39_watcher_healthy_v2_node1/SOLR-39"
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
DISK_FLOOR = 7_650_410_496
MEM_FLOOR_KIB = 8_388_608


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_competing_jvm() -> None:
    processes = subprocess.check_output(
        ["ps", "-u", str(os.getuid()), "-o", "comm="], text=True
    ).splitlines()
    if any(name.strip() in {"java", "mvn"} for name in processes):
        raise ValueError("competing user JVM or Maven process")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    evidence = preflight.main()
    if args.preflight_only:
        print(json.dumps(evidence, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("case-local dispatch GO receipt required")
    grant = json.loads(args.admission_receipt.read_text())
    expected = {
        "go": True,
        "case_id": "SOLR-39",
        "host": "node1",
        "mode": "healthy",
        "config_sha256": evidence["config_sha256"],
        "runner_sha256": sha(Path(__file__)),
        "intended_output": str(OUT),
    }
    if any(grant.get(key) != value for key, value in expected.items()):
        raise ValueError("dispatch GO receipt differs")
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("healthy observation must run on node1")
    if OUT.exists():
        raise ValueError("healthy output must be fresh")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        no_competing_jvm()
        if OUT.exists() or shutil.disk_usage(ROOT).free < DISK_FLOOR:
            raise ValueError("output exists or insufficient free disk")
        mem_kib = next(
            int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
            if row.startswith("MemAvailable:")
        )
        if mem_kib < MEM_FLOOR_KIB:
            raise ValueError("insufficient available memory")
        sys.path.insert(0, str(RELEASE))
        from Mallory.core import campaign

        config_path = BASE / "config.json"
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
