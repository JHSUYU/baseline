#!/usr/bin/env python3
"""Restore a build interrupted by ZK12's emergency disk stop, without JUnit."""

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from guard_zk12_full import BASE, FLOOR, EMERGENCY_HEADROOM, free_bytes, sha256


OVERLAY = BASE / "Mallory/adapters/zookeeper/zookeeper-3.8.7-overlay.json"
OVERLAY_SHA = "6d4bd8d50b2ba979ea37a43107a5b5be58b55532d6a2a862aa12550543577fc8"
RECEIPT = BASE / "data/mallory/admissions/ZOOKEEPER-12-fa5f-compiled-restore-v1.json"
LOG = BASE / "data/mallory/admissions/ZOOKEEPER-12-fa5f-compiled-restore-v1.log"
LOCK = Path("/tmp/mallory-lanes/zookeeper-lane2.lock")


def main() -> None:
    assert sha256(OVERLAY) == OVERLAY_SHA
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    source = Path(overlay["patched_root"])
    for relative, expected in overlay["modified_files"].items():
        assert sha256(source / relative) == expected, relative
    before = free_bytes(BASE)
    if before < FLOOR + 2 * 300 * 1024 ** 2:
        raise RuntimeError(f"disk too low before compile: {before}")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as lock, LOG.open("ab") as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        process = subprocess.Popen(
            ["mvn", "-pl", "zookeeper-server", "-am", "-DskipTests", "test-compile"],
            cwd=source, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        disk_stop = False
        while process.poll() is None:
            free = free_bytes(BASE)
            if free < FLOOR + EMERGENCY_HEADROOM:
                disk_stop = True
                os.killpg(process.pid, signal.SIGTERM)
                break
            time.sleep(5)
        status = process.wait()
    artifacts = []
    mismatches = []
    for item in overlay["compiled_artifacts"]:
        path = Path(item["path"])
        actual = sha256(path) if path.is_file() else None
        artifacts.append({"path": str(path), "expected_sha256": item["sha256"],
                          "actual_sha256": actual})
        if actual != item["sha256"]:
            mismatches.append(str(path))
    receipt = {
        "schema_version": 1, "case_id": "ZOOKEEPER-12",
        "status": "compiled_artifacts_restored" if status == 0 and not mismatches
                  else "compiled_artifact_restore_failed",
        "overlay_receipt_sha256": OVERLAY_SHA,
        "source_modified_file_count": len(overlay["modified_files"]),
        "command": "mvn -pl zookeeper-server -am -DskipTests test-compile",
        "junit_executed": False, "exit_code": status, "disk_emergency_stop": disk_stop,
        "started_free_bytes": before, "finished_free_bytes": free_bytes(BASE),
        "log_sha256": sha256(LOG), "artifacts": artifacts,
        "mismatches": mismatches,
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "receipt_sha256": sha256(RECEIPT),
                      "status": receipt["status"], "mismatch_count": len(mismatches),
                      "finished_free_bytes": receipt["finished_free_bytes"]}, sort_keys=True))
    if receipt["status"] != "compiled_artifacts_restored":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
