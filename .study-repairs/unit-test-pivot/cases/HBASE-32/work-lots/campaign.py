#!/usr/bin/env python3
"""Resumable, graph-free fault search around the original HBase replica JUnit."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CHECKPOINT = HERE / "checkpoint.json"
INFLIGHT = HERE / "inflight.json"
REVIEW_VERDICTS = HERE / "review-verdicts.json"
# TABLE_NOT_FOUND was calibrated separately. Injecting it while the test's
# table exists violates the response's state precondition, so it is excluded
# from the main fault queue.
KINDS = ("DO_NOT_RETRY_IOEXCEPTION", "IOEXCEPTION", "SOCKET_TIMEOUT",
         "EOF_EXCEPTION")
MAX_EFFECTIVE = int(os.environ.get("HBASE32_MAX_EFFECTIVE", "80"))
MAX_ATTEMPTS = int(os.environ.get("HBASE32_MAX_ATTEMPTS", "240"))
MAX_FAULTS = int(os.environ.get("HBASE32_MAX_FAULTS", "8"))
MAX_CHILD_SELECTORS = 24
RNG_SEED = 32
SELECTION_POLICY = "lots_v4_retention_io_coverage_weighted"
CALIBRATION_FIRST_TRIAL = 19
MIN_KIND_SHARE = 0.05


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
              "b7": [], "rs_aborts": [], "shutdown_hook_line": None,
              "junit": None, "elapsed_seconds": None}
    for line_number, line in enumerate(path.read_text(errors="replace").splitlines()):
        if result["shutdown_hook_line"] is None and "Shutdown hook starting" in line:
            result["shutdown_hook_line"] = line_number
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


def admitted_new_io(state: dict, trace: dict) -> int:
    baseline = {event["selector"] for event in state["healthy"]["io"]}
    observed = {event["selector"] for event in trace["io"]
                if event.get("context_match") == "true"}
    return len(observed - baseline)


def kind_feedback(state: dict) -> tuple[dict[str, float], dict[str, dict]]:
    """Weight exception kinds by target retention and admitted feedback only."""
    metrics = {kind: {"attempts": 0, "effective": 0,
                      "admitted_production_novelty": 0,
                      "admitted_new_io_selectors": 0}
               for kind in KINDS}
    for trial in state["trials"]:
        if int(trial["id"][1:]) < CALIBRATION_FIRST_TRIAL:
            continue
        kind = trial["plan"][-1].rsplit("~", 1)[1]
        item = metrics[kind]
        item["attempts"] += 1
        if trial["effective"]:
            item["effective"] += 1
            item["admitted_production_novelty"] += trial["new_production_branches_and_methods"]
            item["admitted_new_io_selectors"] += trial.get("new_related_io_selectors", 0)
    raw = {}
    for kind, item in metrics.items():
        retained = (item["effective"] + 0.5) / (item["attempts"] + 1)
        per_effective_io = item["admitted_new_io_selectors"] / max(1, item["effective"])
        per_effective_code = item["admitted_production_novelty"] / max(1, item["effective"])
        novelty_bonus = (1 + 0.1 * min(per_effective_io / 200, 1)
                         + 0.1 * min(per_effective_code / 3, 1))
        raw[kind] = retained * novelty_bonus
    total = sum(raw.values())
    weights = {kind: MIN_KIND_SHARE + (1 - len(KINDS) * MIN_KIND_SHARE)
               * raw[kind] / total for kind in KINDS}
    return weights, metrics


def choose_kind(state: dict, weights: dict[str, float]) -> str:
    chosen = Counter(trial["plan"][-1].rsplit("~", 1)[1]
                     for trial in state["trials"]
                     if trial.get("selection_policy") == SELECTION_POLICY)
    next_slot = sum(chosen.values()) + 1
    return max(KINDS, key=lambda kind: next_slot * weights[kind] - chosen[kind])


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
    actor = re.search(r"~replica-(\d+)~target-(\d+)~", last["selector"])
    if actor is None:
        return [], []
    replica, ordinal = actor.groups()
    reached = [event for event in trace["guards"]
               if event["line"] > last["line"] and event["raw_primary_region"] == region
               and event["replica_id"] == replica and event["target_ordinal"] == ordinal]
    rethrown = [event for event in trace["b7"]
                if event["line"] > last["line"] and event["raw_primary_region"] == region
                and event["replica_id"] == replica and event["target_ordinal"] == ordinal]
    return reached, rethrown


def enqueue(state: dict, prefix: list[str], trace: dict, after: int, novelty: int,
            parent_seconds: float) -> None:
    if len(prefix) >= MAX_FAULTS:
        return
    seen = set(state["seen_plans"])
    selectors = list(dict.fromkeys(event["selector"] for event in trace["io"]
                                   if event["line"] > after and
                                   event.get("context_match") == "true"))
    seed_material = (str(RNG_SEED) + ";" + ";".join(prefix)).encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    random.Random(seed).shuffle(selectors)
    if prefix:
        # A 542-target healthy run already supplies >2,000 one-fault plans.
        # Bound each effective seed's children while retaining newly exposed
        # post-fault I/O identities ahead of familiar healthy identities.
        baseline = {event["selector"] for event in state["healthy"]["io"]}
        selectors = ([selector for selector in selectors if selector not in baseline]
                     + [selector for selector in selectors if selector in baseline])
        selectors = selectors[:MAX_CHILD_SELECTORS]
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


def priority(entry: dict, tried: Counter, b7_prefixes: list[list[str]]) -> float:
    final = entry["plan"][-1]
    selector, kind = final.rsplit("~", 1)
    replica1 = "~replica-1~" in selector
    recovery = "~target-2~" in selector or "~target-3~" in selector
    prior_abort = any(len(entry["plan"]) > len(prefix)
                      and entry["plan"][:len(prefix)] == prefix
                      for prefix in b7_prefixes)
    # With this original test, a B7 throw aborts an RS and a second throw
    # can exhaust the three-RS cluster. Exercise all distinct, healthy-trace
    # single-fault identities before spending heavily on recovery descendants.
    # Keep a bounded coverage reward and aging so legal depth is still tried.
    return (25 * (not tried[final]) + 12 * replica1 + 10 * (not replica1)
            + (8 if recovery else 0)
            + (55 if len(entry["plan"]) == 1 else -10)
            + min(2 * entry["novelty"], 12)
            + min(entry["wait"] // 5, 20)
            - min(entry["parent_seconds"] / 20, 12)
            - (25 if prior_abort else 0)
            + (6 if kind == "DO_NOT_RETRY_IOEXCEPTION" else 0))


def prune_queue(state: dict) -> None:
    """Exclude semantic-invalid faults and known cluster-exhausting prefixes."""
    invalid = [trial["plan"] for trial in state["trials"]
               if trial.get("invalid_cluster")]
    target_lost = [trial["plan"] for trial in state["trials"]
                   if trial.get("strict") and not trial.get("target_after_fault")]
    b7 = [trial["plan"] for trial in state["trials"]
          if trial.get("exact_b7_after_fault") and not trial.get("invalid_cluster")]
    inflight = json.loads(INFLIGHT.read_text()) if INFLIGHT.exists() else None
    retained = []
    for entry in state["queue"]:
        plan = entry["plan"]
        if inflight and plan == inflight["plan"]:
            retained.append(entry)
            continue
        if any(step.endswith("~TABLE_NOT_FOUND") for step in plan):
            continue
        if any(len(plan) > len(prefix) and plan[:len(prefix)] == prefix
               for prefix in invalid):
            continue
        if any(len(plan) > len(prefix) and plan[:len(prefix)] == prefix
               for prefix in target_lost):
            continue
        # This JUnit does not deliberately abort an RS. Two distinct RS
        # aborts may be tolerated by the three-RS cluster; a third cannot.
        # Runtime abort identities still decide whether a two-fault trial
        # actually remained within the cluster's recovery precondition.
        if sum(step.endswith("~DO_NOT_RETRY_IOEXCEPTION") for step in plan) > 2:
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
    reviewed = json.loads(REVIEW_VERDICTS.read_text()) if REVIEW_VERDICTS.exists() else {}
    pending_review = [trial for trial in trials
                      if trial["review_candidate"] and trial["id"] not in reviewed]
    kind_weights, kind_metrics = kind_feedback(state)
    result.update({
        "status": status,
        "cluster_test": "org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover#testLotsOfRegionReplicas",
        "target_reached": True,
        "elapsed_seconds": elapsed,
        "fault_trials": len(trials),
        "strict_injections": len(strict),
        "fully_applied_trials": len(strict),
        "target_after_fault": len(effective),
        "coverage_gain": state["coverage_union"]["branches"] - state["healthy_coverage"]["branches"],
        "bug_mark": "candidate_review" if pending_review else "none",
        "methodology": "graph_free_original_cluster_junit_flush_rpc_exception_jacoco_feedback",
        "evidence": ["README.md", "work-lots/checkpoint.json", "work-lots/logs/actor-healthy.log",
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
            "review_candidates": sum(trial["review_candidate"] for trial in trials),
            "pending_review_candidates": len(pending_review),
            "reviewed_candidate_dispositions": reviewed,
            "coverage_admitted_trials": sum(trial["effective"]
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
            "checkpoint": "work-lots/checkpoint.json",
            "selection_policy": state.get("selection_policy", "lots_v1_full_children"),
            "child_selector_cap": MAX_CHILD_SELECTORS,
            "depth_cadence": 10,
            "rng_seed": RNG_SEED,
            "exception_kind_weights": kind_weights,
            "exception_kind_feedback": kind_metrics,
        },
    })
    atomic_json(result_path, result)


def main() -> None:
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        if state.get("selection_policy") != SELECTION_POLICY:
            # Backfill only accepted feedback. Target-lost logs remain raw
            # evidence and do not influence kind weights or queue mutation.
            for trial in state["trials"]:
                if (trial["effective"] and int(trial["id"][1:]) >= CALIBRATION_FIRST_TRIAL
                        and "new_related_io_selectors" not in trial):
                    trial["new_related_io_selectors"] = admitted_new_io(
                        state, parse_log(CASE / trial["log"]))
                else:
                    trial.setdefault("new_related_io_selectors", 0)
            weights, feedback = kind_feedback(state)
            state.setdefault("policy_changes", []).append({
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "from": state.get("selection_policy", "lots_v1_full_children"),
                "to": SELECTION_POLICY,
                "completed_trials": len(state["trials"]),
                "effective_trials": sum(trial["effective"] for trial in state["trials"]),
                "queue_retained": len(state["queue"]),
                "seen_plans_retained": len(state["seen_plans"]),
                "coverage_union_retained": state["coverage_union"],
                "rng_seed": RNG_SEED,
                "future_child_selector_cap": MAX_CHILD_SELECTORS,
                "depth_cadence": 10,
                "calibration_first_trial": CALIBRATION_FIRST_TRIAL,
                "exception_kind_weights": weights,
                "exception_kind_feedback": feedback,
                "minimum_kind_share": MIN_KIND_SHARE,
            })
            state["selection_policy"] = SELECTION_POLICY
        if not state.get("target_loss_migration_applied"):
            # Earlier controller revisions admitted a strict retry even when
            # its final fault did not reach the chosen exception guard. Keep
            # the raw attempt but remove its coverage and queue descendants.
            old_queue = len(state["queue"])
            old_execs = len(state["coverage_execs"])
            state["coverage_execs"] = [str(HERE / "logs" / "actor-healthy.exec")]
            for trial in state["trials"]:
                trial["coverage_admitted"] = bool(trial["effective"])
                if trial["effective"]:
                    state["coverage_execs"].append(str(HERE / "logs" / (trial["id"] + ".exec")))
                else:
                    trial["new_production_branches_and_methods"] = 0
            state["coverage_union"] = coverage([Path(path) for path in state["coverage_execs"]])
            prune_queue(state)
            state.setdefault("migration_log", []).append({
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "reason": "exclude final-fault target-lost coverage and descendants",
                "target_lost_ids": [trial["id"] for trial in state["trials"]
                                    if trial["strict"] and not trial["target_after_fault"]],
                "queue_before": old_queue, "queue_after": len(state["queue"]),
                "coverage_execs_before": old_execs,
                "coverage_execs_after": len(state["coverage_execs"]),
            })
            state["target_loss_migration_applied"] = True
        # A controller can stop after writing the inflight marker but before
        # committing that trial. Keep it accountably in the queue on restart.
        pending = json.loads(INFLIGHT.read_text()) if INFLIGHT.exists() else None
        if pending and not any(entry["plan"] == pending["plan"]
                               for entry in state["queue"]):
            state["queue"].insert(0, {"plan": pending["plan"],
                                      "parent_seconds": 60, "novelty": 0, "wait": 0})
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
                 "trials": [], "queue": [], "seen_plans": [],
                 "selection_policy": SELECTION_POLICY}
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
        selection_weights, _ = kind_feedback(state)
        if pending and pending["id"] == trial_id:
            entry = next((item for item in state["queue"] if item["plan"] == pending["plan"]), None)
            if entry is None:
                raise RuntimeError("Inflight plan absent from queue")
            state["queue"].remove(entry)
            desired_kind = entry["plan"][-1].rsplit("~", 1)[1]
        else:
            INFLIGHT.unlink(missing_ok=True)
            tried = Counter(trial["plan"][-1] for trial in state["trials"])
            b7_prefixes = [trial["plan"] for trial in state["trials"]
                           if trial.get("exact_b7_after_fault")]
            state["queue"].sort(key=lambda item: (-priority(item, tried, b7_prefixes),
                                                   item["parent_seconds"],
                                                   ";".join(item["plan"])))
            # Periodically sample legal multi-fault plans. The one-fault
            # preference otherwise starves depth with this large healthy seed.
            round_number = len(state["trials"]) + 1
            desired_kind = choose_kind(state, selection_weights)
            depth_round = round_number % 10 == 0
            chosen = next((index for index, item in enumerate(state["queue"])
                           if (not depth_round or len(item["plan"]) > 1)
                           and item["plan"][-1].endswith("~" + desired_kind)), None)
            if chosen is None and depth_round:
                chosen = next((index for index, item in enumerate(state["queue"])
                               if len(item["plan"]) > 1), None)
            if chosen is None:
                chosen = 0
            entry = state["queue"].pop(chosen)
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
        # A timeout sends SIGTERM to the MiniCluster JVM. Its shutdown hook
        # closes internal connections; handlers can then abort the remaining
        # RSs. Those cleanup aborts must not retroactively invalidate an
        # otherwise tolerated one-RS fault before the timeout.
        cutoff = trace["shutdown_hook_line"]
        aborted_servers = sorted({abort["server"] for abort in trace["rs_aborts"]
                                  if cutoff is None or abort["line"] < cutoff})
        cleanup_aborts = sorted({abort["server"] for abort in trace["rs_aborts"]
                                 if cutoff is not None and abort["line"] >= cutoff})
        invalid_cluster = strict and len(aborted_servers) >= 3
        exec_file = HERE / "logs" / (trial_id + ".exec")
        coverage_present = exec_file.is_file() and exec_file.stat().st_size > 0
        effective = strict and bool(guards) and coverage_present and not invalid_cluster
        coverage_admitted = effective
        old_coverage = state["coverage_union"]
        new_coverage = old_coverage
        if effective:
            state["coverage_execs"].append(str(exec_file))
            new_coverage = coverage([Path(path) for path in state["coverage_execs"]])
            state["coverage_union"] = new_coverage
        novelty = (new_coverage["branches"] - old_coverage["branches"]
                   + new_coverage["methods"] - old_coverage["methods"])
        junit_exit = int(exit_file.read_text().strip())
        timed_out = junit_exit == 124
        unexpected = (strict and bool(guards) and not invalid_cluster
                      and (timed_out or (trace["junit"] is not None
                                        and trace["junit"]["failed"] > 0)))
        item = {"id": trial_id, "plan": entry["plan"], "strict": strict,
                "selection_policy": state.get("selection_policy"),
                "requested_exception_kind": desired_kind,
                "selection_kind_weights": selection_weights,
                "applied_fault_events": len(trace["applied"]),
                "target_after_fault": bool(guards),
                "exact_b7_after_fault": bool(b7),
                "same_region_guard_events": len(guards),
                "same_region_b7_events": len(b7),
                "aborted_region_servers": aborted_servers,
                "cleanup_region_server_aborts": cleanup_aborts,
                "shutdown_hook_line": cutoff,
                "invalid_cluster": bool(invalid_cluster),
                "coverage_admitted": bool(coverage_admitted),
                "effective": effective, "review_candidate": bool(unexpected),
                "junit": trace["junit"], "junit_exit": junit_exit,
                "timed_out": timed_out,
                "elapsed_seconds": trace["elapsed_seconds"],
                "observed_io_events": len(trace["io"]),
                "new_production_branches_and_methods": novelty,
                "new_related_io_selectors": admitted_new_io(state, trace) if effective else 0,
                "log": str(log.relative_to(CASE)),
                "disposition": ("unmatched" if not strict else
                                "invalid_all_region_servers_aborted" if invalid_cluster else
                                "target_lost" if not guards else
                                "timeout_requires_review" if timed_out else
                                "junit_failure_requires_review" if unexpected else
                                "expected_b7_abort" if b7 else "guard_return_or_other")}
        state["trials"].append(item)
        if effective and not timed_out:
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
