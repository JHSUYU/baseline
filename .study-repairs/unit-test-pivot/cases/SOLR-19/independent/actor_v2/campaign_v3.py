#!/usr/bin/env python3
"""Resumable, actor-qualified CrashFuzz-style original-JUnit campaign."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import audit_seeds
import coverage_probes_v3
import seed_queue_v3


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
CAMPAIGN = EVIDENCE / "v3-campaign"
STATE = CAMPAIGN / "state.json"
CASE_RESULT = HERE.parents[1] / "result.json"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
BASE_EFFECTIVE, BASE_FAULTS = 80, 8
EXTENDED_EFFECTIVE, EXTENDED_FAULTS = 128, 10
ATTEMPT_CAP = 240
WALL_CAP_SECONDS = 24 * 3600


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def normalized_path(path: str) -> str:
    # Ephemeral queue sequence numbers and host ports are occurrence data,
    # never a reason to extend the budget for a supposedly new I/O family.
    path = re.sub(r"(?<=/)qn-\d+(?=/|$)", "qn-*", path)
    path = re.sub(r"(?<=/)n_\d+(?=/|$)", "n_*", path)
    if path.startswith("/live_nodes/"):
        return "/live_nodes/<node>"
    return path


def parse_selector(selector: str) -> dict:
    parts = selector.split("|")
    if len(parts) != 5:
        raise ValueError(f"bad selector: {selector}")
    return {"op": parts[0], "path": parts[1], "caller": parts[2],
            "actor_spec": parts[3], "ordinal": int(parts[4])}


def send_by_core(rows: list[dict]) -> dict[str, list[dict]]:
    sends = defaultdict(list)
    for row in rows:
        if row["phase"] in ("SEND_CREATE_COLLECTION", "SEND_ADD_REPLICA"):
            sends[row["core"]].append(row)
    return sends


def latest_sender(sends: dict, core: str, at_seq: int) -> dict | None:
    return next((row for row in reversed(sends.get(core, []))
                 if int(row["seq"]) < at_seq), None)


def role_by_node(rows: list[dict]) -> dict[str, str]:
    return {row["core"]: row["actor"] for row in rows if row["phase"] == "ZK_BIND"}


def producer_role(sender: dict) -> str | None:
    detail = sender["detail"]
    return detail.rsplit("|sourceRole=", 1)[1] if "|sourceRole=" in detail else None


def actor_for(spec: str, senders: dict, roles: dict, at_seq: int) -> str | None:
    if spec.startswith("OWNER_OF_CORE:"):
        sender = latest_sender(senders, spec[len("OWNER_OF_CORE:"):], at_seq)
        return roles.get(sender["actor"]) if sender else None
    if spec.startswith("PRODUCER_OF_CORE:"):
        sender = latest_sender(senders, spec[len("PRODUCER_OF_CORE:"):], at_seq)
        return producer_role(sender) if sender else None
    return None  # Fixed Jetty labels cannot be assumed across original JUnit runs.


def exact_applied(rows: list[dict], steps: list[dict]) -> tuple[bool, list[dict], list[str]]:
    matched = [row for row in rows if row["phase"] == "FAULT_MATCHED"]
    applied = [row for row in rows if row["phase"] == "FAULT_APPLIED_CONNECTION_LOSS"]
    issues = []
    if len(matched) != len(applied) or len(applied) != len(steps):
        issues.append(f"matched={len(matched)} applied={len(applied)} planned={len(steps)}")
    sends, roles = send_by_core(rows), role_by_node(rows)
    by_seq = {int(row["seq"]): row for row in rows}
    previous = 0
    for index, (event, step) in enumerate(zip(applied, steps)):
        parsed = parse_selector(step["selector"])
        seq = int(event["seq"])
        details = dict(part.split("=", 1) for part in event["detail"].split(";") if "=" in part)
        actor = actor_for(parsed["actor_spec"], sends, roles, seq)
        preceding = by_seq.get(seq - 2)  # IO, FAULT_MATCHED, FAULT_APPLIED are synchronized.
        if int(details.get("index", -1)) != index or event["core"] != parsed["path"]:
            issues.append(f"step{index}_wrong_index_or_resource")
        if (details.get("actorSpec") != parsed["actor_spec"] or
                details.get("caller") != parsed["caller"] or
                int(details.get("ordinal", -1)) != parsed["ordinal"]):
            issues.append(f"step{index}_wrong_selector_detail")
        if actor is None or actor == "UNBOUND" or event["actor"] != actor:
            issues.append(f"step{index}_wrong_logical_actor")
        if (preceding is None or preceding["phase"] != "IO_" + parsed["op"] or
                preceding["core"] != parsed["path"] or
                preceding["actor"] != actor or preceding["detail"] != parsed["caller"]):
            issues.append(f"step{index}_no_exact_preceding_io")
        core = step["core"]
        sender = latest_sender(sends, core, seq)
        lower = max(previous, int(sender["seq"]) if sender else 0)
        count = sum(row["phase"] == "IO_" + parsed["op"] and
                    row["core"] == parsed["path"] and row["actor"] == actor and
                    row["detail"] == parsed["caller"] and
                    lower < int(row["seq"]) < seq
                    for row in rows)
        if count != parsed["ordinal"]:
            issues.append(f"step{index}_occurrence_count={count}_expected={parsed['ordinal']}")
        previous = seq
    return not issues and len(applied) == len(steps), applied, issues


def relevant_sites(rows: list[dict], after_seq: int = 0) -> list[dict]:
    """I/O strictly between that core's sender and later exact target guard."""
    senders, roles = send_by_core(rows), role_by_node(rows)
    guards = defaultdict(list)
    for row in rows:
        if row["phase"] == "TARGET_GUARD":
            guards[row["core"]].append(int(row["seq"]))
    io = [row for row in rows if row["phase"].startswith("IO_") and
          audit_seeds.relevant_io_path(row["core"]) and row["actor"] != "UNBOUND"]
    out = []
    emitted = set()
    for core, target_seq in ((core, seq) for core, seqs in guards.items() for seq in seqs):
        sender = latest_sender(senders, core, target_seq)
        if sender is None:
            continue
        start = max(int(sender["seq"]), after_seq)
        owner = roles.get(sender["actor"])
        producer = producer_role(sender)
        for row in io:
            seq = int(row["seq"])
            if not start < seq < target_seq:
                continue
            sides = []
            if row["actor"] == owner:
                sides.append("OWNER")
            if row["actor"] == producer and producer != owner:
                sides.append("PRODUCER")
            for side in sides:
                occurrence = (core, side, seq)
                if occurrence in emitted:
                    continue
                emitted.add(occurrence)
                out.append({"core": core, "side": side, "op": row["phase"][3:],
                            "path": row["core"], "caller": row["detail"],
                            "seq": seq, "distance_to_guard": target_seq - seq,
                            "family": seed_queue_v3.family(row["phase"][3:], row["core"])})
    return out


def behavior_id(site: dict) -> str:
    # Site novelty intentionally excludes hit ordinal and transient queue IDs.
    return "|".join((site["side"], site["op"], normalized_path(site["path"]),
                     site["caller"]))


def new_children(rows: list[dict], steps: list[dict], last_seq: int,
                 known: set[str], novel: bool, max_faults: int) -> list[dict]:
    if len(steps) >= max_faults:
        return []
    candidates = relevant_sites(rows, after_seq=last_seq)
    count = Counter()
    picked = []
    for site in sorted(candidates, key=lambda x: x["seq"]):
        key = (site["core"], site["side"], site["op"], site["path"], site["caller"])
        count[key] += 1
        if any(c in site["path"] or c in site["caller"] for c in ("|", ";")):
            continue
        actor = site["side"] + "_OF_CORE:" + site["core"]
        selector = "|".join((site["op"], site["path"], site["caller"], actor,
                             str(count[key])))
        child = {"steps": steps + [{"selector": selector, "core": site["core"],
                                     "family": site["family"]}],
                 "origin": "mutated_from_observed_postfault_io"}
        signature = json.dumps(child["steps"], sort_keys=True)
        if signature in known:
            continue
        picked.append((site["family"], site["distance_to_guard"], signature, child))
    # Prefer different I/O families, then sites with some recovery work before the guard.
    picked.sort(key=lambda item: (item[0] == "overseer_control", -item[1], item[2]))
    selected, families = [], set()
    for family, _, signature, child in picked:
        if family in families:
            continue
        families.add(family)
        known.add(signature)
        selected.append(child)
        if len(selected) >= (4 if novel else 2):
            break
    return selected


def initialize() -> dict:
    if not CASE_RESULT.exists():
        raise RuntimeError("Sync the case result template before launching the original JUnit")
    initial = json.loads((EVIDENCE / "v3-initial-queue.json").read_text())
    receipt = json.loads((EVIDENCE / "v3-healthy-receipt.json").read_text())
    if any(seed["junit_exit"] != 0 or seed["core_count"] != 9 or seed["issue_count"]
           for seed in receipt["seeds"]):
        raise RuntimeError("two actor-qualified, passing original JUnit seeds required")
    queue = [{"steps": [{"selector": plan["selector"], "core": plan["core"],
                          "family": plan["family"]}], "origin": "stable_two_seed_io"}
             for plan in initial["plans"]]
    if not queue:
        raise RuntimeError("no stable actor-qualified I/O selectors")
    seed_sites = set()
    for name in ("v3-seed-a", "v3-seed-b"):
        rows, _ = audit_seeds.read(EVIDENCE / name)
        seed_sites.update(map(behavior_id, relevant_sites(rows)))
    baseline = (coverage_probes_v3.covered(EVIDENCE / "v3-seed-a/jacoco.exec") |
                coverage_probes_v3.covered(EVIDENCE / "v3-seed-b/jacoco.exec"))
    state = {"case_id": "SOLR-19", "phase": "actor_v3_original_junit",
             "methodology": "coverage_io_no_graph_exact_actor", "started_at": time.time(),
             "budget": {"effective_trials": BASE_EFFECTIVE, "max_ordered_faults": BASE_FAULTS,
                        "attempt_cap": ATTEMPT_CAP, "wall_cap_seconds": WALL_CAP_SECONDS},
             "healthy_production_probes": len(baseline),
             "seen_probes": sorted(baseline), "seen_io": sorted(seed_sites),
             "queue": queue, "seen_plans": [], "attempts": [], "inflight": None,
             "stop_reason": None, "extension_reason": None}
    atomic_json(STATE, state)
    return state


def counts(state: dict) -> dict:
    trials = state["attempts"]
    return {"attempts": len(trials),
            "strict": sum(x["strict_exact_actor"] for x in trials),
            "effective": sum(x["effective"] for x in trials),
            "candidates": sum(x["target_exception"] for x in trials),
            "elapsed_seconds": round(sum(x["elapsed_seconds"] for x in trials), 3),
            "new_production_probes": len(state["seen_probes"]) - state["healthy_production_probes"]}


def publish(state: dict) -> None:
    if not state["attempts"]:
        return
    prior = json.loads(CASE_RESULT.read_text())
    stat = counts(state)
    is_pause = state["stop_reason"] == "paused_by_owner_at_complete_trial_boundary"
    prior.update({"status": "running" if state["stop_reason"] is None or is_pause else
                  "pending_result_review", "quality_complete": False,
                  "methodology": "coverage_io_no_graph_exact_actor",
                  "campaign_workspace": "cases/SOLR-19/independent/actor_v2",
                  "evidence": str(STATE.relative_to(HERE.parents[5])),
                  "fault_trials": stat["attempts"],
                  "strict_injections": stat["strict"],
                  "target_after_fault": stat["effective"],
                  "target_exception_candidates": stat["candidates"],
                  "coverage_gain": stat["new_production_probes"],
                  "elapsed_seconds": stat["elapsed_seconds"],
                  "budget": state["budget"],
                  "bug_mark": "candidate_needs_source_review" if stat["candidates"] else "none",
                  "reason": state["stop_reason"] or "Actor V3 original-JUnit campaign in progress."})
    atomic_json(CASE_RESULT, prior)


def choose(state: dict) -> dict:
    # Spend one in four attempts on a fresh one-fault family. Feedback children
    # take the other three slots, with short JUnit time and wait age as ties.
    queue = state["queue"]
    if len(state["attempts"]) % 4 == 3:
        for i, plan in enumerate(queue):
            if len(plan["steps"]) == 1:
                return queue.pop(i)
    return queue.pop(0)


def finish_attempt(state: dict) -> None:
    inflight = state["inflight"]
    if inflight is None:
        return
    number, plan = inflight["number"], inflight["plan"]
    output = CAMPAIGN / f"r{number:03d}"
    manifest = json.loads((output / "manifest.json").read_text())
    rows, _ = audit_seeds.read(output)
    strict, applied, issues = exact_applied(rows, plan["steps"])
    last_seq = int(applied[-1]["seq"]) if applied else -1
    core = plan["steps"][-1]["core"]
    after = [r for r in rows if r["phase"] == "TARGET_GUARD" and r["core"] == core
             and int(r["seq"]) > last_seq] if last_seq >= 0 else []
    target_after = bool(after)
    target_exception = strict and any(r["detail"] == "missing" for r in after)
    effective = strict and target_after
    covered = coverage_probes_v3.covered(output / "jacoco.exec") if effective else set()
    old_probes = set(state["seen_probes"])
    new_probes = covered - old_probes
    sites = relevant_sites(rows)
    current_io = set(map(behavior_id, sites))
    old_io = set(state["seen_io"])
    new_io = current_io - old_io if effective else set()
    if effective:
        state["seen_probes"] = sorted(old_probes | covered)
        state["seen_io"] = sorted(old_io | current_io)
    record = {"number": number, "plan": plan, "elapsed_seconds": manifest["elapsed_seconds"],
              "junit_exit": manifest["exit_code"], "faults_planned": len(plan["steps"]),
              "faults_applied": len(applied), "strict_exact_actor": strict,
              "identity_issues": issues, "target_core": core,
              "target_after_last_fault": target_after, "target_exception": target_exception,
              "effective": effective, "new_production_probes": len(new_probes),
              "new_stable_io_families": len(new_io), "observed_io_sites": len(sites),
              "evidence": str(output.relative_to(HERE))}
    atomic_json(output / "trial.json", record)
    state["attempts"].append(record)
    state["inflight"] = None
    if effective and (manifest["exit_code"] != 124 or new_probes or new_io):
        known = set(state["seen_plans"]) | {
            json.dumps(x["steps"], sort_keys=True) for x in state["queue"]}
        children = new_children(rows, plan["steps"], last_seq, known,
                                bool(new_probes or new_io), state["budget"]["max_ordered_faults"])
        state["queue"] = children + state["queue"]
    stat = counts(state)
    if stat["effective"] == BASE_EFFECTIVE:
        recent = [x for x in state["attempts"] if x["effective"]][-8:]
        if any(x["new_production_probes"] or x["new_stable_io_families"] for x in recent):
            state["budget"]["effective_trials"] = EXTENDED_EFFECTIVE
            state["budget"]["max_ordered_faults"] = EXTENDED_FAULTS
            state["extension_reason"] = "Novel production probes or normalized I/O sites in final eight effective trials"
    atomic_json(STATE, state)
    publish(state)
    print(json.dumps({"trial": number, "strict": strict, "target_after": target_after,
                      "target_exception": target_exception, "junit_exit": manifest["exit_code"],
                      "new_probes": len(new_probes), "new_io": len(new_io),
                      "elapsed": manifest["elapsed_seconds"], "totals": counts(state)}), flush=True)


def run_one(state: dict) -> None:
    if state["inflight"] is None:
        plan = choose(state)
        signature = json.dumps(plan["steps"], sort_keys=True)
        if signature in state["seen_plans"]:
            raise RuntimeError("duplicate plan reached queue head")
        state["seen_plans"].append(signature)
        state["inflight"] = {"number": len(state["attempts"]) + 1,
                             "plan": plan, "resume_count": 0}
        atomic_json(STATE, state)
    inflight = state["inflight"]
    output = CAMPAIGN / f"r{inflight['number']:03d}"
    if not (output / "manifest.json").exists():
        if output.exists():
            backup = CAMPAIGN / (output.name + f".partial-{inflight['resume_count']}")
            output.rename(backup)
            inflight["resume_count"] += 1
            atomic_json(STATE, state)
        fault_specs = ";".join(step["selector"] for step in inflight["plan"]["steps"])
        with (CAMPAIGN / "runner.log").open("a") as log:
            subprocess.run(["/usr/bin/python3", str(HERE / "run_v2.py"), str(output),
                            "--source-root", str(SOURCE), "--coverage", "--faults", fault_specs,
                            "--timeout", "180"], stdout=log, stderr=subprocess.STDOUT, check=False)
    if not (output / "manifest.json").exists():
        raise RuntimeError(f"original JUnit produced no manifest: {output}")
    finish_attempt(state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-at-effective", type=int)
    parser.add_argument("--max-new-attempts", type=int)
    args = parser.parse_args()
    queue = json.loads((EVIDENCE / "v3-initial-queue.json").read_text())
    if args.dry_run:
        print(json.dumps({"initial_plans": len(queue["plans"]),
                          "families": queue["family_counts"],
                          "source": str(SOURCE), "state_exists": STATE.exists()}))
        return
    if not SOURCE.exists():
        raise RuntimeError(f"Missing exact Solr source on node1: {SOURCE}")
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    if state["stop_reason"] == "paused_by_owner_at_complete_trial_boundary" and not (CAMPAIGN / "STOP_AFTER_TRIAL").exists():
        state["stop_reason"] = None
        atomic_json(STATE, state)
    initial_attempts = len(state["attempts"])
    while True:
        stat = counts(state)
        if args.stop_at_effective is not None and stat["effective"] >= args.stop_at_effective:
            break  # pilot boundary; do not mark terminal or consume another plan
        if args.max_new_attempts is not None and len(state["attempts"]) - initial_attempts >= args.max_new_attempts:
            break
        reason = None
        if stat["effective"] >= state["budget"]["effective_trials"]:
            reason = "effective_budget_reached_pending_source_review"
        elif stat["attempts"] >= state["budget"]["attempt_cap"]:
            reason = "attempt_cap_reached"
        elif stat["elapsed_seconds"] >= state["budget"]["wall_cap_seconds"]:
            reason = "wall_cap_reached"
        elif not state["queue"] and state["inflight"] is None:
            reason = "actor_qualified_io_queue_exhausted"
        elif (CAMPAIGN / "STOP_AFTER_TRIAL").exists():
            reason = "paused_by_owner_at_complete_trial_boundary"
        elif shutil.disk_usage(CAMPAIGN).free < 8 * 1024**3:
            reason = "node1_disk_guard_under_8_gib"
        if reason:
            state["stop_reason"] = reason
            atomic_json(STATE, state)
            publish(state)
            print(json.dumps({"stop": reason, "totals": stat}), flush=True)
            break
        run_one(state)


if __name__ == "__main__":
    main()
