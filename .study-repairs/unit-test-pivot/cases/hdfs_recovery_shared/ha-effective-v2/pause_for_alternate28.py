#!/usr/bin/env python3
"""Pause shared HA only at an audited, unstarted JUnit boundary after peer goals."""
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

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
LOCK = HERE / "campaign.lock"
ALT = HERE / "fallback28-junit-v1" / "checkpoint.json"
BACKUP = HERE / "checkpoint.pre-alternate28-pause.json"
RECEIPT = HERE / "alternate28-pause-receipt.json"
RUNNER_SHA = "80a9f8b365cb228d4c042fbca1a870b0c1d19437dae8c5c476e7f02e0ce74ac7"
ABSENT = ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json")


def actor(pid: int) -> bool:
    proc = Path("/proc") / str(pid)
    try:
        cmd = common.proc_cmd(pid).split(b"\0")
        if (not any(part.endswith(b"focus28_v2.py") for part in cmd)
                or b"--run" not in cmd or (proc / "cwd").resolve() != HERE):
            return False
        inode = LOCK.stat()
        return any((fd.stat().st_dev, fd.stat().st_ino) ==
                   (inode.st_dev, inode.st_ino) for fd in (proc / "fd").iterdir())
    except (OSError, PermissionError):
        return False


def evidence() -> dict:
    shared = json.loads(STATE.read_text())
    alternate = json.loads(ALT.read_text())
    counts = {case: len(rows) for case, rows in campaign.effective(shared).items()}
    alt_valid = sum(bool(row["exact_order_applied"] and
                         row["post_fault_target_checks"]["HDFS-28"])
                    for row in alternate["completed"])
    recent = shared["completed"][-24:]
    shared_recent = sum(bool(row["exact_order_applied"] and
                             row["post_fault_target_checks"]["HDFS-28"])
                        for row in recent)
    alt_tail = alternate["completed"][-12:]
    alternate_recent = sum(bool(row["exact_order_applied"] and
                                row["post_fault_target_checks"]["HDFS-28"])
                           for row in alt_tail)
    basis = {"shared_effective": counts, "shared_recent_window": len(recent),
             "shared_recent_hdfs28_effective": shared_recent,
             "alternate_attempts": len(alternate["completed"]),
             "alternate_hdfs28_effective": alt_valid,
             "alternate_recent_window": len(alt_tail),
             "alternate_recent_hdfs28_effective": alternate_recent,
             "alternate_checkpoint_sha256": common.sha(ALT.read_bytes())}
    if (shared.get("focus28_scheduler", {}).get("policy") is None
            or shared.get("test") !=
            "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"
            or alternate.get("test") !=
            "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testLeaseRecoveryAfterFailover"
            or counts["HDFS-29"] < shared["goals"]["HDFS-29"]
            or counts["HDFS-30"] < shared["goals"]["HDFS-30"]
            or any(shared.get("extensions", {}).get(case, {}).get("novelty") is not False
                   for case in ("HDFS-29", "HDFS-30"))
            or counts["HDFS-28"] >= shared["goals"]["HDFS-28"]
            or len(recent) < 24 or shared_recent * 4 > len(recent)
            or len(alt_tail) < 12 or alternate_recent < 3
            or alternate_recent * len(recent) <= shared_recent * len(alt_tail)
            or alternate.get("stop_reason") is not None
            or campaign.stop_reason(shared) is not None):
        raise RuntimeError("peer goals or measured alternate-yield basis not satisfied")
    return basis


def unstarted(state: dict) -> Path | None:
    if state["active"] is None:
        return None
    directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    if (any((directory / name).exists() for name in ABSENT)
            or campaign.child_java_started(directory)
            or campaign.previous_runner_alive(directory)):
        return None
    plan = directory / "fault-plan.tsv"
    if (not plan.is_file() or
            plan.read_text() != common.planned_contents(state["active"]["sequence"])):
        return None
    return directory


def attempt(pid: int) -> dict | None:
    proc = Path("/proc") / str(pid)
    if not actor(pid) or common.sha((HERE / "focus28_v2.py").read_bytes()) != RUNNER_SHA:
        raise RuntimeError("PID/source is not the known HA focus controller")
    if BACKUP.exists() or RECEIPT.exists():
        raise RuntimeError("alternate pause already has a backup or receipt")
    if ("locks_lock_inode_wait" not in (proc / "wchan").read_text()
            or "Threads:\t1" not in (proc / "status").read_text()):
        return None
    original = STATE.read_bytes()
    state = json.loads(original)
    try:
        basis = evidence()
    except RuntimeError:
        return None
    directory = unstarted(state)
    if directory is None:
        return None
    os.kill(pid, signal.SIGSTOP)
    killed = False
    try:
        for _ in range(50):
            if (proc / "status").read_text().split("State:", 1)[1].lstrip().startswith(("T", "t")):
                break
            time.sleep(0.02)
        else:
            return None
        if (not actor(pid) or "Threads:\t1" not in (proc / "status").read_text()
                or STATE.read_bytes() != original or unstarted(state) != directory
                or evidence() != basis):
            return None
        if audit_raw.main() != 0:
            raise RuntimeError("independent shared HA raw audit rejected frozen checkpoint")
        audit_file = HERE / "raw-audit.json"
        audit = json.loads(audit_file.read_text())
        if (audit["checkpoint_sha256"] != common.sha(original) or audit["errors"]
                or audit["completed_attempts"] != len(state["completed"])
                or STATE.read_bytes() != original):
            raise RuntimeError("raw audit/checkpoint mismatch while frozen")
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
                raise RuntimeError("focus controller did not release campaign lock")
            if STATE.read_bytes() != original or unstarted(state) != directory:
                raise RuntimeError("shared HA plan changed after focus controller stopped")
            common.durable(BACKUP, original)
            receipt = {"schema": 1, "reason": "alternate_original_junit_higher_hdfs28_yield",
                       "created_at_utc": campaign.utc(), "controller_pid": pid,
                       "source_sha256": RUNNER_SHA, "checkpoint_sha256": common.sha(original),
                       "backup_sha256": common.sha(BACKUP.read_bytes()),
                       "raw_audit_sha256": common.sha(audit_file.read_bytes()),
                       "completed": len(state["completed"]), "queue": len(state["queue"]),
                       "seen": len(state["seen"]), "active_plan": state["active"]["id"],
                       "active_plan_sha256": common.sha((directory / "fault-plan.tsv").read_bytes()),
                       "unstarted_trial_directory": str(directory),
                       "junit_started": False, "basis": basis}
            common.durable(RECEIPT, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
            return receipt
    finally:
        if not killed and proc.exists():
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.preview:
        try:
            basis = evidence()
            eligible = True
        except RuntimeError as error:
            basis, eligible = {"reason": str(error)}, False
        state = json.loads(STATE.read_text())
        print(json.dumps({"eligible_yield_basis": eligible, "basis": basis,
                          "active_reserved_unstarted": unstarted(state) is not None,
                          "completed": len(state["completed"]),
                          "controller_source_matches":
                          common.sha((HERE / "focus28_v2.py").read_bytes()) == RUNNER_SHA},
                         sort_keys=True))
        return
    if args.pid is None:
        parser.error("--pid is required unless --preview is used")
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        if not (Path("/proc") / str(args.pid)).exists():
            raise RuntimeError("HA focus controller exited before safe boundary")
        receipt = attempt(args.pid)
        if receipt:
            print(json.dumps(receipt, sort_keys=True), flush=True)
            return
        time.sleep(0.25)
    raise TimeoutError("no eligible unstarted JUnit boundary before timeout")


if __name__ == "__main__":
    main()
