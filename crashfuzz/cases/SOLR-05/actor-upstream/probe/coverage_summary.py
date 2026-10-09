#!/usr/bin/env python3
"""Summarize production JaCoCo feedback from only strict, target-retaining trials."""

import json
from pathlib import Path

from feedback import atomic_json


CASE = Path(__file__).resolve().parents[1]
state = json.loads((CASE / "evidence/campaign/state.json").read_text())
site = "SOLR-05"
eligible = [t for t in state["trials"] if t["strict"] and
            t["target_after_fault"][site]]
healthy_branches = state["healthy_branches"]
seen_branches = state["seen_branches"][site]
summary = {
    "scope": "Solr production classes from release JARs, JaCoCo",
    "branch_note": "Covered branch-count increase per method; equal counts do not prove identical outcomes.",
    "identity_version": state["identity_version"],
    "eligible_trial_numbers": [t["number"] for t in eligible],
    "healthy_probes": len(state["healthy_coverage"]),
    "eligible_union_probes": len(state["seen_coverage"][site]),
    "new_probes": len(state["seen_coverage"][site]) - len(state["healthy_coverage"]),
    "healthy_methods": len(state["healthy_methods"]),
    "eligible_union_methods": len(state["seen_methods"][site]),
    "new_methods": len(state["seen_methods"][site]) - len(state["healthy_methods"]),
    "new_covered_branch_count": sum(max(0, count - healthy_branches.get(method, 0))
                                    for method, count in seen_branches.items()),
    "per_eligible_trial": [{
        "number": t["number"],
        "new_probes": t["new_coverage"][site],
        "new_methods": t["new_methods"][site],
        "new_covered_branch_count": t["new_branches"][site],
        "elapsed_seconds": t["elapsed_seconds"],
    } for t in eligible],
}
atomic_json(CASE / "evidence/campaign/coverage-summary.json", summary)
print(json.dumps({key: summary[key] for key in (
    "new_probes", "new_methods", "new_covered_branch_count")}, sort_keys=True))
