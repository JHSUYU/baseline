#!/usr/bin/env python3
"""Verify UUID-to-replica binding and two ordered I/O faults off cluster."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from build_offline import BUILD, CLASSES, HADOOP, main as build


def main() -> None:
    build()
    directory = BUILD / "smoke"
    directory.mkdir(parents=True, exist_ok=True)
    plan = directory / "faults.tsv"
    trace = directory / "trace.jsonl"
    plan.write_text("".join(
        "\t".join(("FAULT:HDFS_DATA_TRANSFER:READ", "BlockReaderRemote.read",
                   "replica:0", "/preadtest.dat@0", str(ordinal), "pending", kind)) + "\n"
        for ordinal, kind in ((1, "IOException"), (2, "EOFException"))))
    env = dict(os.environ, JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64")
    hadoop_cp = subprocess.check_output(
        [str(HADOOP / "bin/hadoop"), "classpath", "--glob"], env=env,
        text=True).strip()
    command = ["/usr/lib/jvm/java-8-openjdk-amd64/bin/java",
               "-Dhdfs01.actor.trace=" + str(trace),
               "-Dhdfs01.actor.plan=" + str(plan),
               "-cp", str(CLASSES) + os.pathsep + hadoop_cp,
               "ActorProbeSmoke"]
    completed = subprocess.run(command, capture_output=True, text=True,
                               check=False)
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    reads = [row for row in rows if row["event"] == "FAULT_POINT_OBSERVED"]
    applied = [row for row in rows if row["event"] == "FAULT_APPLIED"]
    guards = [row for row in rows if row["event"] == "TARGET_CHECK"]
    locations = [row for row in rows if row["event"] == "BLOCK_LOCATION"]
    if (len(reads) != 3 or reads[0]["identityBound"] is not False
            or [row["actorUuid"] for row in reads] != ["uuid-b", "uuid-a", "uuid-a"]
            or [row["faultIndex"] for row in applied] != [0, 1]
            or [row["faultType"] for row in applied] != ["IOException", "EOFException"]
            or not all(row["actorKey"] == "replica:0" and
                       row["resourceKey"] == "/preadtest.dat@0" for row in applied)
            or not any(row["origin"] == "RPC_RETURN" and row["blockId"] == 42
                       and row["actorUuid"] == "uuid-a" and row["replicaIndex"] == 0
                       for row in locations)
            or len(guards) != 1 or guards[0]["file"] != "/preadtest.dat"):
        raise AssertionError("actor/ordered fault smoke mismatch")
    print("actor probe smoke passed: wrong UUID excluded; ordered same-block faults applied")


if __name__ == "__main__":
    main()
