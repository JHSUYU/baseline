#!/usr/bin/env python3
"""Small resumable graph-free I/O and coverage campaign for HDFS-54.

The known-bug reproduction is a calibration seed. Extra fault trials are
mutations at I/O events observed in that seed, not claims of new bugs.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
STATE = HERE / "campaign-state.json"
RUNS = HERE / "campaign-runs"
TARGET = "FileChecksumHelper$StripedFileNonStripedChecksumComputer.checksumBlocks#L629"
SOURCE = "hdfs/datanode-group"


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)


def rows(path):
    if not path.exists():
        return []
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def covered(path):
    if not path.exists():
        return set()
    return set(path.read_text().splitlines())


def summarize(output, seed=None):
    manifest = json.loads((output / "manifest.json").read_text())
    events = rows(output / "runtime_trace.jsonl")
    log = (output / "junit.log").read_text(errors="replace")
    key_id = None
    for line in log.splitlines():
        if "CONTROL cached_key_id=" in line:
            key_id = int(line.split("CONTROL cached_key_id=")[-1].split()[0])
    first_fault = next((i for i, e in enumerate(events)
                        if e.get("event") == "FAULT_APPLIED"), None)
    relevant = events[first_fault + 1:] if first_fault is not None else events
    matched_target = [e for e in relevant if e.get("event") == "TARGET_CHECK"
                      and e.get("keyId") == key_id and not e.get("keyPresent")]
    target_throws = [e for e in relevant if e.get("event") == "TARGET_THROW"]
    striped_checks = [e for e in relevant if e.get("event") == "STRIPED_CHECK"
                      and e.get("siteId") == TARGET]
    dn_map = {}
    for line in log.splitlines():
        if "CONTROL dn_identity=" in line:
            part = line.split("CONTROL dn_identity=")[-1]
            if " managerIdentity=" in part:
                dn, other = part.split(" managerIdentity=", 1)
                dn_map[other.split()[0]] = dn
    runtime_dns = sorted({dn_map.get(str(e.get("managerIdentity")), "unknown")
                          for e in matched_target})
    gain = {}
    if seed is not None:
        for category in ("probes", "methods", "branch_counts", "lines"):
            file = "covered_" + category + ".txt"
            gain[category] = len(covered(output / file) - covered(seed / file))
    io = [e for e in events if e.get("event") == "FAULT_POINT_OBSERVED"
          and e.get("phase") == "postExpiry"]
    return {
        "elapsed_seconds": manifest["elapsed_seconds"],
        "returncode": manifest["returncode"],
        "mode": manifest["mode"],
        "key_id": key_id,
        "dn_identity_map": dn_map,
        "target_guard_null_for_cached_key": len(matched_target),
        "target_throw_after_fault": len(target_throws),
        "target_check_after_fault": len(striped_checks),
        "target_false_after_fault": sum(not e.get("completed") for e in striped_checks),
        "generic_stale_key_catches_after_fault": sum(
            e.get("event") == "STRIPED_IO_EXCEPTION"
            and e.get("exception", "").endswith("InvalidEncryptionKeyException")
            for e in relevant),
        "matched_faults": sum(e.get("event") == "FAULT_MATCHED" for e in events),
        "applied_faults": sum(e.get("event") == "FAULT_APPLIED" for e in events),
        "runtime_dn_identities": runtime_dns,
        "post_expiry_io_points": len(io),
        "post_expiry_io_sites": sorted(set(e.get("siteId") for e in io)),
        "coverage_gain_vs_seed": gain,
        "operation_failed": "CONTROL post_expiry_exception=" in log,
        "repeat_failed": "CONTROL repeated_failure=" in log,
        "operation_recovered": "CONTROL outcome=fixed_recovered" in log,
        "patched_retry_seen": "CONTROL patched_clear_and_retry_bg=" in log,
        "junit_ok": "OK (1 test)" in log,
        "sha256_log": hashlib.sha256((output / "junit.log").read_bytes()).hexdigest(),
        "sha256_trace": hashlib.sha256((output / "runtime_trace.jsonl").read_bytes()).hexdigest(),
    }


def make_mutations(seed):
    events = rows(seed / "runtime_trace.jsonl")
    possibilities = []
    for e in events:
        if e.get("event") != "FAULT_POINT_OBSERVED" or e.get("phase") != "postExpiry":
            continue
        key = (e["marker"], e["siteId"], e["sourceKey"], e["hitOrdinal"])
        if key not in possibilities:
            possibilities.append(key)
    # These are distinct SASL I/O families, chosen only if observed in the seed.
    preferred = ("readSecret", "readOptions", "readMagic")
    selected = []
    for ordinal in (1, 2):
        for suffix in preferred:
            for key in possibilities:
                if key[1].endswith(suffix) and key[3] == ordinal:
                    selected.append(key)
                    break
    for number, key in enumerate(selected, 1):
        plan = HERE / "plans" / ("mutation-%02d.tsv" % number)
        plan.parent.mkdir(exist_ok=True)
        plan.write_text("\t".join(map(str, (*key, "IOException"))) + "\n")
    return [str(HERE / "plans" / ("mutation-%02d.tsv" % n))
            for n in range(1, len(selected) + 1)]


def prioritize_followups(plans, state):
    """Prefer a second occurrence in the I/O family whose first fault kept
    the target and exposed more code. The score is runtime feedback, not a
    static graph. Unreplayed candidates remain in the checkpointed queue.
    """
    by_id = {row["id"]: row for row in state["trials"]}
    first = plans[:3]
    second = list(enumerate(plans[3:], 4))
    def score(item):
        number, _ = item
        parent = by_id.get("mutation-%02d" % (number - 3))
        if parent is None:
            return -1
        data = parent["summary"]
        gain = data["coverage_gain_vs_seed"]
        return ((1000 if parent["result"] == "target_retaining_fault_trial" else 0)
                + 10 * gain.get("methods", 0) + gain.get("branch_counts", 0))
    second.sort(key=score, reverse=True)
    return [(i, path) for i, path in enumerate(first, 1)] + second


def write_ledger(state):
    with (HERE / "trial-ledger.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("trial", "mode", "elapsed_seconds", "fault_applied",
                         "HDFS11_null_key", "HDFS54_false_check", "operation_failed",
                         "operation_recovered", "coverage_method_gain", "result"))
        for entry in state["trials"]:
            data = entry["summary"]
            writer.writerow((entry["id"], data["mode"], data["elapsed_seconds"],
                             data["applied_faults"], data["target_guard_null_for_cached_key"],
                             data["target_false_after_fault"], data["operation_failed"],
                             data["operation_recovered"],
                             data["coverage_gain_vs_seed"].get("methods", 0),
                             entry["result"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-mutants", type=int, default=3)
    args = parser.parse_args()
    RUNS.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        "case_id": "HDFS-54", "bug_id": "HDFS-17897", "new_bug": False,
        "source_version": "3.4.3", "graph_used": False,
        "budget": {"max_mutants": args.max_mutants, "faults_per_mutant": 1},
        "trials": [], "status": "running"}
    state["budget"]["max_mutants"] = args.max_mutants
    state["status"] = "running"
    atomic(STATE, state)
    seed = RUNS / "seed-original"
    sequence = [("seed-original", "original", None),
                ("fixed-control", "fixed", None)]
    for name, mode, plan in sequence:
        if any(e["id"] == name for e in state["trials"]):
            continue
        output = RUNS / name
        started = time.monotonic()
        command = [sys.executable, str(HERE / "run_control.py"),
                   "--mode", mode, "--output", str(output)]
        recovered = (output / "manifest.json").exists()
        if not recovered:
            with (output.parent / (name + ".runner.log")).open("w") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if not (output / "manifest.json").exists():
            state["status"] = "runner_error"
            atomic(STATE, state)
            return
        data = summarize(output, seed if name != "seed-original" else None)
        result = "known_bug_reproduced" if name == "seed-original" and (
            data["target_guard_null_for_cached_key"] > 0
            and data["target_false_after_fault"] > 0 and data["operation_failed"]
            and data["repeat_failed"] and data["junit_ok"]) else (
            "fix_control_recovered" if name == "fixed-control" and (
                data["target_guard_null_for_cached_key"] > 0
                and data["operation_recovered"] and data["patched_retry_seen"]
                and data["junit_ok"]) else "not_confirmed")
        state["trials"].append({"id": name, "plan": plan, "summary": data,
                               "recovered_existing_run": recovered,
                               "wall_seconds": round(time.monotonic() - started, 3),
                               "result": result})
        atomic(STATE, state)
        write_ledger(state)
    plans = make_mutations(seed)
    for i, plan in prioritize_followups(plans, state)[:args.max_mutants]:
        name = "mutation-%02d" % i
        if any(e["id"] == name for e in state["trials"]):
            continue
        output = RUNS / name
        command = [sys.executable, str(HERE / "run_control.py"), "--mode", "original",
                   "--output", str(output), "--plan", plan]
        started = time.monotonic()
        recovered = (output / "manifest.json").exists()
        if not recovered:
            with (output.parent / (name + ".runner.log")).open("w") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if not (output / "manifest.json").exists():
            state["status"] = "runner_error"
            atomic(STATE, state)
            return
        data = summarize(output, seed)
        result = ("target_retaining_fault_trial" if data["applied_faults"] > 0
                  and data["target_guard_null_for_cached_key"] > 0
                  and data["target_false_after_fault"] > 0
                  and data["operation_failed"] and data["junit_ok"]
                  else "nonretaining_or_inconclusive")
        state["trials"].append({"id": name, "plan": plan, "summary": data,
                               "recovered_existing_run": recovered,
                               "wall_seconds": round(time.monotonic() - started, 3),
                               "result": result})
        atomic(STATE, state)
        write_ledger(state)
    state["status"] = "complete"
    atomic(STATE, state)


if __name__ == "__main__":
    main()
