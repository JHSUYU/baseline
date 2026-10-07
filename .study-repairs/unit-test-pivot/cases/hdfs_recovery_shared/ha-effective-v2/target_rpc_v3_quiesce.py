#!/usr/bin/env python3
"""Stop only the HA Python controller at a proven unstarted JUnit boundary."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import audit_raw
import campaign as C
import early_quiesce as common
import target_rpc_v3 as V3

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
LOCK = HERE / "campaign.lock"
BACKUP = HERE / "checkpoint.pre-target-rpc-v3.json"
RECEIPT = HERE / "target-rpc-v3-quiesce-receipt.json"
ABSENT = ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json", "jacoco.exec")


def controller(pid: int) -> bool:
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        return False
    parts = common.proc_cmd(pid).split(b"\0")
    if (not any(part.endswith(b"focus28_v2.py") for part in parts)
            or b"--run" not in parts or (proc / "cwd").resolve() != HERE):
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


def planned_contents(sequence: list[dict]) -> str:
    return "".join("\t".join(str(row[key]) for key in
                               ("marker", "siteId", "sourceKey",
                                "occurrenceAddress", "hitOrdinal", "faultType"))
                   + "\t" + row["filePhase"] + "\n" for row in sequence)


def unstarted(state: dict) -> tuple[bool, Path]:
    directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    active = state.get("active")
    ready = (active is not None and state.get("target_rpc_v3") is None
             and state.get("focus28_scheduler", {}).get("policy") == V3.V2.POLICY
             and len(C.effective(state)["HDFS-28"]) < state["goals"]["HDFS-28"]
             and C.stop_reason(state) is None
             and not any((directory / name).exists() for name in ABSENT)
             and not C.child_java_started(directory)
             and not C.previous_runner_alive(directory))
    if ready:
        plan = directory / "fault-plan.tsv"
        ready = plan.is_file() and plan.read_text() == planned_contents(active["sequence"])
    return ready, directory


def attempt(pid: int) -> dict | None:
    if not controller(pid):
        raise RuntimeError("PID is not the active focus28 V2 controller")
    if BACKUP.exists() or RECEIPT.exists():
        raise RuntimeError("v3 safe-stop backup/receipt already exists")
    proc = Path("/proc") / str(pid)
    if ("locks_lock_inode_wait" not in (proc / "wchan").read_text()
            or "Threads:\t1" not in (proc / "status").read_text()):
        return None
    original = STATE.read_bytes()
    state = json.loads(original)
    ready, directory = unstarted(state)
    if not ready or "locks_lock_inode_wait" not in (proc / "wchan").read_text():
        return None
    os.kill(pid, signal.SIGSTOP)
    killed = False
    try:
        for _ in range(50):
            status = (proc / "status").read_text()
            if status.split("State:", 1)[1].lstrip().startswith(("T", "t")):
                break
            time.sleep(0.02)
        else:
            return None
        again, other_directory = unstarted(state)
        if (not controller(pid) or "Threads:\t1" not in (proc / "status").read_text()
                or not again or other_directory != directory or STATE.read_bytes() != original):
            return None
        fresh = V3.discover(state)
        if not any(row["sequence"][0]["marker"] == V3.MARKERS[0] for row in fresh):
            return None
        if audit_raw.main() != 0:
            raise RuntimeError("independent raw audit rejected frozen checkpoint")
        audit_path = HERE / "raw-audit.json"
        audit = json.loads(audit_path.read_text())
        if (audit["errors"] or audit["checkpoint_sha256"] != common.sha(original)
                or audit["completed_attempts"] != len(state["completed"])
                or STATE.read_bytes() != original):
            raise RuntimeError("frozen checkpoint and raw audit disagree")
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
                raise RuntimeError("predecessor did not release campaign lock")
            stable, stable_dir = unstarted(state)
            if (not stable or stable_dir != directory
                    or STATE.read_bytes() != original):
                raise RuntimeError("reserved plan changed after controller stop")
            common.durable(BACKUP, original)
            receipt = {"schema": 1, "source_sha256": V3.OLD_SOURCE_SHA,
                       "checkpoint_sha256": common.sha(original),
                       "backup_sha256": common.sha(BACKUP.read_bytes()),
                       "raw_audit_sha256": common.sha(audit_path.read_bytes()),
                       "completed": len(state["completed"]),
                       "effective28": len(C.effective(state)["HDFS-28"]),
                       "active_plan": state["active"]["id"],
                       "active_plan_sha256": common.sha((directory / "fault-plan.tsv").read_bytes()),
                       "trial_directory": str(directory),
                       "new_hdfs_rpc_singletons": sum(
                           row["sequence"][0]["marker"] == V3.MARKERS[0] for row in fresh),
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
    parser.add_argument("--wait-seconds", type=int, default=1800)
    parser.add_argument("--run-successor", action="store_true")
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait_seconds
    while time.monotonic() < deadline:
        if not (Path("/proc") / str(args.pid)).exists():
            raise RuntimeError("V2 controller exited before a safe handoff; inspect natural checkpoint")
        receipt = attempt(args.pid)
        if receipt:
            print(json.dumps(receipt, sort_keys=True), flush=True)
            if args.run_successor:
                subprocess.run([sys.executable, str(HERE / "target_rpc_v3.py"),
                                "--run"], cwd=HERE, check=True)
            return
        time.sleep(0.25)
    raise TimeoutError("no unstarted reserved JUnit while V2 waited on shared start lock")


if __name__ == "__main__":
    main()
