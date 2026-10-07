#!/usr/bin/env python3
"""Check selector application and JSON trace without running a cluster."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from run_original import CASE, HERE, JACOCO, JDK, classpath
from run_coverage import run as export_coverage


def main() -> None:
    out = CASE / "offline-smoke"
    classes = out / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    plan = out / "plan.tsv"
    plan.write_text("\t".join(("RPC_RESPONSE_WAIT", "truncate", "nn0",
        "client", "/testTruncateTwiceTogether/file", "-1", "398", "1",
        "IOException")) + "\n")
    trace = out / "runtime_trace.jsonl"
    cp = str(HERE / "probe-classes") + ":" + classpath()
    subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(classes),
                    str(HERE / "OfflineProbeSmoke.java")], check=True)
    subprocess.run([str(JDK / "java"),
                    "-javaagent:" + str(JACOCO) + "=destfile=" +
                    str(out / "jacoco.exec") + ",append=false,"
                    "includes=org.apache.hadoop.hdfs.*:org.apache.hadoop.ipc.*",
                    "-Dhdfs43.actor.trace=" + str(trace),
                    "-Dhdfs43.actor.plan=" + str(plan),
                    "-cp", str(classes) + ":" + cp,
                    "OfflineProbeSmoke"], check=True)
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
    assert [r["event"] for r in rows] == ["TEST_PHASE", "IO_OBSERVED",
        "FAULT_MATCHED", "FAULT_APPLIED", "TARGET_GUARD"]
    assert rows[3]["rpcKey"] == "010203:7"
    assert rows[3]["path"] == rows[4]["path"]
    assert rows[4]["blockId"] == 1073741825
    assert rows[4]["phase"] == "secondTruncate"
    export_coverage(out / "jacoco.exec", out / "coverage.tsv")
    exported = (out / "coverage.tsv").read_text().splitlines()
    assert exported and all(line.split("\t", 1)[1].startswith((
        "org/apache/hadoop/hdfs/", "org/apache/hadoop/ipc/"))
        for line in exported)
    assert not any("TestFileTruncate" in line or "hdfs43actor" in line
                   for line in exported)
    print(json.dumps({"status": "passed", "synthetic_only": True,
                      "events": [r["event"] for r in rows],
                      "production_coverage_ids": len(exported)}))


if __name__ == "__main__":
    main()
