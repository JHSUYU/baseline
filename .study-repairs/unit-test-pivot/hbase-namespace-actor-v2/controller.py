#!/usr/bin/env python3
"""Resume-safe, graph-free namespace fault search over unchanged cluster JUnit runs.

Only an exact ordered applied plan followed by the selected target on the same
active Master/manager can contribute coverage or I/O feedback. Old case runs
are never imported. Raw run directories are immutable once exit exists.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
RUN = HERE / "run.sh"
KINDS = ("CONNECTIONLOSS", "OPERATIONTIMEOUT", "SYSTEMERROR")
CASES = {
    "HBASE-08": ("table", "TestNamespaceAuditor_np2", {"normal", "selected_namespace_not_found"}),
    "HBASE-21": ("restore", "TestNamespaceAuditor_testRestoreSnapshotQuotaExceed:table1:4",
                 {"normal", "selected_region_count_quota"}),
    "HBASE-22": ("table", "TestNamespaceAuditor_np2:table2:5",
                 {"normal", "selected_table_region_quota"}),
}
BRANCH_LINE = {"HBASE-21": 128, "HBASE-22": 166}
TARGET_CLASS = "org/apache/hadoop/hbase/namespace/NamespaceStateManager"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def publish(state):
    """Atomic case-local table row; historical case counters are excluded."""
    trials = state["trials"]
    branches = state["covered_branches"]
    baseline = state["baseline_branches"]
    row = {"case_id": state["case"],
           "methodology": "graph_free_original_junit_actor_bound_zk_io_jacoco_v2",
           "status": state["status"],
           "healthy_seeds": state["healthy_seeds"],
           "healthy_selected_target_counts": state["healthy_selected_target_counts"],
           "healthy_stable_selectors": len(state["healthy_stable_selectors"]),
           "healthy_io_families": state["healthy_io_families"],
           "healthy_expected_outcomes": state["healthy_expected_outcomes"],
           "attempted_trials": len(trials), "effective_trials": state["effective"],
           "strict_trials": sum(x["strict"] for x in trials),
           "strict_postfault_target_trials": sum(x["effective"] for x in trials),
           "requested_faults": sum(x["requested_faults"] for x in trials),
           "applied_faults": sum(x["applied_count"] for x in trials),
           "target_exception_candidates": sum(x["target_exception_review"] ==
                                               "candidate_needs_source_and_replay" for x in trials),
           "healthy_expected_target_exception_trials": sum(x["target_exception_review"] ==
                                                          "healthy_expected" for x in trials),
           "new_production_methods": len(set(state["covered_methods"])
                                         - set(state["baseline_methods"])),
           "new_production_branches": sum(max(0, count - baseline.get(key, 0))
                                          for key, count in branches.items()),
           "new_stable_io_families": sorted(
               family for family, count in state["io_family_counts"].items()
               if count >= 2 and family not in state["healthy_io_families"]),
           "healthy_elapsed_seconds": state["healthy_elapsed_seconds"],
           "fault_elapsed_seconds": sum(x["elapsed_seconds"] or 0 for x in trials),
           "budget": {"effective_trials": state["max_effective"],
                      "max_faults": state["max_faults"],
                      "max_attempts": state["max_attempts"]},
           "checkpoint": str((HERE / "campaigns" / state["case"] / "checkpoint.json")
                             .relative_to(HERE))}
    atomic_json(HERE / "campaigns" / state["case"] / "result.json", row)


def parse(log):
    events = {"IO_ATTEMPT": [], "IO_END": [], "FAULT_APPLIED": [],
              "FAULT_REJECTED": [], "TARGET_EXIT": [], "TARGET_ENTER": [],
              "GUARD_OPERAND": [], "MANAGER": []}
    for line_number, line in enumerate(log.splitlines()):
        match = re.search(r"NSACTOR (IO_ATTEMPT|IO_END|FAULT_APPLIED|FAULT_REJECTED|TARGET_EXIT|TARGET_ENTER|GUARD_OPERAND|MANAGER) (.*)", line)
        if not match:
            continue
        fields = dict(re.findall(r"(?:^| )([a-z_]+)=([^ ]+)", match.group(2)))
        fields["line_number"] = line_number
        if "seq" in fields:
            fields["seq"] = int(fields["seq"])
        if "event_seq" in fields:
            fields["event_seq"] = int(fields["event_seq"])
        if "manager" in fields:
            fields["manager"] = int(fields["manager"])
        if "step" in fields:
            fields["step"] = int(fields["step"])
        events[match.group(1)].append(fields)
    junit = re.search(r"NSACTOR JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)", log)
    elapsed = re.search(r"ELAPSED_SECONDS=([\d.]+)", log)
    events["junit"] = ([int(x) for x in junit.groups()] if junit else None)
    events["elapsed_seconds"] = float(elapsed.group(1)) if elapsed else None
    return events


def chosen_targets(case, trace):
    return [x for x in trace["TARGET_EXIT"]
            if x.get("point") == case and x.get("subject") == CASES[case][1]]


def same_actor(left, right):
    return (left.get("actor_raw") not in (None, "unassigned")
            and left.get("actor_raw") == right.get("actor_raw")
            and left.get("manager", 0) > 0
            and left.get("manager") == right.get("manager"))


def guard_markers(case, target, trace):
    if trace is None:
        return []
    return [x for x in trace["GUARD_OPERAND"]
            if x.get("point") == case and x.get("seq") == target.get("seq")
            and x.get("subject") == target.get("subject")
            and same_actor(x, target)]


def eligible_target(case, target, coverage_text="", trace=None):
    if target.get("role") != "ACTIVE_MASTER" or target.get("outcome") not in CASES[case][2]:
        return False
    if not guard_markers(case, target, trace):
        return False
    if case == "HBASE-08":
        return True
    # JaCoCo confirms the released predicate line in addition to the
    # invocation-specific guard operand receipt.
    line = BRANCH_LINE[case]
    return bool(re.search(rf"BRANCH class={TARGET_CLASS} line={line} covered=[1-9]", coverage_text))


def exact_receipt(case, plan, trace, coverage_text=""):
    applied = trace["FAULT_APPLIED"]
    wanted = [step.rsplit("~", 1) for step in plan]
    strict = (len(applied) == len(wanted) and
              all(x.get("step") == i + 1 and x.get("selector") == selector
                  and x.get("kind") == kind
                  for i, (x, (selector, kind)) in enumerate(zip(applied, wanted))))
    io_by_seq = {x["seq"]: x for x in trace["IO_ATTEMPT"]}
    strict = strict and all(
        x["seq"] in io_by_seq and io_by_seq[x["seq"]].get("role") == "ACTIVE_MASTER"
        and same_actor(x, io_by_seq[x["seq"]]) for x in applied)
    strict = strict and (not applied or all(same_actor(applied[0], x) for x in applied))
    last = applied[-1]["seq"] if applied else -1
    selected = chosen_targets(case, trace)
    matched = [x for x in selected if strict and x.get("bound_match") == "true"
               and same_actor(applied[-1], x) and eligible_target(case, x, coverage_text, trace)
               and any(marker["event_seq"] > last for marker in guard_markers(case, x, trace))]
    outcome = matched[0].get("outcome") if matched else None
    return {"strict": bool(strict), "target_after_final_fault": bool(matched),
            "target_outcome": outcome,
            "selected_target_count": len(chosen_targets(case, trace)),
            "unadmitted_selected_target_count": len(selected) - len(matched),
            "applied_count": len(applied), "fault_rejected_count": len(trace["FAULT_REJECTED"]),
            "last_fault_seq": last}


def coverage(paths):
    command = ["bash", str(RUN), "coverage", ",".join(map(str, paths))]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("Coverage failed: " + result.stderr[-1200:])
    methods = set()
    branch_lines = {}
    for line in result.stdout.splitlines():
        if line.startswith("METHOD "):
            methods.add(line.rsplit(" branches=", 1)[0])
        elif line.startswith("BRANCH "):
            key, value = line.rsplit(" covered=", 1)
            branch_lines[key] = int(value)
    return result.stdout, methods, branch_lines


def run_dir(kind, seed):
    return HERE / "runs" / (kind + "-" + seed)


def load_run(kind, seed, stem):
    directory = run_dir(kind, seed)
    log = directory / (stem + ".log")
    receipt = directory / (stem + ".exit")
    if not log.is_file() or not receipt.is_file():
        raise FileNotFoundError("Incomplete run: " + str(directory))
    return parse(log.read_text(errors="replace")), int(receipt.read_text().strip())


def stable_seed_io(case, traces):
    per_seed = []
    for trace in traces:
        target = chosen_targets(case, trace)
        valid = [x for x in target if x.get("role") == "ACTIVE_MASTER"
                 and x.get("manager", 0) > 0 and x.get("actor_raw") != "unassigned"]
        if not valid:
            raise RuntimeError("Healthy seed lacks bound selected target: " + case)
        if len({(x["actor_raw"], x["manager"]) for x in valid}) != 1:
            raise RuntimeError("Healthy selected target changed Master/manager within one run")
        markers = [marker for target in valid for marker in guard_markers(case, target, trace)]
        if not markers:
            raise RuntimeError("Healthy selected target lacks precise guard operand")
        last = max(x["event_seq"] for x in markers)
        candidates = {}
        for event in trace["IO_ATTEMPT"]:
            if event["seq"] >= last or event.get("role") != "ACTIVE_MASTER":
                continue
            if not any(event["seq"] < marker["event_seq"] and same_actor(event, marker)
                       for marker in markers):
                continue
            selector = event.get("selector")
            if selector:
                candidates.setdefault(selector, set()).add((event.get("actor_raw"), event.get("manager")))
        # A selector that maps to two Master/manager instances in a seed is
        # ambiguous even if each event is otherwise healthy.
        per_seed.append({selector for selector, actors in candidates.items() if len(actors) == 1})
    return sorted(set.intersection(*per_seed))


def io_family(selector):
    return selector.split("~", 2)[1]


def pretarget_io(case, trace, last_fault):
    bound = next((x for x in trace["FAULT_APPLIED"] if x["seq"] == last_fault), None)
    markers = [marker for target in chosen_targets(case, trace)
               if target.get("role") == "ACTIVE_MASTER" and target.get("manager", 0) > 0
               and (bound is None or same_actor(bound, target))
               for marker in guard_markers(case, target, trace)
               if marker["event_seq"] > last_fault]
    candidates = set()
    for event in trace["IO_ATTEMPT"]:
        if event["seq"] <= last_fault or event.get("role") != "ACTIVE_MASTER":
            continue
        if any(event["seq"] < marker["event_seq"] and same_actor(event, marker)
               for marker in markers):
            candidates.add(event["selector"])
    return sorted(candidates)


def enqueue(state, prefix, selectors, parent_novelty):
    for selector in selectors:
        for kind in KINDS:
            plan = prefix + [selector + "~" + kind]
            key = ";".join(plan)
            if key in state["seen"] or len(plan) > state["max_faults"]:
                continue
            state["seen"].append(key)
            state["queue"].append({"plan": plan, "score": parent_novelty * 4 + len(plan) * 3})


def init(case, seeds):
    work = HERE / "campaigns" / case
    checkpoint = work / "checkpoint.json"
    if checkpoint.exists():
        raise RuntimeError("Checkpoint exists; resume instead of reinitializing")
    kind = CASES[case][0]
    traces = []
    execs = []
    for seed in seeds:
        trace, code = load_run(kind, seed, "healthy")
        if code != 0 or trace["junit"] != [1, 1, 0]:
            raise RuntimeError("Original JUnit failed in healthy seed " + seed)
        if not chosen_targets(case, trace):
            raise RuntimeError("Selected target absent from healthy seed " + seed)
        traces.append(trace)
        execs.append(run_dir(kind, seed) / "healthy.exec")
    for trace, exe in zip(traces, execs):
        one_cov, _, _ = coverage([exe])
        if not any(eligible_target(case, t, one_cov, trace)
                   for t in chosen_targets(case, trace)):
            raise RuntimeError("Selected guard not proven by healthy seed")
    _, methods, branches = coverage(execs)
    stable = stable_seed_io(case, traces)
    if not stable:
        raise RuntimeError("No stable same-actor pretarget I/O selectors")
    state = {"schema": 1, "case": case, "kind": kind, "healthy_seeds": seeds,
             "healthy_selected_target_counts": [len(chosen_targets(case, x)) for x in traces],
             "healthy_elapsed_seconds": sum(x["elapsed_seconds"] or 0 for x in traces),
             "healthy_stable_selectors": stable,
             "healthy_io_families": sorted({io_family(x) for x in stable}),
             "healthy_expected_outcomes": sorted({x["outcome"] for t in traces
                                                   for x in chosen_targets(case, t)}),
             "baseline_methods": sorted(methods), "baseline_branches": branches,
             "coverage_execs": list(map(str, execs)), "covered_methods": sorted(methods),
             "covered_branches": branches, "observed_selectors": stable,
             "io_family_counts": {family: 2 for family in {io_family(x) for x in stable}},
             "queue": [], "seen": [], "trials": [], "effective": 0,
             "max_effective": 80, "max_faults": 8, "max_attempts": 320,
             "status": "ready", "started_at_unix": time.time()}
    enqueue(state, [], stable, 0)
    atomic_json(checkpoint, state)
    publish(state)
    return state


def priority(entry, state):
    last = entry["plan"][-1]
    family = io_family(last)
    used = sum(io_family(t["plan"][-1]) == family for t in state["trials"])
    exact_used = sum(t["plan"][-1] == last for t in state["trials"])
    return entry["score"] + (20 if used == 0 else max(0, 7 - used)) \
        + (10 if exact_used == 0 else 0) + min(len(entry["plan"]), 6) * 2


def next_trial(state):
    state["queue"].sort(key=lambda x: (-priority(x, state), ";".join(x["plan"])))
    return state["queue"][0]


def maybe_expand(state):
    if state["effective"] < 80 or state["max_effective"] > 80:
        return
    recent = [x for x in state["trials"] if x["effective"]][-8:]
    if len(recent) == 8 and any(x.get("new_methods", 0) or x.get("new_branches", 0)
                                 or x.get("new_stable_io_families", 0) for x in recent):
        state["max_effective"] = 128
        state["max_faults"] = 10
        state["max_attempts"] = 512
        state["extended_at_trial"] = state["trials"][-1]["id"]
        for trial in list(state["trials"]):
            if trial["effective"] and len(trial["plan"]) < 10:
                trace, _ = load_run(state["kind"], state["case"] + "-" + trial["id"], "trial")
                enqueue(state, trial["plan"],
                        pretarget_io(state["case"], trace, trial["last_fault_seq"]), 0)


def ingest(state, entry, trial_id):
    case, kind = state["case"], state["kind"]
    seed = case + "-" + trial_id
    trace, code = load_run(kind, seed, "trial")
    exec_path = run_dir(kind, seed) / "trial.exec"
    one_coverage = ""
    if exec_path.is_file():
        one_coverage, _, _ = coverage([exec_path])
    receipt = exact_receipt(case, entry["plan"], trace, one_coverage)
    effective = receipt["strict"] and receipt["target_after_final_fault"]
    item = {"id": trial_id, "plan": entry["plan"], "requested_faults": len(entry["plan"]),
            "junit_exit": code, "junit": trace["junit"],
            "elapsed_seconds": trace["elapsed_seconds"], "effective": effective,
            "raw_run": str(run_dir(kind, seed).relative_to(HERE)), **receipt}
    if effective:
        if not exec_path.is_file():
            raise RuntimeError("Effective trial missing JaCoCo exec: " + trial_id)
        _, methods, branches = coverage(state["coverage_execs"] + [str(exec_path)])
        old_methods, old_branches = set(state["covered_methods"]), state["covered_branches"]
        item["new_methods"] = len(methods - old_methods)
        item["new_branches"] = sum(max(0, count - old_branches.get(key, 0))
                                   for key, count in branches.items())
        state["covered_methods"], state["covered_branches"] = sorted(methods), branches
        state["coverage_execs"].append(str(exec_path))
        observed = set(state["observed_selectors"])
        current = set(pretarget_io(case, trace, receipt["last_fault_seq"]))
        item["new_io_selectors"] = len(current - observed)
        item["new_io_families"] = len({io_family(x) for x in current}
                                      - {io_family(x) for x in observed})
        item["new_stable_io_families"] = 0
        for family in {io_family(x) for x in current}:
            count = state["io_family_counts"].get(family, 0) + 1
            state["io_family_counts"][family] = count
            if count == 2 and family not in state["healthy_io_families"]:
                item["new_stable_io_families"] += 1
        state["observed_selectors"] = sorted(observed | current)
        state["effective"] += 1
        if len(entry["plan"]) < state["max_faults"]:
            enqueue(state, entry["plan"], sorted(current),
                    item["new_methods"] + item["new_branches"]
                    + item["new_io_selectors"] + item["new_stable_io_families"])
    else:
        item["disposition"] = ("unmatched_or_wrong_actor" if not receipt["strict"]
                               else "target_lost_or_guard_unproven")
    # A selected HBASE-21/22 quota throw is already expected in healthy JUnit.
    item["target_exception_review"] = ("healthy_expected" if receipt["target_outcome"] in
                                        state["healthy_expected_outcomes"] else
                                        "candidate_needs_source_and_replay" if receipt["target_outcome"]
                                        and receipt["target_outcome"] != "normal" else "none")
    state["trials"].append(item)
    state["queue"].remove(entry)
    maybe_expand(state)
    return item


def campaign(case):
    checkpoint = HERE / "campaigns" / case / "checkpoint.json"
    if not checkpoint.is_file():
        raise RuntimeError("First run: controller.py init CASE SEED1 SEED2")
    state = json.loads(checkpoint.read_text())
    inflight_path = checkpoint.with_name("inflight.json")
    publish(state)
    if state["status"] == "candidate_review_pending_source_and_replay":
        raise RuntimeError("Review and replay the candidate before resuming this checkpoint")
    while state["effective"] < state["max_effective"] and len(state["trials"]) < state["max_attempts"]:
        if inflight_path.exists():
            inflight = json.loads(inflight_path.read_text())
            if any(x["id"] == inflight["id"] for x in state["trials"]):
                inflight_path.unlink()
                continue
            entry = next((x for x in state["queue"] if x["plan"] == inflight["plan"]), None)
            if entry is None:
                raise RuntimeError("In-flight plan absent from queue")
        else:
            if not state["queue"]:
                state["status"] = "queue_exhausted_pending_audit"
                break
            entry = next_trial(state)
            inflight = {"id": "r%03d" % (len(state["trials"]) + 1), "plan": entry["plan"]}
            atomic_json(inflight_path, inflight)
        seed = case + "-" + inflight["id"]
        directory = run_dir(state["kind"], seed)
        if not (directory / "trial.exit").exists():
            if directory.exists():
                # The previous JVM may still be running. Never reissue a
                # fault plan until a human audits the incomplete run.
                raise RuntimeError("Incomplete in-flight run; inspect process and directory " + str(directory))
            subprocess.run(["bash", str(RUN), "trial", state["kind"], seed,
                            ";".join(entry["plan"])], check=False)
        item = ingest(state, entry, inflight["id"])
        state["status"] = "running"
        atomic_json(checkpoint, state)
        publish(state)
        inflight_path.unlink()
        print(json.dumps({"case": case, "id": item["id"], "effective": state["effective"],
                          "attempted": len(state["trials"]), "queue": len(state["queue"]),
                          "disposition": item.get("disposition", "admitted")}), flush=True)
        if item["target_exception_review"] == "candidate_needs_source_and_replay":
            state["status"] = "candidate_review_pending_source_and_replay"
            break
    if state["effective"] >= state["max_effective"]:
        state["status"] = "budget_complete_pending_audit"
    elif len(state["trials"]) >= state["max_attempts"]:
        state["status"] = "attempt_cap_pending_audit"
    atomic_json(checkpoint, state)
    publish(state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "run", "inspect"))
    parser.add_argument("case", choices=CASES)
    parser.add_argument("seeds", nargs="*")
    args = parser.parse_args()
    if args.command == "init":
        if len(args.seeds) != 2 or args.seeds[0] == args.seeds[1]:
            parser.error("init requires two distinct healthy seed IDs")
        state = init(args.case, args.seeds)
        print(json.dumps({"case": args.case, "selectors": len(state["healthy_stable_selectors"]),
                          "families": state["healthy_io_families"], "queue": len(state["queue"])}))
    elif args.command == "run":
        campaign(args.case)
    else:
        path = HERE / "campaigns" / args.case / "checkpoint.json"
        print(path.read_text() if path.exists() else "No V2 checkpoint")


if __name__ == "__main__":
    main()
