#!/usr/bin/env python3
"""Checkpointed, exact last-writer-epoch file-open fault trials."""
from __future__ import annotations
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import subprocess
import sys
import time

from campaign import HERE, TARGET_SITE, TARGET_METHOD, atomic, parse, production, rows

CHECKPOINT = HERE / "epoch2-trials/checkpoint.json"
MARKERS = {"OPEN": "<org.apache.hadoop.hdfs.util.PersistentLongFile: void writeFile(java.io.File,long)>#u100010",
           "WRITE_FILE": "<org.apache.hadoop.hdfs.util.PersistentLongFile: void set(long)>#u100011"}
SELECTORS = [(2, 1, "WRITE_FILE", "IOException"), (2, 1, "WRITE_FILE", "IOException"),
             (0, 1, "WRITE_FILE", "IOException"), (1, 1, "OPEN", "FileNotFoundException"),
             (2, 1, "OPEN", "FileNotFoundException"), (0, 1, "OPEN", "FileNotFoundException")]


def file_events(path):
    result = []
    for line in path.read_text().splitlines():
        nano, thread, kind, operation, node, ordinal, suffix = line.split("\t", 6)
        result.append({"nano": int(nano), "thread": int(thread), "event": kind, "operation": operation,
                       "node": int(node), "hitOrdinal": int(ordinal), "pathSuffix": suffix})
    return result


def all_targets(path):
    events = list(rows(path))
    enters = {e.get("callId"): e for e in events if e.get("event") == "METHOD_ENTER"}
    exits = {e.get("callId"): e for e in events if e.get("event") in ("METHOD_EXIT_THROW", "METHOD_EXIT_NORMAL")}
    result = []
    for e in events:
        if e.get("event") != "BRANCH" or e.get("siteId") != TARGET_SITE:
            continue
        call = enters[e["callId"]]
        parent = enters.get(call.get("parentCallId"), {})
        epoch_values = [x.get("primitiveValue") for x in events if x.get("callId") == e["callId"]
                        and x.get("event") == "CALL_SITE_RETURN" and x.get("siteId") in
                        (TARGET_METHOD + "#u3", TARGET_METHOD + "#u5")]
        exit_event = exits.get(e["callId"], {})
        result.append({"seq": e["seq"], "sourceKey": call.get("sourceKey"),
                       "parentMethod": parent.get("method"), "branch_equal": e.get("outcome"),
                       "exit": exit_event.get("event"), "exception": exit_event.get("runtimeType"),
                       "epochs": epoch_values})
    return result


def main():
    CHECKPOINT.parent.mkdir(exist_ok=True)
    seed = HERE / "epoch2-healthy/trace/runtime_trace.jsonl"
    healthy = parse(seed)
    observed = file_events(HERE / "epoch2-healthy/epoch-events.tsv")
    for node in (0, 1, 2):
        for operation in MARKERS:
            if not any(e["event"] == "OBSERVED" and e["node"] == node and e["hitOrdinal"] == 1
                       and e["operation"] == operation for e in observed):
                raise RuntimeError("unobserved last-writer-epoch site " + operation + " on node " + str(node))
    state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {
        "case_id": "HDFS-10", "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "healthy_file_events": observed, "trials": [], "stop_reason": None}
    if state.get("stop_reason"):
        print("checkpoint stopped:", state["stop_reason"])
        return
    union = production(healthy["coverage"])
    for trial in state["trials"]:
        union |= production(parse(HERE / trial["trace"])["coverage"])
    for index in range(len(state["trials"]) + 1, len(SELECTORS) + 1):
        node, ordinal, operation, exception = SELECTORS[index - 1]
        name = "epoch2-trial-%02d" % index
        out = HERE / name
        started = time.monotonic()
        if not (out / "manifest.json").exists():
            with (CHECKPOINT.parent / (name + ".log")).open("w") as log:
                subprocess.run([sys.executable, str(HERE / "run_epoch.py"), "--run-name", name,
                    "--node", str(node), "--ordinal", str(ordinal), "--exception", exception,
                    "--operation", operation],
                    cwd=HERE, stdout=log, stderr=subprocess.STDOUT, check=False)
        manifest = json.loads((out / "manifest.json").read_text())
        trace = out / "trace/runtime_trace.jsonl"
        feedback = parse(trace)
        events = file_events(out / "epoch-events.tsv")
        selected = [e for e in events if e["node"] == node and e["hitOrdinal"] == ordinal
                    and e["operation"] == operation]
        markers = [e for e in rows(trace) if e.get("event") == "BRANCH" and e.get("siteId") == MARKERS[operation]
                   and e.get("outcome") is True]
        matched = [e for e in selected if e["event"] == "MATCHED"]
        applied = [e for e in selected if e["event"] == "APPLIED"]
        strict = len(matched) == len(applied) == len(markers) == 1 and len([e for e in events if e["event"] == "APPLIED"]) == 1
        last = markers[0]["seq"] if markers else -1
        after = [t for t in all_targets(trace) if t["seq"] > last >= 0]
        exceptions = [t for t in after if t["branch_equal"] is False and t["exit"] == "METHOD_EXIT_THROW"
                      and t["exception"] == "java.io.IOException"]
        selected_after = [t for t in feedback["targets"] if t["seq"] > last >= 0]
        gain = production(feedback["coverage"]) - union
        union |= production(feedback["coverage"])
        status = "unmatched" if not strict else "lost_target" if not after else "expected_guard_exception" if exceptions else "checked"
        row = {"trial": name, "status": status,
               "selector": {"method": "PersistentLongFile.writeFile(File,long)" if operation == "OPEN" else "PersistentLongFile.set(long)",
                            "operation": "AtomicFileOutputStream(File) open" if operation == "OPEN" else "PersistentLongFile.writeFile(File,long) call", "node": node,
                            "hitOrdinal": ordinal, "exception": exception,
                            "pathSuffix": "journalnode-%s/test-journal/current/last-writer-epoch" % node},
               "matched_count": len(matched), "applied_count": len(applied), "strict_injection": strict,
               "target_reached_after_fault": bool(after), "selected_final_target_after_fault": bool(selected_after),
               "all_targets_after_fault": after, "expected_guard_exception_count": len(exceptions),
               "junit_exit": manifest["runtime"]["exit"], "junit_seconds": manifest["runtime"]["elapsed_seconds"],
               "trial_wall_seconds": round(time.monotonic() - started, 3),
               "method_branch_coverage_ids": len(production(feedback["coverage"])),
               "new_coverage_ids": len(gain), "new_coverage_id_list": sorted(gain),
               "trace": str(trace.relative_to(HERE)), "completed_at_utc": datetime.now(timezone.utc).isoformat()}
        state["trials"].append(row)
        state["coverage_union_ids"] = len(union)
        atomic(CHECKPOINT, state)
        print(json.dumps({k: row[k] for k in ("trial", "status", "strict_injection",
              "target_reached_after_fault", "expected_guard_exception_count", "new_coverage_ids", "junit_seconds")}), flush=True)
    state["stop_reason"] = "six_observed_epoch_file_trials_completed"
    state["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic(CHECKPOINT, state)
    columns = ("trial", "status", "selector", "matched_count", "applied_count", "strict_injection",
               "target_reached_after_fault", "selected_final_target_after_fault", "all_targets_after_fault",
               "expected_guard_exception_count", "junit_exit", "junit_seconds", "trial_wall_seconds",
               "method_branch_coverage_ids", "new_coverage_ids", "trace")
    with (HERE / "epoch2-trial-ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in state["trials"]:
            writer.writerow({key: json.dumps(row[key], separators=(",", ":")) if isinstance(row[key], (list, dict)) else row[key]
                             for key in columns})


if __name__ == "__main__":
    main()
