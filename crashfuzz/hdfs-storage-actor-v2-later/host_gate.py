#!/usr/bin/env python3
"""Fail closed before allocating a MiniDFSCluster calibration JVM.

The caller supplies the explicit slot handoff it received from the running
campaign owner. Run this immediately before each healthy seed, not once for
the entire group. The JSON receipt captures the observed resource state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

import run_original


MAX_RUNNING_JAVA_BEFORE_LAUNCH = 4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff", required=True,
                        help="Exact owner/session and UTC of explicit slot release")
    parser.add_argument("--expected-overlay-sha256", required=True)
    parser.add_argument("--min-free-gib", type=float, default=8.0)
    args = parser.parse_args()
    if not args.handoff.strip():
        parser.error("an explicit slot handoff is required")
    if args.min_free_gib < 8:
        parser.error("minimum free space cannot be less than 8 GiB")
    min_free_bytes = int(args.min_free_gib * 1024 ** 3)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    java_lines = subprocess.check_output(["jps", "-l"], text=True).splitlines()
    app_java = [line for line in java_lines if line.strip() and
                "sun.tools.jps.Jps" not in line]
    free_bytes = shutil.disk_usage(output).free
    digest = run_original.instrumentation_digest()
    dependencies = [run_original.HADOOP, run_original.TESTS,
                    run_original.RESOURCE, run_original.JACOCO,
                    run_original.JACOCO_CORE, *run_original.ASM_JARS,
                    run_original.JDK / "java"]
    missing = [str(path) for path in dependencies if not path.exists()]
    listeners = subprocess.check_output(["ss", "-ltnH"], text=True).splitlines()
    issues = []
    if len(app_java) > MAX_RUNNING_JAVA_BEFORE_LAUNCH:
        issues.append("more than four existing Java processes")
    if free_bytes < min_free_bytes:
        issues.append(f"less than {args.min_free_gib:g} GiB free on the output filesystem")
    if digest != args.expected_overlay_sha256:
        issues.append("overlay digest differs from staged image")
    if missing:
        issues.append("missing Hadoop/JDK/test dependencies")
    receipt = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "handoff": args.handoff,
        "output": str(output),
        "existing_java": app_java,
        "existing_java_count": len(app_java),
        "free_bytes": free_bytes,
        "required_free_bytes": min_free_bytes,
        "tcp_listeners_count": len(listeners),
        "overlay_sha256": digest,
        "expected_overlay_sha256": args.expected_overlay_sha256,
        "missing_dependencies": missing,
        "pass": not issues,
        "issues": issues,
    }
    path = output / "launch_gate.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    temp.replace(path)
    print(json.dumps({k: receipt[k] for k in
                      ("checked_at_utc", "existing_java_count", "free_bytes", "pass", "issues")}))
    if issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
