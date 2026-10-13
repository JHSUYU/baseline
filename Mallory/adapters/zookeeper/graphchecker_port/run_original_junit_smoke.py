#!/usr/bin/env python3
"""Weave an isolated class copy and run the unchanged ZooKeeper JUnit method."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from verify_source import verify


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[3]
RUNTIME = BASE / "Mallory/graphchecker-runtime"


def surefire_classpath(report: Path) -> str:
    root = ET.parse(report).getroot()
    properties = root.findall("./properties/property")
    value = next((row.get("value", "") for row in properties
                  if row.get("name") == "java.class.path"), "")
    if not value:
        raise RuntimeError(f"Surefire report lacks classpath: {report}")
    missing = [entry for entry in value.split(os.pathsep)
               if entry and not Path(entry).exists()]
    if missing:
        raise RuntimeError(f"Surefire classpath has missing entries: {missing}")
    return value


def run_logged(command: list[str], log: Path, stage: str) -> None:
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, stdout=output,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"{stage} failed with exit {result.returncode}; "
                           f"inspect {log}")


def verify_trace(path: Path) -> None:
    exports = set()
    counts = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        kind = row.get("kind")
        counts[kind] += 1
        if kind == "EXPORT":
            exports.add((row.get("transport"), row.get("correlationId"),
                         row.get("attemptId"), row.get("half")))
        if kind == "ATTACH":
            identity = (row.get("transport"), row.get("correlationId"),
                        row.get("attemptId"), row.get("half"))
            if identity not in exports or row.get("pairedBy") != "ENVELOPE":
                raise RuntimeError(f"unproven quorum ATTACH: {identity}")
    if counts["EXPORT"] == 0 or counts["ATTACH"] == 0:
        raise RuntimeError("original JUnit did not exercise a quorum send/receive")
    if counts["READ"] == 0 or counts["WRITE"] == 0:
        raise RuntimeError("original JUnit did not exercise versioned file I/O")
    print("Trace verified: " + ", ".join(
        f"{name}={counts[name]}" for name in
        ("EXPORT", "ATTACH", "WRITE", "READ", "GAP")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("scratch", type=Path)
    args = parser.parse_args()
    source = args.source_root.resolve()
    scratch = args.scratch.resolve()
    verify(source)
    scratch.mkdir(parents=True, exist_ok=True)
    adapter_classes = HERE / "target/classes"
    runtime_classes = RUNTIME / "target/classes"
    adapter_deps = HERE / "target/dependency-classpath.txt"
    report = (source / "zookeeper-server/target/surefire-reports/"
              "TEST-org.apache.zookeeper.test.QuorumRestartTest.xml")
    for required in (adapter_classes, runtime_classes, adapter_deps, report):
        if not required.exists():
            raise RuntimeError(f"build first; missing {required}")
    original_cp = surefire_classpath(report)
    dependency_cp = adapter_deps.read_text(encoding="utf-8").strip()
    common = os.pathsep.join((str(adapter_classes), str(runtime_classes),
                              dependency_cp, original_cp))
    output = scratch / "woven-classes"
    output.mkdir(exist_ok=True)
    run_logged([
        "java", "-Xmx4g", "-cp", common,
        "edu.uva.liftlab.mallory.graphchecker.causynth.WeaveZooKeeperMain",
        str(source / "zookeeper-server/target/classes"), common, str(output),
    ], scratch / "smoke-weave.log", "ZooKeeper Soot weave")
    (scratch / "tmp").mkdir(exist_ok=True)
    (scratch / "test-data").mkdir(exist_ok=True)
    run_cp = os.pathsep.join((str(output), common))
    run_logged([
        "java", "-Xmx3g", f"-Djava.io.tmpdir={scratch / 'tmp'}",
        f"-Dbuild.test.dir={scratch / 'test-data'}",
        "-Dtest.junit.threads=16", "-Dzookeeper.junit.threadid=13",
        f"-Dmallory.graphchecker.trace.file={scratch / 'trace.jsonl'}",
        "-cp", run_cp,
        "edu.uva.liftlab.mallory.graphchecker.causynth.OriginalJUnitMethodMain",
        "org.apache.zookeeper.test.QuorumRestartTest", "testRollingRestart",
    ], scratch / "smoke-junit.log", "original ZooKeeper JUnit")
    verify_trace(scratch / "trace.jsonl")
    print(f"Original JUnit trace: {scratch / 'trace.jsonl'}")


if __name__ == "__main__":
    main()
