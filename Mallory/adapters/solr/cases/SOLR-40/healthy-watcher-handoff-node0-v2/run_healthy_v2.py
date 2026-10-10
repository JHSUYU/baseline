#!/usr/bin/env python3
"""GO-gated one-trial SOLR-40 healthy run with exact reference handoff."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import audit_v2
import gate_v2
import preflight_runtime

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
OUT = ROOT / "data/mallory/calibration_solr40_reference_handoff_v2_node0/SOLR-40"
ADMISSION = HERE / "admission-healthy-node0.json"
LOCKS = ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
         "solr-source-graphchecker-8.11.4.lock")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    evidence = preflight_runtime.main()
    if args.preflight_only:
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting Solr JUnit")
    if args.admission_receipt.resolve() != ADMISSION:
        raise ValueError("case-local node0 GO receipt required")
    receipt = json.loads(args.admission_receipt.read_text())
    if not (receipt.get("go") is True and receipt.get("host") == "node0" and
            receipt.get("case_id") == "SOLR-40" and receipt.get("mode") == "healthy" and
            receipt.get("config_sha256") == evidence["config_sha256"] and
            receipt.get("agent_jar_sha256") == evidence["agent_jar_sha256"] and
            receipt.get("runner_sha256") == sha(Path(__file__)) and
            receipt.get("intended_output") == str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node0" or OUT.exists():
        raise ValueError("node0 and a fresh v2 output are required")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists():
            raise ValueError("v2 output appeared while acquiring locks")
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"]
               for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        sys.path.insert(0, str(PINNED))
        from Mallory.core import campaign  # noqa: E402
        campaign.analyze = gate_v2.analyze
        state = campaign.run(HERE / "config.json", OUT)
        handoff = audit_v2.audit(OUT)
        (OUT / "handoff-audit.json").write_text(
            json.dumps(handoff, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"case_id": "SOLR-40", "status": state["status"],
                          "handoff_status": handoff["status"],
                          "completed_trials": state["completed_trials"],
                          "full_campaign_go": False}, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
