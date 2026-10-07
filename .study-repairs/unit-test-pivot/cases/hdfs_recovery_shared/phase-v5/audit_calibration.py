#!/usr/bin/env python3
"""Admit two unmodified TestBlockRecovery2 healthy JUnits after host handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import v5_model as model

HERE = Path(__file__).resolve().parent
STATE = HERE / "campaign-state.json"
GATE = HERE / "calibration-gate.json"
EXPECTED_TEST = "org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryTimeout"


def verify_seed(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("returncode") != 0 or not manifest.get("instrumented")
            or manifest.get("test") != EXPECTED_TEST or manifest.get("plan") is not None
            or not (directory / "jacoco.exec").is_file()):
        raise RuntimeError("healthy seed did not run the original instrumented JUnit: " + str(directory))
    if any(not (directory / ("covered_" + category + ".txt")).is_file()
           for category in ("probes", "methods", "branch_counts")):
        raise RuntimeError("healthy production JaCoCo report is missing: " + str(directory))
    trace = [json.loads(line) for line in (directory / "runtime_trace.jsonl").read_text().splitlines()
             if line]
    if any(row.get("event") in ("FAULT_APPLIED", "TARGET_THROW") for row in trace):
        raise RuntimeError("healthy seed applied fault or threw selected target: " + str(directory))
    checks = {}
    for case in model.CASES:
        selected = [row for row in trace if row.get("event") == "TARGET_CHECK"
                    and row.get("caseId") == case and row.get("siteId") == model.SITES[case]]
        if not selected or any(row.get("outcome") is not False or not model.valid_owner(row)
                               for row in selected):
            raise RuntimeError("missing/bad healthy target " + case + " in " + str(directory))
        if any(row["clusterEpisode"] != 1 for row in selected):
            raise RuntimeError("V4 pending selectors require stable first startup episode")
        checks[case] = len(selected)
    producer = [row for row in trace if row.get("event") == "FAULT_POINT_OBSERVED"
                and row.get("marker") == model.PRODUCER
                and model.identity_verified(trace, row)
                and model.later_target(trace, row, "HDFS-28")]
    if not producer:
        producer_status = "no_bound_producer_before_hdfs28"
    else:
        producer_status = "bound_pre_target_producer"
    return {"dir": str(directory), "manifest_sha256": hashlib.sha256(
                (directory / "manifest.json").read_bytes()).hexdigest(),
            "trace_sha256": hashlib.sha256((directory / "runtime_trace.jsonl").read_bytes()).hexdigest(),
            "overlay_digest": manifest["overlay_digest"], "elapsed_seconds": manifest["elapsed_seconds"],
            "target_checks": checks, "bound_pre_target_producers": len(producer),
            "producer_status": producer_status,
            "producer_shapes": sorted({"|".join(str(row.get(key, "")) for key in
                ("marker", "siteId", "requestApi", "clusterEpisode", "bpid",
                 "blockId", "recoveryId")) for row in producer}),
            "eligible_io_by_case": {case: sum(bool(model.eligible_io(trace, row, (case,)))
                                             for row in trace if row.get("event") == "FAULT_POINT_OBSERVED")
                                    for case in model.CASES}}


def main() -> None:
    if GATE.exists():
        raise RuntimeError("calibration gate already exists; do not overwrite")
    state = json.loads(STATE.read_text())
    if state["v5_attempts"] or state["active"]:
        raise RuntimeError("cannot activate healthy gate after faults")
    a, b = (verify_seed(HERE / name) for name in ("healthy-v5-a", "healthy-v5-b"))
    for name in ("healthy-file-pilot", "healthy-file-pilot-b"):
        legacy = HERE.parent / "phase-v4" / name / "runtime_trace.jsonl"
        old_trace = [json.loads(line) for line in legacy.read_text().splitlines() if line]
        for case in model.CASES:
            checks = [row for row in old_trace if row.get("event") == "TARGET_CHECK"
                      and row.get("caseId") == case and row.get("siteId") == model.SITES[case]]
            if not checks or any(row.get("outcome") is not False for row in checks):
                raise RuntimeError("V4 healthy selected guard signature changed: " + case)
    if a["overlay_digest"] != b["overlay_digest"]:
        raise RuntimeError("healthy seeds used different overlays")
    stable_shapes = sorted(set(a["producer_shapes"]) & set(b["producer_shapes"]))
    producer_enabled = bool(stable_shapes)
    gate = {"schema": "hdfs-recovery-v5-calibration-1", "passed": True,
            "test": EXPECTED_TEST, "overlay_digest": a["overlay_digest"],
            "hdfs28_producer_enabled": producer_enabled,
            "stable_producer_shapes": stable_shapes,
            "hdfs28_status": "active" if producer_enabled else "budget_recheck_pending",
            "seeds": [a, b], "v4_healthy_comparison":
                "Original V4 controls reached HDFS-28/29/30 with expected false guards; "
                "V5 enforces the same site/guard and added BP/recovery/episode identity."}
    if producer_enabled:
        for seed in (HERE / "healthy-v5-a", HERE / "healthy-v5-b"):
            trace = [json.loads(line) for line in (seed / "runtime_trace.jsonl").read_text().splitlines()
                     if line]
            for event in trace:
                if (event.get("marker") != model.PRODUCER
                        or not model.eligible_io(trace, event, ("HDFS-28",))):
                    continue
                shape = "|".join(str(event.get(key, "")) for key in
                    ("marker", "siteId", "requestApi", "clusterEpisode", "bpid",
                     "blockId", "recoveryId"))
                if shape not in stable_shapes:
                    continue
                sequence = [model.selector(event, "IOException")]
                identity = model.sequence_id(sequence)
                if identity in state["seen_sequences"]:
                    continue
                state["seen_sequences"].append(identity)
                target = model.later_target(trace, event, "HDFS-28")[0]
                state["queue"].append({"id": identity, "sequence": sequence,
                    "expectedEpisode": event["clusterEpisode"], "created": time.time(),
                    "priority": 100, "lane": "hdfs28_producer",
                    "pre_target_cases": ["HDFS-28"], "owner_evidence": [{
                        "healthy_seed": str(seed), "io_seq": event["seq"],
                        "target_seq": target["seq"], "owner": model.owner(event)}],
                    "legacy_unmatched_attempts": 0, "v5_unmatched_attempts": 0})
    baseline = {category: set() for category in ("probes", "methods", "branch_counts")}
    families = set()
    for seed in (HERE / "healthy-v5-a", HERE / "healthy-v5-b"):
        for category in baseline:
            baseline[category].update((seed / ("covered_" + category + ".txt")).read_text().splitlines())
        trace = [json.loads(line) for line in (seed / "runtime_trace.jsonl").read_text().splitlines()
                 if line]
        families.update("|".join(str(row.get(key, "")) for key in
            ("marker", "siteId", "sourceKey", "originSourceKey", "requestApi"))
            for row in trace if row.get("event") == "FAULT_POINT_OBSERVED"
            and row.get("marker", "").startswith("FAULT:"))
    for case in model.CASES:
        state["coverage_v5"][case] = {category: sorted(values)
                                       for category, values in baseline.items()}
        state["io_families_v5"][case] = sorted(families)
    gate["healthy_production_coverage"] = {category: len(values)
                                           for category, values in baseline.items()}
    gate["healthy_io_families"] = len(families)
    for case in model.CASES:
        state["cases"][case]["status"] = gate["hdfs28_status"] if case == "HDFS-28" else "active"
    state["stop_reason"] = None
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    temporary.replace(STATE)
    temporary = GATE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(gate, sort_keys=True, indent=2) + "\n")
    temporary.replace(GATE)
    print(json.dumps(gate, sort_keys=True))


if __name__ == "__main__":
    main()
