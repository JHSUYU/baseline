#!/usr/bin/env python3
"""Emit one compact, internally consistent snapshot of node2's ZK01 run."""

from __future__ import annotations

import json
from pathlib import Path


BASE = Path("/users/ZhenyuLi/zk01-unit/campaign")
CASE = BASE / "results/ZOOKEEPER-01"


def production(identifier: str) -> bool:
    if not identifier.startswith(("METHOD:", "BRANCH:")):
        return False
    method = identifier.split(":", 1)[1].split("#u", 1)[0]
    if not method.startswith("<org.apache.zookeeper."):
        return False
    owner = method[1:].split(":", 1)[0].split("$")[0]
    return not owner.rsplit(".", 1)[-1].endswith("Test")


def main() -> None:
    state = json.loads((CASE / "state.json").read_text())
    result = json.loads((CASE / "result.json").read_text())
    if result["fault_trials"] != len(state["completed"]):
        raise RuntimeError("state/result update in progress")
    seed_coverage = set(state["seed"]["feedback"]["coverage"])
    gain = set(state["coverage"]) - seed_coverage
    methods = sum(identifier.startswith("METHOD:") and production(identifier)
                  for identifier in gain)
    branches = sum(identifier.startswith("BRANCH:") and production(identifier)
                   for identifier in gain)
    ledger = []
    for item in state["completed"]:
        data = json.loads(Path(item["result"]).read_text())
        attempts = sorted(Path(item["result"]).parent.glob("attempt-*/result.json"))
        attempt_seconds = [json.loads(path.read_text()).get("elapsed_seconds", 0)
                           for path in attempts]
        total_seconds = round(sum(attempt_seconds), 3) if attempts else item["elapsed_seconds"]
        ledger.append({
            "trial": item["number"], "fault_count": len(item["sequence"]),
            "fault_markers": [point["marker"] for point in item["sequence"]],
            "fault_site_ids": [point["siteId"] for point in item["sequence"]],
            "status": item["status"],
            "strict_injection": data.get("strict_injection", False),
            "target_reached_after_fault":
                data.get("target_reached_after_fault", False),
            "target_outcomes_after_fault":
                data.get("target_outcomes_after_fault", []),
            "exact_target_exception": data.get("oracle", False),
            "junit_exit": data.get("exit"),
            "elapsed_seconds": total_seconds,
            "attempt_count": len(attempts) if attempts else 1,
            "final_attempt_seconds": item["elapsed_seconds"],
            "new_coverage_count": data.get("new_coverage_count", 0),
            "new_io_families": data.get("new_io_count", 0),
            "attempt": data.get("attempt", 1),
            "result": item["result"],
        })
    print(json.dumps({
        "result": result,
        "budget": json.loads((BASE / "case.json").read_text())["budget"],
        "production_new_methods": methods,
        "production_new_branch_outcomes": branches,
        "pending_queue": len(state["queue"]),
        "active_sequence": bool(state["active"]),
        "ledger": ledger,
        "legacy": json.loads((CASE / "legacy-reassessment.json").read_text()),
        "finished": (CASE / "campaign.done.json").exists(),
    }))


if __name__ == "__main__":
    main()
