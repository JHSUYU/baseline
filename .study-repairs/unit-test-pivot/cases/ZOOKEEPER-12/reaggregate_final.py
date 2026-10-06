#!/usr/bin/env python3
"""Pin ZK12's final restarted peer without rerunning the stock JUnit trace."""
import json
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
run = here / "run"
trial = here / "trials" / sys.argv[1] if len(sys.argv) > 1 else None
trace = trial / "runtime" if trial else run / "runtime"
target = run / "targets" / "zk12"
output = trial / "closure" if trial else run / "final-target" / "runtime"
source = "zk-peer-0#epoch2"
region = "REGION.e58c435f-888b-30d6-93a4-2078e7f4199b"
observed = set()
with (run / "runtime" / "runtime_trace.jsonl").open() as rows:
    for line in rows:
        row = json.loads(line)
        if (row.get("event") == "FAULT_POINT_OBSERVED"
                and row.get("sourceKey") == source
                and row.get("occurrenceAddress", "").split("/region/")[1].startswith(region)):
            observed.add(row["occurrenceAddress"])
assert len(observed) == 1, sorted(observed)
occurrence = observed.pop()
output.mkdir(parents=True, exist_ok=True)
(here / "final-target-occurrence.txt").write_text(occurrence + "\n")
jar = here / "graphchecker" / "target" / "GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar"
spec = "zk12=" + ",".join(map(str, (
    target / "candidate_dataflow_edges.jsonl.gz",
    target / "static_scope_map.jsonl",
    target / "view_region_skeletons.jsonl.gz",
    output,
)))
subprocess.run([
    "/usr/lib/jvm/java-8-openjdk-amd64/bin/java", "-Xmx2048m",
    "-Dcausynth.loop.default.bound=8",
    "-Dcausynth.loop.bounds=" + str(here / "graphchecker" / "experiments"
                                     / "zookeeper" / "zk12" / "loop-bounds.jsonl"),
    "-cp", str(jar),
    "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
    "--trace-dir", str(trace), "--test",
    "org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile",
    "--target-occurrence", occurrence, "--target", spec,
    "--summary", str(trial / "closure-summary.json" if trial else here / "final-target-summary.json"),
], check=True)
