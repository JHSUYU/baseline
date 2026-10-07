#!/usr/bin/env python3
"""Stop the active V5 driver only after a completed, atomically saved trial.

SIGSTOP freezes the driver while its state is inspected. If it has already
started the next trial, SIGCONT lets that trial complete and inspection repeats.
The target JVM is never signalled. This is for a one-way node migration only.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import time

from migrate import CAMPAIGN, digest


STATE = CAMPAIGN / "state.json"


def checked_driver(pid: int) -> None:
    argv = [item.decode(errors="replace") for item in
            Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if item]
    if (not argv or Path(argv[0]).name not in ("python3", "python3.11") or
            not any("SOLR-10/actor-v2/probe/campaign.py" in item for item in argv[1:])):
        raise RuntimeError(f"PID {pid} is not this case's V5 Python driver")


def snapshot() -> dict:
    return json.loads(STATE.read_text())


def wait_stopped(pid: int) -> None:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        status = (Path(f"/proc/{pid}/status")).read_text()
        state = next(line for line in status.splitlines() if line.startswith("State:"))
        if "\tT" in state or "\tt" in state:
            return
        time.sleep(0.001)
    raise RuntimeError("SIGSTOP did not freeze the V5 driver")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    checked_driver(args.pid)
    end = time.monotonic() + args.timeout
    latest_mtime = STATE.stat().st_mtime_ns
    while time.monotonic() < end:
        if not Path(f"/proc/{args.pid}").exists():
            raise RuntimeError("driver exited before this boundary stop")
        mtime = STATE.stat().st_mtime_ns
        if mtime != latest_mtime:
            latest_mtime = mtime
            current = snapshot()
            if current["inflight"] is None:
                os.kill(args.pid, signal.SIGSTOP)
                try:
                    wait_stopped(args.pid)
                    frozen = snapshot()
                except Exception:
                    os.kill(args.pid, signal.SIGCONT)
                    raise
                if frozen["inflight"] is None:
                    number = len(frozen["trials"])
                    raw = CAMPAIGN / f"trial-{number:03d}" / "trial.json"
                    if not raw.exists():
                        os.kill(args.pid, signal.SIGCONT)
                        raise RuntimeError("completed trial receipt is missing")
                    if json.loads(raw.read_text())["number"] != number:
                        os.kill(args.pid, signal.SIGCONT)
                        raise RuntimeError("completed trial receipt number differs")
                    receipt = {
                        "stopped_at_utc": datetime.now(timezone.utc).isoformat(),
                        "driver_pid": args.pid, "completed_trials": number,
                        "queue_count": len(frozen["queue"]),
                        "seen_plan_count": len(frozen["seen_plans"]),
                        "state_sha256_before_stop_receipt": digest(STATE),
                        "last_trial_sha256": digest(raw),
                        "effective": {site: progress["effective"] for site, progress
                                      in frozen["site_progress"].items()},
                    }
                    os.kill(args.pid, signal.SIGKILL)
                    (CAMPAIGN / "migration-v5-stop.json").write_text(
                        json.dumps(receipt, indent=2, sort_keys=True) + "\n")
                    print(json.dumps(receipt, sort_keys=True), flush=True)
                    return
                os.kill(args.pid, signal.SIGCONT)
        time.sleep(0.001)
    raise RuntimeError("No complete-trial boundary observed within timeout; driver left running")


if __name__ == "__main__":
    main()
