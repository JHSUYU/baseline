#!/usr/bin/env python3
"""Run two separate released-JUnit healthy calibrations at HA trial boundaries."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
HA = HERE.parent
START_LOCK = HA.parents[2] / "jvm-start.lock"
RUNNER = HA / "run_original.py"
METHOD = "testLeaseRecoveryAfterFailover"
TEST = "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#" + METHOD
MIN_FREE = 10 * 1024**3
MAX_JAVA = 4


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, data: dict) -> None:
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    pending.replace(path)


def java_count() -> int:
    result = subprocess.run(["pgrep", "-c", "java"], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return int(result.stdout.strip() or "0")


def ha_java_running() -> bool:
    needle = str(HA / "runs" / "trial-").encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if b"/java\0" in cmdline and needle in cmdline:
            return True
    return False


def complete(directory: Path) -> bool:
    manifest = directory / "manifest.json"
    if not manifest.is_file():
        return False
    data = json.loads(manifest.read_text())
    if (data.get("test") != TEST or data.get("returncode") != 0
            or data.get("instrumented") is not True
            or data.get("graphchecker_runtime_used") is not False):
        raise RuntimeError("healthy calibration did not pass: " + str(directory))
    for name in ("runtime_trace.jsonl", "jacoco.exec", "covered_probes.txt",
                 "covered_methods.txt", "covered_branch_counts.txt", "junit.log"):
        if not (directory / name).is_file():
            raise RuntimeError("missing calibration raw " + name + ": " + str(directory))
    return True


def run_one(label: str) -> None:
    directory = HERE / label
    if complete(directory):
        print(label + " already complete; reuse", flush=True)
        return
    if directory.exists() and any(directory.iterdir()):
        raise RuntimeError("partial healthy run requires manual review: " + str(directory))
    directory.mkdir(parents=True, exist_ok=True)
    while True:
        with START_LOCK.open("a+") as gate:
            fcntl.flock(gate, fcntl.LOCK_EX)
            # The HA JVM may have released the start lock while executing its
            # current trial. Wait for that JVM to finish, keeping the next HA
            # start behind this bounded calibration.
            deadline = time.monotonic() + 180
            while ha_java_running() and time.monotonic() < deadline:
                time.sleep(1)
            if (ha_java_running() or java_count() > MAX_JAVA
                    or shutil.disk_usage(HERE).free < MIN_FREE):
                print(label + " waiting for Java/disk gate", flush=True)
            else:
                command = [sys.executable, str(RUNNER), "--instrument",
                           "--test-method", METHOD, "--output", str(directory),
                           "--timeout", "180"]
                with (directory / "driver.log").open("w") as log:
                    code = subprocess.run(command, cwd=HA, stdout=log,
                                          stderr=subprocess.STDOUT).returncode
                if code != 0 or not complete(directory):
                    raise RuntimeError(label + " original JUnit failed; inspect raw")
                print(label + " complete", flush=True)
                return
        time.sleep(20)


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    for label in ("healthy-a", "healthy-b"):
        run_one(label)
    runs = {}
    for label in ("healthy-a", "healthy-b"):
        directory = HERE / label
        manifest = json.loads((directory / "manifest.json").read_text())
        runs[label] = {
            "junit_exit": manifest["returncode"],
            "seconds": manifest["elapsed_seconds"],
            "manifest_sha256": sha(directory / "manifest.json"),
            "trace_sha256": sha(directory / "runtime_trace.jsonl"),
            "jacoco_sha256": sha(directory / "jacoco.exec"),
            "junit_log_sha256": sha(directory / "junit.log"),
            "original_test_class_sha256": manifest["original_test_class_sha256"],
            "original_tests_jar_sha256": manifest["original_tests_jar_sha256"],
        }
    atomic_json(HERE / "healthy-receipt.json", {
        "schema": 1, "test": TEST, "independent_from_ha_campaign": True,
        "shared_start_lock": str(START_LOCK), "min_free_gib": 10,
        "max_java_before_start": MAX_JAVA, "runner_sha256": sha(RUNNER),
        "runs": runs,
    })
    print("two healthy receipts complete", flush=True)


if __name__ == "__main__":
    main()
