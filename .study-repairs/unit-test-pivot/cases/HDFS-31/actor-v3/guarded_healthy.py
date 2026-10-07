#!/usr/bin/env python3
"""Run two original HDFS-31 JUnit calibrations under the shared JVM gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import audit_healthy
import guarded_campaign
import run_original


def append(path: Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=Path, default=run_original.HERE / "evidence")
    parser.add_argument("--expected-overlay-sha256", required=True)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--min-free-gib", type=float, default=10)
    parser.add_argument("--gate-retry-seconds", type=float, default=30)
    args = parser.parse_args()
    if args.timeout <= 0 or args.gate_retry_seconds <= 0 or args.min_free_gib <= 0:
        parser.error("timeout and resource bounds must be positive")
    anchor = args.anchor.resolve()
    anchor.mkdir(parents=True, exist_ok=True)
    run_original.build()
    if run_original.instrumentation_digest() != args.expected_overlay_sha256:
        raise RuntimeError("overlay differs from offline verified image")
    if not run_original.RESOURCE.is_dir():
        raise RuntimeError("original Hadoop test resources missing")
    ledger = anchor / "healthy-gate-ledger.jsonl"
    with (anchor / "healthy-controller.lock").open("a+") as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for seed in ("healthy-a", "healthy-b"):
            out = anchor / seed
            if (out / "manifest.json").is_file():
                inspected = audit_healthy.inspect(out)
                if inspected["issues"] or inspected["instrumentation_digest_sha256"] != args.expected_overlay_sha256:
                    raise RuntimeError(f"existing {seed} does not pass the actor gate: {inspected['issues']}")
                append(ledger, {"at_utc": now(), "seed": seed, "status": "existing_seed_verified",
                                "manifest": inspected["manifest"], "trace_sha256": inspected["trace_sha256"]})
                continue
            if out.exists() and any(out.iterdir()):
                raise RuntimeError(f"{seed} has partial output; reconcile its JVM and raw files before resuming")
            while True:
                with guarded_campaign.LOCK.open("a+") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    sample = guarded_campaign.gate(anchor, args.expected_overlay_sha256,
                                                   args.min_free_gib)
                    append(ledger, {"at_utc": now(), "seed": seed, "status": "gate",
                                    **sample})
                    if sample["ready"]:
                        manifest = run_original.run(run_id=seed, timeout=args.timeout, output=out)
                        inspected = audit_healthy.inspect(out)
                        append(ledger, {"at_utc": now(), "seed": seed, "status": "seed_complete",
                                        "returncode": manifest["returncode"],
                                        "elapsed_seconds": manifest["elapsed_seconds"],
                                        "manifest": inspected["manifest"],
                                        "trace_sha256": inspected["trace_sha256"],
                                        "actor_issues": inspected["issues"]})
                        if inspected["issues"]:
                            raise RuntimeError(f"{seed} failed the actor gate: {inspected['issues']}")
                        break
                time.sleep(args.gate_retry_seconds)
        audit = subprocess.run([sys.executable, str(run_original.HERE / "audit_healthy.py"),
                                str(anchor)], capture_output=True, text=True)
        append(ledger, {"at_utc": now(), "status": "two_seed_audit",
                        "returncode": audit.returncode, "stdout": audit.stdout.strip(),
                        "stderr": audit.stderr.strip()})
        print(audit.stdout.strip(), flush=True)
        if audit.returncode:
            raise RuntimeError("two-seed original JUnit actor calibration failed")


if __name__ == "__main__":
    main()
