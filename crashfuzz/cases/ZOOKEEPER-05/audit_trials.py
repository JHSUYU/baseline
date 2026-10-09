#!/usr/bin/env python3
"""Audit the locally caught selected throw in case-local GraphChecker traces."""

import glob
import gzip
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
METHOD = "<org.apache.zookeeper.server.quorum.Follower: void followLeader()>"
GUARD = METHOD + "#u52"
CONSTRUCTOR = METHOD + "#u67"
THROW = METHOD + "#u68"


def audit(trace, target_addresses):
    applied = []
    guards = []
    constructors = []
    explicit_throws = []
    exits = []
    target_calls = set()
    stream = gzip.open(trace, "rt") if trace.suffix == ".gz" else trace.open()
    for line in stream:
        event = json.loads(line)
        kind = event.get("event")
        if kind == "FAULT_APPLIED":
            applied.append(event)
        if event.get("method") != METHOD:
            continue
        if kind == "METHOD_ENTER" and event.get("occurrenceAddress") in target_addresses:
            target_calls.add(event["callId"])
        elif kind == "BRANCH" and event.get("siteId") == GUARD:
            guards.append(event)
        elif event.get("siteId") == CONSTRUCTOR and kind in {
            "CALL_SITE_ENTER", "CALL_ARGUMENT", "CALL_SITE_RETURN",
            "CALL_SITE_THROW",
        }:
            constructors.append(event)
        elif event.get("siteId") == THROW and kind == "EXPLICIT_THROW":
            explicit_throws.append(event)
        elif kind in {"METHOD_EXIT_THROW", "METHOD_EXIT_NORMAL"}:
            exits.append(event)
    last_fault = max((x["seq"] for x in applied), default=-1)
    selected_guards = [x for x in guards if x.get("callId") in target_calls]
    fatal = [x for x in selected_guards if x.get("outcome") is False]
    constructor_returns = [x for x in constructors
                           if x["event"] == "CALL_SITE_RETURN"]
    selected_throws = [x for x in explicit_throws
                       if x.get("callId") in target_calls and
                       x.get("runtimeType") == "java.io.IOException"]
    return {
        "trace": str(trace),
        "fault_applied_count": len(applied),
        "last_fault_seq": last_fault,
        "selected_target_method_entries": len(target_calls),
        "all_guard_after_fault_count": sum(x["seq"] > last_fault >= 0
                                           for x in guards),
        "guard_true_count": sum(x.get("outcome") is True for x in selected_guards),
        "guard_false_count": len(fatal),
        "guard_after_fault_count": sum(x["seq"] > last_fault >= 0
                                       for x in selected_guards),
        "guard_false_after_fault_count": sum(x["seq"] > last_fault >= 0
                                             for x in fatal),
        "constructor_events": [
            {"seq": x["seq"], "event": x["event"],
             "callId": x.get("callId"),
             "declaredCallee": x.get("declaredCallee"),
             "primitiveValue": x.get("primitiveValue")}
            for x in constructors if x.get("callId") in target_calls],
        "selected_constructor_after_fatal_guard_count": sum(
            c["callId"] == g["callId"] and c["seq"] > g["seq"]
            for c in constructor_returns for g in fatal),
        "selected_explicit_throw_count": len(selected_throws),
        "selected_explicit_throw_after_fault_count": sum(
            x["seq"] > last_fault >= 0 for x in selected_throws),
        "method_exit_normal_count": sum(x["event"] == "METHOD_EXIT_NORMAL"
                                        for x in exits),
        "method_exit_throw_count": sum(x["event"] == "METHOD_EXIT_THROW"
                                       for x in exits),
    }


def main():
    traces = [HERE / "record2/runtime/runtime_trace.jsonl",
              HERE / "record-v2/runtime/runtime_trace.jsonl"]
    for campaign in ("fuzzer-r2", "fuzzer-v2-single"):
        for trial in sorted((HERE / campaign / "ZOOKEEPER-05" / "trials").glob("*")):
            for name in ("runtime_trace.jsonl", "runtime_trace.jsonl.gz"):
                traces.append(trial / "record" / "runtime" / name)
    result = {}
    for trace in traces:
        if not trace.exists():
            continue
        if trace.is_relative_to(HERE / "record2") or trace.is_relative_to(HERE / "record-v2"):
            seed_dir = HERE / ("record2" if trace.is_relative_to(HERE / "record2") else "record-v2")
            plan = seed_dir / "targets/zk05/runtime/concolic_region_plan.jsonl"
            addresses = {row.get("occurrenceId")
                         for line in plan.open() if (row := json.loads(line)).get("regionId")
                         == "REGION.1e25f543-ad81-3ed6-b419-eabbb2153db4"}
        else:
            trial_result = trace.parents[2] / "result.json"
            if not trial_result.exists():
                continue
            addresses = set(json.loads(trial_result.read_text())
                            .get("closure_members", {}))
        result[str(trace.relative_to(HERE))] = audit(trace, addresses)
    (HERE / "trials-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    for name, item in result.items():
        print(name, "faults", item["fault_applied_count"],
              "guard_after", item["guard_after_fault_count"],
              "fatal", item["guard_false_count"],
              "ctor", item["selected_constructor_after_fatal_guard_count"])


if __name__ == "__main__":
    main()
