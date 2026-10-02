"""Audit full fault matches, exact target oracles, and graph/coverage deltas."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = {"hbase": "hbase_266", "zookeeper": "zookeeper_387",
            "solr": "solr_8114"}
DELTAS = ("new_closure_nodes", "new_closure_edges", "new_closure_blocks",
          "new_closure_branch_outcomes", "new_global_blocks",
          "new_global_branch_outcomes")


def audit(system: str, variant: str = "", draws: set[int] | None = None) -> dict:
    example = ROOT / EXAMPLES[system]
    selection = json.loads((example / "selected10.json").read_text())
    suffix = "_" + variant if variant else ""
    result_path = example / ("results10" + suffix + ".json")
    statuses = ({row["draw"]: row["status"] for row in
                 json.loads(result_path.read_text()).get("cases", [])}
                if result_path.exists() else {})
    cases = []
    for target in selection["cases"]:
        draw = target["draw"]
        if draws is not None and draw not in draws:
            continue
        root = example / ("out_campaign" + suffix) / "case-{:02d}".format(draw)
        rows = []
        for path in sorted((root / "runs").glob("*/result.json")):
            result = json.loads(path.read_text())
            feedback_path = path.with_name("feedback.json")
            feedback = (json.loads(feedback_path.read_text())
                        if feedback_path.exists() else {})
            planned = len(result["sequence"]["actions"])
            injected = result["injected"]
            complete = bool(planned and result["triggered"]
                            and len(injected) == planned)
            rows.append({
                "run_id": result["run_id"], "planned": planned,
                "injected": len(injected), "complete": complete,
                "match_modes": [item["match_mode"] for item in injected],
                "target_reached": result["target_reached"],
                "target_fatal": result["target_fatal"],
                "target_hit_count": len(result.get("target_hits", [])),
                "workload_returncode": result["workload"]["returncode"],
                "workload_timed_out": result["workload"]["timed_out"],
                "checker_returncode": None if result["checker"] is None
                else result["checker"]["returncode"],
                "global_blocks": result["global_blocks"],
                "global_branch_outcomes": result["global_branch_outcomes"],
                "closure_blocks": result["closure_blocks"],
                "closure_branch_outcomes": result["closure_branch_outcomes"],
                "feedback": feedback,
            })
        fault_rows = [row for row in rows if row["planned"]]
        matched = [row for row in fault_rows if row["complete"]]
        modes = Counter(mode for row in matched for mode in row["match_modes"])
        findings_path = root / "findings.jsonl"
        findings = ([json.loads(line) for line in findings_path.read_text().splitlines()]
                    if findings_path.exists() else [])
        aggregate = {
            "draw": draw, "site_id": target["site_id"],
            "status": statuses.get(draw, "pending"),
            "guard": target["target_guard"], "throw": target["target_throw"],
            "seed_guard_hits_in_discovery": target["seed_guard_hits"],
            "seed_reached": next((row["target_reached"] for row in rows
                                  if row["run_id"].startswith("seed-")), None),
            "attempted_fault_trials": len(fault_rows),
            "full_matches": len(matched),
            "partial_matches": sum(0 < row["injected"] < row["planned"]
                                   for row in fault_rows),
            "match_modes": dict(modes),
            "full_matches_reaching_target": sum(row["target_reached"]
                                                for row in matched),
            "full_matches_at_exact_throw": sum(row["target_fatal"]
                                               for row in matched),
            "reproduced_target_exception_candidates": sum(
                item.get("confirmation", {}).get("reproduced", False)
                for item in findings),
            "workload_failures_in_full_matches": sum(
                row["workload_returncode"] != 0 or row["workload_timed_out"]
                for row in matched),
            "checker_failures_in_full_matches": sum(
                row["checker_returncode"] not in (0, None)
                for row in matched),
            "checker_missing_in_full_matches": sum(
                row["checker_returncode"] is None for row in matched),
            "feedback": {key: sum(row["feedback"].get(key, 0)
                                  for row in matched) for key in DELTAS},
            "run_count": len(rows),
        }
        cases.append(aggregate)
    totals = {
        "selected": len(cases),
        "complete_cases": sum(row["status"] == "complete" for row in cases),
        "error_cases": sum(row["status"] == "error" for row in cases),
        "pending_cases": sum(row["status"] == "pending" for row in cases),
        "cases_with_no_full_match": sum(row["full_matches"] == 0
                                        for row in cases),
        "attempted_fault_trials": sum(row["attempted_fault_trials"]
                                      for row in cases),
        "full_matches": sum(row["full_matches"] for row in cases),
        "partial_matches": sum(row["partial_matches"] for row in cases),
        "full_matches_reaching_target": sum(
            row["full_matches_reaching_target"] for row in cases),
        "full_matches_at_exact_throw": sum(
            row["full_matches_at_exact_throw"] for row in cases),
        "reproduced_target_exception_candidates": sum(
            row["reproduced_target_exception_candidates"] for row in cases),
        "workload_failures_in_full_matches": sum(
            row["workload_failures_in_full_matches"] for row in cases),
        "checker_failures_in_full_matches": sum(
            row["checker_failures_in_full_matches"] for row in cases),
        "checker_missing_in_full_matches": sum(
            row["checker_missing_in_full_matches"] for row in cases),
        "match_modes": dict(sum((Counter(row["match_modes"]) for row in cases),
                                Counter())),
        "feedback": {key: sum(row["feedback"][key] for row in cases)
                     for key in DELTAS},
    }
    return {"system": system, "variant": variant,
            "selection": selection["selection_seed"],
            "direct_mapped": selection["mapped_direct"],
            "workload_reached_server_guards":
                selection["workload_reached_server_guards"],
            "totals": totals, "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("system", choices=EXAMPLES)
    parser.add_argument("--variant", default="")
    parser.add_argument("--draws", default="",
                        help="comma-separated draw numbers for focused variants")
    args = parser.parse_args()
    if args.variant and not args.variant.replace("_", "").isalnum():
        raise ValueError("variant must contain only letters, digits, underscores")
    draws = ({int(item) for item in args.draws.split(",")}
             if args.draws else None)
    result = audit(args.system, args.variant, draws)
    suffix = "_" + args.variant if args.variant else ""
    path = ROOT / EXAMPLES[args.system] / ("audit10" + suffix + ".json")
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["totals"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
