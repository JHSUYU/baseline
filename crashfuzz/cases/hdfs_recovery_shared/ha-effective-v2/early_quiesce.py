#!/usr/bin/env python3
"""Freeze only the old HA Python controller at a reserved, unstarted trial.

This is an optional early boundary once HDFS-29/30 each have 80 effective
trials and HDFS-28 remains short.  It never signals the JUnit runner or Java.
An unsuccessful check resumes the old controller without changing its state.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import time

import audit_raw
import campaign


HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
LOCK = HERE / "campaign.lock"
BACKUP = HERE / "checkpoint.pre-successor-early.json"
RECEIPT = HERE / "early-quiesce-receipt.json"
ABSENT = ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def durable(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def proc_cmd(pid: int) -> bytes:
    return (Path("/proc") / str(pid) / "cmdline").read_bytes()


def old_controller(pid: int) -> bool:
    proc = Path("/proc") / str(pid)
    cmd = proc_cmd(pid).split(b"\0")
    if not any(x.endswith(b"campaign.py") for x in cmd):
        return False
    if b"--run" not in cmd or (proc / "cwd").resolve() != HERE:
        return False
    inode = LOCK.stat()
    for fd in (proc / "fd").iterdir():
        try:
            opened = fd.stat()
        except (OSError, PermissionError):
            continue
        if (opened.st_dev, opened.st_ino) == (inode.st_dev, inode.st_ino):
            return True
    return False


def planned_contents(sequence: list[dict]) -> str:
    return "".join("\t".join(str(fault[key]) for key in
                             ("marker", "siteId", "sourceKey",
                              "occurrenceAddress", "hitOrdinal", "faultType"))
                   + "\t" + fault["filePhase"] + "\n"
                   for fault in sequence)


def trigger(state: dict, counts: dict) -> dict | None:
    if (counts["HDFS-29"] >= campaign.BASE
            and counts["HDFS-30"] >= campaign.BASE
            and counts["HDFS-28"] < state["goals"]["HDFS-28"]):
        return {"kind": "peer80_focus28", "effective": counts}
    if len(state["completed"]) < 12:
        return None
    recent = state["completed"][-12:]
    file_count = sum(row["sequence"][-1]["marker"].startswith("FAULT:HDFS_FILE:")
                     for row in recent)
    effective_any = sum(bool(row["exact_order_applied"] and
                             any(row["post_fault_target_checks"].values()))
                        for row in recent)
    if file_count < 10 or effective_any > 2:
        return None
    return {"kind": "file_skew_low_yield", "window": 12,
            "file_final_faults": file_count,
            "effective_any": effective_any,
            "last_trial_ids_sha256": sha("\n".join(row["id"] for row in recent).encode()),
            "effective": counts}


def unstarted(state: dict) -> tuple[bool, Path, dict, dict | None]:
    counts = {case: len(rows) for case, rows in campaign.effective(state).items()}
    reason = trigger(state, counts)
    directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    active = state.get("active")
    ready = (active is not None and reason is not None
             and campaign.stop_reason(state) is None
             and not any((directory / name).exists() for name in ABSENT)
             and not campaign.child_java_started(directory)
             and not campaign.previous_runner_alive(directory))
    if ready:
        plan = directory / "fault-plan.tsv"
        ready = plan.is_file() and plan.read_text() == planned_contents(active["sequence"])
    return ready, directory, counts, reason


def attempt(pid: int) -> dict | None:
    if not old_controller(pid):
        raise RuntimeError("PID is not the original HA controller holding its campaign lock")
    if BACKUP.exists() or RECEIPT.exists():
        raise RuntimeError("early boundary backup or receipt already exists")
    proc = Path("/proc") / str(pid)
    if "locks_lock_inode_wait" not in (proc / "wchan").read_text():
        return None
    # The flock wait is in the controller's sole Python thread.
    if "Threads:\t1" not in (proc / "status").read_text():
        return None
    original = STATE.read_bytes()
    state = json.loads(original)
    ready, directory, counts, reason = unstarted(state)
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
        if (not observed_stopped or not old_controller(pid)
                or "Threads:\t1" not in (proc / "status").read_text()):
            return None
        again, same_directory, again_counts, again_reason = unstarted(state)
        if (not again or same_directory != directory or again_counts != counts
                or again_reason != reason or STATE.read_bytes() != original):
            return None
        # Freeze makes the checkpoint and completed raw files stable.  Reject
        # the early switch before signalling SIGKILL if any raw trial differs.
        if audit_raw.main() != 0:
            raise RuntimeError("independent raw audit rejected old checkpoint")
        raw_audit = HERE / "raw-audit.json"
        audited = json.loads(raw_audit.read_text())
        if (audited["checkpoint_sha256"] != sha(original) or audited["errors"]
                or audited["completed_attempts"] != len(state["completed"])):
            raise RuntimeError("independent raw audit receipt disagrees with frozen checkpoint")
        if STATE.read_bytes() != original:
            raise RuntimeError("checkpoint changed during frozen raw audit")
        os.kill(pid, signal.SIGKILL)
        killed = True
        # SIGKILL releases the old controller's campaign flock.  No new
        # controller can alter the checkpoint while this lock is held.
        with LOCK.open("a+") as lock:
            for _ in range(100):
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("old campaign lock did not release after SIGKILL")
            if STATE.read_bytes() != original:
                raise RuntimeError("checkpoint changed after old controller stopped")
            still, _, _, still_reason = unstarted(state)
            if not still or still_reason != reason:
                raise RuntimeError("reserved trial changed after old controller stopped")
            if BACKUP.exists() or RECEIPT.exists():
                raise RuntimeError("early boundary backup or receipt already exists")
            durable(BACKUP, original)
            receipt = {
                "schema": 1, "boundary": "unstarted_reserved_plan",
                "stopped_controller_pid": pid, "created_at_utc": campaign.utc(),
                "old_runner_sha256": sha((HERE / "campaign.py").read_bytes()),
                "checkpoint_sha256": sha(original), "backup_sha256": sha(BACKUP.read_bytes()),
                "active_plan_sha256": sha((directory / "fault-plan.tsv").read_bytes()),
                "independent_raw_audit_sha256": sha(raw_audit.read_bytes()),
                "completed": len(state["completed"]), "queue": len(state["queue"]),
                "seen": len(state["seen"]), "active_plan": state["active"]["id"],
                "unstarted_trial_directory": str(directory),
                "effective": counts, "trigger": reason, "junit_started": False,
            }
            durable(RECEIPT, (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
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
            raise RuntimeError("old controller exited before early safe boundary")
        result = attempt(args.pid)
        if result:
            print(json.dumps(result, sort_keys=True), flush=True)
            return
        time.sleep(0.25)
    raise TimeoutError("no eligible early trigger at an unstarted JUnit boundary")


if __name__ == "__main__":
    main()
