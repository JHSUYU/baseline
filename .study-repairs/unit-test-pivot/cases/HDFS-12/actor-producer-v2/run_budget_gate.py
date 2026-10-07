#!/usr/bin/env python3
"""Run one original HDFS-12 JUnit trial per durable resource-gate boundary.

This case-local supervisor leaves campaign.py and its sequence scheduler unchanged.
It can be restarted from the same checkpoint after a tmux/session disconnect.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
GIB = 1024 ** 3


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temp, path)


def append_jsonl(path: Path, value: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def available_gib(path: Path) -> float:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize / GIB


def available_mem_gib() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024 / GIB
    raise RuntimeError("MemAvailable missing from /proc/meminfo")


def java_process_count() -> int:
    output = subprocess.check_output(["jps", "-l"], text=True)
    return sum(1 for line in output.splitlines()
               if line.split() and not line.endswith("sun.tools.jps.Jps"))


def fault_induced_target_loss(manifest: dict, result: dict, junit_log: str,
                              trace: list[dict]) -> bool:
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    count = result["applied_faults"]
    ordered_prefix = (
        len(matched) == len(applied) == count and
        [row.get("planIndex") for row in matched] == list(range(count)) and
        [row.get("planIndex") for row in applied] == list(range(count)) and
        all(m["seq"] < a["seq"] for m, a in zip(matched, applied)) and
        all(applied[i]["seq"] < matched[i + 1]["seq"]
            for i in range(count - 1)))
    later_target = bool(applied) and any(
        row.get("event") == "TARGET_CHECK" and row.get("caseId") == "HDFS-12" and
        row["seq"] > applied[-1]["seq"] for row in trace)
    return (manifest["returncode"] != 0 and
            result["classification"] == "unmatched_or_target_lost" and
            0 < count == result["matched_faults"] <= result["requested_faults"] and
            ordered_prefix and not later_target and
            result["postfault_target_count"] == 0 and
            "V2 injected I/O" in junit_log and
            "Fail to get block MD5" in junit_log and
            not any(error in junit_log for error in
                    ("BindException", "Address already in use", "OutOfMemoryError")))


def stop_reason(state: dict, output: Path, args: argparse.Namespace) -> str | None:
    if (output / "pause-request.txt").exists():
        return "external_pause_requested"
    if state.get("status") == "candidate_paused_for_replay":
        return "target_exception_candidate"
    if not state.get("queue"):
        return "queue_exhausted"
    if state["attempted_trials"] >= args.max_attempts:
        return "attempt_cap_reached"
    if state["effective_trials"] >= state["max_effective"]:
        if not (state["max_effective"] == 80 and
                any(state.get("recent_gain", [])[-8:])):
            return "effective_budget_reached"
    if available_gib(output) < args.min_disk_gib:
        return "low_disk"
    if available_mem_gib() < args.min_mem_gib:
        return "low_memory"
    if java_process_count() >= args.max_total_java:
        return "java_process_limit"
    return None


def run(output: Path, args: argparse.Namespace) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    state_file = output / "campaign-state.json"
    if not state_file.exists():
        raise RuntimeError("expected existing HDFS-12 pilot checkpoint")
    ledger = output / "budget-gate-ledger.jsonl"
    status_file = output / "budget-gate-status.json"
    with (output / "budget-gate.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            before = read_json(state_file)
            reason = stop_reason(before, output, args)
            if reason:
                status = {"at_utc": utc(), "reason": reason,
                          "attempted_trials": before["attempted_trials"],
                          "effective_trials": before["effective_trials"],
                          "in_flight": before.get("in_flight"),
                          "queue_length": len(before["queue"])}
                atomic_json(status_file, status)
                print(json.dumps(status, sort_keys=True), flush=True)
                return status
            next_cap = before["attempted_trials"] + 1
            started = utc()
            completed_before = set(before["completed"])
            command = [sys.executable, str(HERE / "campaign.py"), "--case", "HDFS-12",
                       "--output", str(output), "--max-attempts", str(next_cap),
                       "--pause-on-candidate"]
            process = subprocess.run(command, cwd=HERE, check=False)
            after = read_json(state_file)
            new_ids = sorted(set(after["completed"]) - completed_before)
            entry = {"started_at_utc": started, "finished_at_utc": utc(),
                     "campaign_exit": process.returncode, "new_ids": new_ids,
                     "attempted_before": before["attempted_trials"],
                     "attempted_after": after["attempted_trials"],
                     "effective_after": after["effective_trials"],
                     "in_flight_after": after.get("in_flight"),
                     "campaign_status": after.get("status"),
                     "disk_available_gib": round(available_gib(output), 2),
                     "memory_available_gib": round(available_mem_gib(), 2)}
            if len(new_ids) == 1:
                run_dir = output / "runs" / new_ids[0]
                manifest = read_json(run_dir / "manifest.json")
                result = read_json(run_dir / "v2_result.json")
                junit_log = (run_dir / "junit.log").read_text(errors="replace")
                trace = [json.loads(line) for line in
                         (run_dir / "runtime_trace.jsonl").read_text().splitlines()]
                entry.update({"junit_exit": manifest["returncode"],
                              "junit_elapsed_seconds": manifest["elapsed_seconds"],
                              "peak_junit_rss_kib": manifest["peak_junit_rss_kib"],
                              "fault_depth": result["requested_faults"],
                              "matched_faults": result["matched_faults"],
                              "applied_faults": result["applied_faults"],
                              "postfault_target_count": result["postfault_target_count"],
                              "postfault_target_exception_count": result["postfault_target_exception_count"],
                              "classification": result["classification"],
                              "fault_induced_target_loss": fault_induced_target_loss(
                                  manifest, result, junit_log, trace),
                              "new_coverage": result["new_coverage"],
                              "new_io_families": result["new_io_families"]})
            append_jsonl(ledger, entry)
            print(json.dumps(entry, sort_keys=True), flush=True)
            if process.returncode:
                reason = "campaign_error"
            elif len(new_ids) != 1 or after["attempted_trials"] != next_cap:
                reason = "unexpected_checkpoint_transition"
            elif entry["junit_elapsed_seconds"] > args.max_junit_seconds:
                reason = "junit_more_than_twice_healthy_time"
            elif entry["peak_junit_rss_kib"] > args.max_junit_rss_kib:
                reason = "junit_rss_more_than_twice_healthy"
            elif (entry["junit_exit"] != 0 and
                  not result["target_exception_candidate"] and
                  not entry["fault_induced_target_loss"]):
                reason = "unexpected_junit_failure"
            else:
                reason = None
            if reason:
                status = {"at_utc": utc(), "reason": reason,
                          "attempted_trials": after["attempted_trials"],
                          "effective_trials": after["effective_trials"],
                          "in_flight": after.get("in_flight"),
                          "queue_length": len(after["queue"])}
                atomic_json(status_file, status)
                print(json.dumps(status, sort_keys=True), flush=True)
                return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=600)
    parser.add_argument("--max-total-java", type=int, default=5)
    parser.add_argument("--min-disk-gib", type=float, default=8.0)
    parser.add_argument("--min-mem-gib", type=float, default=8.0)
    parser.add_argument("--max-junit-seconds", type=float, default=64.0)
    parser.add_argument("--max-junit-rss-kib", type=int, default=2200000)
    args = parser.parse_args()
    print(json.dumps(run(args.output, args), sort_keys=True))


if __name__ == "__main__":
    main()
