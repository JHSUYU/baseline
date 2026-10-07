#!/usr/bin/env python3
"""Resumable V5 shared original-JUnit recovery campaign; requires two-seed gate."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

import v5_model as model

HERE = Path(__file__).resolve().parent
STATE = HERE / "campaign-state.json"
GATE = HERE / "calibration-gate.json"
LOCK = HERE / "campaign.lock"
PAUSE = HERE / "pause.request"
CATEGORIES = ("probes", "methods", "branch_counts")


def atomic(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def rows(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / "runtime_trace.jsonl").read_text().splitlines()
            if line]


def covered(directory: Path, category: str) -> set[str]:
    path = directory / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.exists() else set()


def io_family(event: dict) -> str:
    return "|".join(str(event.get(key, "")) for key in
                    ("marker", "siteId", "sourceKey", "originSourceKey", "requestApi"))


def assess(directory: Path, item: dict, state: dict) -> dict:
    trace = rows(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("overlay_digest") != json.loads(GATE.read_text())["overlay_digest"]:
        raise RuntimeError("trial overlay digest differs from healthy calibration")
    sequence = item["sequence"]
    matched = [r for r in trace if r.get("event") == "FAULT_MATCHED"]
    applied = [r for r in trace if r.get("event") == "FAULT_APPLIED"]
    episode = item["expectedEpisode"]
    strict = (len(matched) == len(applied) == len(sequence)
              and all(model.event_matches(matched[i], sequence[i], i, episode)
                      and model.event_matches(applied[i], sequence[i], i, episode)
                      and matched[i]["seq"] < applied[i]["seq"]
                      and model.identity_verified(trace, applied[i])
                      for i in range(len(sequence)))
              and all(applied[i]["seq"] < matched[i + 1]["seq"]
                      for i in range(len(sequence) - 1)))
    last = applied[-1] if strict else None
    checks = {case: model.later_target(trace, last, case) if last else []
              for case in model.CASES}
    throws = {}
    for case in model.CASES:
        throws[case] = [r for r in trace if r.get("event") == "TARGET_THROW"
                        and r.get("caseId") == case and r.get("siteId") == model.SITES[case]
                        and r.get("runtimeType") == "java.io.IOException"
                        and last is not None and r.get("seq", -1) > last["seq"]
                        and model.same_owner(last, r)
                        and any(c.get("outcome") is True and c["seq"] < r["seq"]
                                for c in checks[case])]
    all_coverage = {category: covered(directory, category) for category in CATEGORIES}
    families = {io_family(r) for r in trace if r.get("event") == "FAULT_POINT_OBSERVED"
                and r.get("marker", "").startswith("FAULT:")}
    gain = {case: {category: len(all_coverage[category]
                                 - set(state["coverage_v5"][case][category]))
                   if checks[case] else 0 for category in CATEGORIES}
            for case in model.CASES}
    new_io = {case: sorted(families - set(state["io_families_v5"][case]))
              if checks[case] else [] for case in model.CASES}
    return {"id": item["id"], "sequence": sequence, "run": str(directory),
            "junit_exit": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "overlay_digest": manifest["overlay_digest"],
            "requested_faults": len(sequence), "matched_faults": len(matched),
            "applied_faults": len(applied), "exact_order_applied": strict,
            "runtime_identity_verified": strict,
            "post_fault_target_checks": {case: len(checks[case]) for case in model.CASES},
            "target_exceptions_after_fault": {case: len(throws[case]) for case in model.CASES},
            "coverage_gain": gain, "new_io_families": new_io,
            "last_applied_seq": last["seq"] if last else None,
            "last_owner": model.owner(last) if last else None,
            "active_cases_at_selection": item["active_cases_at_selection"],
            "lane": item["lane"],
            "unmatched_attempts_before": item.get("legacy_unmatched_attempts", 0)
                + item.get("v5_unmatched_attempts", 0)}


def add_descendants(state: dict, trial: dict) -> None:
    if not trial["exact_order_applied"] or not any(trial["post_fault_target_checks"].values()):
        return
    active = model.active_cases(state)
    if not active:
        return
    if len(trial["sequence"]) >= max(state["cases"][case]["max_faults"]
                                     for case in active):
        return
    trace = rows(Path(trial["run"]))
    for event in trace:
        if event.get("seq", -1) <= trial["last_applied_seq"]:
            continue
        eligible = model.eligible_io(trace, event, active)
        if not eligible:
            continue
        kinds = (("IOException",) if event["marker"] == model.PRODUCER else
                 ("IOException", "FileNotFoundException") if
                 event["marker"].startswith("FAULT:HDFS_FILE:") else
                 ("IOException", "EOFException", "SocketTimeoutException"))
        for kind in kinds:
            seq = trial["sequence"] + [model.selector(event, kind)]
            identity = model.sequence_id(seq)
            if identity in state["seen_sequences"] or identity in state["strict_ids"]:
                continue
            state["seen_sequences"].append(identity)
            state["queue"].append({"id": identity, "sequence": seq,
                "expectedEpisode": event["clusterEpisode"], "created": time.time(),
                "priority": 50 if eligible else 0,
                "lane": "hdfs28_producer" if event["marker"] == model.PRODUCER
                        else "same_owner_second_fault" if len(seq) > 1 else "exploration",
                "pre_target_cases": eligible, "owner_evidence": [{
                    "parent_run": trial["run"], "io_seq": event["seq"],
                    "case": case, "owner": model.owner(event)} for case in eligible],
                "legacy_unmatched_attempts": 0, "v5_unmatched_attempts": 0})


def settle(state: dict, item: dict, trial: dict) -> None:
    state["completed_v5"].append(trial)
    state["v5_attempts"] += 1
    if trial["exact_order_applied"]:
        state["strict_ids"].append(item["id"])
    for case in item["active_cases_at_selection"]:
        c = state["cases"][case]
        c["attempts"] += 1
        if trial["exact_order_applied"] and trial["post_fault_target_checks"][case]:
            c["effective"] += 1
            c["target_exception_trials_v5"] += bool(trial["target_exceptions_after_fault"][case])
            for category in CATEGORIES:
                cset = set(state["coverage_v5"][case][category])
                cset.update(covered(Path(trial["run"]), category))
                state["coverage_v5"][case][category] = sorted(cset)
            family_set = set(state["io_families_v5"][case])
            family_set.update(io_family(row) for row in rows(Path(trial["run"]))
                              if row.get("event") == "FAULT_POINT_OBSERVED"
                              and row.get("marker", "").startswith("FAULT:"))
            state["io_families_v5"][case] = sorted(family_set)
        recent = [t for t in state["completed_v5"]
                  if case in t["active_cases_at_selection"] and t["exact_order_applied"]
                  and t["post_fault_target_checks"][case]]
        model.update_case_budget(c, recent, case)
    add_descendants(state, trial)
    total_unmatched = (item.get("legacy_unmatched_attempts", 0)
                       + item.get("v5_unmatched_attempts", 0))
    if not trial["exact_order_applied"] and total_unmatched + 1 < 3:
        retry = dict(item)
        retry["v5_unmatched_attempts"] = item.get("v5_unmatched_attempts", 0) + 1
        retry["created"] = time.time()
        state["queue"].append(retry)
    state["active"] = None
    if any(trial["target_exceptions_after_fault"][case]
           for case in item["active_cases_at_selection"]):
        state["stop_reason"] = "candidate_needs_exact_replay_and_source_review"
    atomic(STATE, state)


def fault_plan(run: Path, item: dict) -> Path:
    plan = run / "fault-plan.tsv"
    rows = []
    for fault in item["sequence"]:
        fields = [fault[key] for key in ("marker", "siteId", "sourceKey",
                                           "occurrenceAddress", "hitOrdinal", "faultType")]
        fields.extend((fault.get("filePhase", ""),
                       fault.get("clusterEpisode", item["expectedEpisode"])))
        rows.append("\t".join(map(str, fields)))
    content = "\n".join(rows) + "\n"
    if plan.exists() and plan.read_text() != content:
        raise RuntimeError("active plan changed while resuming")
    if not plan.exists():
        plan.write_text(content)
    return plan


def run_one(state: dict) -> None:
    active = state["active"]
    item = active["item"]
    run = Path(active["run"])
    run.mkdir(parents=True, exist_ok=True)
    plan = fault_plan(run, item)
    if not (run / "manifest.json").exists():
        if active["launched"]:
            state["stop_reason"] = "incomplete_receipt_pending_manual_reconcile"
            atomic(STATE, state)
            raise RuntimeError("launched JUnit lacks manifest; refusing automatic duplicate")
        active["launched"] = True
        active["started_at"] = time.time()
        atomic(STATE, state)
        command = [sys.executable, str(HERE / "run_original.py"), "--instrument",
                   "--plan", str(plan), "--output", str(run), "--timeout", "420"]
        with (run / "driver.log").open("w") as stream:
            subprocess.run(command, cwd=HERE, stdout=stream, stderr=subprocess.STDOUT)
    if not (run / "manifest.json").exists():
        raise RuntimeError("JUnit ended without manifest; active receipt preserved")
    trial = assess(run, item, state)
    settle(state, item, trial)
    print(json.dumps({"attempt": active["number"], "plan": item["id"],
                      "strict": trial["exact_order_applied"],
                      "post_target": trial["post_fault_target_checks"],
                      "effective": {case: state["cases"][case]["effective"]
                                    for case in model.CASES}}, sort_keys=True), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", type=int, default=0, help="maximum new complete trials")
    args = parser.parse_args()
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gate = json.loads(GATE.read_text()) if GATE.exists() else None
        if not gate or gate.get("passed") is not True:
            raise RuntimeError("two original-JUnit healthy calibrations have not passed")
        state = json.loads(STATE.read_text())
        if state["migration"]["v4_sha256"]["campaign-state.json"] != \
                __import__("hashlib").sha256(Path(state["migration"]["v4_dir"],
                    "campaign-state.json").read_bytes()).hexdigest():
            raise RuntimeError("V4 ancestry SHA changed")
        if any(c["status"] == "awaiting_calibration" for c in state["cases"].values()):
            raise RuntimeError("activate two-seed gate before scheduling")
        completed_here = 0
        while state["active"] or (model.active_cases(state) and state["queue"]):
            if state.get("stop_reason") == "candidate_needs_exact_replay_and_source_review":
                return
            if PAUSE.exists():
                state["stop_reason"] = "operator_pause"
                atomic(STATE, state)
                return
            if not state["active"]:
                try:
                    index = model.select_index(state)
                except RuntimeError:
                    for case in model.active_cases(state):
                        state["cases"][case]["status"] = "budget_recheck_pending"
                    state["stop_reason"] = "no_eligible_queue_pending_scope_review"
                    atomic(STATE, state)
                    return
                item = state["queue"].pop(index)
                item["active_cases_at_selection"] = list(model.active_cases(state))
                number = 129 + state["v5_attempts"]
                state["active"] = {"item": item, "number": number,
                                   "run": str(HERE / "runs" / ("trial-%03d" % number)),
                                   "launched": False}
                state["stop_reason"] = None
                atomic(STATE, state)
            run_one(state)
            if state.get("stop_reason") == "candidate_needs_exact_replay_and_source_review":
                return
            completed_here += 1
            if args.once and completed_here >= args.once:
                return
        if model.active_cases(state):
            for case in model.active_cases(state):
                state["cases"][case]["status"] = "budget_recheck_pending"
            state["stop_reason"] = "queue_exhausted_pending_scope_review"
        else:
            state["stop_reason"] = "quality_budget_met_pending_audit"
        atomic(STATE, state)


if __name__ == "__main__":
    main()
