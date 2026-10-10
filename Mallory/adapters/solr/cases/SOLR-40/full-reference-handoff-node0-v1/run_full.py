#!/usr/bin/env python3
"""GO-gated SOLR-40 full campaign with a fresh exact-reference seed gate."""

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

import gate_v2
import preflight_full
from seed_gate import promote, validate_plan, verify_promotion

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"
OUT = ROOT / "data/mallory/solr40_reference_full_v1_node0/SOLR-40"
ADMISSION = HERE / "admission-full-node0.json"
LOCKS = ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
         "solr-source-graphchecker-8.11.4.lock")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    evidence = preflight_full.main()
    if args.preflight_only:
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch full GO receipt required before starting Solr JUnit")
    if args.admission_receipt.resolve() != ADMISSION:
        raise ValueError("case-local node0 full GO receipt required")
    receipt = json.loads(args.admission_receipt.read_text())
    if not (receipt.get("go") is True and receipt.get("host") == "node0" and
            receipt.get("case_id") == "SOLR-40" and receipt.get("mode") == "full" and
            receipt.get("config_sha256") == evidence["config_sha256"] and
            receipt.get("agent_jar_sha256") == evidence["agent_jar_sha256"] and
            receipt.get("runner_sha256") == sha(Path(__file__)) and
            receipt.get("intended_output") == str(OUT)):
        raise ValueError("dispatch full GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node0":
        raise ValueError("full campaign must run on node0")
    if OUT.exists() != args.resume:
        raise ValueError("use a fresh output, or --resume for an existing campaign")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in LOCKS:
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists() != args.resume:
            raise ValueError("campaign output changed while acquiring locks")
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
        base_run_trial = campaign._run_trial

        def run_trial(config, out, trial_id, plan, save_running, target_binding):
            if trial_id > 0:
                validate_plan(out, plan)
            # The JUnit may reassign the routed request to another named node.
            # Runtime identity is checked again on every trial by gate_v2.
            return base_run_trial(config, out, trial_id, plan, save_running, None)

        campaign.analyze = gate_v2.analyze
        campaign._run_trial = run_trial
        if not (OUT / "checkpoint.json").exists():
            campaign.run(HERE / "config.json", OUT, calibration_only=True)
        state = json.loads((OUT / "checkpoint.json").read_text())
        if state.get("calibration_only") is True and state.get("status") == "running":
            campaign.run(HERE / "config.json", OUT, calibration_only=True)
        state = json.loads((OUT / "checkpoint.json").read_text())
        if state.get("calibration_only") is True:
            promote(OUT)
        verify_promotion(OUT)
        state = campaign.run(HERE / "config.json", OUT)
        print(json.dumps({"case_id": "SOLR-40", "status": state["status"],
                          "completed_trials": state["completed_trials"],
                          "full_campaign_go_receipt_sha256": sha(ADMISSION)},
                         sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
