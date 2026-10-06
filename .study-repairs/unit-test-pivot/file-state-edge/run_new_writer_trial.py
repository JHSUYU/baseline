#!/usr/bin/env python3
"""Extend ZK12's observed writer sequence by one new fault under the file graph."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import time

here = Path(__file__).resolve().parent
graphchecker = here / "graphchecker"
run = here / "zk12-run"
old = here.parent / "cases" / "ZOOKEEPER-12"
name = "four_accepted_writes"
trial = here / "trials" / name
trace = trial / "runtime"
trace.mkdir(parents=True, exist_ok=False)
marker = "FAULT:ZOOKEEPER_FILE:WRITE"
source = "zk-peer-0#epoch1"
region = "REGION.77ac7573-6fd5-35c3-b2e6-edccead64143"
target_region = "REGION.e58c435f-888b-30d6-93a4-2078e7f4199b"
target_guard = "<org.apache.zookeeper.server.quorum.QuorumPeer: void loadDataBase()>#u62"
target_method = "<org.apache.zookeeper.server.quorum.QuorumPeer: void loadDataBase()>"


def points(path, opener):
    found = {}
    with opener(path, "rt") as stream:
        for line in stream:
            row = json.loads(line)
            if (row.get("event") == "FAULT_POINT_OBSERVED"
                    and row.get("marker") == marker
                    and row.get("sourceKey") == source
                    and "/region/" + region + "/" in row.get("occurrenceAddress", "")):
                found[row["hitOrdinal"]] = row
    return found


healthy = points(run / "runtime" / "runtime_trace.jsonl", open)
mutated = points(old / "trials" / "triple_accepted_writes" / "runtime"
                 / "runtime_trace.jsonl.gz", gzip.open)
assert 1 in healthy and all(ordinal in mutated for ordinal in (2, 3, 4))
selected = [healthy[1], *(mutated[index] for index in (2, 3, 4))]
assert len({point["siteId"] for point in selected}) == 1
assert len({point["occurrenceAddress"] for point in selected}) == 1
assert selected[0]["occurrenceAddress"] in (
    row["writerOccurrence"] for row in map(json.loads,
        (run / "final-target" / "runtime" / "persistent_file_edges.jsonl").open())
    if row["path"].endswith("/acceptedEpoch")
    and row["readerOccurrence"] == (here / "final-target-occurrence.txt")
    .read_text().strip()
)
plan = {
    "schemaVersion": 1,
    "faults": [{
        "faultId": "zk12-file-version-four-write-" + str(index),
        "marker": marker,
        "siteId": point["siteId"],
        "occurrence": point["occurrenceAddress"],
        "sourceKey": source,
        "hitOrdinal": index,
        "value": True,
    } for index, point in enumerate(selected, 1)],
    "targetSiteId": target_guard,
    "targetRegionId": target_region,
}
(trial / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
env = os.environ.copy()
env.update({
    "GRAPHCHECKER_JAR": str(graphchecker / "target" / "GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar"),
    "CAUSYNTH_INSTRUMENTED_CLASSES_DIR": str(run / "instrumented-classes"),
    "CAUSYNTH_TRACE_OUTPUT_DIR": str(trace),
    "CAUSYNTH_WORKLOAD_JAVA_OPTS": "-Dcausynth.fault.trial=" + str(trial / "plan.json"),
})
started = time.monotonic()
with (trial / "junit.log").open("w") as log:
    outcome = subprocess.run([
        "timeout", "--signal=TERM", "--kill-after=5s", "150s", "bash",
        str(graphchecker / "experiments" / "lib" / "execute.sh"),
        str(graphchecker / "experiments" / "zookeeper" / "zk12"), "",
    ], cwd=graphchecker, env=env, stdout=log, stderr=subprocess.STDOUT)
elapsed = time.monotonic() - started
events = []
branches = []
target_calls = {}
file_events = []
with (trace / "runtime_trace.jsonl").open() as stream:
    for line in stream:
        row = json.loads(line)
        event = row.get("event", "")
        if event.startswith("FAULT_"):
            events.append(row)
        if event == "METHOD_ENTER" and row.get("method") == target_method:
            target_calls[row["callId"]] = row.get("sourceKey")
        if event == "BRANCH":
            branches.append((row.get("seq"), row.get("callId"),
                             row.get("siteId"), row.get("outcome")))
        if event.startswith("FILE_"):
            file_events.append(row)
applied = [row["seq"] for row in events if row["event"] == "FAULT_APPLIED"]
selected_after = [branch for branch in branches
                  if branch[2] == target_guard
                  and target_calls.get(branch[1]) == "zk-peer-0#epoch2"
                  and applied and branch[0] > max(applied)]
summary = {
    "case_id": "ZOOKEEPER-12",
    "trial": name,
    "elapsed_seconds": round(elapsed, 3),
    "exit_code": outcome.returncode,
    "matched": sum(row["event"] == "FAULT_MATCHED" for row in events),
    "applied": len(applied),
    "target_selected_after_fault": bool(selected_after),
    "target_fatal_after_fault": any(branch[3] is False for branch in selected_after),
    "target_guard_outcomes_after_fault": [branch[3] for branch in selected_after],
    "file_success_events": len(file_events),
    "accepted_epoch_success_after_four_faults": [
        row["seq"] for row in file_events
        if row["event"] == "FILE_WRITE_SUCCESS"
        and row.get("sourceKey") == source
        and row["path"].endswith("/acceptedEpoch")
        and applied and row["seq"] > max(applied)],
}
(trial / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
