#!/usr/bin/env python3
"""Audit dynamic depth≥3 plans against each parent and every raw target receipt."""

from __future__ import annotations

import json

import deep_campaign as deep
from receipt_validator import parse_events, fault_selector


def main():
    _, _, manifest, source, pilot_state = deep.verify()
    state = json.loads(deep.CHECKPOINT.read_text())
    covered, known_io = deep.baseline_feedback(source)
    source_by_id = {row["run_id"]: (row, deep.CHILD_ROOT / row["run_id"])
                    for row in source["results"]}
    checked = []
    seen = {tuple([row["selector"]]) for row in pilot_state["results"]}
    seen |= {tuple(row["plan"]) for row in source["results"]}
    for previous in state["results"]:
        run_id = previous["run_id"]
        root = deep.ROOT / run_id
        receipt = json.loads((root / "run.json").read_text())
        if receipt["selector"] != "|||".join(previous["plan"]) or \
                receipt["events_sha256"] != deep.children.pilot.sha(root / "events.tsv") or \
                receipt["coverage_sha256"] != deep.children.pilot.sha(root / "coverage.tsv"):
            raise RuntimeError("deep raw receipt/plan/hash disagreement: " + run_id)
        plan = tuple(previous["plan"])
        if plan in seen or len(plan) < 3 or len(plan) > manifest["max_faults"]:
            raise RuntimeError("duplicate or out-of-budget deep plan: " + run_id)
        parent_id = previous["parent"]
        if parent_id not in source_by_id:
            raise RuntimeError("deep plan parent absent or not earlier: " + run_id)
        parent, parent_root = source_by_id[parent_id]
        if not parent["target_after_final_fault"] or \
                tuple(parent["plan"]) != plan[:-1]:
            raise RuntimeError("parent does not retain target or match prefix: " + run_id)
        parent_rows = parse_events(parent_root / "events.tsv")
        parent_last = max(s for s, kind, _ in parent_rows if kind == "FAULT_APPLIED")
        parent_target = parent["target_receipt"]["target_sequence"]
        occurrence = [(s, f) for s, kind, f in parent_rows
                      if parent_last < s < parent_target and kind == "IO"
                      and len(f) >= 7 and f[6] == "upgradedSession"
                      and fault_selector(f) == plan[-1]]
        if len(occurrence) != 1 or occurrence[0][0] != previous[
                "observed_parent_sequence"]:
            raise RuntimeError("last fault not observed after parent fault before target: " +
                               run_id)
        job = {"child_id": run_id, "parent": parent_id,
               "plan": list(plan), "child_family": previous["child_family"]}
        current = deep.children.audit(job, receipt, covered, known_io)
        for key in ("run_id", "parent", "plan", "faults_matched",
                    "faults_applied", "exact_injection", "target_after_final_fault",
                    "target_receipt", "selected_target_throws", "junit_exit",
                    "new_target_coverage_lines", "new_target_io_families",
                    "events_sha256", "coverage_sha256"):
            if current[key] != previous[key]:
                raise RuntimeError("deep stored vs raw mismatch: " + run_id + " " + key)
        if current["target_after_final_fault"]:
            covered |= set(current["coverage"])
            known_io |= set(current["io_families"])
        source_by_id[run_id] = (current, root)
        seen.add(plan)
        checked.append({key: current[key] for key in
                        ("run_id", "parent", "plan", "faults_matched",
                         "faults_applied", "exact_injection",
                         "target_after_final_fault", "target_receipt",
                         "selected_target_throws", "junit_exit",
                         "new_target_coverage_lines", "new_target_io_families",
                         "elapsed_seconds", "events_sha256", "coverage_sha256")})
    if set(state["seen_coverage"]) != covered or \
            set(state["seen_io_families"]) != known_io:
        raise RuntimeError("deep saved coverage/I/O feedback differs from raw reaggregation")
    result = {"case_id": "ZOOKEEPER-03", "phase": manifest["phase"],
              "status": state["status"],
              "manifest_sha256": deep.children.pilot.sha(deep.MANIFEST),
              "checkpoint_sha256": deep.children.pilot.sha(deep.CHECKPOINT),
              "source_pilot_selected": 10, "source_child_selected": 13,
              "source_pilot_effective": state["source_pilot_effective"],
              "source_child_effective": state["source_child_effective"],
              "deep_selected": len(checked),
              "deep_strict_injections": sum(r["exact_injection"] for r in checked),
              "deep_target_retaining": sum(r["target_after_final_fault"] for r in checked),
              "new_seed_total_effective": state["source_pilot_effective"] +
                                          state["source_child_effective"] +
                                          sum(r["target_after_final_fault"] for r in checked),
              "selected_target_throws": sum(r["selected_target_throws"] for r in checked),
              "deep_new_target_coverage_lines": sum(r["new_target_coverage_lines"] for r in checked),
              "deep_new_target_io_families": sum(r["new_target_io_families"] for r in checked),
              "sum_elapsed_seconds": round(sum(r["elapsed_seconds"] for r in checked), 3),
              "pending_queue": len(state["queue"]), "trials": checked}
    deep.children.pilot.up.write_json(deep.ROOT / "deep-independent-audit.json", result)
    print(json.dumps({key: result[key] for key in
          ("status", "deep_selected", "deep_strict_injections",
           "deep_target_retaining", "new_seed_total_effective",
           "selected_target_throws", "deep_new_target_coverage_lines",
           "deep_new_target_io_families", "pending_queue")}, sort_keys=True))


if __name__ == "__main__":
    main()
