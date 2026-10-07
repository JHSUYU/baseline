#!/usr/bin/env python3
"""Resumable, graph-free fault/coverage campaign for the original EC JUnit.

One trial always reruns the unchanged Hadoop TestFileChecksum method in its
own MiniDFSCluster. Plans name observed checksum RPC points, never elapsed
time. The known HDFS-17897 reproduction lives in the parent case and is not
inferred from this synthetic-I/O campaign.
"""

import argparse
import csv
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
FAULT_TYPES = ("IOException", "EOFException", "SocketTimeoutException",
               "InvalidEncryptionKeyException")
SITE = "FileChecksumHelper$StripedFileNonStripedChecksumComputer.checksumBlocks#L629"
FIELDS = ("file", "blockGroup", "dnRole", "site", "ordinal")
DEFAULT_RUNS = Path("/users/ZhenyuLi/hdfs54-original-campaign/runs")


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def load_events(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def tokens(path):
    return set(path.read_text().splitlines()) if path.exists() else set()


def fault_key(fault):
    return tuple(str(fault[key]) for key in FIELDS) + (fault["type"],)


def plan_id(faults):
    data = json.dumps([fault_key(fault) for fault in faults], separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def as_fault(event, fault_type):
    return {key: event[key] for key in FIELDS} | {"type": fault_type}


def write_plan(path, faults):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join("\t".join(fault_key(fault)) for fault in faults) + "\n")


def initial_state(runs, effective_budget, max_faults, attempt_cap):
    healthy = runs / "healthy-01"
    manifest_path = healthy / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("healthy-01/manifest.json missing; run original JUnit healthy first")
    manifest = json.loads(manifest_path.read_text())
    if (manifest["junit"] != {"runs": 1, "failures": 0, "ignored": 0}
            or manifest["junit_exit"] != 0 or manifest["target_checks"] < 1
            or manifest["requested_faults"] != 0 or not manifest["strict_ordered"]):
        raise RuntimeError("healthy original JUnit/target evidence invalid")
    events = load_events(healthy / "runtime_trace.jsonl")
    targets = [e for e in events if e.get("event") == "TARGET_CHECK"
               and e.get("siteId") == SITE and e.get("completed")]
    if not targets:
        raise RuntimeError("healthy exact HDFS-54 target missing")
    target_file = targets[0]["file"]
    io = [e for e in events if e.get("event") == "IO_OBSERVED"
          and e.get("file") == target_file and e["seq"] < targets[0]["seq"]]
    if not io:
        raise RuntimeError("healthy checksum RPC I/O points missing")
    queue = []
    for event in io:
        for fault_type in FAULT_TYPES:
            faults = [as_fault(event, fault_type)]
            queue.append({"id": plan_id(faults), "faults": faults,
                          "parent": "healthy-01", "added_round": 0,
                          "retry_count": 0})
    return {"schema": 1, "test": manifest["test"], "source_tag": manifest["source_tag"],
            "target_site": SITE, "target_file": target_file,
            "original_test_jar_sha256": manifest["test_jar_sha256"],
            "healthy": str(healthy), "effective_budget": effective_budget,
            "max_faults": max_faults, "attempt_cap": attempt_cap,
            "effective": 0, "attempts": [], "queue": queue,
            "seen_plans": sorted(item["id"] for item in queue),
            "global_coverage": {kind: sorted(tokens(healthy / ("covered_" + kind + ".txt")))
                                for kind in ("probes", "methods", "branch_counts")},
            "global_io_sites": sorted({(e["dnRole"], e["site"]) for e in io}),
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "in_flight": None}


def score(candidate, state):
    parent = next((entry for entry in reversed(state["attempts"])
                   if entry["id"] == candidate["parent"]), None)
    novelty = parent.get("coverage_gain", {}) if parent else {}
    n = len(candidate["faults"])
    last = candidate["faults"][-1]
    applied_families = [fault for row in state["attempts"]
                        if row.get("strict_ordered")
                        and row.get("applied") == row.get("requested")
                        for fault in row["faults"]]
    prior_roles = {fault["dnRole"] for fault in applied_families}
    prior_role_sites = {(fault["dnRole"], fault["site"])
                        for fault in applied_families}
    prior_role_site_types = {(fault["dnRole"], fault["site"], fault["type"])
                             for fault in applied_families}
    role_site = (last["dnRole"], last["site"])
    family = (*role_site, last["type"])
    distinct_roles = len({fault["dnRole"] for fault in candidate["faults"]})
    wait_rounds = len(state["attempts"]) - candidate["added_round"]
    # A nine-DN sequence can exhaust every checksum source and take the
    # expected false branch. Treat plans with the same ordered actor/site
    # path as one recovery family, regardless of synthetic exception subtype.
    # Explore two representatives, then let other I/O paths and coverage
    # seeds compete before revisiting equivalent terminal failures.
    actor_site_path = tuple((fault["dnRole"], fault["site"])
                            for fault in candidate["faults"])
    exhausted_equivalents = sum(
        prior.get("result") == "effective"
        and prior.get("target_false_after_final_fault", 0) > 0
        and tuple((fault["dnRole"], fault["site"])
                  for fault in prior["faults"]) == actor_site_path
        and prior["faults"][0]["file"] == candidate["faults"][0]["file"]
        and prior["faults"][0]["blockGroup"] == candidate["faults"][0]["blockGroup"]
        for prior in state["attempts"])
    # The original RS-6+3 checksum may need all nine located DNs to fail.
    # Favor new actor/site families and deep sequences, while capping one
    # parent's coverage windfall so its many sibling exception variants do
    # not consume the whole budget. Bounded wait credit retains exploration.
    return (900 * (last["dnRole"] not in prior_roles)
            + 700 * (role_site not in prior_role_sites)
            + 120 * (family not in prior_role_site_types)
            + 20 * min(novelty.get("probes", 0), 30)
            + 40 * min(novelty.get("methods", 0), 10)
            + 2 * min(novelty.get("branch_counts", 0), 40)
            + 140 * min(n, 9) - 180 * max(0, n - 9)
            + 160 * distinct_roles + 1500 * (n >= 9)
            - 1200 * (n >= 9 and exhausted_equivalents >= 2)
            + min(400, 10 * wait_rounds)
            - (parent.get("seconds", 0) / 10 if parent else 0))


def add_mutations(state, candidate, events, last_fault_seq):
    if len(candidate["faults"]) >= state["max_faults"]:
        return 0
    target_after = [event["seq"] for event in events
                    if event.get("event") == "TARGET_CHECK"
                    and event.get("siteId") == SITE
                    and event.get("file") == state["target_file"]
                    and event["seq"] > last_fault_seq]
    if not target_after:
        return 0
    end_seq = min(target_after)
    seen = set(state["seen_plans"])
    added = 0
    for event in events:
        if (event.get("event") != "IO_OBSERVED" or event["seq"] <= last_fault_seq
                or event["seq"] >= end_seq
                or event.get("file") != state["target_file"]):
            continue
        for fault_type in FAULT_TYPES:
            faults = candidate["faults"] + [as_fault(event, fault_type)]
            identifier = plan_id(faults)
            if identifier in seen:
                continue
            state["queue"].append({"id": identifier, "faults": faults,
                                   "parent": candidate["id"],
                                   "added_round": len(state["attempts"]),
                                   "retry_count": 0})
            seen.add(identifier)
            added += 1
    state["seen_plans"] = sorted(seen)
    return added


def summarize(state, candidate, run_dir):
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if (manifest["test"] != state["test"]
            or manifest["source_tag"] != state["source_tag"]
            or manifest["test_jar_sha256"] != state["original_test_jar_sha256"]
            or not manifest["original_test_unmodified"]
            or manifest["graph_used"]):
        raise RuntimeError("trial source/workload identity differs from healthy")
    events = load_events(run_dir / "runtime_trace.jsonl")
    faults = [e for e in events if e.get("event") == "FAULT_APPLIED"]
    last_seq = faults[-1]["seq"] if faults else -1
    target = [e for e in events if e.get("event") == "TARGET_CHECK"
              and e.get("siteId") == SITE and e.get("file") == state["target_file"]
              and e["seq"] > last_seq]
    full = (manifest["strict_ordered"]
            and manifest["requested_faults"] == len(candidate["faults"])
            and manifest["applied_faults"] == len(candidate["faults"])
            and all(fault_key(event) == fault_key(planned)
                    for event, planned in zip(faults, candidate["faults"])))
    effective = full and bool(target)
    gains = {}
    for kind in ("probes", "methods", "branch_counts"):
        newly = tokens(run_dir / ("covered_" + kind + ".txt"))
        previous = set(state["global_coverage"][kind])
        gains[kind] = len(newly - previous)
        if effective:
            state["global_coverage"][kind] = sorted(previous | newly)
    observed = {(e["dnRole"], e["site"]) for e in events
                if e.get("event") == "IO_OBSERVED" and e.get("file") == state["target_file"]}
    if effective:
        state["global_io_sites"] = sorted(set(map(tuple, state["global_io_sites"])) | observed)
    record = {"id": candidate["id"], "parent": candidate["parent"],
              "faults": candidate["faults"], "run": str(run_dir),
              "seconds": manifest["elapsed_seconds"],
              "junit_exit": manifest["junit_exit"], "junit": manifest["junit"],
              "requested": manifest["requested_faults"],
              "matched": manifest["matched_faults"],
              "applied": manifest["applied_faults"],
              "strict_ordered": full, "target_after_final_fault": len(target),
              "target_false_after_final_fault": sum(not e["completed"] for e in target),
              "target_completed_after_final_fault": sum(e["completed"] for e in target),
              "coverage": manifest["coverage"], "coverage_gain": gains,
              "observed_io": manifest["observed_io"],
              "review_status": ("needs_source_and_replay"
                                if any(not e["completed"] for e in target)
                                else "not_applicable"),
              "result": "effective" if effective else (
                  "target_lost" if full else "fault_unmatched"),
              "completed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return record, events, last_seq


def ledger(state, runs):
    path = runs / "trial-ledger.csv"
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("trial", "id", "faults", "elapsed_seconds", "requested",
                         "matched", "applied", "strict_ordered", "target_postfault",
                         "target_false", "coverage_probe_gain", "coverage_method_gain",
                         "coverage_branch_gain", "junit_failures", "result", "run_dir"))
        for index, row in enumerate(state["attempts"], 1):
            writer.writerow((index, row["id"], len(row["faults"]), row["seconds"],
                             row["requested"], row["matched"], row["applied"],
                             row["strict_ordered"], row["target_after_final_fault"],
                             row["target_false_after_final_fault"],
                             row["coverage_gain"]["probes"],
                             row["coverage_gain"]["methods"],
                             row["coverage_gain"]["branch_counts"],
                             row["junit"]["failures"] if row["junit"] else "",
                             row["result"], row["run"]))
    temp.replace(path)


def run_campaign(runs, budget, max_faults, cap, timeout, once):
    runs.mkdir(parents=True, exist_ok=True)
    with (runs / ".campaign.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = runs / "campaign-state.json"
        state = (json.loads(state_path.read_text()) if state_path.exists()
                 else initial_state(runs, budget, max_faults, cap))
        if state["test"] != "org.apache.hadoop.hdfs.TestFileChecksum#testStripedAndReplicatedFileChecksum2[0]":
            raise RuntimeError("wrong original-JUnit campaign state")
        if state["original_test_jar_sha256"] != json.loads(
                (runs / "healthy-01/manifest.json").read_text())["test_jar_sha256"]:
            raise RuntimeError("original JUnit jar changed")
        old_max_faults = state["max_faults"]
        state["effective_budget"] = max(state["effective_budget"], budget)
        state["max_faults"] = max(state["max_faults"], max_faults)
        state["attempt_cap"] = max(state["attempt_cap"], cap)
        if state["max_faults"] > old_max_faults:
            # A prior max-depth result has not yet been mutated. Reopen only
            # those successful seeds when the conditional budget is extended.
            for prior in state["attempts"]:
                if (prior["result"] != "effective"
                        or len(prior["faults"]) < old_max_faults
                        or len(prior["faults"]) >= state["max_faults"]):
                    continue
                prior_events = load_events(Path(prior["run"]) / "runtime_trace.jsonl")
                applied = [event for event in prior_events
                           if event.get("event") == "FAULT_APPLIED"]
                if applied:
                    add_mutations(state, prior, prior_events, applied[-1]["seq"])
        atomic_json(state_path, state)
        made = 0
        while (state["queue"] and state["effective"] < state["effective_budget"]
               and len(state["attempts"]) < state["attempt_cap"]):
            if state["in_flight"]:
                pending = state["in_flight"]
                candidate = pending["candidate"]
                run_dir = Path(pending["run"])
                if not (run_dir / "manifest.json").exists():
                    # Preserve an interrupted run's raw output; retry separately.
                    state["attempts"].append({
                        "id": candidate["id"], "parent": candidate["parent"],
                        "faults": candidate["faults"], "run": str(run_dir),
                        "seconds": round(time.time() - pending["started_epoch"], 3),
                        "junit_exit": None, "junit": None,
                        "requested": len(candidate["faults"]), "matched": 0,
                        "applied": 0, "strict_ordered": False,
                        "target_after_final_fault": 0,
                        "target_false_after_final_fault": 0,
                        "target_completed_after_final_fault": 0,
                        "coverage": {},
                        "coverage_gain": {kind: 0 for kind in (
                            "probes", "methods", "branch_counts")},
                        "observed_io": 0, "result": "infra_incomplete",
                        "completed_utc": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                    state["in_flight"] = None
                    candidate["retry_count"] += 1
                    if candidate["retry_count"] <= 2:
                        state["queue"].append(candidate)
                    atomic_json(state_path, state)
                    ledger(state, runs)
                    continue
            else:
                choice = max(range(len(state["queue"])),
                             key=lambda i: score(state["queue"][i], state))
                candidate = state["queue"].pop(choice)
                serial = len(state["attempts"]) + 1
                run_dir = runs / ("trial-%04d-%s-r%d" % (
                    serial, candidate["id"], candidate["retry_count"]))
                plan = runs / "plans" / (candidate["id"] + ".tsv")
                write_plan(plan, candidate["faults"])
                state["in_flight"] = {"candidate": candidate, "run": str(run_dir),
                                      "plan": str(plan), "started_epoch": time.time()}
                atomic_json(state_path, state)
                subprocess.run([sys.executable, str(HERE / "run_original.py"),
                                "--output", str(run_dir), "--plan", str(plan),
                                "--timeout", str(timeout)], check=False)
            if not (run_dir / "manifest.json").exists():
                continue
            record, events, last_seq = summarize(state, candidate, run_dir)
            state["attempts"].append(record)
            if record["result"] == "effective":
                state["effective"] += 1
                add_mutations(state, candidate, events, last_seq)
            elif record["result"] == "fault_unmatched" and candidate["retry_count"] < 2:
                retry = dict(candidate, retry_count=candidate["retry_count"] + 1)
                state["queue"].append(retry)
            state["in_flight"] = None
            atomic_json(state_path, state)
            ledger(state, runs)
            print(json.dumps({"attempt": len(state["attempts"]), "id": candidate["id"],
                              "effective": state["effective"], "queued": len(state["queue"]),
                              "result": record["result"], "target_false":
                              record["target_false_after_final_fault"],
                              "seconds": record["seconds"]}), flush=True)
            made += 1
            if once and made >= once:
                break
        print(json.dumps({"total_attempts": len(state["attempts"]),
                          "effective": state["effective"],
                          "queued": len(state["queue"]),
                          "budget": state["effective_budget"],
                          "max_faults": state["max_faults"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--effective-budget", type=int, default=80)
    parser.add_argument("--max-faults", type=int, default=8)
    parser.add_argument("--attempt-cap", type=int, default=320)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--once", type=int, default=0)
    args = parser.parse_args()
    run_campaign(args.runs.resolve(), args.effective_budget, args.max_faults,
                 args.attempt_cap, args.timeout, args.once)


if __name__ == "__main__":
    main()
