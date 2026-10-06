#!/usr/bin/env python3
"""Run the unchanged ZK01 embedded-cluster JUnit with runtime I/O feedback."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET


BASE = Path("/users/ZhenyuLi/zk01-unit")
SOURCE = BASE / "source"
WOVEN = BASE / "woven-client"
RECORDER = BASE / "graphchecker-client.jar"
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/java")
TEST_CLASS = "org.apache.zookeeper.server.quorum.SessionUpgradeQuorumTest"
TEST_METHOD = "testCloseSessionWhileUpgradeOnLeader"


def classpath() -> str:
    report = (SOURCE / "zookeeper-server/target/surefire-reports" /
              ("TEST-" + TEST_CLASS + ".xml"))
    root = ET.parse(report).getroot()
    value = next((item.get("value", "") for item in
                  root.findall("./properties/property")
                  if item.get("name") == "java.class.path"), "")
    missing = [part for part in value.split(os.pathsep)
               if part and not Path(part).exists()]
    if not value or missing:
        raise RuntimeError("JUnit classpath unavailable: " + repr(missing[:5]))
    return value


def run(output: Path, fault_plan: Path | None, timeout: int) -> dict:
    if output.exists():
        raise FileExistsError(output)
    trace = output / "trace"
    scratch = output / "scratch"
    for folder in (trace, scratch / "tmp", scratch / "test-data"):
        folder.mkdir(parents=True, exist_ok=True)
    test = TEST_CLASS + "#" + TEST_METHOD
    command = [str(JAVA), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dbuild.test.dir=" + str(scratch / "test-data"),
               "-Dtest.junit.threads=24", "-Dzookeeper.junit.threadid=9",
               "-Dcausynth.cluster.automatic=true",
               "-Dcausynth.trace.mode=discovery",
               "-Dcausynth.trace.start.paused=true",
               "-Dcausynth.trace.test=" + test,
               "-Dcausynth.junit.record.test.body=true"]
    if fault_plan is not None:
        command.append("-Dcausynth.fault.trial=" + str(fault_plan.resolve()))
    command.extend(["-cp", os.pathsep.join((str(WOVEN), str(RECORDER),
                                            classpath())),
                    "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
                    TEST_CLASS, TEST_METHOD])
    environment = {**os.environ, "TMPDIR": str(scratch / "tmp"),
                   "CAUSYNTH_LOCAL_SCRATCH": str(scratch / "tmp"),
                   "CAUSYNTH_TRACE_OUTPUT_DIR": str(trace)}
    started = time.monotonic()
    with (output / "junit.log").open("w") as stream:
        try:
            process = subprocess.run(command, cwd=SOURCE / "zookeeper-server",
                                     env=environment, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=timeout)
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = 124
    result = {"test": test, "fault_plan": str(fault_plan) if fault_plan else None,
              "junit_exit": code, "elapsed_seconds": round(time.monotonic()-started, 3),
              "trace": str(trace / "runtime_trace.jsonl")}
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fault-plan", type=Path)
    parser.add_argument("--timeout", type=int, default=75)
    args = parser.parse_args()
    outcome = run(args.output, args.fault_plan, args.timeout)
    print(json.dumps(outcome))
    raise SystemExit(outcome["junit_exit"])
