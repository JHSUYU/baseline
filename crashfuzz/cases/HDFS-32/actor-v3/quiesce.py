#!/usr/bin/env python3
"""Stop only the V3 Python controller at an unstarted reserved-plan boundary.

The observed checkpoint remains intact. Never signal an active JUnit or its
runner; if they race the freeze, resume the controller and retry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
RECEIPT = HERE / "quiescent-stop-receipt.json"
UNSTARTED_ABSENT = ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json")


def proc_cmd(pid: int) -> bytes:
    return Path(f"/proc/{pid}/cmdline").read_bytes()


def has_trial_java(directory: Path) -> bool:
    needle = str(directory).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if b"/java\0" in cmd and needle in cmd:
            return True
    return False


def unstarted(state: dict) -> tuple[bool, Path]:
    directory = HERE / "runs" / f"trial-{len(state['completed']) + 1:04d}"
    return (state.get("active") is not None
            and not any((directory / x).exists() for x in UNSTARTED_ABSENT)
            and not has_trial_java(directory)), directory


def attempt(pid: int) -> dict | None:
    if b"actor-v3/campaign.py\0" not in proc_cmd(pid):
        raise RuntimeError("controller command identity changed")
    previous = STATE.read_bytes()
    state = json.loads(previous)
    ready, directory = unstarted(state)
    if not ready or "locks_lock_inode_wait" not in Path(f"/proc/{pid}/wchan").read_text():
        return None
    os.kill(pid, signal.SIGSTOP)
    try:
        for _ in range(50):
            status = Path(f"/proc/{pid}/status").read_text()
            if status.split("State:", 1)[1].lstrip().startswith(("T", "t")):
                break
            time.sleep(0.02)
        else:
            return None
        ready_after, same_directory = unstarted(state)
        if (not ready_after or same_directory != directory
                or STATE.read_bytes() != previous):
            return None
        os.kill(pid, signal.SIGKILL)
        receipt = {"schema": 1, "stopped_controller_pid": pid,
                   "completed": len(state["completed"]),
                   "active_plan": state["active"]["id"],
                   "checkpoint_sha256": hashlib.sha256(previous).hexdigest(),
                   "junit_started": False}
        pending = RECEIPT.with_suffix(".json.tmp")
        pending.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        pending.replace(RECEIPT)
        return receipt
    finally:
        if Path(f"/proc/{pid}").exists():
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
        if not Path(f"/proc/{args.pid}").exists():
            raise RuntimeError("controller exited before safe boundary")
        receipt = attempt(args.pid)
        if receipt:
            print(json.dumps(receipt, sort_keys=True), flush=True)
            return
        time.sleep(0.05)
    raise TimeoutError("no unstarted reserved-plan boundary within timeout")


if __name__ == "__main__":
    main()
