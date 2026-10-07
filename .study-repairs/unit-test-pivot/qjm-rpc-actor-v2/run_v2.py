#!/usr/bin/env python3
"""One immutable original QJM JUnit using an independent actor-V2 overlay."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from build_offline import BASE, HADOOP, HERE

METHOD = {"07": "testRecoverAfterIncompleteRecovery",
          "09": "testSingleWriter", "10": "testSingleWriter"}
JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
JACOCO = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/"
              "org.jacoco.agent-0.8.15-runtime.jar")
JVM_START_LOCK = HERE.parent / "jvm-start.lock"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classpath(case: str, overlay: Path) -> str:
    original = BASE / f"HDFS-{case}" / "independent"
    resources = original.parent / "hadoop-3.4.3/hadoop-hdfs-project/hadoop-hdfs/src/test/resources"
    env = dict(os.environ, JAVA_HOME=str(JDK.parent))
    base = subprocess.check_output([str(HADOOP / "bin/hadoop"), "classpath", "--glob"],
                                   env=env, text=True).strip()
    m2 = Path("/users/ZhenyuLi/.m2/repository")
    test_dependencies = [
        m2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
        m2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
        m2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
        m2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar"]
    return os.pathsep.join((str(overlay), str(original / "build/classes"),
        str(resources), str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3-tests.jar"),
        str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
        base, *(str(path) for path in test_dependencies),
        *(str(path) for path in sorted((HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))


def start_jvm(cmd: list[str], scratch: Path, log, output: Path) -> subprocess.Popen:
    """Atomically check node capacity and start one QJM JVM.

    Other controllers can use the same lock path. The lock covers only the
    capacity check and Popen, not the JUnit run, so trials still overlap.
    """
    JVM_START_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with JVM_START_LOCK.open("a") as gate:
        while True:
            fcntl.flock(gate, fcntl.LOCK_EX)
            active = subprocess.run(["pgrep", "-x", "java"], capture_output=True,
                                    text=True, check=False)
            free_gib = shutil.disk_usage(HERE).free / (1024 ** 3)
            if len(active.stdout.splitlines()) <= 4 and free_gib >= 8:
                process = subprocess.Popen(cmd, cwd=scratch,
                    env=dict(os.environ, JAVA_HOME=str(JDK.parent)),
                    stdout=log, stderr=subprocess.STDOUT)
                (output / "jvm.pid").write_text(str(process.pid) + "\n")
                # Make the reservation visible to the next holder before
                # releasing the lock; Popen can return before exec(java).
                for _ in range(50):
                    if process.poll() is not None:
                        break
                    try:
                        if Path(f"/proc/{process.pid}/comm").read_text().strip() == "java":
                            break
                    except OSError:
                        break
                    time.sleep(0.1)
                fcntl.flock(gate, fcntl.LOCK_UN)
                return process
            fcntl.flock(gate, fcntl.LOCK_UN)
            if (output.name.startswith("trial-") and
                    (output.parent / "campaign-v2/PAUSE").exists()):
                raise RuntimeError("JVM start paused at the resource gate")
            time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=METHOD)
    parser.add_argument("--name", required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args()
    if (not args.name or any(character not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in args.name)):
        parser.error("--name must be a safe single run ID")
    if args.timeout < 1 or args.plan and not args.plan.is_file():
        parser.error("invalid timeout or missing plan")
    original = BASE / f"HDFS-{args.case}" / "independent"
    overlay = HERE / "build" / f"HDFS-{args.case}" / "overlay"
    classes = original / "build/classes"
    for path in (overlay / f"Hdfs{args.case}Probe.class",
                 overlay / "QjmRpcActor.class", classes / "RunJUnitMethod.class",
                 classes / "CoverageHdfs50.class"):
        if not path.is_file():
            parser.error(f"offline build/class missing: {path}")
    output = HERE / "evidence" / f"HDFS-{args.case}" / args.name
    scratch = HERE / "build" / "scratch" / f"HDFS-{args.case}" / args.name
    if output.exists() or scratch.exists():
        parser.error("run ID already exists; retain raw evidence and choose a new attempt ID")
    for path in (output, scratch / "data", scratch / "tmp", scratch / "logs"):
        path.mkdir(parents=True, exist_ok=False)
    plan = args.plan.resolve() if args.plan else None
    cmd = [str(JDK / "java"), "-ea", "-Xmx3g", "-Djava.awt.headless=true",
        "-Djava.net.preferIPv4Stack=true",
        "-Dorg.slf4j.simpleLogger.defaultLogLevel=warn",
        "-Dtest.build.data=" + str(scratch / "data"),
        "-Djava.io.tmpdir=" + str(scratch / "tmp"),
        "-Dhadoop.log.dir=" + str(scratch / "logs"),
        f"-Dhdfs{args.case}.independent.trace=" + str(output / "runtime_trace.jsonl"),
        "-javaagent:" + str(JACOCO) + "=destfile=" + str(output / "jacoco.exec") +
        ",includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*,dumponexit=true,append=false"]
    if plan:
        cmd.append(f"-Dhdfs{args.case}.independent.plan=" + str(plan))
    cmd += ["-cp", classpath(args.case, overlay), "RunJUnitMethod",
            "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager",
            METHOD[args.case]]
    started = time.monotonic()
    with (output / "junit.log").open("w") as log:
        process = start_jvm(cmd, scratch, log, output)
        try:
            returncode = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            returncode = 124
    if (output / "jacoco.exec").is_file() and (output / "jacoco.exec").stat().st_size:
        subprocess.run([sys.executable, str(HERE / "coverage_v2.py"),
                        "--case", args.case, "--name", args.name], check=True)
    feedback = {}
    for kind in ("probes", "methods", "branch_counts", "lines"):
        path = output / f"covered_{kind}.txt"
        feedback[kind] = sha(path) if path.is_file() else None
    manifest = {"case_id": f"HDFS-{args.case}",
        "test": "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#" +
                METHOD[args.case],
        "returncode": returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "plan": str(plan) if plan else None,
        "plan_sha256": sha(plan) if plan else None,
        "overlay_probe_sha256": sha(overlay / f"Hdfs{args.case}Probe.class"),
        "overlay_client_sha256": sha(overlay / "org/apache/hadoop/ipc/Client.class"),
        "trace_sha256": sha(output / "runtime_trace.jsonl") if
            (output / "runtime_trace.jsonl").is_file() else None,
        "jacoco_sha256": sha(output / "jacoco.exec") if
            (output / "jacoco.exec").is_file() else None,
        "coverage_sha256": feedback}
    temp = output / "manifest.json.tmp"
    temp.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temp, output / "manifest.json")
    shutil.rmtree(scratch)
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
