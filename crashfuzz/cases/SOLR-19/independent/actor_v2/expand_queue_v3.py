#!/usr/bin/env python3
"""Add lower-priority one-seed actor-qualified I/O without replaying trials."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time

import seed_queue_v3


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
STATE = EVIDENCE / "v3-campaign/state.json"
RECEIPT = EVIDENCE / "v3-exploratory-queue-receipt.json"
RANK = {"collection_state": 0, "replica_terms": 1,
        "leader_control": 2, "collection_other": 3,
        "overseer_control": 4, "live_nodes": 5, "other": 6}


def atomically(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> None:
    healthy_file = EVIDENCE / "v3-healthy-receipt.json"
    healthy = json.loads(healthy_file.read_text())
    a, b = (seed_queue_v3.candidates(EVIDENCE / name, seed)[0]
            for name, seed in zip(("v3-seed-a", "v3-seed-b"), healthy["seeds"]))
    only_a, only_b = set(a) - set(b), set(b) - set(a)
    plans = []
    rejected = Counter()
    for source, keys, counts in (("v3-seed-a", only_a, a), ("v3-seed-b", only_b, b)):
        for core, side, op, path, caller in sorted(keys):
            if re.search(r"/qn-\d+", path):
                rejected["ephemeral_overseer_queue_child"] += 1
                continue
            if any(delimiter in path or delimiter in caller for delimiter in ("|", ";")):
                rejected["selector_delimiter"] += 1
                continue
            count = counts[(core, side, op, path, caller)]
            for ordinal in sorted({1, count}):
                actor = side + "_OF_CORE:" + core
                selector = "|".join((op, path, caller, actor, str(ordinal)))
                plans.append({"steps": [{"selector": selector, "core": core,
                                           "family": seed_queue_v3.family(op, path)}],
                              "origin": "single_seed_actor_observed_exploratory",
                              "observed_seed": source,
                              "confidence": "one_of_two_original_healthy_runs"})
    plans.sort(key=lambda plan: (RANK[plan["steps"][0]["family"]],
                                 plan["steps"][0]["core"],
                                 plan["steps"][0]["selector"]))
    receipt = {"case_id": "SOLR-19", "phase": "v3_exploratory_io_queue",
               "healthy_receipt_sha256": hashlib.sha256(healthy_file.read_bytes()).hexdigest(),
               "one_seed_raw_site_counts": {"a_only": len(only_a), "b_only": len(only_b)},
               "rejected": dict(rejected), "plans_added": len(plans),
               "family_counts": dict(Counter(plan["steps"][0]["family"] for plan in plans)),
               "policy": "Distinct actor-relative marker, operation, exact path and caller; excludes generated qn sequence path. Each plan tried at most once; unmatched/lost-target never counts effective.",
               "plans": plans}
    if not STATE.exists():
        atomically(RECEIPT, receipt)
        print(json.dumps({k: v for k, v in receipt.items() if k != "plans"}))
        return
    state = json.loads(STATE.read_text())
    if state.get("inflight") is not None or state.get("stop_reason") != "paused_by_owner_at_complete_trial_boundary":
        raise RuntimeError("Queue migration requires a completed, paused original JUnit boundary")
    if "exploratory_migration" in state:
        raise RuntimeError("Exploratory queue already added; no duplicate migration")
    known = set(state["seen_plans"]) | {
        json.dumps(item["steps"], sort_keys=True) for item in state["queue"]}
    unique = []
    for plan in plans:
        signature = json.dumps(plan["steps"], sort_keys=True)
        if signature in known:
            continue
        unique.append(plan)
        known.add(signature)
    priority = [plan for plan in unique if plan["steps"][0]["family"] == "collection_state"]
    others = [plan for plan in unique if plan not in priority]
    # State checks are absent from the two-seed intersection and are worth a
    # bounded first look; stable plans still retain the next queue positions.
    state["queue"] = priority + state["queue"] + others
    state["exploratory_migration"] = {"created_at": time.time(),
                                     "added": len(unique),
                                     "priority_collection_state": len(priority),
                                     "receipt": str(RECEIPT.relative_to(HERE))}
    atomically(RECEIPT, receipt)
    atomically(STATE, state)
    print(json.dumps({"added": len(unique), "priority_collection_state": len(priority),
                      "remaining_queue": len(state["queue"]),
                      "attempts_unchanged": len(state["attempts"])}))


if __name__ == "__main__":
    main()
