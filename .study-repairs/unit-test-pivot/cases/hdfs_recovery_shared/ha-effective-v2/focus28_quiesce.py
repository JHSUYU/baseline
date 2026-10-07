#!/usr/bin/env python3
"""Optional safe stop of the running HA successor for versioned HDFS-28 focus.

Only the Python controller can be stopped, and only while it is the sole
thread waiting on the shared JVM-start flock with an unstarted reserved plan.
The full original raw audit runs before SIGKILL; failure SIGCONTs the runner.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import time

import audit_raw
import campaign
import early_quiesce as common
import focus28_v2


HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
LOCK = HERE / "campaign.lock"
BACKUP = HERE / "checkpoint.pre-focus28-v2.json"
RECEIPT = HERE / "focus28-v2-quiesce-receipt.json"
ABSENT = ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json")


def controller(pid: int) -> bool:
    proc = Path("/proc") / str(pid)
    parts = common.proc_cmd(pid).split(b"\0")
    if not any(part.endswith(b"successor.py") for part in parts):
        return False
    if b"--run" not in parts or (proc / "cwd").resolve() != HERE:
        return False
    expected = LOCK.stat()
    for fd in (proc / "fd").iterdir():
        try:
            opened = fd.stat()
        except (OSError, PermissionError):
            continue
        if (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino):
            return True
    return False


def unstarted(state: dict) -> tuple[bool, Path, dict]:
    directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    active = state.get("active")
    counts = {case: len(rows) for case, rows in campaign.effective(state).items()}
    canonical = focus28_v2.healthy_early(state)
    stats = focus28_v2.candidate_counts(state, canonical)
    queued_early = sum("HDFS-28" in item["eligible"] and len(item["sequence"]) == 1
                       and focus28_v2.successor.lane(item["sequence"][-1]) == "RPC"
                       for item in state["queue"])
    basis = {"effective": counts, "canonical": stats,
             "queued_one_fault_28_rpc": queued_early,
             "focus_gap": min(counts["HDFS-29"], counts["HDFS-30"]) - counts["HDFS-28"]}
    ready = (active is not None and focus28_v2.focus_needed(state)
             and queued_early > 0 and campaign.stop_reason(state) is None
             and not any((directory / name).exists() for name in ABSENT)
             and not campaign.child_java_started(directory)
             and not campaign.previous_runner_alive(directory))
    if ready:
        plan = directory / "fault-plan.tsv"
        ready = plan.is_file() and plan.read_text() == common.planned_contents(active["sequence"])
    return ready, directory, basis


def attempt(pid: int) -> dict | None:
    if not controller(pid):
        raise RuntimeError("PID is not the running HA successor holding campaign.lock")
    if BACKUP.exists() or RECEIPT.exists():
        raise RuntimeError("focus28 safe-stop backup or receipt already exists")
    proc = Path("/proc") / str(pid)
    if ("locks_lock_inode_wait" not in (proc / "wchan").read_text()
            or "Threads:\t1" not in (proc / "status").read_text()):
        return None
    original = STATE.read_bytes()
    state = json.loads(original)
    ready, directory, basis = unstarted(state)
    if not ready or "locks_lock_inode_wait" not in (proc / "wchan").read_text():
        return None
    os.kill(pid, signal.SIGSTOP)
    killed = False
    try:
        observed_stopped = False
        for _ in range(50):
            status = (proc / "status").read_text()
            if status.split("State:", 1)[1].lstrip().startswith(("T", "t")):
                observed_stopped = True
                break
            time.sleep(0.02)
        if (not observed_stopped or not controller(pid)
                or "Threads:\t1" not in (proc / "status").read_text()):
            return None
        still, same_directory, same_basis = unstarted(state)
        if (not still or same_directory != directory or same_basis != basis
                or STATE.read_bytes() != original):
            return None
        if audit_raw.main() != 0:
            raise RuntimeError("independent raw audit rejected frozen checkpoint")
        audit = HERE / "raw-audit.json"
        audited = json.loads(audit.read_text())
        if (audited["checkpoint_sha256"] != common.sha(original) or audited["errors"]
                or audited["completed_attempts"] != len(state["completed"])
                or STATE.read_bytes() != original):
            raise RuntimeError("frozen checkpoint differs from raw audit")
        os.kill(pid, signal.SIGKILL)
        killed = True
        with LOCK.open("a+") as lock:
            for _ in range(100):
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("old successor did not release campaign lock")
            if STATE.read_bytes() != original:
                raise RuntimeError("checkpoint changed after old successor stopped")
            still, _, same_basis = unstarted(state)
            if not still or same_basis != basis:
                raise RuntimeError("reserved plan changed after old successor stopped")
            common.durable(BACKUP, original)
            receipt = {"schema": 1, "created_at_utc": campaign.utc(),
                       "stopped_controller_pid": pid,
                       "source_sha256": common.sha((HERE / "successor.py").read_bytes()),
                       "checkpoint_sha256": common.sha(original),
                       "backup_sha256": common.sha(BACKUP.read_bytes()),
                       "raw_audit_sha256": common.sha(audit.read_bytes()),
                       "completed": len(state["completed"]),
                       "active_plan": state["active"]["id"],
                       "active_plan_sha256": common.sha((directory / "fault-plan.tsv").read_bytes()),
                       "trial_directory": str(directory), "basis": basis,
                       "junit_started": False}
            common.durable(RECEIPT, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
            return receipt
    finally:
        if not killed and proc.exists():
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        if not (Path("/proc") / str(args.pid)).exists():
            raise RuntimeError("old HA successor exited before safe boundary")
        receipt = attempt(args.pid)
        if receipt:
            print(json.dumps(receipt, sort_keys=True), flush=True)
            return
        time.sleep(0.25)
    raise TimeoutError("no HDFS-28 focus trigger at an unstarted reserved JUnit")


if __name__ == "__main__":
    main()
