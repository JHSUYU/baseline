#!/usr/bin/env python3
"""Rebuild the pinned final restart graph from the unchanged stock JUnit."""
import json
from pathlib import Path
import subprocess
import sys

here = Path(__file__).resolve().parent
run = here / "zk12-run"
graphchecker = here.parent / "graphchecker"
region = "REGION.e58c435f-888b-30d6-93a4-2078e7f4199b"
source = "zk-peer-0#epoch2"
trial_name = sys.argv[1] if len(sys.argv) > 1 else None
runtime_dir = (here / "trials" / trial_name / "runtime"
               if trial_name else run / "runtime")
trace = runtime_dir / "runtime_trace.jsonl"
observed = set()
for line in trace.open():
    row = json.loads(line)
    if (row.get("event") == "FAULT_POINT_OBSERVED"
            and row.get("sourceKey") == source
            and "/region/" + region + "/" in row.get("occurrenceAddress", "")):
        observed.add(row["occurrenceAddress"])
assert len(observed) == 1, sorted(observed)
occurrence = observed.pop()
if not trial_name:
    (here / "final-target-occurrence.txt").write_text(occurrence + "\n")
output = (here / "trials" / trial_name / "closure"
          if trial_name else here / "final-target")
output.mkdir(parents=True, exist_ok=True)
target = run / "targets" / "zk12"
spec = "zk12=" + ",".join(map(str, (
    target / "candidate_dataflow_edges.jsonl.gz",
    target / "static_scope_map.jsonl",
    target / "view_region_skeletons.jsonl.gz",
    output,
)))
jar = Path("/users/ZhenyuLi/.graphchecker-builds/unit-test-zookeeper-4d87a7c24c-28d298f0e310.jar")
logfile = (here / "trials" / trial_name / "reaggregate.log"
           if trial_name else here / "reaggregate.log")
summary = (here / "trials" / trial_name / "closure-summary.json"
           if trial_name else here / "final-target-summary.json")
with logfile.open("w") as log:
    subprocess.run([
        "/usr/lib/jvm/java-8-openjdk-amd64/bin/java", "-Xmx2048m",
        "-Dcausynth.loop.default.bound=8",
        "-Dcausynth.loop.bounds=" + str(graphchecker / "experiments" / "zookeeper"
                                           / "zk12_merged_validation" / "loop-bounds.jsonl"),
        "-cp", str(jar),
        "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
        "--trace-dir", str(runtime_dir), "--test",
        "org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile",
        "--target-occurrence", occurrence, "--target", spec,
        "--summary", str(summary),
    ], check=True, stdout=log, stderr=subprocess.STDOUT)
