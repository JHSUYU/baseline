#!/usr/bin/env python3
"""One immutable original HDFS-16 MiniDFSCluster JUnit with actor-V2 overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from build_offline import BUILD, CASE, HADOOP, HERE, JDK, OVERLAY

TEST = ("org.apache.hadoop.hdfs.TestClientProtocolForPipelineRecovery"
        "#testUpdatePipeLineAfterDNReg")
FILES = {"probe": OVERLAY / "org/apache/hadoop/hdfs/hdfs16independent/Probe.class",
         "client": OVERLAY / "org/apache/hadoop/ipc/Client.class",
         "translator": OVERLAY / ("org/apache/hadoop/hdfs/protocolPB/"
                                  "DatanodeProtocolClientSideTranslatorPB.class"),
         "target": OVERLAY / ("org/apache/hadoop/hdfs/server/blockmanagement/"
                              "BlockInfo.class")}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classpath() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                   env=env, text=True).strip()
    tools = sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))
    dependencies = sorted((CASE / "deps").glob("*.jar"))
    return os.pathsep.join((str(BUILD / "runner-classes"), str(OVERLAY),
        str(CASE / "source/test-resources"), str(CASE / "source/test"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(path) for path in dependencies), base,
        *(str(path) for path in tools)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()
    if (not args.name or any(c not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in args.name) or args.timeout < 1):
        parser.error("unsafe run ID or timeout")
    if args.plan and not args.plan.is_file():
        parser.error("plan does not exist")
    if any(not path.is_file() for path in FILES.values()) or not \
            (BUILD / "runner-classes/OriginalHdfs16Test.class").is_file() or not \
            (BUILD / "runner-classes/CoverageDump.class").is_file():
        parser.error("V2 overlay/runner missing; run build_offline.py first")
    output = HERE / "evidence" / args.name
    scratch = BUILD / "scratch" / args.name
    if output.exists() or scratch.exists():
        parser.error("immutable run ID or scratch already exists")
    output.mkdir(parents=True)
    for path in (scratch / "data", scratch / "tmp", scratch / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    plan = args.plan.resolve() if args.plan else None
    trace = output / "runtime_trace.jsonl"
    jacoco = output / "jacoco.exec"
    agent = CASE / "deps/jacoco-agent-0.8.15.jar"
    command = [str(JDK / "java"), "-ea", "-Xmx4g",
        "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
        "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
        "-Dtest.build.data=" + str(scratch / "data"),
        "-Djava.io.tmpdir=" + str(scratch / "tmp"),
        "-Dhadoop.log.dir=" + str(scratch / "logs"),
        "-Dhdfs16.independent.trace=" + str(trace),
        "-javaagent:" + str(agent) + "=destfile=" + str(jacoco) +
        ",append=false,dumponexit=true"]
    if plan:
        command.append("-Dhdfs16.independent.fault.plan=" + str(plan))
    command += ["-cp", classpath(), "OriginalHdfs16Test",
                "testUpdatePipeLineAfterDNReg"]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        process = subprocess.Popen(command, cwd=scratch,
            env=dict(os.environ, JAVA_HOME=str(JDK.parent)),
            stdout=log, stderr=subprocess.STDOUT)
        (output / "jvm.pid").write_text(str(process.pid) + "\n")
        try:
            returncode = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            returncode = 124
    elapsed = round(time.monotonic() - started, 3)
    if jacoco.is_file() and jacoco.stat().st_size:
        subprocess.run([sys.executable, str(HERE / "coverage_v2.py"),
                        "--name", args.name], check=True)
    coverage_path = output / "coverage.tsv"
    manifest = {"case_id": "HDFS-16", "test": TEST, "returncode": returncode,
        "elapsed_seconds": elapsed, "plan": str(plan) if plan else None,
        "plan_sha256": sha(plan) if plan else None,
        "trace_sha256": sha(trace) if trace.is_file() else None,
        "jacoco_sha256": sha(jacoco) if jacoco.is_file() else None,
        "coverage_sha256": sha(coverage_path) if coverage_path.is_file() else None,
        "overlay_sha256": {key: sha(path) for key, path in FILES.items()}}
    temp = output / "manifest.json.tmp"
    temp.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temp, output / "manifest.json")
    shutil.rmtree(scratch)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
