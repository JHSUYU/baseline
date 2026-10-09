#!/usr/bin/env python3
"""Summarize exact HBASE-01 runtime fault and scoped coverage evidence."""

import json
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
names = ("healthy5", "io01", "timeout02", "double03")
target_site = "<org.apache.hadoop.hbase.client.ConnectionImplementation: org.apache.hadoop.hbase.RegionLocations locateRegionInMeta(org.apache.hadoop.hbase.TableName,byte[],boolean,boolean,int)>#u222"
target_method = target_site.rsplit("#", 1)[0]
synthetic = {target_site.replace("#u222", "#u122"), target_site.replace("#u222", "#u127")}
results = {}
all_seen_methods = set()
all_seen_branches = set()
healthy_methods = set()
healthy_branches = set()

for name in names:
    trace_path = root / f"trace-{name}" / "runtime_trace.jsonl"
    if not trace_path.exists():
        continue
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    methods = {e["method"] for e in events if e.get("event") == "METHOD_ENTER"}
    branches = {(e["siteId"], e["outcome"]) for e in events if e.get("event") == "BRANCH"}
    markers = {e["marker"] for e in events if e.get("event") == "FAULT_POINT_OBSERVED"}
    matched = [e for e in events if e.get("event") == "FAULT_MATCHED"]
    applied = [e for e in events if e.get("event") == "FAULT_APPLIED"]
    trial_summaries = [e for e in events if e.get("event") == "FAULT_TRIAL_SUMMARY"]
    last_fault_seq = max((e["seq"] for e in applied), default=-1)
    guard = [e for e in events if e.get("event") == "BRANCH" and e.get("siteId") == target_site]
    after_fault = [e for e in guard if e["seq"] > last_fault_seq] if applied else []
    log = root / ("healthy5.log" if name == "healthy5" else f"{name}.log")
    time_match = re.search(r"ELAPSED_SECONDS=([\d.]+) MAX_RSS_KB=(\d+)", log.read_text()) if log.exists() else None
    target_entries = [e for e in events if e.get("event") == "METHOD_ENTER" and e.get("method") == target_method]
    results[name] = {
        "elapsed_seconds": float(time_match.group(1)) if time_match else None,
        "max_rss_kb": int(time_match.group(2)) if time_match else None,
        "junit_exit": (root / f"{name}.exit").read_text().strip() if (root / f"{name}.exit").exists() else None,
        "trace_events": len(events),
        "fault_markers_observed": sorted(markers),
        "fault_requested": sum(e.get("requested", 0) for e in trial_summaries),
        "fault_matched": len(matched),
        "fault_applied": len(applied),
        "matched_fault_ids": [e["faultId"] for e in matched],
        "applied_fault_ids": [e["faultId"] for e in applied],
        "exact_applied_selector": [{k: e.get(k) for k in ("faultId", "marker", "siteId", "occurrenceAddress", "sourceKey", "hitOrdinal")} for e in applied],
        "target_occurrences": sorted({e.get("occurrenceAddress", "") for e in target_entries}),
        "target_method_entries": len(target_entries),
        "fatal_guard_count": sum(e["outcome"] is False for e in guard),
        "guard_outcomes": [e["outcome"] for e in guard],
        "guard_outcomes_after_final_fault": [e["outcome"] for e in after_fault],
        "summary_target_after_fault": [e.get("targetAfterFault") for e in trial_summaries],
        "scoped_method_coverage": len(methods),
        "scoped_branch_outcome_coverage_raw": len(branches),
        "scoped_branch_outcome_coverage_excluding_fault_gate": len({b for b in branches if b[0] not in synthetic}),
        "new_methods_vs_healthy": [],
        "new_branches_vs_healthy_raw": [],
        "new_branches_vs_healthy_excluding_fault_gate": [],
        "new_methods_vs_previous_runs": sorted(methods - all_seen_methods),
        "new_branches_vs_previous_runs_raw": sorted([f"{site}={outcome}" for site, outcome in branches - all_seen_branches]),
    }
    if name == "healthy5":
        healthy_methods = methods
        healthy_branches = branches
    else:
        results[name]["new_methods_vs_healthy"] = sorted(methods - healthy_methods)
        results[name]["new_branches_vs_healthy_raw"] = sorted([f"{site}={outcome}" for site, outcome in branches - healthy_branches])
        results[name]["new_branches_vs_healthy_excluding_fault_gate"] = sorted([f"{site}={outcome}" for site, outcome in branches - healthy_branches if site not in synthetic])
    all_seen_methods |= methods
    all_seen_branches |= branches

print(json.dumps(results, indent=2, sort_keys=True))
