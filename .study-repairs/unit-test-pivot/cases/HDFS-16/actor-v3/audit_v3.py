#!/usr/bin/env python3
"""Independently reconstruct HDFS-16 V3 trials from raw trace and JaCoCo."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from identity_gate import HERE, evaluate, rows


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage(run: Path) -> set[str]:
    path = run / "coverage.tsv"
    return set(path.read_text().splitlines()) if path.is_file() else set()


def family(row: dict) -> str:
    return "|".join(str(row.get(key)) for key in
                    ("marker", "api", "actorKey", "peerClass", "poolClass"))


def main() -> None:
    receipt_path = HERE / "healthy-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    assert receipt["pass"]
    state = json.loads((HERE / "campaign/checkpoint.json").read_text())
    assert state["healthy_receipt_sha256"] == sha(receipt_path)
    assert state["controller_sha256"] == sha(HERE / "campaign.py")
    assert state["gate_sha256"] == sha(HERE / "identity_gate.py")
    source = {name: sha(HERE / "system-test" / name)
              for name in receipt["source_shas"]}
    assert source == receipt["source_shas"]
    entries = sorted(state["completed"].items(), key=lambda pair: pair[1]["attempt"])
    assert len(entries) == state["attempted"]
    assert [entry["attempt"] for _, entry in entries] == list(range(1, len(entries) + 1))
    ledger_path = HERE / "campaign/trial-ledger.jsonl"
    ledger = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    assert len(ledger) == len(entries)
    baseline_coverage = coverage(HERE / "healthy/a") | coverage(HERE / "healthy/b")
    baseline_io = {family(row) for run in (HERE / "healthy/a", HERE / "healthy/b")
                   for row in rows(run) if row.get("event") == "IO_OBSERVED"}
    union_coverage, union_io = set(baseline_coverage), set(baseline_io)
    counts = Counter()
    raw = []
    for (identifier, entry), ledger_row in zip(entries, ledger):
        number = entry["attempt"]
        run = HERE / "campaign" / f"trial-{number:04d}"
        plan = HERE / "campaign/plans" / (identifier + ".tsv")
        recorded = json.loads((run / "v3-result.json").read_text())
        recomputed = evaluate(run, plan, receipt_path)
        for key in ("exact_order_applied", "requested_faults", "matched_faults",
                    "applied_faults", "postfault_target_count",
                    "manual_registration_join", "fault_actor_join",
                    "target_exception_count", "target_exception_candidate",
                    "valid_for_feedback", "workload_failure", "junit_exit",
                    "injected_exception_in_junit_log",
                    "environment_failure_in_junit_log", "elapsed_seconds"):
            assert recorded[key] == recomputed[key], (number, key)
        assert recorded["sequence_id"] == identifier == ledger_row["sequence_id"]
        new_coverage = coverage(run) - union_coverage
        new_io = {family(row) for row in rows(run) if row.get("event") ==
                  "IO_OBSERVED"} - union_io
        if not recomputed["valid_for_feedback"]:
            new_coverage.clear()
            new_io.clear()
        assert set(recorded["new_coverage_ids"]) == new_coverage
        assert set(recorded["new_io_families"]) == new_io
        union_coverage |= new_coverage
        union_io |= new_io
        for field in ("exact_order_applied", "valid_for_feedback",
                      "target_exception_candidate", "workload_failure"):
            counts[field] += bool(recomputed[field])
        counts["matched_fault_events"] += recomputed["matched_faults"]
        counts["applied_fault_events"] += recomputed["applied_faults"]
        raw.append({"number": number, "sequence_id": identifier,
                    "manifest_sha256": sha(run / "manifest.json"),
                    "trace_sha256": sha(run / "trace/runtime_trace.jsonl"),
                    "coverage_sha256": sha(run / "coverage.tsv")
                    if (run / "coverage.tsv").exists() else None,
                    "plan_sha256": sha(plan),
                    "result_sha256": sha(run / "v3-result.json")})
    assert counts["valid_for_feedback"] == state["effective"]
    assert union_coverage == set(state["coverage_ids"])
    assert union_io == set(state["io_families"])
    summary = {"schema": "hdfs16-v3-independent-raw-audit-1",
               "case_id": "HDFS-16", "checkpoint_status": state["status"],
               "attempted": state["attempted"], "effective": state["effective"],
               "counts": dict(counts),
               "coverage_gain": {kind: sum(row.startswith(kind + "\t")
                                     for row in union_coverage - baseline_coverage)
                                 for kind in ("PROBE", "METHOD", "BRANCH_UNIT")},
               "new_io_families": sorted(union_io - baseline_io),
               "checkpoint_sha256": sha(HERE / "campaign/checkpoint.json"),
               "healthy_receipt_sha256": sha(receipt_path),
               "raw": raw}
    output = HERE / "campaign/audit-v3.json"
    output.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in
                      ("attempted", "effective", "counts", "coverage_gain",
                       "new_io_families")}, sort_keys=True))


if __name__ == "__main__":
    main()
