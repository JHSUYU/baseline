#!/usr/bin/env python3
"""Merge completed HDFS-10 runtime campaigns, preserving all trial evidence."""
from __future__ import annotations
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import time

from campaign import HERE, TARGET_SITE, atomic, parse, production
from epoch_campaign import all_targets


def clean_coverage(path):
    return {x for x in production(parse(path)["coverage"]) if "#u100010" not in x and "#u100011" not in x}


def main():
    ipc = json.loads((HERE / "trials/checkpoint.json").read_text())
    epoch = json.loads((HERE / "epoch2-trials/checkpoint.json").read_text())
    ipc_trials = ipc["attempts"]
    epoch_trials = epoch["trials"]
    effective_ipc = [x for x in ipc_trials if x["status"] == "checked"]
    effective_epoch = [x for x in epoch_trials if x["strict_injection"] and x["target_reached_after_fault"]]
    if len(effective_ipc) != 42 or len(effective_epoch) != 6:
        raise RuntimeError("expected 42 effective IPC and six effective epoch file trials")
    if any(not x["strict_injection"] or not x["target_reached_after_fault"] for x in effective_ipc + effective_epoch):
        raise RuntimeError("an effective trial lost strict injection or target")
    seeds = [HERE / "healthy/trace/runtime_trace.jsonl", HERE / "epoch2-healthy/trace/runtime_trace.jsonl"]
    baseline = set().union(*(clean_coverage(path) for path in seeds))
    union = set(baseline)
    all_trials = []
    for trial in ipc_trials:
        trace = HERE / trial["trace"]
        union |= clean_coverage(trace)
        target_events = all_targets(trace)
        direct_markers = [event for event in parse(trace)["applied"]]
        last = max((event["seq"] for event in direct_markers), default=-1)
        after = [event for event in target_events if event["seq"] > last >= 0]
        exceptions = [event for event in after if event["branch_equal"] is False
                      and event["exit"] == "METHOD_EXIT_THROW" and event["exception"] == "java.io.IOException"]
        record = dict(trial)
        record["family"] = "IPC response"
        record["trace_mode"] = "region-state" if int(trial["trial"].split("-")[-1]) <= 30 else "discovery"
        record["all_targets_after_fault"] = after
        record["expected_guard_exception_count"] = len(exceptions)
        if trial["trial"] == "trial-26":
            record["junit_failure_review"] = ("Original JUnit failed after the selected target returned normally: "
                "QuorumOutputStream.flushAndSync raised QuorumException with one successful and two failed "
                "JournalNode responses under three matched IPC faults. This is the documented 2-of-3 quorum condition, "
                "not the checkWriteRequest IOException guard.")
        all_trials.append(record)
    for trial in epoch_trials:
        trace = HERE / trial["trace"]
        union |= clean_coverage(trace)
        record = dict(trial)
        record["family"] = "last-writer-epoch file operation"
        record["trace_mode"] = "region-state"
        all_trials.append(record)
    start = (HERE / "hadoop-3.4.3/.git").stat().st_birthtime if hasattr((HERE / "hadoop-3.4.3/.git").stat(), "st_birthtime") else None
    if start is None:
        # Linux statx birth time is exposed by the command line stat tool.
        import subprocess
        start = float(subprocess.check_output(["stat", "-c", "%W", str(HERE / "hadoop-3.4.3/.git")], text=True))
    end = time.time()
    exception_ipc = sum(row["expected_guard_exception_count"] for row in all_trials if row["family"] == "IPC response")
    exception_epoch = sum(row["expected_guard_exception_count"] for row in all_trials if row["family"] == "last-writer-epoch file operation")
    result = {"case_id": "HDFS-10", "status": "completed", "system": "Hadoop HDFS 3.4.3",
              "source_ref": "rel/release-3.4.3 (9d50c6884666e794e45102260a4017bb31802e1b)",
              "cluster_test": "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#testSingleWriter",
              "target_site": TARGET_SITE, "target_reached": True,
              "healthy_target": parse(seeds[0])["targets"],
              "started_at_utc": datetime.fromtimestamp(start, timezone.utc).isoformat(),
              "finished_at_utc": datetime.fromtimestamp(end, timezone.utc).isoformat(),
              "elapsed_seconds": round(end - start, 3),
              "total_elapsed_seconds": round(end - start, 3),
              "fault_trials": len(effective_ipc) + len(effective_epoch),
              "attempted_trials": len(all_trials),
              "strict_injections": sum(x["strict_injection"] for x in all_trials),
              "target_after_fault": sum(x["target_reached_after_fault"] for x in all_trials),
              "coverage_gain": len(union - baseline), "healthy_coverage_ids": len(baseline),
              "coverage_ids": len(union), "expected_guard_exceptions": exception_ipc + exception_epoch,
              "effective_junit_failures": sum(t["junit_exit"] != 0 for t in all_trials
                                              if t["status"] in ("checked", "expected_guard_exception")),
              "trace_mode_validation": "discovery-validation.json",
              "bug_mark": "none", "stop_reason": "bounded_48_effective_trial_budget_reached",
              "source_review": {
                  "guard": "Journal.java:514-522 checkWriteRequest compares RequestInfo.epoch to PersistentLongFile lastWriterEpoch; mismatch throws IOException at lines 518-520.",
                  "state_transition": "Journal.java:606-611 startLogSegment sets lastWriterEpoch before creating the segment. An injected file write failure leaves this node's value at 0 while the client sends epoch 1.",
                  "test_behavior": "The unchanged testSingleWriter runs two segments on three JournalNodes. QuorumOutputStream waits for a write majority; IPCLoggerChannel records one failed remote journal and retries after the next log roll.",
                  "fault_legality": "Client.getRpcResponse and PersistentLongFile.writeFile declare IOException, permitting IOException subclasses. AtomicFileOutputStream(File) declares FileNotFoundException, so only that type is counted at the constructor. Earlier generic IOException constructor probes are excluded.",
                  "junit_failure": "IPC trial-26 reached and returned from the exact target after all three faults, then failed with QuorumException: two of three responses failed at QuorumOutputStream.flushAndSync. It is a quorum failure caused by the injected responses, not this epoch guard.",
                  "assessment": "The observed epoch mismatch IOException is the intended guard response to a failed writer-epoch write. Clean replay reproduced it and the original JUnit completed; no new coordination bug is established."},
              "families": {"ipc_response": {"effective_trials": len(effective_ipc), "attempts": len(ipc_trials),
                                            "guard_exceptions": exception_ipc},
                           "last_writer_epoch_file": {"effective_trials": len(effective_epoch),
                                                      "attempts": len(epoch_trials),
                                                      "guard_exceptions": exception_epoch}},
              "trials": all_trials,
              "evidence": {"ipc_checkpoint": "trials/checkpoint.json",
                           "epoch_checkpoint": "epoch2-trials/checkpoint.json",
                           "combined_ledger": "trial-ledger.csv",
                           "healthy_trace": "healthy/trace/runtime_trace.jsonl",
                           "epoch_healthy_trace": "epoch2-healthy/trace/runtime_trace.jsonl",
                           "bytecode": "original-Journal-javap.txt",
                           "epoch_patch_proof": "epoch-door/patched-javap.txt",
                           "excluded_probe_checkpoint": "epoch-trials/checkpoint.json",
                           "trace_mode_equivalence": "discovery-validation.json"}}
    atomic(HERE / "result.json", result)
    columns = ("trial", "family", "trace_mode", "status", "fault_count", "selector", "selectors", "matched_count",
               "applied_count", "strict_injection", "target_reached_after_fault",
               "expected_guard_exception_count", "junit_exit", "junit_seconds", "trial_wall_seconds",
               "method_branch_coverage_ids", "new_coverage_ids", "junit_failure_review", "trace")
    with (HERE / "trial-ledger.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for trial in all_trials:
            writer.writerow({key: json.dumps(trial.get(key), separators=(",", ":")) if isinstance(trial.get(key), (list, dict))
                             else trial.get(key) for key in columns})
    print(json.dumps({key: result[key] for key in ("case_id", "status", "fault_trials", "strict_injections",
          "target_after_fault", "coverage_gain", "expected_guard_exceptions", "bug_mark", "elapsed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
