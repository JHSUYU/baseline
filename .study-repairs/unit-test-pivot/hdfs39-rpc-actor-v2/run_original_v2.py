#!/usr/bin/env python3
"""One isolated original HDFS-39 embedded-cluster JUnit with the V2 overlay.

This file only starts a JVM when invoked. The offline build does not call it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from build_offline import CASE, HADOOP, HERE, JDK, OVERLAY

TEST = "org.apache.hadoop.hdfs.TestFileAppend#testMultipleAppends"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classpath() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    extras = [CASE / "deps" / name for name in (
        "mockito-core-4.9.0.jar", "byte-buddy-1.12.16.jar",
        "byte-buddy-agent-1.12.16.jar", "objenesis-3.3.jar")]
    return os.pathsep.join((str(OVERLAY), str(CASE / "source/test-resources"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(path) for path in extras), base,
        *(str(path) for path in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True,
                        help="new case-local run ID, e.g. healthy-a or trial-0001")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    if (not args.name or args.name in (".", "..") or
            any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for char in args.name)):
        parser.error("--name must be a single safe new run ID")
    if args.timeout_seconds < 1:
        parser.error("timeout must be positive")
    if args.plan and not args.plan.is_file():
        parser.error("fault plan missing")
    wrapper = OVERLAY / "OriginalHdfs39Test.class"
    target = OVERLAY / "org/apache/hadoop/hdfs/TestFileAppend.class"
    if not wrapper.is_file() or not target.is_file():
        parser.error("run build_offline.py before any JUnit")
    output = HERE / "evidence" / args.name
    scratch = HERE / "build" / "scratch" / args.name
    if output.exists() or scratch.exists():
        parser.error("run ID already exists; never overwrite a completed or interrupted run")
    for directory in (output / "logs", output / "trace", scratch / "data", scratch / "tmp"):
        directory.mkdir(parents=True, exist_ok=False)
    plan = args.plan.resolve() if args.plan else None
    command = [str(JDK / "java"), "-ea", "-Xmx4g",
        "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
        "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
        "-Dtest.build.data=" + str(scratch / "data"),
        "-Djava.io.tmpdir=" + str(scratch / "tmp"),
        "-Dhdfs39.independent.trace=" + str(output / "trace/runtime_trace.jsonl")]
    if plan:
        command.append("-Dhdfs39.independent.fault.plan=" + str(plan))
    agent = CASE / "deps/jacoco-agent-0.8.15.jar"
    command.append("-javaagent:" + str(agent) + "=destfile=" +
                   str(output / "jacoco.exec") + ",append=false")
    command.extend(["-cp", classpath(), "OriginalHdfs39Test", "testMultipleAppends"])
    started = time.monotonic()
    with (output / "logs/runtime.log").open("w") as log:
        try:
            result = subprocess.run(command, cwd=scratch, stdout=log,
                                    stderr=subprocess.STDOUT,
                                    timeout=args.timeout_seconds)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    manifest = {
        "test": TEST, "exit": exit_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "timeout_seconds": args.timeout_seconds,
        "plan": str(plan) if plan else None,
        "plan_sha256": sha(plan) if plan else None,
        "overlay_test_sha256": sha(target),
        "trace": str(output / "trace/runtime_trace.jsonl"),
        "trace_sha256": sha(output / "trace/runtime_trace.jsonl") if
            (output / "trace/runtime_trace.jsonl").is_file() else None,
        "jacoco_exec": str(output / "jacoco.exec"),
        "jacoco_sha256": sha(output / "jacoco.exec") if
            (output / "jacoco.exec").is_file() else None,
        "runtime_log": str(output / "logs/runtime.log")}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
