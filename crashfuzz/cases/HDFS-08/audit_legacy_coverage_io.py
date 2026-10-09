"""Reassess HDFS-08's 40 completed trials without a graph decision.

This reads existing traces and results only. It never launches a JUnit run or
replays a completed fault selector. The output is the continuation checkpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import coverage_io_feedback as feedback


HERE = Path(__file__).resolve().parent
OUT = HERE / "coverage-io-checkpoint.json"
METHOD = "<org.apache.hadoop.hdfs.qjournal.server.Journal: void checkRequest(org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo)>"
GUARD = METHOD + "#u7"


def target(policy_name: str) -> dict:
    policy = json.loads((HERE / policy_name).read_text())
    return {
        "method": METHOD,
        "occurrence": policy["selected_occurrence"],
        "site_id": GUARD,
        "fatal_guards": [{"siteId": GUARD, "outcome": False}],
        "exception_type": "java.io.IOException",
        "coverage_include_prefixes": ["<org.apache.hadoop.hdfs."],
    }


def production_coverage(raw: list[str]) -> set[str]:
    """Conservative HDFS method/branch IDs, excluding file-door branch gates."""
    return {identifier for identifier in raw
            if identifier.startswith(("METHOD:<org.apache.hadoop.hdfs.",
                                      "BRANCH:<org.apache.hadoop.hdfs."))
            and not (identifier.startswith("BRANCH:") and
                     "<org.apache.hadoop.hdfs.util.PersistentLongFile: void writeFile("
                     in identifier)}


def io_families(points: list[dict]) -> list[str]:
    return sorted({feedback.fault_family(point) for point in points})


def old_trials() -> list[dict]:
    state = json.loads((HERE / "fuzzer-cases/HDFS-08/state.json").read_text())
    existing: list[dict] = []
    for row in state["completed"]:
        old = json.loads(Path(row["result"]).read_text())
        existing.append({
            "phase": "single_writer_rpc", "trial": f"rpc-{row['number']:02d}",
            "test_method": "testSingleWriter", "policy": "target-runtime-state.json",
            "trace": old["trace"], "result": row["result"],
            "requested_selectors": row["sequence"],
            "prior_strict": old["strict_injection"],
            "prior_target_after_fault": old["target_reached_after_fault"],
            "junit_exit": old["exit"], "seconds": old["elapsed_seconds"],
        })
    files = json.loads((HERE / "state-file-trials/checkpoint.json").read_text())
    for row in files["results"]:
        existing.append({
            "phase": "single_writer_epoch_file", "trial": row["trial"],
            "test_method": "testSingleWriter", "policy": "target-runtime-state.json",
            "trace": row["trace"], "result": str(HERE / row["trial"] / "state-file-result.json"),
            "requested_selectors": [row["selector"]],
            "prior_strict": row["strict_injection"],
            "prior_target_after_fault": row["target_reached_after_fault"],
            "junit_exit": row["junit_exit"], "seconds": row["measured_trial_wall_seconds"],
        })
    multi = json.loads((HERE / "multiwriter-trials/checkpoint.json").read_text())
    for row in multi["results"]:
        existing.append({
            "phase": "multi_writer_recovery", "trial": row["trial"],
            "test_method": "testChangeWritersLogsInSync",
            "policy": "target-runtime-multiwriter.json",
            "trace": row["trace"], "result": str(HERE / row["trial"] / "multiwriter-result.json"),
            "requested_selectors": row["selectors"],
            "prior_strict": row["strict_injection"],
            "prior_target_after_fault": row["target_reached_after_fault"],
            "junit_exit": row["junit_exit"], "seconds": row["measured_trial_wall_seconds"],
        })
    if len(existing) != 40:
        raise RuntimeError(f"expected 40 completed trials, got {len(existing)}")
    return existing


def main() -> None:
    seeds = {
        "single_writer_rpc": (HERE / "healthy-control-door/trace/runtime_trace.jsonl",
                              target("target-runtime-state.json")),
        "single_writer_epoch_file": (HERE / "healthy-state/trace/runtime_trace.jsonl",
                                     target("target-runtime-state.json")),
        "multi_writer_recovery": (HERE / "healthy-multiwriter/trace/runtime_trace.jsonl",
                                  target("target-runtime-multiwriter.json")),
    }
    checkpoint = json.loads(OUT.read_text()) if OUT.is_file() else {
        "schema_version": 1, "case_id": "HDFS-08",
        "methodology": "coverage_io_no_graph", "budget": {"max_trials": 48, "max_faults": 4},
        "legacy_completed": [], "continuation_completed": [], "seed": {}}
    if not checkpoint["seed"]:
        for phase, (path, policy) in seeds.items():
            assessed = feedback.trace_feedback(path, policy)
            if not assessed["target_reached"] or assessed["target_fatal_exception_count"]:
                raise RuntimeError(f"invalid healthy target in {phase}")
            checkpoint["seed"][phase] = {
                "trace": str(path), "target_occurrence": policy["occurrence"],
                "production_coverage": sorted(production_coverage(assessed["coverage"])),
                "io_families": io_families(assessed["points"]),
                "observed_io_points": len(assessed["points"]),
                "target_outcomes": assessed["target_outcomes"],
            }
        feedback.atomic_json(OUT, checkpoint)
    old = old_trials()
    done = {row["trial"] for row in checkpoint["legacy_completed"]}
    for item in old:
        if item["trial"] in done:
            continue
        policy = seeds[item["phase"]][1]
        assessed = feedback.trace_feedback(Path(item["trace"]), policy)
        strict = feedback.strict_injection(assessed, item["requested_selectors"])
        retained = assessed["target_reached_after_fault"]
        if strict != item["prior_strict"] or retained != item["prior_target_after_fault"]:
            raise RuntimeError(f"legacy/oracle disagreement in {item['trial']}: "
                               f"strict {strict}/{item['prior_strict']}, "
                               f"retained {retained}/{item['prior_target_after_fault']}")
        row = {
            **{key: item[key] for key in ("phase", "trial", "test_method", "trace",
                                           "result", "requested_selectors", "seconds",
                                           "junit_exit")},
            "selector_ids": [feedback.fingerprint(p) for p in item["requested_selectors"]],
            "strict_injection": strict,
            "matched_faults": assessed["matched_count"],
            "applied_faults": assessed["applied_count"],
            "target_guard_after_last_fault": retained,
            "target_outcomes_after_fault": assessed["target_outcomes_after_fault"],
            "target_fatal_exception_count": assessed["target_fatal_exception_count"],
            "target_exception_after_fault": assessed["target_after_fault"],
            "production_coverage": sorted(production_coverage(assessed["coverage"])),
            "observed_io_families": io_families(assessed["points"]),
            "observed_io_points": len(assessed["points"]),
            "status": "checked" if strict and retained else
                      "lost_target" if strict else "unmatched",
            "bug_mark": "candidate" if assessed["oracle"] and
                         assessed["target_fatal_exception_count"] > 0 else "none",
            "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        checkpoint["legacy_completed"].append(row)
        feedback.atomic_json(OUT, checkpoint)
        print(item["trial"], row["status"], len(row["production_coverage"]),
              flush=True)
    print("legacy reassessment complete", len(checkpoint["legacy_completed"]), flush=True)


if __name__ == "__main__":
    main()
