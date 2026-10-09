#!/usr/bin/env python3
"""Journal completed ZK12 trials and stop an admitted run on critical disk pressure.

The campaign's own checkpoint and trial files remain authoritative. This guard
only writes an append-only resource journal and a terminal collection receipt.
An emergency stop leaves the current trial incomplete for the core's normal
resume path; it never edits the checkpoint or result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable


BASE = Path("/users/ZhenyuLi/baseline")
CONFIG = BASE / "Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-fa5f-filenotfound-full.json"
OUTPUT = BASE / "data/mallory/campaigns/ZOOKEEPER-12-fnf-v1"
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
RUNNER = BASE / "Mallory/adapters/zookeeper/run_lane2_campaign.sh"
FLOOR = 5 * 1024 ** 3
RESERVE = 2 * 300 * 1024 ** 2
EMERGENCY_HEADROOM = 150 * 1024 ** 2
PINS = {
    CONFIG: "7a559292dd1f3ddbf949417f1b633786046481fe098a7dad59d235fba933af55",
    CORE / "manifest.json": "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8",
    BASE / "Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-fa5f-filenotfound-healthy.sites.json":
        "42f97e952d68012889021149719ea7c50d50e2aaa8990e1290612204448acbb8",
    BASE / "data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-pilot.json":
        "037ca40b0e73d80227fe7e14a8a9650c732ca13832f004465942aadbfe5aedba",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def append(output: Path, record: dict) -> None:
    path = output / "resource-journal.jsonl"
    record = {"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **record}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def free_bytes(output: Path) -> int:
    stats = os.statvfs(output)
    return stats.f_bavail * stats.f_frsize


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def trial_record(output: Path, trial_id: int) -> dict | None:
    trial = output / "trials" / f"r{trial_id:04d}"
    result_path = trial / "result.json"
    result = read_json(result_path)
    if result is None:
        return None
    evidence = result.get("events_evidence") or {}
    name = evidence.get("gzip_path") or evidence.get("raw_path")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError(f"r{trial_id:04d}: invalid event evidence name")
    trace = trial / name
    if not trace.is_file():
        return None
    actual = sha256(trace)
    expected = evidence.get("gzip_sha256") or evidence.get("raw_sha256")
    if actual != expected:
        raise ValueError(f"r{trial_id:04d}: trace SHA mismatch")
    return {"event": "completed_trial", "trial_id": trial_id,
            "trial_result_sha256": sha256(result_path),
            "trace_file": name, "trace_sha256": actual,
            "trace_raw_sha256": evidence.get("raw_sha256"),
            "status": result.get("feedback", {}).get("status")}


def stop_for_disk(output: Path, runner_pid: int, checkpoint: dict | None,
                  free: int, threshold: int) -> None:
    child_pid = ((checkpoint or {}).get("running") or {}).get("pid")
    append(output, {"event": "emergency_disk_stop", "free_bytes": free,
                    "threshold_bytes": threshold, "runner_pid": runner_pid,
                    "trial_process_group": child_pid,
                    "checkpoint_sha256": sha256(output / "checkpoint.json")
                    if (output / "checkpoint.json").is_file() else None})
    # run_zk12... starts the lane runner with setsid. Never signal a group
    # unless the supplied PID is its leader. The JUnit process has its own
    # session, recorded atomically in the campaign checkpoint.
    if os.getpgid(runner_pid) != runner_pid:
        raise RuntimeError("runner is not a separate process-group leader")
    os.killpg(runner_pid, signal.SIGTERM)
    if isinstance(child_pid, int) and child_pid > 0:
        try:
            if os.getpgid(child_pid) == child_pid:
                os.killpg(child_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def monitor(output: Path, runner_pid: int, floor: int, threshold: int,
            interval: int, runner_running: Callable[[], bool] | None = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    append(output, {"event": "monitor_start", "runner_pid": runner_pid,
                    "free_bytes": free_bytes(output), "floor_bytes": floor,
                    "emergency_threshold_bytes": threshold})
    seen: set[int] = set()
    last_sample = 0.0
    running = runner_running or (lambda: alive(runner_pid))
    while running():
        checkpoint = read_json(output / "checkpoint.json")
        if checkpoint:
            for trial_id in checkpoint.get("completed_trials", []):
                if trial_id in seen:
                    continue
                record = trial_record(output, trial_id)
                if record:
                    append(output, record)
                    seen.add(trial_id)
        now = time.monotonic()
        free = free_bytes(output)
        if now - last_sample >= 30:
            append(output, {"event": "disk_sample", "free_bytes": free,
                            "completed_trials": len(seen),
                            "running_trial": (checkpoint or {}).get("running")})
            last_sample = now
        if free < threshold:
            stop_for_disk(output, runner_pid, checkpoint, free, threshold)
            break
        time.sleep(interval)
    checkpoint = read_json(output / "checkpoint.json")
    if checkpoint:
        for trial_id in checkpoint.get("completed_trials", []):
            if trial_id not in seen:
                record = trial_record(output, trial_id)
                if record:
                    append(output, record)
    append(output, {"event": "monitor_exit", "free_bytes": free_bytes(output),
                    "runner_alive": alive(runner_pid)})


def collect(output: Path, config: Path, launcher: Path) -> None:
    files = {"config": config, "launcher": launcher,
             "journal": output / "resource-journal.jsonl",
             "checkpoint": output / "checkpoint.json",
             "result": output / "result.json",
             "driver_exit": output / "driver-exit.json",
             "offline_audit": output / "offline-causal-audit.json"}
    receipt = {"schema_version": 1, "case_id": "ZOOKEEPER-12",
               "output": str(output.resolve()),
               "collected_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "free_bytes": free_bytes(output),
               "files": {name: {"path": str(path.resolve()), "sha256": sha256(path),
                                "bytes": path.stat().st_size}
                         for name, path in files.items() if path.is_file()}}
    result = read_json(output / "result.json")
    receipt["campaign_status"] = result.get("status") if result else None
    receipt["fault_trials_completed"] = (result.get("fault_trials_completed")
                                           if result else None)
    path = output / "collection-receipt.json"
    if path.exists():
        previous = path.with_name(f"collection-receipt.previous-{time.time_ns()}.json")
        path.rename(previous)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def launch() -> int:
    for path, expected in PINS.items():
        if sha256(path) != expected:
            raise ValueError(f"pinned input changed: {path}")
    subprocess.run(["python3", str(BASE / "Mallory/adapters/zookeeper/verify_lane2_campaign.py"),
                    str(CONFIG)], check=True, cwd=BASE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    free = free_bytes(OUTPUT)
    if free < FLOOR + RESERVE:
        raise RuntimeError(f"disk admission: {free} < {FLOOR + RESERVE} bytes")
    append(OUTPUT, {"event": "admission", "free_bytes": free,
                    "required_free_bytes": FLOOR + RESERVE,
                    "config_sha256": PINS[CONFIG],
                    "launcher_sha256": sha256(Path(__file__)),
                    "core_manifest_sha256": PINS[CORE / "manifest.json"]})
    with (OUTPUT / "launcher.log").open("ab") as stream:
        process = subprocess.Popen(["bash", str(RUNNER), str(CONFIG), str(OUTPUT), str(CORE)],
                                   cwd=BASE, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            monitor(OUTPUT, process.pid, FLOOR, FLOOR + EMERGENCY_HEADROOM, 5,
                    runner_running=lambda: process.poll() is None)
        except Exception as exc:
            checkpoint = read_json(OUTPUT / "checkpoint.json")
            append(OUTPUT, {"event": "monitor_failure", "error": repr(exc)})
            if process.poll() is None:
                stop_for_disk(OUTPUT, process.pid, checkpoint, free_bytes(OUTPUT),
                              FLOOR + EMERGENCY_HEADROOM)
            raise
        finally:
            process.wait()
    result = read_json(OUTPUT / "result.json")
    if result and result.get("status") in {"budget_exhausted", "queue_exhausted",
                                           "healthy_seed_invalid", "healthy_node_identity_missing",
                                           "healthy_seed_ambiguous", "healthy_no_injectable_door",
                                           "healthy_attestation_failed", "fault_trials_not_attested"}:
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{CORE}:{BASE}"
        audit = subprocess.run(["python3", "-m", "Mallory.core.audit", "--campaign",
                                str(OUTPUT), "--out", str(OUTPUT / "offline-causal-audit.json")],
                               cwd=CORE, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
        (OUTPUT / "offline-audit.log").write_text(audit.stdout, encoding="utf-8")
        append(OUTPUT, {"event": "offline_audit", "exit_code": audit.returncode,
                        "audit_sha256": sha256(OUTPUT / "offline-causal-audit.json")
                        if (OUTPUT / "offline-causal-audit.json").is_file() else None})
    append(OUTPUT, {"event": "collection_start", "runner_exit_code": process.returncode})
    collect(OUTPUT, CONFIG, Path(__file__))
    print(json.dumps({"collection_receipt_sha256":
                      sha256(OUTPUT / "collection-receipt.json"),
                      "runner_exit_code": process.returncode}, sort_keys=True), flush=True)
    return process.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("launch")
    watch = sub.add_parser("monitor")
    watch.add_argument("--output", type=Path, required=True)
    watch.add_argument("--runner-pid", type=int, required=True)
    watch.add_argument("--floor-bytes", type=int, required=True)
    watch.add_argument("--threshold-bytes", type=int, required=True)
    watch.add_argument("--interval-seconds", type=int, default=5)
    finish = sub.add_parser("collect")
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument("--config", type=Path, required=True)
    finish.add_argument("--launcher", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "launch":
        raise SystemExit(launch())
    if args.mode == "monitor":
        monitor(args.output.resolve(), args.runner_pid, args.floor_bytes,
                args.threshold_bytes, args.interval_seconds)
    else:
        collect(args.output.resolve(), args.config.resolve(), args.launcher.resolve())
