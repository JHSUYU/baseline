#!/usr/bin/env python3
"""Run the released TestFileTruncate JUnit with case-local actor probes."""

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
JACOCO = (Path.home() / ".m2/repository/org/jacoco/org.jacoco.agent/0.8.15/"
          "org.jacoco.agent-0.8.15-runtime.jar")
TEST = "org.apache.hadoop.hdfs.server.namenode.TestFileTruncate"


def classpath() -> str:
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env,
        text=True).strip()
    m2 = Path.home() / ".m2/repository"
    extra = [
        m2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
        m2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
        m2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
        m2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar",
    ]
    for path in extra:
        if not path.is_file():
            raise FileNotFoundError(path)
    return os.pathsep.join((
        str(CASE / "source/test-resources"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        *(str(path) for path in extra), base,
        *(str(path) for path in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar"))),
    ))


def run(method: str, name: str, plan: Path | None = None,
        timeout_seconds: int = 240) -> dict:
    if method not in ("testTruncateTwiceTogether", "testMultipleTruncate"):
        raise ValueError("Only the two reviewed original JUnit methods are allowed")
    out = CASE / name
    if out.exists() and (out / "manifest.json").is_file():
        raise FileExistsError(f"completed JUnit already exists: {out}")
    scratch = CASE / "temp" / name.replace("/", "-")
    if scratch.exists():
        shutil.rmtree(scratch)
    for path in (scratch / "data", scratch / "tmp", out / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    probe_classes = HERE / "probe-classes"
    if not probe_classes.is_dir():
        raise FileNotFoundError(probe_classes)
    classes = HERE / "classes"
    classes.mkdir(exist_ok=True)
    cp = classpath()
    compiled = subprocess.run([
        str(JDK / "javac"), "-cp", cp, "-d", str(classes),
        str(HERE / "RunJUnitMethod.java")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out / "logs/compile.log").write_text(compiled.stdout)
    if compiled.returncode:
        raise RuntimeError("Original JUnit wrapper compile failed")
    command = [str(JDK / "java"), "-ea", "-Xmx4g",
               "-Djava.awt.headless=true", "-Djava.net.preferIPv4Stack=true",
               "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
               "-Dtest.cache.data=" + str(CASE / "source/test-resources"),
               "-Dtest.build.data=" + str(scratch / "data"),
               "-Djava.io.tmpdir=" + str(scratch / "tmp"),
               "-Dhadoop.log.dir=" + str(scratch / "logs"),
               "-Dhdfs43.actor.trace=" + str(out / "trace/runtime_trace.jsonl"),
               "-javaagent:" + str(JACOCO) + "=destfile=" +
               str(out / "jacoco.exec") + ",append=false,"
               "includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*"]
    if plan:
        command.append("-Dhdfs43.actor.plan=" + str(plan.resolve()))
    command.extend(["-cp", os.pathsep.join((str(classes), str(probe_classes), cp)),
                    "RunJUnitMethod", TEST, method])
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    started = time.monotonic()
    with (out / "logs/runtime.log").open("w") as stream:
        try:
            proc = subprocess.run(command, cwd=scratch, env=env, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=timeout_seconds)
            status = proc.returncode
        except subprocess.TimeoutExpired:
            status = 124
    manifest = {"test": TEST + "#" + method, "exit": status,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "compile_exit": compiled.returncode, "timeout_seconds": timeout_seconds,
                "probe": True, "coverage": True,
                "fault_plan": str(plan.resolve()) if plan else None,
                "trace": str(out / "trace/runtime_trace.jsonl"),
                "jacoco_exec": str(out / "jacoco.exec"),
                "runtime_log": str(out / "logs/runtime.log")}
    temporary = out / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(out / "manifest.json")
    print(json.dumps(manifest), flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default="testTruncateTwiceTogether")
    parser.add_argument("--name", required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    run(args.method, args.name, args.plan, args.timeout_seconds)
