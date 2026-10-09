#!/usr/bin/env python3
"""Compare trace-based method and branch-outcome coverage across valid trials."""

import glob
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CAMPAIGNS = ("fuzzer-r2", "fuzzer-v2-single")
TARGET_REGION = "REGION.1e25f543-ad81-3ed6-b419-eabbb2153db4"


def main():
    healthy = set()
    closure_methods = set()
    for campaign in CAMPAIGNS:
        path = HERE / campaign / "ZOOKEEPER-05/state.json"
        if not path.exists():
            continue
        state = json.loads(path.read_text())
        healthy.update(state["seed"]["feedback"]["coverage"])
    for name in ("record2", "record-v2"):
        plan = HERE / name / "targets/zk05/runtime/concolic_region_plan.jsonl"
        if not plan.exists():
            continue
        for line in plan.open():
            row = json.loads(line)
            if row.get("regionId") != TARGET_REGION:
                continue
            for goal in row.get("closureGoals", []):
                closure_methods.update(branch.get("method")
                                       for branch in goal.get("branches", [])
                                       if branch.get("method"))
    checked = []
    trial_coverage = set()
    for campaign in CAMPAIGNS:
        pattern = HERE / campaign / "ZOOKEEPER-05/trials/*/result.json"
        for name in sorted(glob.glob(str(pattern))):
            trial = json.loads(Path(name).read_text())
            if trial.get("status") != "checked" or not trial.get("strict_injection"):
                continue
            checked.append(str(Path(name).relative_to(HERE)))
            trial_coverage.update(trial.get("coverage", []))
    new = trial_coverage - healthy
    new_closure_branches = sorted(
        item for item in new if item.startswith("BRANCH:") and
        any(item.startswith("BRANCH:" + method + "#")
            for method in closure_methods))
    result = {
        "kind": "trace-instrumented methods and branch outcome pairs",
        "healthy_union": len(healthy),
        "healthy_method_count": sum(x.startswith("METHOD:") for x in healthy),
        "healthy_branch_outcome_count": sum(x.startswith("BRANCH:") for x in healthy),
        "valid_checked_trials": len(checked),
        "checked_trial_results": checked,
        "new_coverage_count": len(new),
        "new_method_count": sum(x.startswith("METHOD:") for x in new),
        "new_branch_outcome_count": sum(x.startswith("BRANCH:") for x in new),
        "new_target_closure_branch_outcome_count": len(new_closure_branches),
        "new_target_closure_branch_outcomes": new_closure_branches,
        "new_coverage": sorted(new),
    }
    (HERE / "coverage-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if not isinstance(value, list)}, indent=2))


if __name__ == "__main__":
    main()
