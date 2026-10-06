#!/usr/bin/env python3
"""Run one original Hadoop JUnit with optional exact outbound SASL fault."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "independent" / "run_original.py"
spec = importlib.util.spec_from_file_location("hdfs11_runner", BASE)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
BUILD = HERE / "build"
OVERLAY = BUILD / "overlay"
TEST_RESOURCES = (HERE.parents[2] / "hdfs32/worktrees/hadoop"
                  / "hadoop-hdfs-project/hadoop-hdfs/src/test/resources")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--test-class", required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--parameter", default="-")
    parser.add_argument("--plan", default="", help="writeBlock:N or replaceBlock:N")
    parser.add_argument("--mode", choices=("clean", "probe"), default="probe")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    for leaf in ("data", "tmp", "logs"):
        (scratch / leaf).mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    class_file = BUILD / "RunControlJUnit.class"
    source = HERE / "RunControlJUnit.java"
    if not class_file.is_file() or class_file.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(runner.JDK / "javac"), "-cp", str(runner.JUNIT),
                        "-d", str(BUILD), str(source)], check=True)
    if args.mode == "probe":
        subprocess.run(["python3", str(HERE / "prepare_overlay.py")], check=True,
                       stdout=subprocess.DEVNULL)
    env = dict(os.environ, JAVA_HOME=str(runner.JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(runner.HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    classpath = os.pathsep.join((
        *((str(OVERLAY),) if args.mode == "probe" else ()),
        str(BUILD), str(runner.TESTS), str(runner.COMMON_TESTS),
        str(TEST_RESOURCES), str(runner.SOURCE_RESOURCES), hadoop_cp,
        *(str(p) for p in (runner.MOCKITO, runner.BYTE_BUDDY,
                          runner.BYTE_BUDDY_AGENT, runner.OBJENESIS)),
        *(str(p) for p in sorted((runner.HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    command = [str(runner.JDK / "java"), "-ea", "-Xmx3g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs")]
    if args.mode == "probe":
        command.extend([
            "-Dhdfs11.trace=" + str(output / "key_trace.jsonl"),
            "-Dhdfs17967.trace=" + str(output / "outbound_trace.tsv"),
            "-Dhdfs17967.plan=" + args.plan,
            "-javaagent:" + str(runner.JACOCO) + "=destfile="
            + str(output / "jacoco.exec")
            + ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,"
              "dumponexit=true,append=false"])
    command.extend(["-cp", classpath, "RunControlJUnit", args.test_class,
                    args.method, args.parameter])
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        try:
            exit_code = subprocess.run(command, cwd=scratch, env=env,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       timeout=args.timeout, check=False).returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    result = {"test": args.test_class + "#" + args.method,
              "parameter": args.parameter, "mode": args.mode,
              "plan": args.plan, "returncode": exit_code,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "graphchecker_runtime": False,
              "original_distribution": str(runner.HADOOP)}
    temp = output / "manifest.json.tmp"
    temp.write_text(json.dumps(result, indent=2) + "\n")
    temp.replace(output / "manifest.json")
    print(json.dumps(result))
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
