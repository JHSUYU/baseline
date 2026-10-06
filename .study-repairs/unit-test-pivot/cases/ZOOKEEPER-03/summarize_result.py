#!/usr/bin/env python3
"""Print a compact case result with separate production coverage metrics."""

import json
from pathlib import Path

CASE = Path("/users/ZhenyuLi/zk03-case/campaign/ZOOKEEPER-03")
result = json.loads((CASE / "result.json").read_text())
state = json.loads((CASE / "state.json").read_text())
seed = set(state["seed"]["feedback"]["coverage"])
current = set(state["coverage"])
new = current - seed


def production(item):
    # Runtime controller and synthetic fault gates are outside the target
    # system's package. The rewritten target branch is the real source guard.
    return "<org.apache.zookeeper." in item and not any(
        marker in item for marker in ("<edu.uva.", "CausynthFault", "FaultInjector"))


def count(prefix, items):
    return sum(item.startswith(prefix) and production(item) for item in items)


result["healthy_production_methods"] = count("METHOD:", seed)
result["healthy_production_branch_outcomes"] = count("BRANCH:", seed)
result["healthy_production_call_site_ids"] = count("CALL_SITE:", seed)
result["production_new_methods"] = count("METHOD:", new)
result["production_new_branch_outcomes"] = count("BRANCH:", new)
result["production_new_call_site_ids"] = count("CALL_SITE:", new)
result["production_coverage_gain"] = (
    result["production_new_methods"] + result["production_new_branch_outcomes"])
result["combined_feedback_gain"] = result.pop("coverage_gain")
result["coverage_gain"] = result["production_coverage_gain"]
result["coverage_kind"] = "production methods plus branch outcomes"
result["combined_feedback_kind"] = (
    "production methods, branch outcomes, and call-site return/throw IDs")
result["synthetic_fault_gates_excluded"] = True
print(json.dumps(result, sort_keys=True))
