#!/usr/bin/env python3
"""Run an unchanged ZooKeeper embedded-cluster JUnit with event recording.

The class files and recorder are copied to a case-local node2 workspace.  No
graph reconstruction or static scope computation occurs during this runner.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

BASE = Path("/users/ZhenyuLi/zk03-case")
SOURCE = Path("/users/ZhenyuLi/zk03-unit")
WOVEN = Path("/users/ZhenyuLi/zk03-woven")
TARGET_CLASSES = Path("/users/ZhenyuLi/zk03-target-classes")
RECORDER = Path("/users/ZhenyuLi/zk03-runtime.jar")
SKELETONS = Path("/users/ZhenyuLi/zk03-skeletons.jsonl.gz")
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
TEST_CLASS = "org.apache.zookeeper.test.QuorumTest"
DEFAULT_METHOD = "testSessionMoved"


def test_classpath() -> str:
    report = (SOURCE / "zookeeper-server/target/surefire-reports/"
              "TEST-org.apache.zookeeper.server.quorum.SessionUpgradeQuorumTest.xml")
    properties = ET.parse(report).getroot().findall("./properties/property")
    value = next(p.get("value", "") for p in properties
                 if p.get("name") == "java.class.path")
    value = value.replace("/users/ZhenyuLi/zk01-unit/source", str(SOURCE))
    missing = [entry for entry in value.split(os.pathsep)
               if entry and not Path(entry).exists()]
    if missing:
        raise RuntimeError("Missing classpath entries: " + repr(missing[:5]))
    return value


def run(name: str, method: str, fault_plan: Path | None, timeout: int) -> dict:
    output = BASE / "runs" / name
    if output.exists():
        raise FileExistsError(output)
    tmp = output / "tmp"
    test_data = output / "test-data"
    trace_dir = output / "trace"
    for path in (tmp, test_data, trace_dir):
        path.mkdir(parents=True, exist_ok=True)
    test = TEST_CLASS + "#" + method
    command = [JAVA, "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.net.preferIPv4Stack=true",
               "-Djava.io.tmpdir=" + str(tmp),
               "-Dbuild.test.dir=" + str(test_data),
               "-Dtest.junit.threads=10", "-Dzookeeper.junit.threadid=9",
               "-Dcausynth.cluster.automatic=true",
               "-Dcausynth.trace.mode=region-state",
               "-Dcausynth.trace.start.paused=true",
               "-Dcausynth.trace.test=" + test,
               "-Dcausynth.junit.record.test.body=true",
               "-Dcausynth.region.preserve.failure-target=true",
               "-Dcausynth.region.skeletons=" + str(SKELETONS)]
    if fault_plan:
        command.append("-Dcausynth.fault.trial=" + str(fault_plan.resolve()))
    command += ["-cp", os.pathsep.join((str(TARGET_CLASSES), str(WOVEN), str(RECORDER),
                                        test_classpath())),
                "edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner",
                TEST_CLASS, method]
    env = dict(os.environ, TMPDIR=str(tmp),
               CAUSYNTH_TRACE_OUTPUT_DIR=str(trace_dir))
    start = time.monotonic()
    with (output / "runtime.log").open("w") as stream:
        try:
            finished = subprocess.run(command, cwd=SOURCE / "zookeeper-server",
                                      env=env, stdout=stream,
                                      stderr=subprocess.STDOUT, timeout=timeout)
            exit_code = finished.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    result = {"test": test, "fault_plan": str(fault_plan) if fault_plan else None,
              "exit_code": exit_code,
              "elapsed_seconds": round(time.monotonic() - start, 3),
              "trace": str(trace_dir / "runtime_trace.jsonl"),
              "log": str(output / "runtime.log")}
    temp = output / "manifest.json.tmp"
    temp.write_text(json.dumps(result, indent=2) + "\n")
    temp.replace(output / "manifest.json")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--method", default=DEFAULT_METHOD)
    parser.add_argument("--fault-plan", type=Path)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    print(json.dumps(run(args.name, args.method, args.fault_plan,
                         args.timeout), indent=2))
