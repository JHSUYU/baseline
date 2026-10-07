#!/usr/bin/env python3
"""Launch one original HDFS-16 healthy JUnit under the shared node1 gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from run_original import CASE, HERE

LOCK = Path("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/jvm-start.lock")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def java_count() -> int:
    output = subprocess.check_output(["jps", "-l"], text=True)
    return sum(bool(line.strip()) and not line.endswith("sun.tools.jps.Jps")
               for line in output.splitlines())


def disk_gib() -> float:
    stats = os.statvfs(CASE)
    return stats.f_bavail * stats.f_frsize / 1024 ** 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, choices=("healthy/a", "healthy/b"))
    args = parser.parse_args()
    out = CASE / args.name
    if (out / "manifest.json").exists():
        raise RuntimeError("healthy seed already exists; never repeat it")
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        count, free = java_count(), disk_gib()
        gate = {"case": "HDFS-16", "seed": args.name, "at_utc": utc(),
                "java_before_launch": count, "free_disk_gib": round(free, 3),
                "java_limit_before_launch": 4, "min_free_disk_gib": 10.0,
                "shared_lock": str(LOCK)}
        out.mkdir(parents=True, exist_ok=True)
        (out / "launch-gate.json").write_text(json.dumps(gate, indent=2) + "\n")
        if count > 4 or free < 10.0:
            raise RuntimeError("resource gate rejected healthy seed: " + json.dumps(gate))
        command = [sys.executable, str(HERE / "run_original.py"),
                   "--name", args.name, "--probe", "--coverage",
                   "--timeout-seconds", "480"]
        with (out / "seed-runner.log").open("w") as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        gate["finished_at_utc"] = utc()
        gate["runner_exit"] = result.returncode
        (out / "launch-gate.json").write_text(json.dumps(gate, indent=2) + "\n")
        if result.returncode:
            raise SystemExit(result.returncode)
        subprocess.run([sys.executable, str(HERE / "run_coverage.py"),
                        "--exec", str(out / "jacoco.exec"),
                        "--output", str(out / "coverage.tsv")],
                       stdout=(out / "coverage-runner.log").open("w"),
                       stderr=subprocess.STDOUT, check=True)
    print(json.dumps(gate, sort_keys=True))


if __name__ == "__main__":
    main()
