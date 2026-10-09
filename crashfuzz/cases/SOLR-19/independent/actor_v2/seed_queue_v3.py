#!/usr/bin/env python3
"""Build actor-qualified one-fault seeds from two unchanged cluster runs."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import audit_seeds


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"
RECEIPT = EVIDENCE / "v3-healthy-receipt.json"
OUT = EVIDENCE / "v3-initial-queue.json"


def family(operation: str, path: str) -> str:
    if path.endswith("/state.json"):
        return "collection_state"
    if "/terms/" in path or path.endswith("/terms"):
        return "replica_terms"
    if "/leaders/" in path or "/leader_elect/" in path:
        return "leader_control"
    if path.startswith("/collections/testAddMultipleReplicas"):
        return "collection_other"
    if path.startswith("/overseer"):
        return "overseer_control"
    if path == "/live_nodes":
        return "live_nodes"
    return "other"


def candidates(seed: Path, seed_audit: dict):
    rows, groups = audit_seeds.read(seed)
    io = [row for row in rows if row["phase"].startswith("IO_")]
    counts = Counter()
    last_distance = {}
    for core_info in seed_audit["cores"]:
        core = core_info["core"]
        phases = groups[core]
        send = phases.get("SEND_CREATE_COLLECTION", []) + phases.get("SEND_ADD_REPLICA", [])
        target = phases.get("TARGET_GUARD", [])
        if len(send) != 1 or len(target) != 1:
            continue
        start, end = int(send[0]["seq"]), int(target[0]["seq"])
        for row in io:
            seq = int(row["seq"])
            if not start < seq < end or not audit_seeds.relevant_io_path(row["core"]):
                continue
            for side, role in (("OWNER", core_info["sender_role"]),
                               ("PRODUCER", core_info["producer_role"])):
                if side == "PRODUCER" and role == core_info["sender_role"]:
                    continue
                if role and role != "UNBOUND" and row["actor"] == role:
                    key = (core, side, row["phase"][3:], row["core"], row["detail"])
                    counts[key] += 1
                    last_distance[key] = end - seq
    return counts, last_distance


def main() -> None:
    receipt = json.loads(RECEIPT.read_text())
    a, b = receipt["seeds"]
    if any(seed["junit_exit"] != 0 or seed["core_count"] != 9 or seed["issue_count"]
           for seed in (a, b)):
        raise RuntimeError("Final two actor-aware original-JUnit seeds did not pass")
    seed_a, seed_b = EVIDENCE / "v3-seed-a", EVIDENCE / "v3-seed-b"
    count_a, distance_a = candidates(seed_a, a)
    count_b, distance_b = candidates(seed_b, b)
    stable = count_a.keys() & count_b.keys()
    priorities = {"collection_state": 0, "replica_terms": 1,
                  "leader_control": 2, "collection_other": 3,
                  "overseer_control": 4, "live_nodes": 5, "other": 6}
    plans = []
    for core, side, operation, path, caller in sorted(stable):
        key = core, side, operation, path, caller
        minimum = min(count_a[key], count_b[key])
        ordinals = {1, minimum, max(1, minimum // 2)}
        for ordinal in sorted(ordinals):
            if "|" in path or ";" in path or "|" in caller or ";" in caller:
                continue
            actor = side + "_OF_CORE:" + core
            selector = "|".join((operation, path, caller, actor, str(ordinal)))
            plans.append({"selector": selector, "core": core, "actor_spec": actor,
                          "family": family(operation, path),
                          "seed_a_occurrences": count_a[key],
                          "seed_b_occurrences": count_b[key],
                          "seed_a_last_distance_to_guard": distance_a[key],
                          "seed_b_last_distance_to_guard": distance_b[key],
                          "ordinal": ordinal})
    plans.sort(key=lambda plan: (priorities[plan["family"]], plan["ordinal"],
                                 -min(plan["seed_a_last_distance_to_guard"],
                                      plan["seed_b_last_distance_to_guard"]),
                                 plan["core"], plan["selector"]))
    output = {
        "case_id": "SOLR-19", "phase": "v3_actor_qualified_seed_queue",
        "original_junit": "AddReplicaTest.testAddMultipleReplicas",
        "receipt_sha256": hashlib.sha256(RECEIPT.read_bytes()).hexdigest(),
        "stable_actor_relative_site_count": len(stable),
        "distinct_one_fault_plan_count": len(plans),
        "family_counts": dict(Counter(plan["family"] for plan in plans)),
        "plans": plans,
    }
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, indent=2) + "\n")
    temporary.replace(OUT)
    print(json.dumps({key: value for key, value in output.items() if key != "plans"}))


if __name__ == "__main__":
    main()
