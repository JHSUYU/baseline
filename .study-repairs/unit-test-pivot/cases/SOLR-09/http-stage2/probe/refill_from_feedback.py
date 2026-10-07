#!/usr/bin/env python3
"""Replenish an exhausted queue from exact I/O seen in valid faulted runs.

The normal mutation admits only three children per run. Queue exhaustion is
therefore not evidence that all observed pre-target I/O was tried. This
checkpoint-only pass offers the remaining exact selectors without changing
any completed trial or counting hit ordinals as I/O novelty.
"""

from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import sys

from campaign import (CAMPAIGN, STATE, WORK, atomic_json, events, io_identity,
                      plan_key, rank, relevant, valid, write_results)
from feedback import sequence_applied_in_order


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def alternatives(state: dict) -> list[dict]:
    known = set(state["seen_plans"]) | {plan_key(p) for p in state["queue"]}
    per_parent = []
    for trial in state["trials"]:
        if (not valid(trial) or trial["junit_exit"] != 0 or
                len(trial["plan"]) >= state["budget"]["max_faults"]):
            continue
        trace_file = WORK / trial["evidence"] / "events.tsv"
        trace = events(trace_file)
        applied = [e for e in trace if e["kind"].startswith("IO_APPLIED_")]
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        if not sequence_applied_in_order(trial["plan"], applied, matched, trace):
            raise AssertionError(f"Parent trial {trial['number']} is not strict in raw trace")
        faults = [e["seq"] for e in applied]
        if not faults:
            continue
        last_fault = max(faults)
        targets = [e["seq"] for e in trace if e["kind"] == "TARGET_CHECK"
                   and len(e["parts"]) >= 2 and e["parts"][1] == "SOLR-09"
                   and e["seq"] > last_fault]
        if not targets:
            raise AssertionError(f"Parent trial {trial['number']} missed post-fault target")
        next_target = min(targets)
        trace_hash = sha256(trace_file.read_bytes())
        global_count, relative_count = Counter(), Counter()
        options = []
        for event in trace:
            identity = io_identity(event)
            if identity is None:
                continue
            global_count[identity] += 1
            if event["seq"] > last_fault:
                relative_count[identity] += 1
            if not (last_fault < event["seq"] < next_target and relevant(identity)
                    and len(event["parts"]) >= 3
                    and event["parts"][2].startswith("caller=")):
                continue
            operation, path = identity
            selector = (f"{operation}|{path}|@{relative_count[identity]}|"
                        f"{event['parts'][2]}|after=F{len(trial['plan']) - 1}|"
                        f"seed_global={global_count[identity]}")
            child = trial["plan"] + [selector]
            key = plan_key(child)
            if key not in known:
                if len(child) > state["budget"]["max_faults"]:
                    raise AssertionError("Child exceeds the current fault budget")
                record = {
                    "plan": child,
                    "plan_sha256": sha256(key.encode()),
                    "source_trial": trial["number"],
                    "source_trace": str(trace_file.relative_to(WORK)),
                    "source_trace_sha256": trace_hash,
                    "parent_last_fault_seq": last_fault,
                    "observed_io_seq": event["seq"],
                    "next_target_seq": next_target,
                    "stable_io_identity": "|".join((operation, path, event["parts"][2])),
                }
                options.append((rank(identity), event["seq"],
                                (operation, path, event["parts"][2]), record))
        options.sort(key=lambda item: (item[0], item[1]))
        # Try each stable callsite/operation/resource once before another hit
        # ordinal of the same I/O family. Ordinals only select fault timing.
        first, later, stable_seen = [], [], set()
        for option in options:
            stable = option[2]
            if stable in stable_seen:
                later.append(option[3])
            else:
                stable_seen.add(stable)
                first.append(option[3])
        if first or later:
            per_parent.append((len(trial["plan"]), trial["number"],
                               deque(first + later)))
    per_parent.sort(key=lambda item: (item[0], item[1]))
    selected = []
    while per_parent and len(selected) < 64:
        remaining = []
        for depth, number, options in per_parent:
            while options:
                record = options.popleft()
                key = plan_key(record["plan"])
                if key not in known:
                    known.add(key)
                    selected.append(record)
                    break
            if options:
                remaining.append((depth, number, options))
            if len(selected) == 64:
                break
        per_parent = remaining
    return selected


def checkpoint_allowed(state: dict) -> None:
    if state["queue"] or "finished_at" not in state:
        raise RuntimeError("Prepare/apply only after a finished, exhausted checkpoint")
    if len(state["trials"]) >= state["budget"]["max_attempts"] or sum(
            valid(t) for t in state["trials"]) >= state["budget"]["max_valid_trials"]:
        raise RuntimeError("The configured attempt or valid budget is complete")


def main() -> None:
    state_bytes = STATE.read_bytes()
    state = json.loads(state_bytes)
    candidates = alternatives(state)
    plans = [record["plan"] for record in candidates]
    plans_hash = sha256(json.dumps(plans, sort_keys=True, separators=(",", ":")).encode())
    receipt_path = CAMPAIGN / f"refill-{len(state.get('feedback_refills', [])) + 1:03d}-receipt.json"
    if "--prepare" not in sys.argv and "--apply" not in sys.argv:
        print(json.dumps({"untried_selected": len(candidates),
                          "plans_sha256": plans_hash,
                          "attempts": len(state["trials"]),
                          "queue": len(state["queue"])}))
        return
    checkpoint_allowed(state)
    if not candidates:
        print("No untried exact pre-target I/O selectors remain")
        return
    if len({plan_key(p) for p in plans}) != len(plans):
        raise AssertionError("Prepared plans are not unique")
    if "--prepare" in sys.argv:
        receipt = {
            "state_sha256_before": sha256(state_bytes),
            "plans_sha256": plans_hash,
            "selected_count": len(candidates),
            "unique_count": len({plan_key(p) for p in plans}),
            "budget": state["budget"],
            "after_attempt": len(state["trials"]),
            "source_filter": "raw_strict_and_target_after_last_fault_and_original_junit_passed",
            "candidate_constraints": "parent_last_fault_seq < observed_io_seq < next_target_seq; no seen/queued plan; child length within max faults",
            "candidates": candidates,
        }
        atomic_json(receipt_path, receipt)
        print(json.dumps({"receipt": str(receipt_path),
                          "selected_count": len(candidates),
                          "plans_sha256": plans_hash}, sort_keys=True))
        return
    if not receipt_path.exists():
        raise RuntimeError("First run --prepare and inspect the saved receipt")
    receipt = json.loads(receipt_path.read_text())
    if (receipt["state_sha256_before"] != sha256(state_bytes) or
            receipt["plans_sha256"] != plans_hash or
            receipt["candidates"] != candidates):
        raise RuntimeError("Prepared receipt differs from the current checkpoint")
    state["queue"] = plans
    state.pop("finished_at")
    state.setdefault("feedback_refills", []).append({
        "after_attempt": len(state["trials"]),
        "added_plans": len(plans),
        "receipt": str(receipt_path.relative_to(WORK)),
        "plans_sha256": plans_hash,
        "source": "strict_post_final_target_run_observed_io",
    })
    atomic_json(STATE, state)
    write_results(state)
    print(json.dumps(state["feedback_refills"][-1], sort_keys=True))


if __name__ == "__main__":
    main()
