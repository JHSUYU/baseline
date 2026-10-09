#!/usr/bin/env python3
"""Run one unchanged Hadoop 3.4.3 HA failover MiniDFSCluster JUnit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

CASE = Path(__file__).resolve().parents[1]
HERE = CASE / "system-test"
HADOOP = Path.home() / ".baseline-deps/hadoop-3.4.3"
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
TEST = "org.apache.hadoop.hdfs.server.namenode.ha.TestHAStateTransitions"


def classpath() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env,
        text=True).strip()
    tools = sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    extra = [
        CASE / "deps/mockito-core-4.9.0.jar",
        CASE / "deps/byte-buddy-1.12.16.jar",
        CASE / "deps/byte-buddy-agent-1.12.16.jar",
        CASE / "deps/objenesis-3.3.jar",
    ]
    for path in extra:
        if not path.is_file():
            raise FileNotFoundError(path)
    return os.pathsep.join((
        str(CASE / "source/test-resources"),
        str(CASE / "source/test"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(path) for path in extra), base,
        *(str(path) for path in tools),
    ))


def run(method: str, name: str, probe: bool = False,
        plan: Path | None = None, coverage: bool = False,
        timeout_seconds: int = 480) -> dict:
    out = CASE / name
    scratch = CASE / "temp" / name.replace("/", "-")
    if scratch.exists():
        shutil.rmtree(scratch)
    for path in (scratch / "data", scratch / "tmp", out / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    cp = classpath()
    classes = HERE / "ha-classes"
    classes.mkdir(parents=True, exist_ok=True)
    compiled = subprocess.run([
        str(JDK / "javac"), "-cp", cp, "-d", str(classes),
        str(HERE / "OriginalHdfs20HATest.java")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out / "logs/compile.log").write_text(compiled.stdout)
    if compiled.returncode:
        raise RuntimeError("JUnit wrapper compile failed")
    command = [str(JDK / "java"), "-ea", "-Xmx4g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp")]
    if probe:
        probe_classes = HERE / "probe-classes"
        if not probe_classes.is_dir():
            raise FileNotFoundError(probe_classes)
        trace = out / "trace/runtime_trace.jsonl"
        command.append("-Dhdfs20.independent.trace=" + str(trace))
        if plan:
            command.append("-Dhdfs20.independent.fault.plan=" + str(plan.resolve()))
    if coverage:
        agent = CASE / "deps/jacoco-agent-0.8.15.jar"
        if not agent.is_file():
            raise FileNotFoundError(agent)
        command.append("-javaagent:" + str(agent) + "=destfile=" +
                       str(out / "jacoco.exec") + ",append=false")
    runtime_cp = [str(classes)]
    if probe:
        runtime_cp.append(str(HERE / "probe-classes"))
    runtime_cp.append(cp)
    command.extend(["-cp", os.pathsep.join(runtime_cp),
                    "OriginalHdfs20HATest", method])
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    started = time.monotonic()
    with (out / "logs/runtime.log").open("w") as stream:
        try:
            proc = subprocess.run(command, cwd=scratch, env=env,
                                  stdout=stream, stderr=subprocess.STDOUT,
                                  timeout=timeout_seconds)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    result = {"test": TEST + "#" + method, "exit": exit_code,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "compile_exit": compiled.returncode,
              "timeout_seconds": timeout_seconds,
              "probe": probe, "coverage": coverage,
              "fault_plan": str(plan) if plan else None,
              "trace": str(out / "trace/runtime_trace.jsonl") if probe else None,
              "jacoco_exec": str(out / "jacoco.exec") if coverage else None,
              "runtime_log": str(out / "logs/runtime.log")}
    (out / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default="testManualFailoverAndFailback")
    parser.add_argument("--name", default="healthy/legacy")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=480)
    args = parser.parse_args()
    run(args.method, args.name, args.probe, args.plan, args.coverage,
        args.timeout_seconds)
