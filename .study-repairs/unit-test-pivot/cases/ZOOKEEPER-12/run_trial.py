#!/usr/bin/env python3
"""Run one original ZK12 JUnit fault trial at an exact observed marker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

here = Path(__file__).resolve().parent
graphchecker = here / "graphchecker"
run = here / "run"
target_occurrence = (here / "final-target-occurrence.txt").read_text().strip()
target_region = "REGION.e58c435f-888b-30d6-93a4-2078e7f4199b"
target_guard = "<org.apache.zookeeper.server.quorum.QuorumPeer: void loadDataBase()>#u62"
target_method = "<org.apache.zookeeper.server.quorum.QuorumPeer: void loadDataBase()>"

name, source, operation, ordinal = sys.argv[1:5]
ordinal = int(ordinal)
fault_region = sys.argv[5] if len(sys.argv) > 5 else target_region
marker = "FAULT:ZOOKEEPER_FILE:" + operation
observed = []
with (run / "runtime" / "runtime_trace.jsonl").open() as rows:
    for line in rows:
        row = json.loads(line)
        if (row.get("event") == "FAULT_POINT_OBSERVED"
                and row.get("marker") == marker
                and row.get("sourceKey") == source
                and row.get("hitOrdinal") == ordinal
                and "/region/" + fault_region + "/" in row.get("occurrenceAddress", "")):
            observed.append(row)
assert len(observed) == 1, [(r.get("seq"), r.get("occurrenceAddress")) for r in observed]
point = observed[0]
trial = here / "trials" / name
trace = trial / "runtime"
trace.mkdir(parents=True, exist_ok=False)
plan = {
    "schemaVersion": 1,
    "faults": [{
        "faultId": "zk12-" + name,
        "marker": marker,
        "siteId": point["siteId"],
        "occurrence": point["occurrenceAddress"],
        "sourceKey": source,
        "hitOrdinal": ordinal,
        "value": True,
    }],
    "targetSiteId": target_guard,
    "targetRegionId": target_region,
}
assert (len(sys.argv) - 6) % 2 == 0
for fault_index in range(6, len(sys.argv), 2):
    prior_trial = sys.argv[fault_index]
    second_ordinal = int(sys.argv[fault_index + 1])
    new_points = []
    prior_trace = here / "trials" / prior_trial / "runtime" / "runtime_trace.jsonl"
    with prior_trace.open() as rows:
        for line in rows:
            row = json.loads(line)
            if (row.get("event") == "FAULT_POINT_OBSERVED"
                    and row.get("marker") == marker
                    and row.get("sourceKey") == source
                    and row.get("hitOrdinal") == second_ordinal
                    and row.get("occurrenceAddress") == point["occurrenceAddress"]):
                new_points.append(row)
    assert len(new_points) == 1, [(r.get("seq"), r.get("occurrenceAddress")) for r in new_points]
    second = new_points[0]
    plan["faults"].append({
        "faultId": "zk12-" + name + "-" + str(len(plan["faults"]) + 1),
        "marker": marker,
        "siteId": second["siteId"],
        "occurrence": second["occurrenceAddress"],
        "sourceKey": source,
        "hitOrdinal": second_ordinal,
        "value": True,
    })
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
trace_file = trace / "runtime_trace.jsonl"
if trace_file.exists():
    with trace_file.open() as rows:
        for line in rows:
            row = json.loads(line)
            event = row.get("event")
            if event.startswith("FAULT_"):
                events.append({k: row.get(k) for k in (
                    "seq", "event", "faultId", "marker", "siteId", "occurrenceAddress",
                    "sourceKey", "hitOrdinal", "requested", "matched", "applied",
                    "targetAfterFault")})
            if event == "METHOD_ENTER" and row.get("method") == target_method:
                target_calls[row["callId"]] = row.get("sourceKey")
            if event == "BRANCH":
                branches.append((row.get("seq"), row.get("callId"),
                                 row.get("siteId"), row.get("outcome")))
applied = [e["seq"] for e in events if e["event"] == "FAULT_APPLIED"]
selected_after = [b for b in branches if b[2] == target_guard
                  and target_calls.get(b[1]) == "zk-peer-0#epoch2"
                  and applied and b[0] > max(applied)]
fatal = [b for b in selected_after if b[3] is False]
healthy_branches = set()
with (run / "runtime" / "runtime_trace.jsonl").open() as rows:
    for line in rows:
        row = json.loads(line)
        if row.get("event") == "BRANCH":
            healthy_branches.add((row.get("siteId"), row.get("outcome")))
trial_branches = {(b[2], b[3]) for b in branches}
summary = {
    "case_id": "ZOOKEEPER-12", "trial": name,
    "elapsed_seconds": round(elapsed, 3), "exit_code": outcome.returncode,
    "matched": sum(e["event"] == "FAULT_MATCHED" for e in events),
    "applied": len(applied),
    "target_selected_after_fault": bool(selected_after),
    "target_fatal_after_fault": bool(fatal),
    "target_guard_outcomes_after_fault": [b[3] for b in selected_after],
    "branch_coverage_gain": len(trial_branches - healthy_branches),
    "events": events,
}
(trial / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({k:v for k,v in summary.items() if k != "events"}, indent=2))
