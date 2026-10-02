"""Summarize the ten-check run without treating method coverage as check coverage."""

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE / "out_coverage10"


def guard_outcomes(run_dir: Path, guard: str,
                   workload_end_wall_ms: int) -> set[str]:
    outcomes: set[str] = set()
    for path in (run_dir / "traces").glob("trace-*.jsonl"):
        with path.open() as handle:
            for line in handle:
                if '"kind":"BRANCH"' not in line or guard not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # A killed process may leave an incomplete tail.
                if (row.get("site") == guard
                        and int(row.get("wall_ms", 0))
                        <= workload_end_wall_ms):
                    outcomes.add(str(row.get("outcome")))
    return outcomes


def main() -> None:
    progress = json.loads((ROOT / "progress.json").read_text())
    rows = []
    for draw in range(1, 11):
        name = "candidate-{:02d}".format(draw)
        detail = progress["targets"].get(name, {})
        directory = ROOT / name / "runs"
        seed = None
        faults = []
        outcomes = set()
        for path in sorted(directory.glob("*/result.json")):
            result = json.loads(path.read_text())
            run_dir = path.parent
            run_outcomes = (guard_outcomes(
                run_dir, detail["target_guard"],
                int(result.get("workload_end_wall_ms", 2**63 - 1)))
                            if detail.get("target_guard") else set())
            outcomes.update(run_outcomes)
            feedback_path = run_dir / "feedback.json"
            feedback = (json.loads(feedback_path.read_text())
                        if feedback_path.exists() else {})
            record = {"run_id": result["run_id"],
                      "matched": bool(result["triggered"]),
                      "planned_actions": len(result["sequence"]["actions"]),
                      "matched_actions": len(result["injected"]),
                      "fault_kinds": [step["action"]["kind"]
                                      for step in result["injected"]],
                      "target_reached": result["target_reached"],
                      "target_fatal": result["target_fatal"],
                      "guard_outcomes": sorted(run_outcomes),
                      "global_blocks": result.get("global_blocks", 0),
                      "global_branch_outcomes": result.get(
                          "global_branch_outcomes", 0),
                      "closure_blocks": result.get("closure_blocks", 0),
                      "closure_branch_outcomes": result.get(
                          "closure_branch_outcomes", 0),
                      "feedback": feedback,
                      "workload_returncode": result["workload"]["returncode"],
                      "checker_returncode": (None if result["checker"] is None
                                             else result["checker"]["returncode"])}
            if result["run_id"].startswith("seed-"):
                seed = record
            elif result["run_id"].startswith("run-"):
                faults.append(record)
        rows.append({
            "draw": draw, "status": detail.get("status", "not_started"),
            "site_id": detail.get("site_id"),
            "guard": detail.get("target_guard"),
            "guard_outcomes_any": sorted(outcomes),
            "fault_only_guard_outcomes": sorted(
                set().union(*(set(r["guard_outcomes"]) for r in faults
                              if r["matched"]))
                - (set(seed["guard_outcomes"]) if seed else set())),
            "seed": seed, "fault_trials": faults,
            "matched_fault_trials": sum(r["matched"] for r in faults),
            "matched_actions": sum(r["matched_actions"] for r in faults),
            "partially_injected_fault_trials": sum(
                r["matched_actions"] > 0 and not r["matched"]
                for r in faults),
            "new_global_blocks_in_matched_faults": sum(
                r["feedback"].get("new_global_blocks", 0)
                for r in faults if r["matched"]),
            "new_closure_blocks_in_matched_faults": sum(
                r["feedback"].get("new_closure_blocks", 0)
                for r in faults if r["matched"]),
            "new_closure_branch_outcomes_in_matched_faults": sum(
                r["feedback"].get("new_closure_branch_outcomes", 0)
                for r in faults if r["matched"]),
            "target_fatal_in_faults": any(
                r["target_fatal"] for r in faults if r["matched"]),
            "checker_failures_in_matched_faults": sum(
                r["checker_returncode"] not in (0, None)
                for r in faults if r["matched"]),
            "checker_missing_in_matched_faults": sum(
                r["checker_returncode"] is None
                for r in faults if r["matched"]),
        })
    result = {"sample_size": 10, "rows": rows}
    path = HERE / "coverage10.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for row in rows:
        print("{:02d} status={} faults={}/{} seed_guard={} any_guard={} "
              "new_global_blocks={} new_closure_blocks={} "
              "new_closure_branches={} guard_flip={} fatal={}".format(
                  row["draw"], row["status"], row["matched_fault_trials"],
                  len(row["fault_trials"]),
                  bool(row["seed"] and row["seed"]["target_reached"]),
                  ",".join(row["guard_outcomes_any"]) or "-",
                  row["new_global_blocks_in_matched_faults"],
                  row["new_closure_blocks_in_matched_faults"],
                  row["new_closure_branch_outcomes_in_matched_faults"],
                  ",".join(row["fault_only_guard_outcomes"]) or "-",
                  row["target_fatal_in_faults"]))
    print("wrote", path)


if __name__ == "__main__":
    main()
