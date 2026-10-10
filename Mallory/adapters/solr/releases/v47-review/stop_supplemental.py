#!/usr/bin/env python3
"""Seal SOLR-31's noncanonical v47 run after its authorized stop bound.

This leaves every original campaign/trial result unchanged. A child JUnit that
has already started may finish after the controller stops; it is retained as
pending raw evidence and is not counted as a completed fault trial.
"""

import argparse
import fcntl
import hashlib
import json
import os
import signal
import time
from pathlib import Path

from verify_full import review_trial


LOCK = Path("/tmp/mallory-lanes/solr-lane4.lock")
KEEP = {"result.json", "config.json", "checkpoint.json", "plan.json",
        "junit-receipt.json", "sites.jsonl", "pilot-result.json", "junit.log",
        "stderr.log", "stdout.log", "events.jsonl.gz", "events.jsonl"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def active(pid: int) -> bool:
    stat = Path(f"/proc/{pid}/stat")
    return stat.is_file() and stat.read_text().split()[2] != "Z"


def lock_is_free() -> bool:
    with LOCK.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True


def live_campaign_java(root: Path) -> list[int]:
    marker = str(root / "trials").encode()
    live = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"java" in command.split(b"\0", 1)[0] and marker in command:
            live.append(int(entry.name))
    return live


def exact_repeat(root: Path, trial_id: int, result: dict) -> bool:
    row = next((r for r in result["trials"] if r["trial_id"] == trial_id), None)
    if row is None:
        return False
    trial = root / row["result"]
    keep = [trial, trial.parent / "events.jsonl.gz", trial.parent / "junit.log",
            trial.parent / "junit-receipt.json"]
    manifest = {str(p.relative_to(root)): sha(p) for p in keep}
    config = read_json(root / "config.json")
    bound = set(result["target_binding"]["nodes"])
    reviewed = review_trial(root, row, config, manifest, bound)
    return any((fault["state_witness"] or {}).get("selected_throw_seqs")
               for fault in reviewed["faults"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--controller-pid", type=int, required=True)
    parser.add_argument("--reason", choices=("effective_cap", "strict_repeat"), required=True)
    parser.add_argument("--witness-trial", type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = args.campaign.resolve()
    result = read_json(root / "result.json")
    checkpoint = read_json(root / "checkpoint.json")
    assert result["case_id"] == "SOLR-31" and result["status"] == "running"
    assert checkpoint["status"] == "running"
    assert not (root / "supplemental-stop.json").exists()
    effective = sum(bool(row.get("all_faults_effective")) for row in result["trials"][1:])
    if args.reason == "effective_cap":
        assert effective >= 7, effective  # One already-started trial may become the eighth.
    else:
        assert args.witness_trial is not None
        assert exact_repeat(root, args.witness_trial, result)
    cmdline = Path(f"/proc/{args.controller_pid}/cmdline").read_bytes().replace(b"\0", b" ")
    assert b"Mallory.core.campaign" in cmdline and str(root).encode() in cmdline
    print(json.dumps({"authorized_reason": args.reason, "effective_completed": effective,
                      "running_trial": (checkpoint.get("running") or {}).get("trial_id"),
                      "controller_pid": args.controller_pid, "execute": args.execute}))
    if not args.execute:
        return

    pending = checkpoint.get("running") or {}
    runner_pid = pending.get("pid")
    os.kill(args.controller_pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while active(args.controller_pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not active(args.controller_pid), "controller did not stop"
    if isinstance(runner_pid, int) and active(runner_pid):
        deadline = time.monotonic() + 510
        while active(runner_pid) and time.monotonic() < deadline:
            time.sleep(1)
    runner_exited = not isinstance(runner_pid, int) or not active(runner_pid)
    assert runner_exited, "in-flight JUnit still active; preserve lane and retry sealing later"
    assert not live_campaign_java(root), "campaign Java still active; preserve lane"
    deadline = time.monotonic() + 10
    while not lock_is_free() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert lock_is_free(), "lane4 flock still held"

    # The raw result can advance between the first read and SIGTERM. Seal its
    # final bytes only after controller and runner have both exited.
    result = read_json(root / "result.json")
    checkpoint = read_json(root / "checkpoint.json")
    assert result["status"] == "running" and checkpoint["status"] == "running"
    final_effective = sum(bool(row.get("all_faults_effective"))
                          for row in result["trials"][1:])
    assert final_effective <= 8, final_effective
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name not in KEEP or "scratch" in path.parts:
            continue
        rows.append({"path": str(path.relative_to(root)), "bytes": path.stat().st_size,
                     "sha256": sha(path)})
    manifest = {"schema_version": 1, "case_id": "SOLR-31",
                "terminal_status": "supplemental_stopped", "files": rows}
    manifest_path = root / "terminal-manifest.json"
    assert not manifest_path.exists()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    pending_dir = root / "trials" / f"r{pending['trial_id']:04d}" if pending else None
    sidecar = {"schema_version": 1, "case_id": "SOLR-31", "status": "supplemental_stopped",
               "reason": args.reason, "controller_pid": args.controller_pid,
               "controller_exited": True, "runner_pid": runner_pid, "runner_exited": True,
               "lane_released": True, "campaign_java_exited": True,
               "effective_completed": final_effective,
               "completed_fault_trials": result["fault_trials_completed"],
               "pending_trial_id": pending.get("trial_id"),
               "pending_pilot_result_present": bool(pending_dir and
                                                    (pending_dir / "pilot-result.json").is_file()),
               "result_sha256": sha(root / "result.json"),
               "checkpoint_sha256": sha(root / "checkpoint.json"),
               "terminal_manifest_sha256": sha(manifest_path),
               "canonical_completion_count_delta": 0,
               "raw_location": "node2; no campaign or trial result bytes modified"}
    stop_path = root / "supplemental-stop.json"
    stop_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"stop_receipt_sha256": sha(stop_path),
                      "terminal_manifest_sha256": sha(manifest_path),
                      "effective_completed": sidecar["effective_completed"],
                      "pending_trial_id": sidecar["pending_trial_id"]}))


if __name__ == "__main__":
    main()
