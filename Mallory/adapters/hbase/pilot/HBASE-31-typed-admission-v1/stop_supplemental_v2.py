#!/usr/bin/env python3
"""Stop the redundant typed run only after a complete trial checkpoint."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time


ROOT = Path("/users/ZhenyuLi/baseline")
OLD = ROOT / "data/mallory/cases/HBASE-31"
SUPPLEMENTAL = OLD / "campaigns/typed-dispatch-v2-full"
CONFIG = ROOT / "Mallory/adapters/hbase/pilot/HBASE-31-typed-admission-v1/HBASE-31.dispatch-binding-v2.full.json"
LOCK = Path("/tmp/mallory-lanes/hbase-lane9-next.lock")
OLD_RESULT_SHA = "68422ac12b13d017825fec023fee3ca3cea024a3d53e687e0891ea80e0c08a8f"
CONTROLLER_PID = 3769845


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def controller_alive() -> bool:
    cmd = Path(f"/proc/{CONTROLLER_PID}/cmdline")
    if not cmd.is_file():
        return False
    text = cmd.read_bytes().replace(b"\0", b" ").decode(errors="replace")
    return ("Mallory.core.campaign" in text and str(CONFIG) in text and
            str(SUPPLEMENTAL) in text)


def lock_free() -> bool:
    with LOCK.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(stream, fcntl.LOCK_UN)
        return True


def main() -> None:
    old = load(OLD / "result.json")
    if (sha(OLD / "result.json") != OLD_RESULT_SHA or
            old.get("case_id") != "HBASE-31" or
            old.get("status") != "budget_exhausted" or
            old.get("fault_trials_completed") != 80):
        raise RuntimeError("old canonical full completion not verified")
    if not controller_alive():
        raise RuntimeError("exact supplemental controller no longer active")
    first = load(SUPPLEMENTAL / "checkpoint.json")
    baseline = max(first["completed_trials"])
    deadline = time.monotonic() + 900
    boundary = None
    while time.monotonic() < deadline:
        if not controller_alive():
            raise RuntimeError("supplemental controller exited before controlled stop")
        state = load(SUPPLEMENTAL / "checkpoint.json")
        latest = max(state["completed_trials"])
        trial = SUPPLEMENTAL / "trials" / f"r{latest:04d}" / "result.json"
        if latest >= baseline + 1 and state.get("running") is None and trial.is_file():
            boundary = latest
            os.kill(CONTROLLER_PID, signal.SIGTERM)
            break
        time.sleep(0.005)
    if boundary is None:
        raise TimeoutError("could not observe a complete trial boundary")
    release_deadline = time.monotonic() + 300
    while time.monotonic() < release_deadline and not lock_free():
        time.sleep(0.1)
    if not lock_free():
        raise TimeoutError("lane lock still held after supplemental stop")
    state = load(SUPPLEMENTAL / "checkpoint.json")
    latest = max(state["completed_trials"])
    receipt = {
        "schema_version": 1,
        "case_id": "HBASE-31",
        "kind": "redundant_supplemental_checkpoint_stop",
        "reason": "An earlier exact HBASE-31 full campaign already reached its 80-fault natural budget terminal; terminal-only completion does not require this typed rerun.",
        "old_canonical_result_sha256": OLD_RESULT_SHA,
        "supplemental_config_sha256": sha(CONFIG),
        "controller_pid": CONTROLLER_PID,
        "baseline_completed_trial": baseline,
        "stop_boundary_trial": boundary,
        "completed_fault_trials_after_stop": latest,
        "last_trial_result_sha256": sha(SUPPLEMENTAL / "trials" / f"r{latest:04d}" / "result.json"),
        "checkpoint_sha256": sha(SUPPLEMENTAL / "checkpoint.json"),
        "partial_result_sha256": sha(SUPPLEMENTAL / "result.json"),
        "partial_result_status": load(SUPPLEMENTAL / "result.json")["status"],
        "lane_lock_released": True,
        "counts_as_completed_campaign": False,
        "raw_tree_preserved": True,
    }
    out = SUPPLEMENTAL / "supplemental-stop-receipt.json"
    if out.exists():
        raise RuntimeError("supplemental stop receipt already exists")
    out.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
