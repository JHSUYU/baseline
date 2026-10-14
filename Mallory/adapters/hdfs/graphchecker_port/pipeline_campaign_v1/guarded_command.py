#!/usr/bin/env python3
"""Run one local-only preparation command under bounded host-space checks."""

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PG0 = Path("/proj/silentfailure-PG0")
ROOT = Path("/")
SHM = Path("/dev/shm")
START_PG0 = 10 * 1024 ** 3
STOP_PG0 = 9 * 1024 ** 3


def available(path):
    status = os.statvfs(path)
    return status.f_bavail * status.f_frsize


def mem_available():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ValueError("MemAvailable missing")


def sample():
    return {"pg0_available_bytes": available(PG0),
            "root_available_bytes": available(ROOT),
            "shm_available_bytes": available(SHM),
            "mem_available_bytes": mem_available()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--min-root-bytes", type=int, default=1024 ** 3)
    parser.add_argument("--min-shm-bytes", type=int, default=1024 ** 3)
    parser.add_argument("--min-memory-bytes", type=int, default=16 * 1024 ** 3)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.poll_seconds <= 0 or args.poll_seconds > 3:
        parser.error("poll interval must be within (0, 3] seconds")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command required after --")
    if args.receipt.exists() or args.stdout.exists() or args.stderr.exists():
        parser.error("refusing to replace an existing run artifact")
    first = sample()
    receipt = {"schema_version": 1, "command": command,
               "started_utc": datetime.now(timezone.utc).isoformat(),
               "poll_seconds": args.poll_seconds, "preflight": first,
               "limits": {"pg0_start_min": START_PG0,
                          "pg0_stop_max": STOP_PG0,
                          "root_min": args.min_root_bytes,
                          "shm_min": args.min_shm_bytes,
                          "memory_min": args.min_memory_bytes},
               "durable_pg0_bytes_written": 0}
    reason = None
    if first["pg0_available_bytes"] < START_PG0:
        reason = "pg0_start_floor"
    elif first["root_available_bytes"] <= args.min_root_bytes:
        reason = "root_floor"
    elif first["shm_available_bytes"] <= args.min_shm_bytes:
        reason = "shm_floor"
    elif first["mem_available_bytes"] <= args.min_memory_bytes:
        reason = "memory_floor"
    if reason:
        receipt.update(status="not_started", reason=reason)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        return 98
    with args.stdout.open("wb") as stdout, args.stderr.open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        receipt["pid"] = process.pid
        while True:
            try:
                code = process.wait(timeout=args.poll_seconds)
                break
            except subprocess.TimeoutExpired:
                current = sample()
                if current["pg0_available_bytes"] <= STOP_PG0:
                    reason = "pg0_stop_floor"
                elif current["root_available_bytes"] <= args.min_root_bytes:
                    reason = "root_floor"
                elif current["shm_available_bytes"] <= args.min_shm_bytes:
                    reason = "shm_floor"
                elif current["mem_available_bytes"] <= args.min_memory_bytes:
                    reason = "memory_floor"
                if reason:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    code = process.returncode
                    break
    receipt.update(status="guard_stopped" if reason else "finished",
                   reason=reason, return_code=code, final=sample(),
                   finished_utc=datetime.now(timezone.utc).isoformat())
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    return 97 if reason else code


if __name__ == "__main__":
    raise SystemExit(main())
