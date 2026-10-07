#!/usr/bin/env python3
"""Run one completed HDFS storage V2 plan under the shared JVM launch lock."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import subprocess
import sys

import campaign


LOCK = Path("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/jvm-start.lock")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=campaign.GROUPS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--min-free-gib", type=float, default=10)
    parser.add_argument("--expected-overlay-sha256", required=True)
    args = parser.parse_args()
    anchor = args.output.resolve()
    anchor.mkdir(parents=True, exist_ok=True)
    state_path = anchor / "campaign-state.json"
    before = json.loads(state_path.read_text())
    old_count = len(before["completion_order"])
    if before["in_flight"] is not None:
        raise RuntimeError("existing in-flight plan needs reconciliation")
    if args.expected_overlay_sha256 != before["instrumentation_digest_sha256"]:
        raise RuntimeError("overlay differs from checkpoint")
    receipt_path = anchor / f"locked-plan-{old_count + 1:04d}.json"
    if receipt_path.exists():
        raise RuntimeError("one-plan receipt already exists")
    receipt = {"schema": "hdfs-storage-v2-locked-one-plan-1",
               "group": args.group, "old_completed": old_count,
               "started_at_utc": stamp(), "handoff": args.handoff,
               "lock": str(LOCK), "expected_overlay_sha256": args.expected_overlay_sha256}
    with LOCK.open("a+") as lock:
        # Another JUnit may be starting at this boundary. Wait for the shared
        # lock, then recheck Java/disk under it; do not drop a queued plan.
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt["lock_acquired_at_utc"] = stamp()
        gate_dir = anchor / "gates" / f"locked-plan-{old_count + 1:04d}"
        gate = subprocess.run([sys.executable, str(campaign.HERE / "host_gate.py"),
                               "--output", str(gate_dir), "--handoff", args.handoff,
                               "--expected-overlay-sha256", args.expected_overlay_sha256,
                               "--min-free-gib", str(args.min_free_gib)],
                              capture_output=True, text=True)
        receipt.update({"gate": str(gate_dir / "launch_gate.json"),
                        "gate_returncode": gate.returncode,
                        "gate_stdout": gate.stdout, "gate_stderr": gate.stderr})
        if gate.returncode:
            receipt["status"] = "resource_gate_pause"
        else:
            log_path = anchor / f"locked-plan-{old_count + 1:04d}.log"
            with log_path.open("w") as log:
                result = subprocess.run([sys.executable, str(campaign.HERE / "campaign.py"),
                                         "--group", args.group, "--output", str(anchor),
                                         "--max-attempts", "600", "--timeout", str(args.timeout),
                                         "--max-new-completions", "1"],
                                        stdout=log, stderr=subprocess.STDOUT)
            after = json.loads(state_path.read_text())
            receipt.update({"campaign_returncode": result.returncode,
                            "campaign_log": str(log_path),
                            "new_completed": len(after["completion_order"]),
                            "new_in_flight": after["in_flight"],
                            "effective_by_case": after["effective_by_case"]})
            receipt["status"] = ("complete_plan" if result.returncode == 0 and
                                 len(after["completion_order"]) == old_count + 1 and
                                 after["in_flight"] is None else "campaign_error_pause")
    receipt["finished_at_utc"] = stamp()
    campaign.write_json(receipt_path, receipt)
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "complete_plan":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
