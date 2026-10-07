#!/usr/bin/env python3
"""Coverage and I/O feedback guided mutation from original-JUnit recovery traces."""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import re
import socket
import time

import run_recovery_children as children
from receipt_validator import parse_events, fault_selector


ROOT = Path("/users/ZhenyuLi/zk03-upgrade-deep")
MANIFEST = ROOT / "deep-manifest.json"
CHECKPOINT = ROOT / "deep-checkpoint.json"
CHILD_ROOT = Path("/users/ZhenyuLi/zk03-upgrade-recovery-children")
children.ROOT = ROOT
children.pilot.PILOT = ROOT
CHANNEL = re.compile(r":channel:(\d+):op:")


def verify():
    assets, build = children.pilot.up.assets()
    manifest = json.loads(MANIFEST.read_text())
    source = json.loads((CHILD_ROOT / "child-checkpoint.json").read_text())
    pilot_state = json.loads((children.PARENT / "pilot-checkpoint.json").read_text())
    if manifest["original_commit"] != children.pilot.up.base.ORIGINAL_SOURCE or \
            manifest["agent_sha256"] != build["agent_sha256"] or \
            manifest["child_checkpoint_sha256"] != children.pilot.sha(
                CHILD_ROOT / "child-checkpoint.json") or \
            manifest["child_archive_sha256"] != children.pilot.sha(
                ROOT / "zk03-upgrade-recovery-children-raw.tar.gz") or \
            source["status"] != "queue_exhausted" or len(source["results"]) != 13 or \
            pilot_state["status"] != "queue_exhausted" or \
            manifest["effective_target"] != 80 or \
            manifest["max_faults"] != 8 or manifest["selected_cap"] != 256:
        raise RuntimeError("deep source, agent, or fixed budget changed")
    return assets, build, manifest, source, pilot_state


def baseline_feedback(source):
    parent_audit = json.loads((children.PARENT / "pilot-feedback-audit.json").read_text())
    covered, known_io = children.base_feedback(parent_audit)
    for row in source["results"]:
        if not row["target_after_final_fault"]:
            continue
        run = CHILD_ROOT / row["run_id"]
        covered |= set((run / "coverage.tsv").read_text().splitlines())
        last = max(s for s, kind, _ in parse_events(run / "events.tsv")
                   if kind == "FAULT_APPLIED")
        target = row["target_receipt"]["target_sequence"]
        known_io |= {"@@".join(f[:3]) for s, kind, f in
                     parse_events(run / "events.tsv")
                     if last < s < target and kind == "IO"
                     and len(f) >= 7 and f[6] == "upgradedSession"}
    return covered, known_io


def mutate(seed, rows, known_io, max_faults, seen_plans, trial_round):
    if not seed["target_after_final_fault"] or len(seed["plan"]) >= max_faults:
        return []
    last = max(s for s, kind, _ in rows if kind == "FAULT_APPLIED")
    target = seed["target_receipt"]["target_sequence"]
    observed = []
    for seq, kind, fields in rows:
        if not (last < seq < target and kind == "IO" and len(fields) >= 7
                and fields[6] == "upgradedSession" and fields[1] and fields[2]):
            continue
        selector = fault_selector(fields)
        plan = seed["plan"] + [selector]
        token = "|||".join(plan)
        if token in seen_plans:
            continue
        family = "@@".join(fields[:3])
        channel = CHANNEL.search(fields[2])
        generation = int(channel.group(1)) if channel else 0
        novel = family not in known_io
        priority = (10 if novel else 0) + (5 if generation > 1 else 0)
        priority += min(4, seed["new_target_io_families"])
        priority += min(4, seed["new_target_coverage_lines"])
        priority += min(len(plan), 6)
        if len(plan) > 6:
            priority -= 2 * (len(plan) - 6)
        observed.append({"parent": seed["run_id"], "plan": plan,
                         "child_family": fields[1].split(":", 1)[0] + ":" +
                                         fields[2].rsplit(":op:", 1)[-1],
                         "family": family, "novel_at_generation": novel,
                         "channel_generation": generation,
                         "observed_sequence": seq,
                         "parent_last_fault_sequence": last,
                         "parent_target_sequence": target,
                         "priority": priority,
                         "enqueued_round": trial_round})
    observed.sort(key=lambda x: (-x["priority"], x["observed_sequence"]))
    selected = []
    per_family = {}
    for entry in observed:
        if per_family.get(entry["family"], 0) >= 3:
            continue
        token = "|||".join(entry["plan"])
        if token in seen_plans:
            continue
        selected.append(entry)
        seen_plans.add(token)
        per_family[entry["family"]] = per_family.get(entry["family"], 0) + 1
        if len(selected) == 6:
            break
    return selected


def initial_state(manifest, source, pilot_state):
    covered, known_io = baseline_feedback(source)
    seen_plans = {"|||".join([r["selector"]]) for r in pilot_state["results"]}
    seen_plans |= {"|||".join(r["plan"]) for r in source["results"]}
    queue = []
    for row in source["results"]:
        if not row["target_after_final_fault"]:
            continue
        raw = parse_events(CHILD_ROOT / row["run_id"] / "events.tsv")
        queue.extend(mutate(row, raw, known_io, manifest["max_faults"],
                            seen_plans, 0))
    return {"schema": 1, "case_id": "ZOOKEEPER-03",
            "phase": "session-upgrade-depth3plus", "status": "running",
            "manifest_sha256": children.pilot.sha(MANIFEST),
            "source_pilot_selected": 10, "source_child_selected": 13,
            "source_pilot_effective": sum(r["target_after_final_fault"]
                                          for r in pilot_state["results"]),
            "source_child_effective": sum(r["target_after_final_fault"]
                                          for r in source["results"]),
            "seen_coverage": sorted(covered), "seen_io_families": sorted(known_io),
            "seen_plans": sorted(seen_plans), "queue": queue,
            "results": [], "inflight": None, "started_wall": time.time()}


def choose(state):
    round_number = len(state["results"])
    return max(state["queue"], key=lambda x: (
        x["priority"] + min(5, (round_number - x["enqueued_round"]) // 10),
        x["novel_at_generation"], -x["observed_sequence"]))


def complete(state, job, run_id, receipt, manifest):
    if receipt["selector"] != "|||".join(job["plan"]) or \
            receipt["agent_sha256"] != manifest["agent_sha256"] or \
            receipt["events_sha256"] != children.pilot.sha(ROOT / run_id / "events.tsv") or \
            receipt["coverage_sha256"] != children.pilot.sha(ROOT / run_id / "coverage.tsv"):
        raise RuntimeError("deep trial receipt differs from frozen actor plan or raw")
    audit_job = {"child_id": run_id, "parent": job["parent"],
                 "plan": job["plan"], "child_family": job["child_family"]}
    row = children.audit(audit_job, receipt, set(state["seen_coverage"]),
                         set(state["seen_io_families"]))
    row["queue_priority"] = job["priority"]
    row["observed_parent_sequence"] = job["observed_sequence"]
    state["results"].append(row)
    state["queue"].remove(job)
    state["inflight"] = None
    if row["target_after_final_fault"]:
        known_before = set(state["seen_io_families"])
        state["seen_coverage"] = sorted(set(state["seen_coverage"]) |
                                        set(row["coverage"]))
        state["seen_io_families"] = sorted(set(state["seen_io_families"]) |
                                           set(row["io_families"]))
        seen_plans = set(state["seen_plans"])
        state["queue"].extend(mutate(row, parse_events(ROOT / run_id / "events.tsv"),
                                     known_before,
                                     manifest["max_faults"], seen_plans,
                                     len(state["results"])))
        state["seen_plans"] = sorted(seen_plans)
    children.pilot.up.write_json(CHECKPOINT, state)
    print(json.dumps({key: row[key] for key in
          ("run_id", "exact_injection", "target_after_final_fault",
           "selected_target_throws", "new_target_coverage_lines",
           "new_target_io_families", "elapsed_seconds")}, sort_keys=True), flush=True)
    return row


def recover(state, manifest):
    inflight = state["inflight"]
    if inflight is None:
        return True
    job = inflight["job"]
    run_id = inflight["run_id"]
    receipt = ROOT / run_id / "run.json"
    if receipt.is_file():
        complete(state, job, run_id, json.loads(receipt.read_text()), manifest)
        return True
    state["status"] = "paused_inflight_needs_manual_audit"
    children.pilot.up.write_json(CHECKPOINT, state)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--wall-limit", type=int, default=1800)
    args = parser.parse_args()
    if not socket.gethostname().startswith("node1"):
        raise RuntimeError("ZK03 depth stage reserved for node1")
    assets, build, manifest, source, pilot_state = verify()
    if not args.run:
        print(json.dumps({"status": "prepared_no_jvm", "pilot_selected": 10,
                          "child_selected": 13, "target": manifest["effective_target"],
                          "max_faults": manifest["max_faults"]}, sort_keys=True))
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "deep.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(CHECKPOINT.read_text()) if CHECKPOINT.is_file() else \
            initial_state(manifest, source, pilot_state)
        if state["manifest_sha256"] != children.pilot.sha(MANIFEST):
            raise RuntimeError("deep checkpoint/manifest mismatch")
        if not CHECKPOINT.is_file():
            children.pilot.up.write_json(CHECKPOINT, state)
        if not recover(state, manifest):
            print(json.dumps({"status": state["status"],
                              "inflight": state["inflight"]}, sort_keys=True))
            return
        if state["status"] in ("candidate_needs_replay", "paused_junit_timeout",
                               "effective_budget_80_reached",
                               "selected_cap_before_effective_budget",
                               "queue_exhausted_before_effective_budget"):
            print(json.dumps({"status": state["status"],
                              "selected": len(state["results"])}, sort_keys=True))
            return
        started = time.monotonic()
        while state["queue"]:
            effective = (state["source_pilot_effective"] +
                         state["source_child_effective"] +
                         sum(r["target_after_final_fault"] for r in state["results"]))
            if effective >= manifest["effective_target"]:
                state["status"] = "effective_budget_80_reached"
                break
            if len(state["results"]) >= manifest["selected_cap"]:
                state["status"] = "selected_cap_before_effective_budget"
                break
            if time.monotonic() - started >= args.wall_limit:
                state["status"] = "paused_wall_limit"
                break
            job = choose(state)
            run_id = "deep-{:04d}".format(len(state["results"]) + 1)
            state["inflight"] = {"run_id": run_id, "job": job}
            state["status"] = "running"
            children.pilot.up.write_json(CHECKPOINT, state)
            try:
                receipt = children.pilot.run_one(
                    {"pilot_id": run_id, "selector": "|||".join(job["plan"])},
                    assets, build, args.timeout)
            except RuntimeError as error:
                state["status"] = "paused_resource_or_inflight"
                state["pause_reason"] = str(error)
                children.pilot.up.write_json(CHECKPOINT, state)
                break
            row = complete(state, job, run_id, receipt, manifest)
            if row["selected_target_throws"]:
                state["status"] = "candidate_needs_replay"
                break
            if receipt["exit_code"] == 124:
                state["status"] = "paused_junit_timeout"
                break
        else:
            state["status"] = "queue_exhausted_before_effective_budget"
        state["finished_wall"] = time.time()
        children.pilot.up.write_json(CHECKPOINT, state)
        print(json.dumps({"status": state["status"],
                          "deep_selected": len(state["results"]),
                          "deep_effective": sum(r["target_after_final_fault"]
                                                for r in state["results"]),
                          "total_new_seed_effective": (
                              state["source_pilot_effective"] +
                              state["source_child_effective"] +
                              sum(r["target_after_final_fault"]
                                  for r in state["results"])),
                          "pending": len(state["queue"])}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
