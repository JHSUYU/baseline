#!/usr/bin/env python3
"""Resumable, graph-free fault search around the original HBase replica JUnit."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import random
import re
import subprocess


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CHECKPOINT = HERE / "checkpoint.json"
INFLIGHT = HERE / "inflight.json"
# TABLE_NOT_FOUND was calibrated separately. Injecting it while the test's
# table exists violates the response's state precondition, so it is excluded
# from the main fault queue.
KINDS = ("DO_NOT_RETRY_IOEXCEPTION", "IOEXCEPTION", "SOCKET_TIMEOUT",
         "EOF_EXCEPTION")
MAX_EFFECTIVE = int(os.environ.get("HBASE32_MAX_EFFECTIVE", "80"))
MAX_ATTEMPTS = int(os.environ.get("HBASE32_MAX_ATTEMPTS", "240"))
MAX_FAULTS = int(os.environ.get("HBASE32_MAX_FAULTS", "8"))
RNG = random.Random(32)


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def parse_log(path: Path) -> dict:
    result = {"io": [], "applied": [], "target_enters": [], "guards": [],
              "b7": [], "rs_aborts": [], "junit": None, "elapsed_seconds": None}
    for line_number, line in enumerate(path.read_text(errors="replace").splitlines()):
        marker = re.search(r"HBASE32 (IO|FAULT_APPLIED|TARGET_ENTER|TARGET_GUARD|TARGET_B7_RETHROW) seq=(\d+)", line)
        if marker:
            fields = dict(re.findall(r"([a-z_]+)=(\S+)", line[marker.start():]))
            entry = {"line": line_number, "seq": int(marker[2]), **fields}
            category = {"IO": "io", "FAULT_APPLIED": "applied",
                        "TARGET_ENTER": "target_enters", "TARGET_GUARD": "guards",
                        "TARGET_B7_RETHROW": "b7"}[marker[1]]
            result[category].append(entry)
        match = re.search(r"HBASE32 JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)", line)
        if match:
            result["junit"] = {"found": int(match[1]), "succeeded": int(match[2]),
                               "failed": int(match[3])}
        match = re.search(r"ELAPSED_SECONDS=([\d.]+)", line)
        if match:
            result["elapsed_seconds"] = float(match[1])
        match = re.search(r"\*\*\*\*\* ABORTING region server ([^: ]+): (.+?) \*\*\*\*\*", line)
        if match:
            result["rs_aborts"].append({"line": line_number, "server": match[1],
                                         "reason": match[2]})
    return result


def coverage(paths: list[Path]) -> dict:
    completed = subprocess.run(["bash", str(HERE / "run.sh"), "coverage",
                                ",".join(str(path) for path in paths)],
                               capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError("JaCoCo report failed: " + completed.stderr[-1500:])
    classes = {}
    target = None
    for line in completed.stdout.splitlines():
        match = re.fullmatch(r"COVERAGE class=(\S+) methods=(\d+) branches=(\d+) lines=(\d+)", line)
        if match:
            classes[match[1]] = {"methods": int(match[2]), "branches": int(match[3]),
                                 "lines": int(match[4])}
        match = re.fullmatch(r"TARGET line=136 instructions=(\d+) branches=(\d+)", line)
        if match:
            target = {"line": 136, "instructions": int(match[1]),
                      "branches": int(match[2])}
    if len(classes) != 2 or target is None:
        raise RuntimeError("Expected two production classes and target line, got " + completed.stdout)
    return {"classes": classes, "target": target,
            "methods": sum(value["methods"] for value in classes.values()),
            "branches": sum(value["branches"] for value in classes.values()),
            "lines": sum(value["lines"] for value in classes.values())}


def strict_trace(trace: dict, plan: list[str]) -> bool:
    events = trace["applied"]
    return (len(events) == len(plan) and
            all(event["selector"] + "~" + event["kind"] == desired
                and int(event["step"]) == step
                for step, (event, desired) in enumerate(zip(events, plan), 1)))


def related_after_fault(trace: dict, strict: bool) -> tuple[list[dict], list[dict]]:
    if not strict:
        return [], []
    last = trace["applied"][-1]
    region = last["raw_primary_region"]
    reached = [event for event in trace["guards"]
               if event["line"] > last["line"] and event["raw_primary_region"] == region]
    rethrown = [event for event in trace["b7"]
                if event["line"] > last["line"] and event["raw_primary_region"] == region]
    return reached, rethrown


def enqueue(state: dict, prefix: list[str], trace: dict, after: int, novelty: int,
            parent_seconds: float) -> None:
    if len(prefix) >= MAX_FAULTS:
        return
    seen = set(state["seen_plans"])
    selectors = list(dict.fromkeys(event["selector"] for event in trace["io"]
                                   if event["line"] > after and
                                   event.get("context_match") == "true"))
    RNG.shuffle(selectors)
    for selector in selectors:
        for kind in KINDS:
            plan = prefix + [selector + "~" + kind]
            key = ";".join(plan)
            if key in seen:
                continue
            seen.add(key)
            state["queue"].append({"plan": plan, "parent_seconds": parent_seconds,
                                   "novelty": novelty, "wait": 0})
    state["seen_plans"] = sorted(seen)


def priority(entry: dict, tried: Counter) -> float:
    final = entry["plan"][-1]
    selector, kind = final.rsplit("~", 1)
    replica1 = "~replica-1~" in selector
    recovery = "~target-2~" in selector or "~target-3~" in selector
    # Prefer a previously unseen fault identity, a recovery invocation, and
    # previously productive prefixes. Aging avoids trapping the search locally.
    return (20 * (not tried[final]) + 12 * replica1 + 15 * recovery
            + 5 * len(entry["plan"]) + 4 * entry["novelty"]
            + min(entry["wait"] // 8, 15)
            - min(entry["parent_seconds"] / 20, 12)
            + (6 if kind == "DO_NOT_RETRY_IOEXCEPTION" else 0))


def prune_queue(state: dict) -> None:
    """Exclude semantic-invalid faults and known cluster-exhausting prefixes."""
    invalid = [trial["plan"] for trial in state["trials"]
               if trial.get("invalid_cluster")]
    b7 = [trial["plan"] for trial in state["trials"]
          if trial.get("exact_b7_after_fault") and not trial.get("invalid_cluster")]
    retained = []
    for entry in state["queue"]:
        plan = entry["plan"]
        if any(step.endswith("~TABLE_NOT_FOUND") for step in plan):
            continue
        if any(len(plan) > len(prefix) and plan[:len(prefix)] == prefix
               for prefix in invalid):
            continue
        # The original JUnit has already deliberately aborted one of three
        # RSs. A second immediate no-retry throw after a first B7 abort would
        # abort the last RS, exceeding this workload's tolerance.
        if (plan[-1].endswith("~DO_NOT_RETRY_IOEXCEPTION") and
                any(len(plan) > len(prefix) and plan[:len(prefix)] == prefix
                    for prefix in b7)):
            continue
        retained.append(entry)
    state["queue"] = retained


def publish(state: dict, status: str = "running_coverage_io_campaign") -> None:
    atomic_json(CHECKPOINT, state)
    trials = state["trials"]
    healthy = state["healthy"]
    elapsed = healthy["elapsed_seconds"] + sum(trial["elapsed_seconds"] or 0 for trial in trials)
    result_path = CASE / "result.json"
    result = json.loads(result_path.read_text())
    strict = [trial for trial in trials if trial["strict"]]
    effective = [trial for trial in trials if trial["effective"]]
    result.update({
        "status": status,
        "cluster_test": "org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover#testSecondaryRegionKill",
        "target_reached": True,
        "elapsed_seconds": elapsed,
        "fault_trials": len(trials),
        "strict_injections": len(strict),
        "fully_applied_trials": len(strict),
        "target_after_fault": len(effective),
        "coverage_gain": state["coverage_union"]["branches"] - state["healthy_coverage"]["branches"],
        "bug_mark": "candidate_review" if any(trial["review_candidate"] for trial in trials) else "none",
        "methodology": "graph_free_original_cluster_junit_flush_rpc_exception_jacoco_feedback",
        "evidence": ["README.md", "work/checkpoint.json", "work/logs/actor-healthy.log",
                     "work/src/HBase32Agent.java", "work/src/CoverageReport.java", "work/run.sh"],
        "current_campaign": {
            "healthy_elapsed_seconds": healthy["elapsed_seconds"],
            "healthy_related_io_events": len(healthy["io"]),
            "healthy_target_invocations": len(healthy["target_enters"]),
            "healthy_exact_guard_evaluations": len(healthy["guards"]),
            "healthy_coverage": state["healthy_coverage"],
            "attempted_trials": len(trials), "strict_trials": len(strict),
            "effective_trials": len(effective),
            "exact_b7_trials": sum(trial["exact_b7_after_fault"] for trial in strict),
            "invalid_cluster_exhaustion_trials": sum(trial.get("invalid_cluster", False)
                                                     for trial in trials),
            "requested_fault_events": sum(len(trial["plan"]) for trial in trials),
            "applied_fault_events": sum(trial["applied_fault_events"] for trial in trials),
            "new_production_branches": state["coverage_union"]["branches"]
                - state["healthy_coverage"]["branches"],
            "new_production_methods": state["coverage_union"]["methods"]
                - state["healthy_coverage"]["methods"],
            "target_line_136_coverage": state["coverage_union"]["target"],
            "queue_length": len(state["queue"]),
            "budget": {"effective_trials": MAX_EFFECTIVE, "max_attempts": MAX_ATTEMPTS,
                       "max_faults": MAX_FAULTS},
            "checkpoint": "work/checkpoint.json",
        },
    })
    atomic_json(result_path, result)


def main() -> None:
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
    else:
        healthy = parse_log(HERE / "logs" / "actor-healthy.log")
        if (healthy["junit"] != {"found": 1, "succeeded": 1, "failed": 0}
                or not healthy["target_enters"] or not healthy["io"]
                or any(event.get("context_match") != "true" for event in healthy["io"])
                or healthy["guards"] or healthy["b7"]):
            raise RuntimeError("Healthy original JUnit lacks a clean target/RPC path")
        baseline = coverage([HERE / "logs" / "actor-healthy.exec"])
        state = {"healthy": healthy, "healthy_coverage": baseline,
                 "coverage_union": baseline,
                 "coverage_execs": [str(HERE / "logs" / "actor-healthy.exec")],
                 "trials": [], "queue": [], "seen_plans": []}
        enqueue(state, [], healthy, -1, 0, healthy["elapsed_seconds"])
        publish(state)
    prune_queue(state)
    publish(state)
    while (len([trial for trial in state["trials"] if trial["effective"]]) < MAX_EFFECTIVE
           and len(state["trials"]) < MAX_ATTEMPTS and state["queue"]):
        trial_id = "r%03d" % (len(state["trials"]) + 1)
        for entry in state["queue"]:
            entry["wait"] += 1
        pending = json.loads(INFLIGHT.read_text()) if INFLIGHT.exists() else None
        if pending and pending["id"] == trial_id:
            entry = next((item for item in state["queue"] if item["plan"] == pending["plan"]), None)
            if entry is None:
                raise RuntimeError("Inflight plan absent from queue")
            state["queue"].remove(entry)
        else:
            INFLIGHT.unlink(missing_ok=True)
            tried = Counter(trial["plan"][-1] for trial in state["trials"])
            state["queue"].sort(key=lambda item: (-priority(item, tried),
                                                   item["parent_seconds"],
                                                   ";".join(item["plan"])))
            entry = state["queue"].pop(0)
            atomic_json(INFLIGHT, {"id": trial_id, "plan": entry["plan"]})
        log = HERE / "logs" / (trial_id + ".log")
        exit_file = HERE / "logs" / (trial_id + ".exit")
        trace = parse_log(log) if log.exists() else None
        if not trace or trace["elapsed_seconds"] is None or not exit_file.exists():
            with log.open("w") as output:
                run = subprocess.run(["bash", str(HERE / "run.sh"), "run", trial_id,
                                      ";".join(entry["plan"])], stdout=output,
                                     stderr=subprocess.STDOUT, check=False)
            exit_file.write_text(str(run.returncode) + "\n")
            trace = parse_log(log)
        strict = strict_trace(trace, entry["plan"])
        guards, b7 = related_after_fault(trace, strict)
        aborted_servers = sorted({abort["server"] for abort in trace["rs_aborts"]})
        invalid_cluster = strict and len(aborted_servers) >= 3
        exec_file = HERE / "logs" / (trial_id + ".exec")
        effective = strict and bool(guards) and exec_file.exists() and not invalid_cluster
        old_coverage = state["coverage_union"]
        new_coverage = old_coverage
        if effective:
            state["coverage_execs"].append(str(exec_file))
            new_coverage = coverage([Path(path) for path in state["coverage_execs"]])
            state["coverage_union"] = new_coverage
        novelty = (new_coverage["branches"] - old_coverage["branches"]
                   + new_coverage["methods"] - old_coverage["methods"])
        unexpected = (strict and not invalid_cluster and trace["junit"] is not None
                      and trace["junit"]["failed"] > 0 and not b7)
        item = {"id": trial_id, "plan": entry["plan"], "strict": strict,
                "applied_fault_events": len(trace["applied"]),
                "target_after_fault": bool(guards),
                "exact_b7_after_fault": bool(b7),
                "same_region_guard_events": len(guards),
                "same_region_b7_events": len(b7),
                "aborted_region_servers": aborted_servers,
                "invalid_cluster": bool(invalid_cluster),
                "effective": effective, "review_candidate": bool(unexpected),
                "junit": trace["junit"], "junit_exit": int(exit_file.read_text().strip()),
                "elapsed_seconds": trace["elapsed_seconds"],
                "observed_io_events": len(trace["io"]),
                "new_production_branches_and_methods": novelty,
                "log": str(log.relative_to(CASE)),
                "disposition": ("unmatched" if not strict else
                                "invalid_all_region_servers_aborted" if invalid_cluster else
                                "target_lost" if not guards else
                                "expected_b7_abort" if b7 else "guard_return_or_other")}
        state["trials"].append(item)
        if strict and not invalid_cluster:
            enqueue(state, entry["plan"], trace, trace["applied"][-1]["line"],
                    novelty, trace["elapsed_seconds"] or 60)
        prune_queue(state)
        publish(state)
        INFLIGHT.unlink(missing_ok=True)
        print("HBASE32 checkpoint", trial_id, item["disposition"],
              "effective", sum(trial["effective"] for trial in state["trials"]),
              "queue", len(state["queue"]), flush=True)
    publish(state, "campaign_budget_reached" if
            sum(trial["effective"] for trial in state["trials"]) >= MAX_EFFECTIVE
            else "campaign_queue_exhausted" if not state["queue"]
            else "campaign_attempt_limit_reached")


if __name__ == "__main__":
    main()
