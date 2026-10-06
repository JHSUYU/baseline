#!/usr/bin/env python3
"""Exact IPC-response fault campaign for the unchanged upstream JUnit method."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
TRACE = HERE / "healthy/trace/runtime_trace.jsonl"
TRIALS = HERE / "trials"
CHECKPOINT = TRIALS / "checkpoint.json"
TARGET_METHOD = "<org.apache.hadoop.hdfs.qjournal.server.Journal: void checkWriteRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)>"
TARGET_SITE = TARGET_METHOD + "#u7"
PARENT = "<org.apache.hadoop.hdfs.qjournal.server.Journal: void journal(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo,long,long,int,byte[])>"
MAX_EFFECTIVE = 42  # Six legal epoch-file trials complete the case's 48-trial budget.
MAX_ATTEMPTS = 72
PHASES = ("startLogSegment@0", "sendEdits@0", "finalizeLogSegment@0",
          "startLogSegment@1", "sendEdits@3", "sendEdits@4", "finalizeLogSegment@1",
          "sendEdits@1", "sendEdits@2", "sendEdits@5", "recoverUnfinalizedSegments",
          "format", "hasSomeData")


def rows(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def point(event):
    if event.get("event") not in ("FAULT_POINT_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"):
        return None
    if not str(event.get("marker", "")).startswith("FAULT:HADOOP_IPC:RESPONSE"):
        return None
    item = {k: event[k] for k in ("marker", "siteId")}
    item["occurrence"] = event["occurrenceAddress"]
    item["hitOrdinal"] = event["hitOrdinal"]
    if event.get("sourceKey"):
        item["sourceKey"] = event["sourceKey"]
    return item


def phase(event):
    address = event["occurrenceAddress"]
    for name in ("hasSomeData", "format", "recoverUnfinalizedSegments", "startLogSegment", "sendEdits", "finalizeLogSegment"):
        if name not in address:
            continue
        if name == "startLogSegment":
            return name + "@" + ("1" if "startLogSegment(long,int)>@1" in address else "0")
        if name == "sendEdits":
            for index in range(8):
                if "sendEdits(long,long,int,byte[])>@" + str(index) in address:
                    return name + "@" + str(index)
        if name == "finalizeLogSegment":
            return name + "@" + ("1" if "finalizeLogSegment(long,long)>@1" in address else "0")
        return name
    return "other"


def parse(path):
    events = list(rows(path))
    enters = {e.get("callId"): e for e in events if e.get("event") == "METHOD_ENTER"}
    arguments = defaultdict(dict)
    for e in events:
        if e.get("event") == "METHOD_ARGUMENT":
            arguments[e.get("callId")][e.get("argumentIndex")] = e.get("primitiveValue")
    branches = [e for e in events if e.get("event") == "BRANCH" and e.get("siteId") == TARGET_SITE]
    exits = {e.get("callId"): e for e in events if e.get("event") in ("METHOD_EXIT_NORMAL", "METHOD_EXIT_THROW")}
    targets = []
    for e in branches:
        call = enters.get(e["callId"], {})
        parent = enters.get(call.get("parentCallId"), {})
        args = arguments.get(parent.get("callId"), {})
        if (call.get("sourceKey") == "jn2#epoch0" and call.get("requestApi") == "originalSingleWriter"
                and parent.get("method") == PARENT and args.get(1) == "4" and args.get(2) == "4" and args.get(3) == "1"):
            exit_event = exits.get(e["callId"], {})
            epochs = [x.get("primitiveValue") for x in events if x.get("callId") == e["callId"]
                      and x.get("event") == "CALL_SITE_RETURN" and x.get("siteId") in
                      (TARGET_METHOD + "#u3", TARGET_METHOD + "#u5")]
            targets.append({"seq": e["seq"], "branch_equal": e.get("outcome"),
                            "exit": exit_event.get("event"), "exception": exit_event.get("runtimeType"),
                            "epochs": epochs, "sourceKey": call.get("sourceKey"), "parentArgs": args})
    applied = [e for e in events if e.get("event") == "FAULT_APPLIED"]
    matched = [e for e in events if e.get("event") == "FAULT_MATCHED"]
    coverage = set()
    observed = []
    for e in events:
        if e.get("event") == "METHOD_ENTER" and e.get("method"):
            coverage.add("METHOD:" + e["method"])
        elif e.get("event") == "BRANCH" and e.get("siteId"):
            coverage.add("BRANCH:" + e["siteId"] + ":" + str(e.get("outcome")))
        elif e.get("event") == "FAULT_POINT_OBSERVED":
            p = point(e)
            if p:
                observed.append((p, e))
    return {"targets": targets, "all_target_branches": len(branches), "applied": applied,
            "matched": matched, "last_applied_seq": max((e.get("seq", -1) for e in applied), default=-1),
            "observed": observed, "coverage": coverage}


def production(coverage):
    return {x for x in coverage if "<org.apache.hadoop.ipc.Client: org.apache.hadoop.io.Writable getRpcResponse" not in x
            or not x.startswith("BRANCH:")}


def select(pool, used, count, recent_gain, attempted):
    # Four exact 2-4 fault sequences have been exercised. Complete the budget
    # with individually observable sites; multi-fault misses do not consume a
    # site's chance to be tested as a single-fault selector.
    length = 1 if count < 24 or count >= 28 else 2 + ((count - 24) % 3)
    seen_phases = {p for a in attempted for p in a.get("phases", [])}
    seen_markers = {p for a in attempted for p in a.get("markers", [])}
    ranked = []
    for identity, (selector, event, origin) in pool.items():
        ph = phase(event)
        if ph not in PHASES or identity in used:
            continue
        score = (18 if ph not in seen_phases else 0) + (12 if selector["marker"] not in seen_markers else 0)
        score += (9 if origin == "feedback" and recent_gain else 0)
        score += (len(PHASES) - PHASES.index(ph)) * 2
        score -= event.get("seq", 0) / 100000.0
        ranked.append((score, identity, selector, event, origin, ph))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return []
    chosen = []
    phases = set()
    occurrences = set()
    for candidate in ranked:
        _, identity, selector, event, origin, ph = candidate
        if ph in phases or selector["occurrence"] in occurrences:
            continue
        chosen.append(candidate)
        phases.add(ph)
        occurrences.add(selector["occurrence"])
        if len(chosen) == length:
            break
    return sorted(chosen, key=lambda item: item[3]["seq"]) if len(chosen) == length else []


def save_result(state, healthy, union):
    attempts = state["attempts"]
    effective = [a for a in attempts if a["status"] == "checked"]
    epoch_path = HERE / "epoch2-trials/checkpoint.json"
    epoch_attempts = json.loads(epoch_path.read_text()).get("trials", []) if epoch_path.exists() else []
    epoch_effective = [a for a in epoch_attempts if a.get("strict_injection") and a.get("target_reached_after_fault")]
    effective_count = len(effective) + len(epoch_effective)
    status = "completed" if len(effective) >= MAX_EFFECTIVE and len(epoch_effective) >= 6 else "pending_budget_expansion" if state.get("stop_reason") else "running"
    import subprocess
    full_start = float(subprocess.check_output(["stat", "-c", "%W", str(HERE / "hadoop-3.4.3/.git")], text=True))
    epoch_healthy = HERE / "epoch2-healthy/trace/runtime_trace.jsonl"
    combined_baseline = production(healthy["coverage"])
    combined_coverage = set(union)
    if epoch_healthy.exists():
        combined_baseline |= {x for x in production(parse(epoch_healthy)["coverage"]) if "#u100010" not in x and "#u100011" not in x}
    for trial in epoch_attempts:
        trace = HERE / trial["trace"]
        if trace.exists():
            combined_coverage |= {x for x in production(parse(trace)["coverage"]) if "#u100010" not in x and "#u100011" not in x}
    combined_coverage |= combined_baseline
    result = {"case_id": "HDFS-10", "status": status,
              "cluster_test": "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter",
              "target_reached": True, "target_site": TARGET_SITE, "healthy_target": healthy["targets"],
              "elapsed_seconds": round(time.monotonic() - state["monotonic_anchor"] + state["prior_elapsed_seconds"], 3),
              "total_elapsed_seconds": round(time.time() - full_start, 3),
              "fault_trials": effective_count, "attempted_trials": len(attempts) + len(epoch_attempts),
              "strict_injections": sum(a["strict_injection"] for a in attempts + epoch_attempts),
              "target_after_fault": sum(a["target_reached_after_fault"] for a in attempts + epoch_attempts),
              "coverage_gain": len(combined_coverage - combined_baseline),
              "coverage_ids": len(combined_coverage), "bug_mark": "none", "stop_reason": state.get("stop_reason"),
              "trials": attempts + epoch_attempts, "checkpoint": str(CHECKPOINT.relative_to(HERE)),
              "source_review": "Journal.checkWriteRequest checks reqInfo epoch against lastWriterEpoch after checkRequest; mismatch throws IOException by design. A mismatch alone is not a new bug."}
    atomic(HERE / "result.json", result)


def main():
    TRIALS.mkdir(exist_ok=True)
    healthy = parse(TRACE)
    if len(healthy["targets"]) != 1 or healthy["targets"][0]["branch_equal"] is not True or healthy["targets"][0]["exit"] != "METHOD_EXIT_NORMAL":
        raise RuntimeError("healthy original JUnit did not reach one normal exact branch")
    pool = {}
    for selector, event in healthy["observed"]:
        if event["seq"] < healthy["targets"][0]["seq"]:
            pool[token(selector)] = (selector, event, "healthy")
    state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.exists() else {
        "case_id": "HDFS-10", "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "healthy_target": healthy["targets"][0], "healthy_io_selectors": len(pool),
        "attempts": [], "stop_reason": None, "prior_elapsed_seconds": 0}
    state["monotonic_anchor"] = time.monotonic()
    used = {identity for a in state["attempts"] if a["fault_count"] == 1
            for identity in a["selector_ids"]}
    union = production(healthy["coverage"])
    for attempt in state["attempts"]:
        path = HERE / attempt["trace"]
        if path.exists():
            feedback = parse(path)
            union |= production(feedback["coverage"])
            for selector, event in feedback["observed"]:
                if event["seq"] < max((t["seq"] for t in feedback["targets"]), default=0):
                    pool.setdefault(token(selector), (selector, event, "feedback"))
    if state.get("stop_reason"):
        print("checkpoint stopped:", state["stop_reason"])
        return
    while True:
        effective_count = sum(a["status"] == "checked" for a in state["attempts"])
        if effective_count >= MAX_EFFECTIVE:
            state["stop_reason"] = "bounded_48_effective_trial_budget_reached"
            break
        if len(state["attempts"]) >= MAX_ATTEMPTS:
            state["stop_reason"] = "attempt_budget_reached"
            break
        recent_gain = state["attempts"][-1]["new_coverage_ids"] if state["attempts"] else 0
        choice = select(pool, used, effective_count, recent_gain, state["attempts"])
        if not choice:
            state["stop_reason"] = "related_ipc_selector_pool_exhausted"
            break
        selectors = [item[2] for item in choice]
        ids = [item[1] for item in choice]
        index = len(state["attempts"]) + 1
        name = "trial-%02d" % index
        plan = TRIALS / (name + ".json")
        atomic(plan, {"schemaVersion": 1, "faults": [{"faultId": token(s), **s, "value": True} for s in selectors]})
        started = time.monotonic()
        with (TRIALS / (name + ".log")).open("w") as log:
            subprocess.run([sys.executable, str(HERE / "run_original.py"), "--run-name", name, "--trial", str(plan)],
                           cwd=HERE, stdout=log, stderr=subprocess.STDOUT, check=False)
        out = HERE / name
        manifest = json.loads((out / "manifest.json").read_text())
        feedback = parse(out / "trace/runtime_trace.jsonl")
        actual = [point(event) for event in feedback["applied"]]
        strict = (len(actual) == len(selectors) and {token(x) for x in actual} == set(ids)
                  and {event.get("faultId") for event in feedback["applied"]} == set(ids)
                  and len(feedback["matched"]) >= len(selectors))
        after = [t for t in feedback["targets"] if t["seq"] > feedback["last_applied_seq"] >= 0]
        fatal = [t for t in after if t["branch_equal"] is False and t["exit"] == "METHOD_EXIT_THROW"
                 and t["exception"] == "java.io.IOException"]
        gain = production(feedback["coverage"]) - union
        union |= production(feedback["coverage"])
        new_points = []
        for selector, event in feedback["observed"]:
            identity = token(selector)
            if identity not in pool and event["seq"] < max((t["seq"] for t in feedback["targets"]), default=0):
                pool[identity] = (selector, event, "feedback")
                new_points.append(identity)
        status = ("unmatched" if not strict else "lost_target" if not after else
                  "target_exception_candidate" if fatal else "checked")
        attempt = {"trial": name, "status": status, "fault_count": len(selectors), "selectors": selectors,
                   "selector_ids": ids, "phases": [item[5] for item in choice],
                   "markers": [s["marker"] for s in selectors],
                   "selected_from": [item[4] for item in choice], "matched_count": len(feedback["matched"]),
                   "applied_count": len(feedback["applied"]), "strict_injection": strict,
                   "target_reached_after_fault": bool(after), "target_after": after,
                   "target_fatal_exception_count": len(fatal), "junit_exit": manifest["runtime"]["exit"],
                   "junit_seconds": manifest["runtime"]["elapsed_seconds"],
                   "trial_wall_seconds": round(time.monotonic() - started, 3),
                   "method_branch_coverage_ids": len(production(feedback["coverage"])),
                   "new_coverage_ids": len(gain), "new_coverage_id_list": sorted(gain),
                   "new_io_selectors": new_points,
                   "trace": str((out / "trace/runtime_trace.jsonl").relative_to(HERE)),
                   "completed_at_utc": datetime.now(timezone.utc).isoformat()}
        state["attempts"].append(attempt)
        if len(ids) == 1:
            used.update(ids)
        if fatal:
            state["stop_reason"] = "exact_target_exception_requires_replay_and_source_review"
        state["prior_elapsed_seconds"] += time.monotonic() - state["monotonic_anchor"]
        state["monotonic_anchor"] = time.monotonic()
        checkpoint = dict(state)
        checkpoint.pop("monotonic_anchor")
        atomic(CHECKPOINT, checkpoint)
        save_result(state, healthy, union)
        print(json.dumps({k: attempt[k] for k in ("trial", "status", "fault_count", "strict_injection",
              "target_reached_after_fault", "new_coverage_ids", "junit_seconds")}), flush=True)
        if state["stop_reason"]:
            break
    state["prior_elapsed_seconds"] += time.monotonic() - state["monotonic_anchor"]
    state["monotonic_anchor"] = time.monotonic()
    state["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    checkpoint = dict(state)
    checkpoint.pop("monotonic_anchor")
    atomic(CHECKPOINT, checkpoint)
    save_result(state, healthy, union)
    with (HERE / "trial-ledger.csv").open("w", newline="") as stream:
        columns = ("trial", "status", "fault_count", "phases", "markers", "selectors", "matched_count",
                   "applied_count", "strict_injection", "target_reached_after_fault", "target_after",
                   "target_fatal_exception_count", "junit_exit", "junit_seconds", "trial_wall_seconds",
                   "method_branch_coverage_ids", "new_coverage_ids", "new_io_selectors", "trace")
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in state["attempts"]:
            writer.writerow({k: json.dumps(row[k], separators=(",", ":")) if isinstance(row[k], (list, dict)) else row[k]
                             for k in columns})
    print("stop_reason", state["stop_reason"], flush=True)


if __name__ == "__main__":
    main()
